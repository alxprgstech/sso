# ADR-0034: Reauthentication UX, сессионный read-grant и диагностика повторного TOTP

Статус: принято 26.10.2026. Дополняет [ADR-0015](0015-security-revision-and-reauth.md) и [ADR-0032](0032-default-on-mfa-and-admin-policy.md); не меняет модель assurance, action-bound proof или TOTP replay protection.

## Контекст

Аудит 26.10.2026 подтвердил, что пользователи видят окно «пароль + 2FA» чаще, чем обещает политика:

1. пятиминутный grant просмотра сессий жил только в памяти SPA и терялся при каждом full reload;
2. смена режима регистрации требовала пароль в форме и ещё раз в reauth-диалоге;
3. повторно использованный TOTP-шаг выглядел как неверный код, провоцировал повторные попытки и расходовал `failed_attempts`, после чего требовался новый пароль;
4. второй конкурентный чувствительный запрос немедленно отклонялся.

При этом action-bound одноразовые подтверждения записывающих операций и строгая одноразовость TOTP являются согласованной политикой и не подлежат ослаблению.

## Решение

### 1. Read-grant просмотра сессий

`GET /api/v1/auth/sessions` остаётся защищённым reauthentication proof с TTL 5 минут, привязанным к user/session/security revision/action/body. Сервер по-прежнему не погашает его для GET и отклоняет для mutation.

Клиент сохраняет полученный grant в **tab-scoped `sessionStorage`** (`alxprgs.sso.sessions-read-grant.v1`) вместе с серверным `expires_at`:

- при reload в пределах TTL повторное подтверждение не запрашивается;
- запись удаляется при login/logout, смене CSRF-сессии, истечении, 401 от сервера и после успешного нового подтверждения;
- grant отправляется только в `GET /api/v1/auth/sessions`; mutations никогда его не используют;
- одинаковые concurrent GET объединяются в один запрос подтверждения.

`localStorage` не используется: grant не должен переживать закрытие вкладки и не должен разделяться между вкладками. Новая вкладка требует отдельного подтверждения — это принятая цена.

### 2. Reauth-диалог

- Очередь подтверждений вместо немедленного reject; отмена отклоняет текущую и все ожидающие операции.
- Mutation-proof никогда не разделяется между запросами.
- После `totp_code_reused` показывается пояснение об одноразовости и countdown до следующего кода; authorization остаётся валидным, пароль не запрашивается заново.
- При истечении/инвалидации authorization диалог возвращается к шагу пароля с явным сообщением.

### 3. Повторный TOTP

`verify_totp` при `replay_error=True` (только authenticated elevation/reauthentication) различает «неверный код» и «код уже погашен»: для второго поднимается `TOTPReplayException` → `401 totp_code_reused` с `Retry-After`/`retry_after`. Replay не увеличивает `failed_attempts`. Политика `matched > last_verified_step` под row lock не изменена; код не принимается дважды ни на одном пути.

### 4. Один пароль для смены режима регистрации

`POST /api/v1/admin/system/registration-mode`: action-bound proof (пароль + настроенный фактор, привязка к телу) является подтверждением REG-02. Legacy-поле `current_admin_password` остаётся необязательным и проверяется только если передано; новый клиент его не отправляет.

### 5. Authorization до reauthentication для admin API

RBAC/assurance проверяются до выдачи reauth-челленджа. Regular user получает `403 forbidden` без создания `SecurityAuthorization`; admin без assurance — `403 admin_mfa_required`; anonymous — `401`.

## Альтернативы

1. **Не сохранять grant между reload.** Отклонено: противоречит документированному пятиминутному сроку и является основной причиной жалобы.
2. **`localStorage`.** Отклонено: bearer-подобный секрет не должен разделяться между вкладками и переживать сессию.
3. **Серверный флаг «сессии можно читать 5 минут» без proof-токена.** Отклонено: любой запрос с cookie мог бы читать список без подтверждения, что снижает channel binding.
4. **Разрешить повторное использование TOTP в пределах шага.** Отклонено: ослабляет replay protection и делает код многоразовым ключом.
5. **Убрать отдельное поле пароля, но оставить проверку всегда обязательной.** Невозможно без второго ввода; action-bound proof уже проверяет тот же credential.

## Последствия

- Меньше необоснованных подтверждений; политика one-proof-per-mutation сохранена.
- Появляется JS-читаемый read-only grant с TTL 5 минут; impact ограничен списком собственных сессий, mutation недоступны. Это осознанный trade-off, зафиксированный в threat model.
- Повторный TOTP-код по-прежнему отклоняется; UX объясняет причину и не сжигает попытки.
- Legacy-клиенты с паролем в теле продолжают работать; поле помечено устаревшим.
- Порядок зависимостей admin router (RBAC → reauth) закреплён regression-тестом.

## Проверки

`tests/integration/test_totp_reauth_replay_pg.py`, `test_registration_mode_reauth_pg.py`, `test_admin_authorization_order_pg.py`, `tests/test_totp_policy.py`; frontend `session-grants.component.test.tsx`, `ReauthenticationDialog.component.test.tsx`, `App.component.test.tsx`; Playwright `sso.spec.ts` 02/04/06, `totp.spec.ts`.

# Разбор частого Password + 2FA и 30-секундного TOTP (26.10.2026)

Документ фиксирует инструментирование локального потока `UI action → HTTP → 401/403 → reauthentication → proof → retry → response`, причины повторных подтверждений и решение. Все эксперименты — на синтетических аккаунтах, без production.

## 1. Как устроено подтверждение (до изменений)

1. `frontend/src/api/client.ts` при `401 reauthentication_required` вычисляет canonical SHA-256 тела, вызывает зарегистрированный handler и повторяет **только исходный** запрос с `X-Reauthentication`.
2. `ReauthenticationDialog` собирает пароль, затем второй фактор; `POST /api/v1/auth/reauthentication` + `/factor`.
3. Сервер (`reauthentication_service.py`) выдаёт одноразовый proof, привязанный к user/session/revision/action/body; для mutation он погашается в той же транзакции, для `GET /api/v1/auth/sessions` — переиспользуется 5 минут.

Инструментирование: Playwright-скрипт логировал все `/api/*` запросы/ответы, открытия диалога, `sessionStorage`, ошибки консоли. Скрипт не коммитится (временный), результаты ниже воспроизводимы вручную.

## 2. Наблюдения

| Сценарий | До исправлений | После |
| --- | --- | --- |
| Первый визит `/account/sessions` (SPA) | 1 диалог, затем 200 | 1 диалог |
| Уйти в «Профиль» и вернуться (SPA) | диалога нет (grant в памяти) | диалога нет |
| F5 на `/account/sessions` в пределах 5 минут | **снова диалог** | диалога нет; GET с сохранённым grant возвращает 200 |
| Новая вкладка в том же профиле | **снова диалог** | снова диалог (осознанно; см. §5) |
| Смена режима регистрации | **пароль в форме + пароль в диалоге + MFA** | один диалог: пароль + MFA |
| Второй чувствительный запрос при открытом диалоге | `reject("Дождитесь завершения…")`, операция терялась | ставится в очередь, подтверждается следующим |
| TOTP-код, уже принятый при login, для reauth | generic 401; повторные попытки инкрементировали `failed_attempts` | `401 totp_code_reused` + `Retry-After`, budget не расходуется, UI countdown |
| Concurrent два одинаковых GET /sessions | два диалога (второй падал) | один общий диалог, один grant |
| Отмена диалога | reject исходного запроса | reject текущего и всей очереди, без unhandled rejection |

Дополнительно проверено, что диалог **не** появляется на `/` (профиль), `/admin/system` (чтение), `/account/security` (чтение passkey credentials) — ложных срабатываний на GET нет.

## 3. Причины повторений

1. **AUD-2026-02:** серверный read grant корректен, но клиент хранил его только в памяти модуля. Любой full reload (в т.ч. переход по внешней ссылке/обновление) терял grant → новый password+MFA, хотя политика обещает 5 минут. Это не «дыра», но нарушение обещанного UX-контракта.
2. **AUD-2026-01:** legacy-поле `current_admin_password` дублировало action-bound proof; пользователь вводил пароль дважды.
3. **AUD-2026-03:** replay TOTP не отличался от неверного кода. Пользователь после login почти всегда попадал в тот же 30-секундный шаг; повторные попытки выглядели как ошибки и могли исчерпать 5 попыток, после чего требовался новый пароль.
4. **AUD-2026-06:** второй конкурентный запрос немедленно отклонялся, поэтому некоторые операции требовали ручного повтора (воспринимается как «ещё одно подтверждение»).
5. **Политика, не баг:** каждая записывающая критическая операция (admin mutations, смена пароля, TOTP/Passkey/recovery, отзыв сессии) требует отдельного одноразового proof. Это сохранено: объединение mutation-proof запрещено.

## 4. Что изменено

- `client.ts`: tab-scoped `sessionStorage` для read grant с серверным `expires_at`; очистка при login/logout/401/expiry; grant никогда не уходит мутациям; coalescing одинаковых concurrent GET; `ApiError.retryAfter`.
- `ReauthenticationDialog.tsx`: очередь вместо reject; понятное пояснение для read vs mutation; текст об одноразовости TOTP; countdown после `totp_code_reused`; при истечении authorization — возврат к шагу пароля с сообщением.
- Backend: distinct replay error + headers (AUD-2026-03/04); RBAC до reauth для admin (AUD-2026-05); optional legacy password (AUD-2026-01).
- Добавлены регрессии: PostgreSQL (TOTP replay, registration-mode proof, admin order), frontend unit/component, Playwright (reload grant, один пароль).

## 5. Почему один TOTP нельзя использовать дважды

RFC 6238 TOTP — одноразовый пароль в рамках шага. Если разрешить повторное использование «уже успешного» кода, украденный/подсмотренный код становится многоразовым ключом на окно до 90 секунд (valid_window ±1), а reauth-proof перестаёт быть доказательством присутствия. Поэтому:

- `TOTPCredential.last_verified_step` обновляется под `SELECT … FOR UPDATE` вместе с user row lock; следующий код должен быть строго больше.
- Один код не проходит: повторно в том же flow; во втором браузере; при конкурентных запросах; после login для reauth; после enrollment для elevation.
- Изменения аудита **не ослабляют** это: replay теперь возвращает отдельную ошибку и не тратит failed-attempt budget, но по-прежнему не принимается. `last_verified_step` не удалён, окно и проверки не расширены.
- UX-компенсация: пояснение, countdown, предпочтение Passkey, сохранение authorization (не нужно заново вводить пароль).

## 6. Остаточный UX

- В пределах одного шага вторую операцию нельзя подтвердить тем же кодом — нужно дождаться следующего (≤30 с) или использовать Passkey.
- Новая вкладка требует отдельного подтверждения: `sessionStorage` не разделяется между вкладками, а `localStorage` для bearer-подобного grant сознательно не используется.
- Каждая mutation требует отдельного proof по политике; это не «частые ошибки», а согласованный уровень защиты.

## 7. Воспроизведение

```powershell
# 1. отдельная PostgreSQL 16 на 127.0.0.1:5433 + marker (docs/testing/README.md)
# 2. backend default-on и frontend preview (scripts/manage_test_server.py)
# 3. seed: python scripts/prepare_e2e_data.py
# 4. Playwright: e2e/sso.spec.ts (06), e2e/totp.spec.ts
python -m pytest tests/integration/test_totp_reauth_replay_pg.py tests/integration/test_registration_mode_reauth_pg.py -q
cd frontend; npm run test:components
```

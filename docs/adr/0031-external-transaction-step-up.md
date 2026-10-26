# ADR-0031: Cross-application transaction step-up

- Статус: accepted для реализации; production-активация не выполнена
- Дата: 2026-10-26
- Область: OIDC client policy, hosted step-up, transaction-bound proof, Python SDK
- Связанные документы: [API](../api.md), [безопасность](../security.md), [SDK](../sdk.md), [миграция](../migration.md)

## Контекст

Обычный OIDC login подтверждает, что пользователь вошёл в SSO. Он не доказывает,
что пользователь в момент выполнения конкретного опасного действия на стороне
внешнего приложения всё ещё присутствует, прошёл требуемый фактор и согласен
именно с этой операцией. `prompt=login`, `max_age=0` и свежий `auth_time` не
являются transaction authorization: они не привязывают consent к canonical
payload, не защищают от повторного использования короткого login-события и не
дают RP проверяемого одноразового результата.

SSO уже имеет внутренний `SecurityAuthorization` для собственных mutations:
password → configured MFA, action/body digest, security revision, session binding,
5-минутный TTL и атомарное погашение. Этот proof нельзя открыть внешним клиентам:
он выпускается для маршрутов самого SSO и привязан к browser session.

## Рассмотренные варианты

### A. Только стандартный OIDC step-up (`acr_values`, `auth_time`, `amr`)

Плюсы: знакомый OIDC, минимальный новый протокол, работает с существующими
библиотеками. Минусы: стандартный Authorization Code подтверждает вход, но не
привязывает consent к action/payload; `acr`/`amr` описывают authentication
context, а не конкретную операцию; повторное использование code регулируется
PKCE и TTL, но нет явного контракта «это доказательство можно применить только
к этой транзакции». Для административных действий этого недостаточно.

### B. Отдельное transaction authorization разрешение

Плюсы: точная привязка к client/user/action/payload/session, одноразовое
погашение. Минусы: если строить его вне OIDC, появляется второй набор
client/redirect/JWT правил и риск расхождения с issuer/audience/JWKS. Это
усложняет сопровождение и интеграцию.

### C. Гибрид: OIDC-совместимый hosted step-up + одноразовый transaction proof

Выбран. Используются существующие OIDC client registry, confidential client
authentication, точные redirect URI, PKCE S256, state, nonce, RS256/JWKS и
issuer. Поверх них добавляется отдельный, явно ограниченный протокол:

1. RP backend создаёт challenge для exact `subject/action/payload_hash`.
2. SSO-hosted страница показывает client name из регистрации и server-fixed
   описание операции; браузер не присылает произвольное описание.
3. Пользователь проходит policy-driven password/TOTP/Passkey (с обязательным
   порядком password → second factor для комбинированных политик).
4. SSO возвращает exact registered redirect URI одноразовый code.
5. RP backend погашает code с PKCE и получает короткоживущий JWT
   `external_step_up_proof`; одноразовость обеспечивает PostgreSQL state, а не
   подпись JWT.
6. RP локально проверяет issuer/audience/subject/action/payload/acr/amr/nonce и
   только затем выполняет действие.

## Assurance policy

| Уровень | Допустимые планы |
| --- | --- |
| `reauth_basic` | password; Passkey UV |
| `reauth_mfa` | Passkey UV; password + TOTP |
| `reauth_password_mfa` | password + TOTP; password + Passkey UV |
| `reauth_strict` | password + Passkey UV |

Passkey с обязательным user verification считается phishing-resistant
multifactor. TOTP никогда не удовлетворяет MFA без свежего password. Recovery
code исключён из transaction step-up. Выключенный feature flag или
неподтверждённый/удалённый фактор не считается доступным. Пароль не обновляет
глобальную session freshness; он подтверждает только данную операцию.

## Trust boundaries и инварианты

- RP не получает password, TOTP-код, WebAuthn assertion для самостоятельной
  проверки, MFA-секрет или приватный ключ Passkey.
- `client_id` без confidential client authentication не даёт права создать или
  погасить proof; public clients не получают эту возможность.
- Browser URL содержит только непрозрачный request token; proof code передаётся
  в exact redirect URI, живёт не более 60 секунд и погашается server-side.
- Request token не является разрешением: нужна live SSO session, совпадающий
  subject, session binding и совпадающая security revision.
- `session_id` фиксируется при первом authenticated view; другая browser session
  получает отказ. Logout, password/MFA/Passkey change, block, delete, client
  deactivation и истечение срока инвалидируют pending request/proof.
- `state` связывает callback с RP flow; `nonce` входит в подписанный proof.
- JWT имеет отдельный `token_use`, `aud=client_id`, issuer, auth_time, action,
  payload hash и transaction ID. Он не принимается как Access/ID Token.
- Повторное погашение, гонка двух workers, неверный client/redirect/PKCE,
  изменённый payload истёкший/отозванный proof отклоняются.
- Feature flag `FEATURE_EXTERNAL_STEP_UP_ENABLED=false` по умолчанию; каждый
  client после миграции имеет `step_up_enabled=false` и пустые policy lists.

## PostgreSQL state

`external_step_up_requests` хранит хэш request token, client/user/session,
security revision, action, payload hash, assurance, plan, отметки факторов,
webauthn challenge, статус, хэш одноразового proof и TTL. Уникальные индексы на
request/proof hashes и `SELECT ... FOR UPDATE` обеспечивают атомарность.
Погашение меняет status/consumed_at в той же транзакции, в которой выпускается
JWT; сбой между ними откатывает оба изменения.

## SDK

SDK генерирует state/nonce/PKCE, сохраняет их в `StepUpRequest`, вызывает
creation/redeem через Basic client authentication, проверяет JWT по JWKS и
сравнивает subject/action/payload/acr/amr/nonce. Одноразовость обеспечивается
redemption; SDK не считает локальную проверку подписи достаточной.

## Совместимость

`/oauth/*` и внутренний `X-Reauthentication` не меняются. Discovery получает
дополнительные `acr_values_supported` и два custom endpoint metadata; старые
клиенты их игнорируют. Миграция добавляет только новые nullable/с-default
поля и таблицу, существующие clients остаются выключенными. Backend/SDK 0.3.0
совместимы с 0.2.0 OIDC-потоком; SDK step-up API новое и требует обновления
пакета.

## Остаточные риски

- Self-audit не заменяет независимый review, внешний OIF, нагрузочный тест
  нескольких реплик и production-мониторинг.
- Компрометация RP backend или его client secret позволяет создавать запросы и
  погашать proof от имени RP; SSO всё равно требует реального пользователя.
- In-memory demo RP не является production persistence; reference UI не
  заменяет review frontend CSP/edge.
- Стандартные OIDC RP, не обновлённые до 0.3.0 SDK, не используют новый flow;
  это осознанно, автоматическое включение отсутствует.

## Ссылки

- [RFC 9470 — OAuth 2.0 Step Up Authentication Challenge Protocol](https://www.rfc-editor.org/rfc/rfc9470.html)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/)
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html)
- [OWASP Transaction Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transaction_Authorization_Cheat_Sheet.html)
- [NIST SP 800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html)

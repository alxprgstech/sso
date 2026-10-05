# API ALXPRGS SSO

Версия продукта0.2.0. Целевой HTTPS issuer `https://auth.alxprgs.tech` — проектный адрес, не свидетельство существующего production. Local HTTP разрешён только выбранному development/testing профилю. Нормативный machine-readable интерфейс — FastAPI OpenAPI из данной ревизии; список ниже проверяется `tests/test_documented_api_contract.py`.

Cookie API использует host-only HttpOnly cookie (`__Host-alx_session`/Secure в production); mutations требуют `X-CSRF-Token` и точный Origin. OAuth client/grant authentication не подменяется browser cookie. JSON errors не отражают raw inputs/SQL/secrets. OAuth errors имеют `error/error_description`; responses `/oauth/*` включают `Cache-Control:no-store`, `Pragma:no-cache`, Basic/Bearer challenges при применимости. Duplicate query/form parameters отвергаются.

Discovery: `/.well-known/openid-configuration`, публичный JWKS: `/.well-known/jwks.json`. Только Authorization Code + PKCE S256, verifier43–128 ASCII unreserved, challenge43base64url без padding. Redirect URI совпадает буквально с зарегистрированным. `scope` включает openid и входит в per-client `allowed_scopes`; profile/email claims подавляются без соответствующего grant. Обязательные JWT profiles/access vs ID разделены.

`GET /oauth/authorize`: response_type=code/client_id/redirect_uri/code_challenge обязательны; code_challenge_method=S256, scope/state/nonce, prompt=login|none и max_age integer0..604800. Prompt login/max_age0 требуют новой аутентификации; чтение API и refresh не меняют auth_time. Prompt none никогда не показывает UI, возвращает login_required/interaction_required. Ошибки перенаправляются с state только после проверки зарегистрированного redirect; при неизвестном client/redirect Location отсутствует.

`GET /oauth/client-context`: публичная read-only метаинформация для страницы входа. Обязательны client_id (1–64) и redirect_uri (1–512); проверяются активный зарегистрированный клиент и буквальное совпадение redirect URI. Ответ содержит только client_name и redirect_origin (scheme + host/port), no-store/no-cache, без cookie/session/code/grant. Общий OAuth limiter и запрет duplicate parameters сохраняются. Query client_name/logo frontend не использует. Это не согласие OAuth и не проверка authorize-параметров вместо /authorize.

`POST /oauth/token`: URL-encoded grant_type=authorization_code с code/verifier/redirect либо refresh_token с текущим refresh. Confidential client аутентифицируется Basic или form secret (один метод), public — client_id+PKCE. Code одноразовый; refresh заменяется при каждом использовании, replay отзывает семейство. UserInfo GET/POST принимает только Bearer Access Token с текущим account state. Revocation form token/client credentials: own refresh отзывает grant, unknown/SSO cookie/other-client token возвращает совместимый успех без удаления OP-сессии.

`GET/POST /oauth/logout`: id_token_hint, post_logout_redirect_uri, client_id и state по применимости. Подпись/issuer/ID profile/client/subject/redirect проверяются; expired signed hint допустим только с соответствующей live OP session/auth_time. Без hint GET показывает подтверждение, POST требует её CSRF и exact Origin. Успешный logout удаляет OP session и cookie; RP самостоятельно закрывает свою локальную session. Front/back-channel logout не заявлены.

Самостоятельная регистрация: POST register создаёт заявку202/challenge_id, не User. Обязательны username/email/password/confirm_password, terms_accepted/data_processing_consent=true и актуальные legal_versions из public documents. Confirm-code/link после реального подтверждения email создаёт пользователя200; resend инвалидирует старые secrets. FEATURE_EMAIL_VERIFICATION_ENABLED=false отвергается. REQUIRE_VERIFIED_EMAIL управляет входом legacy/admin-created адресов на всех grant/session/UserInfo путях.

Login возвращает user/csrf_token либо mfa_required/mfa_token/methods; полноценных cookies до фактора нет. Admin recovery/create password временный15min/one restricted use: session_purpose=password_change10min, обычные grants запрещены; change-password после успеха возвращает requires_login=true и удаляет cookie. Обычная password mutation отзывает старые grants и сохраняет только текущую сессию с новой revision. Password policy15–128 + blocklist; recovery code35formatted characters/32normalized.

Чувствительные mutations требуют header `X-Reauthentication`. При отсутствии proof API403 с reauthentication_required/action/payload_hash: canonical SHA-256 точного request body. POST `/api/v1/auth/reauthentication` принимает current_password/action/payload_hash; настроенный MFA возвращает factor_required/options/methods. POST factor принимает authorization/method и code либо signed credential. Proof5min привязан к user/session/revision/action/body и погашается в транзакции mutation. ТOTP setup хранит только pending, confirm активирует после проверки; Passkey registration challenge также связан с Session. Feature-disabled APIs404 до начала операции.

Admin API: PATCH users/{user_id} изменяет email/is_active/is_superuser/roles/new_password; email всегда очищает verified, критические изменения отзывают grants. POST sessions/revoke — отдельная команда, не DELETE по выдуманному пути. Clients allowed_scopes задаётся при создании; secret показывается только один раз. Audit использует offset/limit/event_type, экспорт — отдельный /audit/export. Поля/точные bounds см. схемы OpenAPI и `backend/app/schemas`.

Privacy/legal/deletion и telemetry-контракты: [privacy.md](privacy.md), [observability.md](observability.md). Pending deletion допускает только ограниченное управление/выход; нет публичного API немедленного физического удаления. Body budget64KiB/10s; 413/408 при превышении. Quotas429 и инфраструктурные503 не означают успешной аутентификации.

Все зарегистрированные пути текущей ревизии:

| Метод | Путь |
| --- | --- |
| DELETE | `/api/v1/admin/clients/{client_id}` |
| DELETE | `/api/v1/auth/account-deletion` |
| DELETE | `/api/v1/auth/sessions` |
| DELETE | `/api/v1/auth/sessions/{session_id}` |
| DELETE | `/api/v1/mfa/passkey/credentials/{credential_id}` |
| DELETE | `/api/v1/mfa/totp` |
| GET | `/.well-known/jwks.json` |
| GET | `/.well-known/openid-configuration` |
| GET | `/api/v1/admin/audit` |
| GET | `/api/v1/admin/audit/export` |
| GET | `/api/v1/admin/clients` |
| GET | `/api/v1/admin/system/status` |
| GET | `/api/v1/admin/users` |
| GET | `/api/v1/admin/users/{user_id}` |
| GET | `/api/v1/auth/account-deletion` |
| GET | `/api/v1/auth/capabilities` |
| GET | `/api/v1/auth/me` |
| GET | `/api/v1/auth/sessions` |
| GET | `/api/v1/auth/telemetry-config` |
| GET | `/api/v1/legal/documents` |
| GET | `/api/v1/mfa/passkey/credentials` |
| GET | `/health/live` |
| GET | `/health/ready` |
| GET | `/oauth/authorize` |
| GET | `/oauth/client-context` |
| GET | `/oauth/logout` |
| GET | `/oauth/userinfo` |
| PATCH | `/api/v1/admin/users/{user_id}` |
| POST | `/api/v1/admin/clients` |
| POST | `/api/v1/admin/clients/{client_id}/rotate-secret` |
| POST | `/api/v1/admin/system/registration-mode` |
| POST | `/api/v1/admin/users` |
| POST | `/api/v1/admin/users/{user_id}/sessions/revoke` |
| POST | `/api/v1/auth/account-deletion` |
| POST | `/api/v1/auth/account-deletion/confirm-factor` |
| POST | `/api/v1/auth/account-deletion/reauthenticate` |
| POST | `/api/v1/auth/change-password` |
| POST | `/api/v1/auth/legal-acceptance` |
| POST | `/api/v1/auth/login` |
| POST | `/api/v1/auth/logout` |
| POST | `/api/v1/auth/reauthentication` |
| POST | `/api/v1/auth/reauthentication/factor` |
| POST | `/api/v1/auth/register` |
| POST | `/api/v1/auth/register/confirm-code` |
| POST | `/api/v1/auth/register/confirm-gmail` |
| POST | `/api/v1/auth/register/confirm-link` |
| POST | `/api/v1/auth/register/preview-link` |
| POST | `/api/v1/auth/register/resend` |
| POST | `/api/v1/mfa/email/confirm` |
| POST | `/api/v1/mfa/email/confirm-code` |
| POST | `/api/v1/mfa/email/request` |
| POST | `/api/v1/mfa/passkey/auth/options` |
| POST | `/api/v1/mfa/passkey/auth/verify` |
| POST | `/api/v1/mfa/passkey/register/options` |
| POST | `/api/v1/mfa/passkey/register/verify` |
| POST | `/api/v1/mfa/recovery-codes/generate` |
| POST | `/api/v1/mfa/recovery-codes/verify` |
| POST | `/api/v1/mfa/totp/confirm` |
| POST | `/api/v1/mfa/totp/setup` |
| POST | `/api/v1/mfa/totp/verify` |
| POST | `/oauth/logout` |
| POST | `/oauth/revoke` |
| POST | `/oauth/token` |
| POST | `/oauth/userinfo` |

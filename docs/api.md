# API ALXPRGS SSO

Версия продукта 0.3.0. Целевой HTTPS issuer `https://auth.alxprgs.tech` — проектный адрес, не свидетельство существующего production. Local HTTP разрешён только выбранному development/testing профилю. Нормативный machine-readable интерфейс — FastAPI OpenAPI из данной ревизии; список ниже проверяется `tests/test_documented_api_contract.py`.

Cookie API использует host-only HttpOnly cookie (`__Host-alx_session`/Secure в production); mutations требуют `X-CSRF-Token` и точный Origin. OAuth client/grant authentication не подменяется browser cookie. JSON errors не отражают raw inputs/SQL/secrets. OAuth errors имеют `error/error_description`; responses `/oauth/*` включают `Cache-Control:no-store`, `Pragma:no-cache`, Basic/Bearer challenges при применимости. Duplicate query/form parameters отвергаются.

Discovery: `/.well-known/openid-configuration`, публичный JWKS: `/.well-known/jwks.json`. Только Authorization Code + PKCE S256, verifier43–128 ASCII unreserved, challenge43base64url без padding. Redirect URI совпадает буквально с зарегистрированным. `scope` включает openid и входит в per-client `allowed_scopes`; profile/email claims подавляются без соответствующего grant. Обязательные JWT profiles/access vs ID разделены.

`GET /oauth/authorize`: response_type=code/client_id/redirect_uri/code_challenge обязательны; code_challenge_method=S256, scope/state/nonce, prompt=login|none и max_age integer0..604800. Prompt login/max_age0 требуют новой аутентификации; чтение API и refresh не меняют auth_time. Prompt none никогда не показывает UI, возвращает login_required/interaction_required. Ошибки перенаправляются с state только после проверки зарегистрированного redirect; при неизвестном client/redirect Location отсутствует.

`GET /oauth/client-context`: публичная read-only метаинформация для страницы входа. Обязательны client_id (1–64) и redirect_uri (1–512); проверяются активный зарегистрированный клиент и буквальное совпадение redirect URI. Ответ содержит только client_name и redirect_origin (scheme + host/port), no-store/no-cache, без cookie/session/code/grant. Общий OAuth limiter и запрет duplicate parameters сохраняются. Query client_name/logo frontend не использует. Это не согласие OAuth и не проверка authorize-параметров вместо /authorize.

`POST /oauth/token`: URL-encoded grant_type=authorization_code с code/verifier/redirect либо refresh_token с текущим refresh. Confidential client аутентифицируется Basic или form secret (один метод), public — client_id+PKCE. Code одноразовый; refresh заменяется при каждом использовании, replay отзывает семейство. UserInfo GET/POST принимает только Bearer Access Token с текущим account state. Revocation form token/client credentials: own refresh отзывает grant, unknown/SSO cookie/other-client token возвращает совместимый успех без удаления OP-сессии.

`GET/POST /oauth/logout`: id_token_hint, post_logout_redirect_uri, client_id и state по применимости. Подпись/issuer/ID profile/client/subject/redirect проверяются; expired signed hint допустим только с соответствующей live OP session/auth_time. Без hint GET показывает подтверждение, POST требует её CSRF и exact Origin. Успешный logout удаляет OP session и cookie; RP самостоятельно закрывает свою локальную session. Front/back-channel logout не заявлены.

Самостоятельная регистрация: POST register создаёт заявку202/challenge_id, не User. Обязательны username/email/password/confirm_password, terms_accepted/data_processing_consent=true и актуальные legal_versions из public documents. Confirm-code/link после реального подтверждения email создаёт пользователя200; resend инвалидирует старые secrets. FEATURE_EMAIL_VERIFICATION_ENABLED=false отвергается. REQUIRE_VERIFIED_EMAIL управляет входом legacy/admin-created адресов на всех grant/session/UserInfo путях.

Login возвращает user/csrf_token либо mfa_required/mfa_token/methods; полноценных cookies до фактора нет. Admin recovery/create password временный15min/one restricted use: session_purpose=password_change10min, обычные grants запрещены; change-password после успеха возвращает requires_login=true и удаляет cookie. Обычная password mutation отзывает старые grants и сохраняет только текущую сессию с новой revision. Password policy15–128 + blocklist; recovery code35formatted characters/32normalized.

Чувствительные mutations требуют header `X-Reauthentication`. При отсутствии proof API401 с reauthentication_required. payload_hash — canonical SHA-256 точного request body. POST `/api/v1/auth/reauthentication` принимает current_password/action/payload_hash; настроенный MFA возвращает factor_required/options/methods. POST factor принимает authorization/method и code либо signed credential. Proof5min привязан к user/session/revision/action/body и погашается в транзакции mutation. ТOTP setup хранит только pending, confirm активирует после проверки; Passkey registration challenge также связан с Session. Feature-disabled APIs404 до начала операции.

Повторный TOTP-шаг: `POST /api/v1/auth/reauthentication/factor` (и `session/elevate`) возвращает `401` с `error=totp_code_reused`, `detail`, `retry_after` и заголовком `Retry-After`, если код структурно верный, но его временной шаг уже погашен. Такой ответ не увеличивает `failed_attempts`; одноразовое authorization остаётся валидным, и следующий код можно ввести без повторного пароля. Неверный код по-прежнему даёт generic `reauthentication_required` и считается неудачной попыткой. Код не принимается дважды ни при каких условиях.

`GET /api/v1/auth/sessions` требует password+настроенный фактор один раз на 5 минут: proof привязан к action `GET /api/v1/auth/sessions`, переиспользуется для чтения в пределах TTL и отклоняется для mutation. Frontend сохраняет этот read grant в tab-scoped `sessionStorage` вместе с серверным `expires_at`, очищает при login/logout/401/истечении; mutation-proof никогда не кэшируется ([ADR-0034](adr/0034-reauthentication-ux-and-session-read-grant.md)).

`POST /api/v1/admin/system/registration-mode` принимает `{"mode":"closed|open"}`. Action-bound proof (пароль + настроенный фактор, привязка к телу) является подтверждением REG-02; legacy-поле `current_admin_password` необязательно и проверяется только если передано. Новым клиентам не нужно вводить пароль второй раз.

Admin API: PATCH users/{user_id} изменяет email/is_active/is_superuser/roles/new_password; email всегда очищает verified, критические изменения отзывают grants. POST sessions/revoke — отдельная команда, не DELETE по выдуманному пути. Clients allowed_scopes задаётся при создании; secret показывается только один раз. Audit использует offset/limit/event_type, экспорт — отдельный /audit/export. RBAC и session assurance проверяются до reauth-челленджа: regular user получает `403 forbidden` без создания proof, admin без assurance — `403 admin_mfa_required`, anonymous — `401`. Поля/точные bounds см. схемы OpenAPI и `backend/app/schemas`.

## MFA, session assurance и административный доступ

`GET /api/v1/auth/capabilities` возвращает `totp_enabled`, `passkey_enabled`, `recovery_codes_enabled`, `admin_mfa_required` и `registration_mode`. Default — все три MFA и admin policy `true`. `/api/v1/auth/login` без настроенного фактора создаёт обычную сессию (`mfa_verified=false`); пользователь с TOTP/Passkey получает `mfa_required`, `mfa_token` и `available_methods`. `/api/v1/mfa/totp/verify`, `/api/v1/mfa/passkey/auth/verify`, `/api/v1/mfa/recovery-codes/verify` завершают вход и создают assured-сессию. `/api/v1/auth/me` и login/elevation возвращают `mfa_verified`, `mfa_method`, `admin_mfa_required`, `session_purpose`.

Администратор без активного фактора после пароля получает `session_purpose=admin_mfa_enrollment`: доступны только `me/logout/legal`, TOTP/Passkey enrollment, управление собственными passkey, reauthentication и `POST /api/v1/auth/session/elevate`. Остальные пути отклоняются `401 admin_mfa_enrollment_required`. `POST /api/v1/auth/session/elevate` (CSRF) принимает `method=totp|passkey|recovery_code`, `code` либо `credential`; `POST /api/v1/auth/session/elevate/passkey/options` выдаёт fresh WebAuthn challenge. Успех пишет assurance в эту сессию, переводит onboarding в `full` и возвращает профиль. `auth_time`, cookie и клиентское поле `mfa_verified` не принимаются. Admin API без assurance возвращает `403 admin_mfa_required`.

OIDC access/ID tokens содержат `amr` (`pwd`, `otp`, `hwk`, `mfa`) и `acr` (`urn:alxprgs:acr:pwd`/`urn:alxprgs:acr:mfa`). Роль `admin` не выдаётся authorization code/refresh, созданному без требуемого assurance; UserInfo фильтрует её по `amr` токена. `auth_time` остаётся временем аутентификации, но не доказательством MFA. Recovery codes выпускаются при TOTP или Passkey после fresh reauth; коды одноразовые и не участвуют в external step-up.

## Cross-application transaction step-up

Новая возможность включена только при `FEATURE_EXTERNAL_STEP_UP_ENABLED=true`; у клиента дополнительно должны быть `step_up_enabled=true`, разрешённый `action` и assurance. Это opt-in, существующие клиенты после миграции остаются выключенными. Все `/api/v1/step-up/*` ответы имеют `Cache-Control: no-store`; browser endpoints требуют host-only SSO cookie и CSRF, server-to-server endpoints — только существующую confidential client authentication (HTTP Basic). Публичный client_id не является разрешением.

`POST /api/v1/step-up/requests` (Basic client secret) принимает subject, action, payload_hash (SHA-256 hex), description, assurance, exact redirect_uri, state, nonce, PKCE S256 challenge и ttl 30–300. Сервер проверяет клиентскую policy, фактические факторы пользователя, pending caps и возвращает короткоживущий `authorization_url`; браузер не получает client secret. `GET /api/v1/step-up/requests/{request_token}` требует SSO session, привязывает запрос к первой сессии и проверяет subject/security_revision/client policy. `POST .../passkey/options`, `.../verify` и `.../deny` требуют CSRF; verify выполняет реальную проверку password/WebAuthn/TOTP и строго соблюдает порядок password → второй фактор, когда он требуется.

При успехе SSO возвращает exact registered redirect URI одноразовый `code`, `state` и `iss`; `code` живёт не более 60 секунд. `POST /api/v1/step-up/redeem` (Basic client secret, code, PKCE verifier, redirect_uri) атомарно погашает proof и возвращает RS256 JWT с `token_use=external_step_up_proof`, `aud=client_id`, `sub`, `acr`, `amr`, `transaction_id`, `action`, `payload_hash`, `nonce` и `security_revision`. Это доказательство, а не OAuth Access/ID Token и не универсальный grant. Повторное погашение, другой client, другой redirect, другой subject, изменённый payload, истёкший срок и отозванная session отклоняются. `GET /.well-known/openid-configuration` публикует `acr_values_supported`, а также `external_step_up_request_endpoint`/`external_step_up_redemption_endpoint`; стандартный OIDC login и `/oauth/*` не меняются.

`PATCH /api/v1/admin/clients/{client_id}/step-up` (admin + внутренний reauth/CSRF) задаёт `step_up_enabled`, assurance levels, actions и max TTL. Включать step-up можно только confidential-клиенту; пустые списки при включении отклоняются. Существующие public/legacy клиенты не получают возможность автоматически.

Privacy/legal/deletion и telemetry-контракты: [privacy.md](privacy.md), [observability.md](observability.md). Pending deletion допускает только ограниченное управление/выход; нет публичного API немедленного физического удаления. Body budget64KiB/10s; 413/408 при превышении. Quotas429 и инфраструктурные503 не означают успешной аутентификации.

`GET /health/identity` — небольшой публичный runtime-контракт для CD: при готовой БД и известной встроенной build metadata возвращает `200` и ровно `{"status":"ready","database":"connected","commit_sha":"<40 lowercase hex>"}`; при недоступной БД или отсутствии/повреждении metadata — `503` с `status=unavailable` и тем же полем `commit_sha` (пустая строка, если SHA неизвестен). Ответ содержит только эти поля, не включает конфигурацию, пути сервера, запросные данные или секреты и всегда имеет `Cache-Control: no-store`/`Pragma: no-cache`. Endpoint не заменяет `/health/ready` для мониторинга и не доказывает корректность установки без опубликованного frontend `build-info.json`.

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
| GET | `/health/identity` |
| GET | `/health/live` |
| GET | `/health/ready` |
| GET | `/oauth/authorize` |
| GET | `/oauth/client-context` |
| GET | `/oauth/logout` |
| GET | `/oauth/userinfo` |
| PATCH | `/api/v1/admin/clients/{client_id}/step-up` |
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
| POST | `/api/v1/auth/session/elevate` |
| POST | `/api/v1/auth/session/elevate/passkey/options` |
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
| POST | `/api/v1/step-up/redeem` |
| POST | `/api/v1/step-up/requests` |
| POST | `/api/v1/step-up/requests/{request_token}/deny` |
| POST | `/api/v1/step-up/requests/{request_token}/passkey/options` |
| POST | `/api/v1/step-up/requests/{request_token}/verify` |
| GET | `/api/v1/step-up/requests/{request_token}` |
| POST | `/oauth/logout` |
| POST | `/oauth/revoke` |
| POST | `/oauth/token` |
| POST | `/oauth/userinfo` |

## Источники контракта

[api-routes.json](api-routes.json) сверяется с app.openapi() существующим тестом. Поля — backend/app/schemas и handlers. Login/me возвращают csrf_token в JSON; клиент отправляет его в X-CSRF-Token. OpenAPI не доказывает транзакционную политику; [методика](03-test-procedure.md) описывает проверки.

## Изменения безопасности SEC-REMED-20261007

Gmail action `POST /api/v1/auth/register/confirm-gmail` требует query `challenge_id` и `action_token` (43 base64url символа, 32 случайных байта), а также действительный Google bearer и browser proof исходной регистрации (SSO-SEC-0005). Новые письма используют ViewAction для открытия страницы в исходном браузере. Секрет хранится как SHA-256, действует десять минут и меняется при resend. Подтверждение code/link/action атомарно удаляет pending; старые Gmail URL без секрета отвергаются. После0014 code/link/action также требуют browser proof; legacy pending требует повторного старта.

GET `/api/v1/auth/sessions` требует `X-Reauthentication` с exact action `GET /api/v1/auth/sessions` и digest пустого body. Допуск read-only действует пять минут, связан с user/session/security_revision и допускает повторные GET. DELETE списка или конкретной сессии требует собственного exact action/body одноразового proof; read grant для него не подходит. Отказ — 401 `reauthentication_required`. Logout не требует дополнительного proof.

Cookie-auth проверяет предоставленный Origin по точному allowlist BASE_URL/FRONTEND_URL. Если Origin отсутствует, предоставленный Referer проверяется по origin; отсутствие обоих не отменяет обязательный CSRF для mutations. Только OIDC front-channel GET `/oauth/authorize` и GET `/oauth/logout` допускают переход с Referer клиента без Origin: проверки client/redirect/PKCE, signed logout hint либо confirmation+CSRF остаются обязательными. Явный чужой Origin отвергается и на этих маршрутах. Redirect URI не допускает wildcard/userinfo/fragment/опасные schemes. HTTPS обязателен; `REDIRECT_TRANSPORT_PROFILE=local` допускает HTTP loopback только вне production. Matching URI с query остаётся буквальным. Небезопасные старые записи отвергаются при использовании.

### SSO-SEC-0002: отзыв OIDC-грантов
POST /api/v1/auth/logout и успешный GET/POST /oauth/logout, DELETE /api/v1/auth/sessions/{id} (только собственная существующая сессия), DELETE /api/v1/auth/sessions теперь также отзывают ВСЕ refresh-гранты и незавершённые authorization codes пользователя, независимо от устройства/клиента. Revoke-others сохраняет текущую browser session; logout/точечный revoke сохраняют другие browser sessions. Они могут начать новый OIDC-вход. Некорректный/чужой session_id не отзывает grants. Уже выданные accessJWT, включая UserInfo при неизменной revision, действуют до exp (до300с); автономный RP не получает мгновенного отзыва. RP закрывает собственную session самостоятельно.
OAuth token/revoke: раздельные source-IP квоты30/60с; 429 ограничивает источник, а не всех пользователей client_id. Проверки client_secret/PKCE/redirect/replay сохранены.

### SSO-SEC-0003: нейтральная регистрация
POST register для всех identities использует один путь: реальный Argon2, pending-заявка202/challenge_id и письмо с mailbox proof. Предварительной проверки существования User нет; повторныеID/send quotas/provider failures ведут себя одинаково для занятых и доступных identities. User и его credentials не меняются. Коллизия username/email разрешается только после действительного mailbox proof в confirm:409 без раскрытия поля и без создания/изменения User. MAX_SENDS3/час и source quotas сохранены. Resend неизвестного/исчерпанного challenge нейтрален202 без отправки. Ошибка провайдера для любой заявки503; pending сохраняется.202 не гарантирует доступность имени. Это единый кодовый путь, не обещание точного constant-time БД/сети.

### SSO-SEC-0005: enrollment browser proof
Register ставит host-only HttpOnly SameSite=Lax cookie alx_registration (__Host-alx_registration/Secure при HTTPS/production),1час. Confirm-code/link/gmail и resend требуют этот browser proof вместе с прежними mail/Google proofs; Для существующей свежей заявки чужой/отсутствующий/legacy proof→401, в том числе при исчерпанном send budget. Неизвестная/устаревшая заявка при resend возвращает нейтральный202 без отправки; существующая заявка с действительным browser proof и исчерпанным send budget также202 без отправки. Повторный start вращает все proofs; старый browser не подтверждает новые credentials. При потере cookie начните регистрацию заново. Ссылка должна открываться в исходном браузере; код из письма на другом устройстве вводите в исходной форме. Один активный flow на браузер. Origin/Referer проверяются на enrollment mutations. Новые письма содержат Gmail ViewAction→verification page, а не autonomous ConfirmAction. Старый Gmail API не создаёт аккаунт без browser proof. Старые pending после0014 требуют нового start.

SSO-SEC-0006: login квоты —30/60с source и5/60с identifier+source/account+source (username/email aliases суммируются). Превышение429 Retry-After60; Argon2 admission429 authentication_busy Retry-After1. Ошибка проверки quotas в БД остаётся503. Чужой source не расходует индивидуальное account окно владельца. Источники за одним NAT разделяют лимиты; успешные попытки тоже учитываются.

# Спецификация программных интерфейсов (API) ALXPRGS SSO

- **Версия**: 1.0.0
- **Дата**: 24.09.2026
- **Базовый URL**: `https://auth.alxprgs.tech` (локально: `http://localhost:8000`)
- **Формат обмена**: JSON (application/json), form-data (application/x-www-form-urlencoded)

---

## 1. Протокольные эндпоинты OpenID Connect и OAuth 2.0

### 1.1. Discovery
- **Метод**: `GET /.well-known/openid-configuration`
- **Аутентификация**: Не требуется
- **Ответ 200 OK**:
```json
{
  "issuer": "https://auth.alxprgs.tech",
  "authorization_endpoint": "https://auth.alxprgs.tech/oauth/authorize",
  "token_endpoint": "https://auth.alxprgs.tech/oauth/token",
  "userinfo_endpoint": "https://auth.alxprgs.tech/oauth/userinfo",
  "jwks_uri": "https://auth.alxprgs.tech/jwks.json",
  "revocation_endpoint": "https://auth.alxprgs.tech/oauth/revoke",
  "end_session_endpoint": "https://auth.alxprgs.tech/oauth/logout",
  "response_types_supported": ["code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["RS256"],
  "scopes_supported": ["openid", "profile", "email"],
  "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post", "none"],
  "code_challenge_methods_supported": ["S256"]
}
```

### 1.2. JSON Web Key Set (JWKS)
- **Метод**: `GET /jwks.json`
- **Аутентификация**: Не требуется
- **Ответ 200 OK**:
```json
{
  "keys": [
    {
      "kty": "RSA",
      "use": "sig",
      "alg": "RS256",
      "kid": "alx-sso-key-1",
      "n": "<base64url-modulus>",
      "e": "AQAB"
    }
  ]
}
```

### 1.3. Авторизация (Authorization Endpoint)
- **Метод**: `GET /oauth/authorize`
- **Параметры запроса (Query)**:
  - `response_type`: строго `code`
  - `client_id`: идентификатор клиента
  - `redirect_uri`: адрес перенаправления (точное совпадение)
  - `scope`: запрашиваемые скоупы (`openid profile email`)
  - `state`: значение для защиты от CSRF на клиенте
  - `nonce`: случайное значение для привязки ID Token
  - `code_challenge`: значение хеша `BASE64URL(SHA256(code_verifier))`
  - `code_challenge_method`: строго `S256`
- **Ответы**:
  - `302 Found`:
    - Если сессия SSO активна -> редирект на `redirect_uri?code=...&state=...`
    - Если сессия отсутствует -> редирект на страницу входа `/login?return_to=...`

### 1.4. Выпуск токенов (Token Endpoint)
- **Метод**: `POST /oauth/token`
- **Content-Type**: `application/x-www-form-urlencoded`
- **Вариант 1 (Обмен Authorization Code)**:
  - `grant_type`: `authorization_code`
  - `code`: одноразовый код
  - `redirect_uri`: совпадает с исходным
  - `client_id`: ID клиента
  - `client_secret`: секрет клиента (для confidential)
  - `code_verifier`: исходный PKCE верификатор
- **Вариант 2 (Ротация Refresh Token)**:
  - `grant_type`: `refresh_token`
  - `refresh_token`: текущий refresh токен
  - `client_id`: ID клиента
- **Ответ 200 OK**:
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIs...",
  "token_type": "Bearer",
  "expires_in": 300,
  "refresh_token": "rt_abc123...",
  "id_token": "eyJhbGciOiJSUzI1NiIs...",
  "scope": "openid profile email"
}
```

### 1.5. Профиль пользователя (UserInfo)
- **Метод**: `GET /oauth/userinfo` или `POST /oauth/userinfo`
- **Заголовок**: `Authorization: Bearer <access_token>` (ID Token строго отклоняется с 401)
- **Ответ 200 OK**:
```json
{
  "sub": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "preferred_username": "john_doe",
  "email": "john@alxprgs.tech",
  "email_verified": false,
  "roles": ["developer"]
}
```

### 1.6. Отзыв токена (Token Revocation RFC 7009)
- **Метод**: `POST /oauth/revoke`
- **Параметры (form-data)**:
  - `token`: токен для отзыва
  - `token_type_hint`: `access_token` или `refresh_token`
- **Ответ 200 OK**: `{"status": "revoked"}`

### 1.7. Выход (RP-Initiated Logout)
- **Метод**: `GET /oauth/logout`
- **Параметры**:
  - `post_logout_redirect_uri`: адрес возврата (опционально)
- **Ответ**: `302 Found` с удалением сессионного cookie.

---

## 2. API аутентификации и личного кабинета

### 2.1. Витрина возможностей
- **Метод**: `GET /api/v1/auth/capabilities`
- **Ответ 200 OK**:
```json
{
  "totp_enabled": false,
  "passkey_enabled": false,
  "recovery_codes_enabled": false,
  "email_verification_enabled": true,
  "require_verified_email": false,
  "registration_mode": "closed"
}
```

### 2.2. Самостоятельная регистрация пользователя (REG-01..REG-09)
- **Метод**: `POST /api/v1/auth/register`
- **Заголовки**: `Origin` (валидируется), `Content-Type: application/json`
- **Ограничения**: Доступен только при `registration_mode == "open"`. Защищён межпроцессными лимитами регистрации и отправки письма. Пользователь до подтверждения не создаётся.
- **Тело запроса**:
```json
{
  "username": "alex_ivanov",
  "email": "alex@alxprgs.tech",
  "password": "SecurePassword123!",
  "confirm_password": "SecurePassword123!"
}
```
- **Ответ 202 Accepted**:
```json
{
  "status": "verification_pending",
  "challenge_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "expires_at": "2026-09-29T16:00:00Z",
  "request_details": {"ip": "192.0.2.10", "city": "Неизвестно", "country": "Неизвестно"}
}
```
- **Ошибки**:
  - `403 Forbidden`: `{"detail": "Самостоятельная регистрация пользователей в настоящий момент закрыта"}` (если режим `closed`);
  - `409 Conflict`: `{"detail": {"error": "user_already_exists", "detail": "Пользователь с указанными учётными данными уже существует"}}` (без раскрытия совпавшего поля);
  - `429 Too Many Requests`: `{"detail": {"error": "rate_limit_exceeded"}}`.
  - `503 Service Unavailable`: доставка письма не удалась; заявка остаётся, письмо можно запросить снова.

Подтверждение кода: `POST /api/v1/auth/register/confirm-code` с `{"challenge_id":"...","code":"000123"}`. Подтверждение ссылки: `POST /api/v1/auth/register/confirm-link` с `{"token":"..."}`. Оба при успехе возвращают HTTP 200 и `{"status":"ok","user_id":"..."}`; код и ссылка действуют 10 минут и погашаются один раз. Пять неверных кодов блокируют текущий код. Повтор письма: `POST /api/v1/auth/register/resend` с `{"challenge_id":"..."}` возвращает HTTP 202 и новый срок; прежние код и ссылка гаснут. `POST /api/v1/auth/register/preview-link` возвращает сведения о запросе без погашения ссылки. Gmail action `POST /api/v1/auth/register/confirm-gmail?challenge_id=...` доступен только при проверенном Google bearer token. Клиентам прежнего API необходимо перейти с ответа `201/user_id` на `202/challenge_id` и отдельное подтверждение.

### 2.3. Вход по паролю
- **Метод**: `POST /api/v1/auth/login`
- **Тело запроса**:
```json
{
  "username": "admin",
  "password": "StrongPassword123!"
}
```
- **Ответ 200 OK**:
```json
{
  "mfa_required": false,
  "csrf_token": "d7a8f9...",
  "user": {
    "id": "...",
    "username": "admin",
    "email": "admin@alxprgs.tech",
    "is_superuser": true,
    "roles": ["admin"]
  }
}
```
- **Заголовки ответа**: `Set-Cookie: alx_session=...; HttpOnly; SameSite=Lax; Path=/`

### 2.3. Выход из сессии
- **Метод**: `POST /api/v1/auth/logout`
- **Заголовок**: `X-CSRF-Token: <csrf_token>`
- **Ответ 200 OK**: `{"status": "logged_out"}`

### 2.4. Текущий пользователь
- **Метод**: `GET /api/v1/auth/me`
- **Аутентификация**: Сессионный cookie
- **Ответ 200 OK**: данные пользователя и роли.

### 2.5. Смена пароля
- **Метод**: `POST /api/v1/users/me/password`
- **Заголовок**: `X-CSRF-Token: <csrf_token>`
- **Тело запроса**:
```json
{
  "current_password": "OldPassword123!",
  "new_password": "NewStrongPassword456!"
}
```
- **Ответ 200 OK**: `{"status": "password_updated"}`

### 2.6. Активные сессии
- **Метод**: `GET /api/v1/users/me/sessions`
- **Ответ 200 OK**: список активных сессий пользователя с IP, датами и флагом `is_current`.
- **Отзыв сессии**: `DELETE /api/v1/users/me/sessions/{session_id}` (с заголовком `X-CSRF-Token`).

---

## 3. Административное API (RBAC: Superuser / Admin)

### 3.1. Управление пользователями
- `GET /api/v1/admin/users`: список пользователей (с пагинацией и поиском по логину/email).
- `POST /api/v1/admin/users`: создание пользователя (username, email, password, roles, is_superuser).
- `PATCH /api/v1/admin/users/{user_id}/status`: блокировка/разблокировка пользователя (с защитой последнего администратора USR-08).
- `DELETE /api/v1/admin/users/{user_id}/sessions`: отзыв всех сессий пользователя.

### 3.2. Управление OIDC клиентами
- `GET /api/v1/admin/clients`: список зарегистрированных клиентов.
- `POST /api/v1/admin/clients`: регистрация клиента. Для confidential клиентов возвращает поле `client_secret` (разовый показ USR-09).
- `POST /api/v1/admin/clients/{client_id}/rotate-secret`: ротация секрета клиента (разовый показ).
- `DELETE /api/v1/admin/clients/{client_id}`: удаление клиента.

### 3.3. Журнал аудита безопасности
- `GET /api/v1/admin/audit-log`: просмотр событий безопасности (фильтрация по `event_type`, пагинация `skip`/`limit`).

### Публичная telemetry-конфигурация

`GET /api/v1/auth/telemetry-config` не требует cookies/авторизации и не обращается к БД. Ответ `200`, `Cache-Control: no-store`. Поля: `enabled: boolean`, `dsn: string` (только public frontend DSN; пусто при отключении), `environment: local|test|staging|production`, `traces_sample_rate: number`, `replay_enabled: boolean`, `replays_session_sample_rate: number`, `replays_on_error_sample_rate: number`, `trace_propagation_targets: string[]` (точные configured-origin `/api/` и `/oauth/` prefixes). Все rates в [0,1]. Backend DSN, credentials и пользовательские данные отсутствуют.

Defaults: enabled/replay false, DSN пустой, rates 0, targets пустые. Replay принудительно выключен вне staging. Browser дополнительно строит anchored propagation matchers текущего same-origin; runtime config не может разрешить сторонний origin. Конфигурация применяется при следующем reload; bootstrap ограничен 300 ms и продолжает render при отказе telemetry. Privacy policy — [observability.md](observability.md). OIDC wire contracts не изменены.

## Политики и управление удалением — дополнение 03.10.2026

| Метод и путь | Контракт |
| --- | --- |
| GET `/api/v1/legal/documents` | Public, no-cache; `documents` (id/path/title/version/status/paragraphs), `required_versions` terms/data-consent. |
| POST `/api/v1/auth/register` | Дополнительно обязательны `terms_accepted:true`, `data_processing_consent:true`, `legal_versions` с точными актуальными версиями; отсутствие/подмена boolean 422, старые версии 409 до заявки/письма. |
| POST `/api/v1/auth/legal-acceptance` | Cookie + CSRF; те же три поля, повторная запись идемпотентна, pending deletion 403. |
| GET `/api/v1/auth/account-deletion` | Cookie; `pending`, `requested_at`, `scheduled_for`, `request_allowed_at`; timestamps UTC/null. |
| POST `/api/v1/auth/account-deletion/reauthenticate` | Cookie + CSRF; `action:request/cancel`, `current_password`; proof TTL 5m, `factor_required`, `methods`, optional `passkey_options`, `expires_at`. |
| POST `/api/v1/auth/account-deletion/confirm-factor` | Cookie + CSRF; action/authorization/method (`totp`, `recovery_code`, `passkey`), code либо credential; проверяет configured MFA, возвращает новый proof. |
| POST `/api/v1/auth/account-deletion` | Cookie + CSRF + `{authorization}`; 202 со статусом и новой limited cookie/X-CSRF-Token, срок 14 дней; повтор не сдвигает срок. |
| DELETE `/api/v1/auth/account-deletion` | Cookie + CSRF + отдельное cancel-разрешение; до срока 200, отзывает все sessions, clears cookie, cooldown 7 дней. |

`GET /me` дополнительно возвращает `legal_acceptance_required`, `deletion_pending`, `deletion_scheduled_for`, `session_purpose`. До согласий разрешены me/legal-acceptance/logout/deletion management; остальные cookie API 403. Pending разрешает только me/deletion management/logout и public documents. OIDC authorize направляет на `/accept-terms?return_to=...` или `/account-deletion`; code/token issuance и userinfo проверяют DB state. Структурированные privacy ошибки: legal_versions_changed/legal_acceptance_required/account_deletion_pending (409/403), invalid_deletion_authorization (401), deletion_already_pending/deletion_not_cancellable (409), deletion_cooldown/rate_limit_exceeded (429), service_unavailable (503). Неверный пароль/factor 401, CSRF 403, last admin 403. Нет endpoint физического немедленного удаления.


## Статические файлы темы web/demo

Frontend отдаёт `/theme/theme.js` и `/theme/palette.css` из build. Каждый demo предоставляет только явно разрешённые GET `/theme/theme.js`, `/theme/palette.css`, `/theme/demo.css` (JS/CSS, nosniff, cache max-age 300); остальные `/theme/{asset}` — 404. Настройка не имеет API и не отправляется серверу. Wire contracts auth/CSRF/OIDC/last-admin остаются прежними. Политика cookies имеет собственную версию 2026-10-03.1; обязательные версии terms/data-consent остаются 2026-10-03.

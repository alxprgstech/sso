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
  "email_verification_enabled": false,
  "require_verified_email": false
}
```

### 2.2. Вход по паролю
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

# ALXPRGS SSO Python SDK (`alxprgs-sso`)

Клиентская библиотека и интеграционные инструменты Python для работы с единым сервером идентификации ALXPRGS SSO (`alxprgs.tech`).

## Возможности

- Валидация Bearer Access Token по протоколу OIDC:
  - Автоматическая загрузка и локальное кэширование ключей из JWKS (`/.well-known/jwks.json`);
  - Проверка криптографической подписи RS256, срока действия (`exp`, `nbf`), издателя (`iss`), получателя (`aud`);
  - Строгая защита от подмены: отклонение ID Token вместо Access Token (инвариант SSO-03).
- Встроенные зависимости для FastAPI:
  - `verify_token` / `get_current_user` для защиты эндпоинтов API;
  - `require_role("admin")` для разграничения прав доступа на основе ролей (RBAC).
- Хелпер для веб-приложений (Authorization Code Flow + PKCE S256):
  - Генерация URL авторизации с `code_challenge` (S256), `state` и `nonce`;
  - Обмен авторизационного кода на токены (`exchange_code_for_tokens`);
  - Ротация refresh-токенов (`refresh_token`);
  - Отзыв токенов по стандарту RFC 7009 (`revoke_token`).

## Установка

```bash
pip install alxprgs-sso
# С поддержкой зависимостей FastAPI:
pip install "alxprgs-sso[fastapi]"
```

## Быстрый старт

### 1. Защита FastAPI эндпоинтов

```python
from fastapi import FastAPI, Depends
from alxprgs_sso import SSOClient, UserClaims
from alxprgs_sso.fastapi import SSOFastAPISecurity

app = FastAPI()

sso_client = SSOClient(
    server_url="https://auth.alxprgs.tech",
    client_id="client_my_service",
)
security = SSOFastAPISecurity(sso_client)


@app.get("/api/protected")
async def protected_route(user: UserClaims = Depends(security.get_current_user)):
    return {
        "message": f"Здравствуйте, {user.preferred_username}!",
        "user_id": user.sub,
        "roles": user.roles,
    }


@app.get("/api/admin-only")
async def admin_route(user: UserClaims = Depends(security.require_role("admin"))):
    return {"message": "Секретные данные администратора"}
```

### 2. Авторизация веб-клиента (SSO Web Login)

```python
from alxprgs_sso import SSOClient

client = SSOClient(
    server_url="https://auth.alxprgs.tech",
    client_id="client_portal_app",
    client_secret="sec_your_secret",
)

# Шаг 1: перенаправление пользователя на сервер авторизации
auth_url, code_verifier, state = client.generate_authorization_url(
    redirect_uri="https://portal.alxprgs.tech/callback",
    scope="openid profile email",
)
# Сохраните code_verifier и state в сессии пользователя и выполните 302-редирект на auth_url

# Шаг 2: обработка callback
tokens = await client.exchange_code_for_tokens(
    code=received_code,
    redirect_uri="https://portal.alxprgs.tech/callback",
    code_verifier=saved_code_verifier,
)
print(tokens.access_token, tokens.id_token)
```

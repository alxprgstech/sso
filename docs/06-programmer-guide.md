# Руководство программиста ALXPRGS SSO

- **Обозначение документа**: ЕСПД.ГОСТ 19.504-79.РП-06
- **Проект**: ALXPRGS SSO
- **Версия**: 1.0.0
- **Дата**: 24.09.2026
- **Статус**: Действующий

---

## 1. Назначение документа

Настоящее руководство предназначено для разработчиков прикладных информационных систем, веб-приложений и микросервисов, интегрируемых с системой единого входа ALXPRGS SSO с использованием Python SDK `alxprgs-sso` либо напрямую по протоколу OpenID Connect Core 1.0.

---

## 2. Использование Python SDK `alxprgs-sso`

### 2.1. Установка пакета
Библиотека устанавливается из локального или корпоративного репозитория пакетов:
```bash
pip install alxprgs_sso-0.1.0-py3-none-any.whl
```

### 2.2. Защита API эндпоинтов в FastAPI
Для валидации JWT Bearer токенов на стороне микросервиса используйте класс `SSOFastAPISecurity`:

```python
from fastapi import FastAPI, Depends
from alxprgs_sso import SSOFastAPISecurity, UserClaims

app = FastAPI(title="Resource Server")

# Инициализация защиты с адресом SSO-сервера и ожидаемым клиентом (audience)
sso_sec = SSOFastAPISecurity(
    server_url="https://auth.alxprgs.tech",
    audience="my_service_api",
    expected_issuer="https://auth.alxprgs.tech"
)

# Защищенный маршрут, доступный любому аутентифицированному пользователю
@app.get("/api/v1/profile")
async def get_profile(user: UserClaims = Depends(sso_sec.get_current_user)):
    return {
        "user_id": user.sub,
        "username": user.preferred_username,
        "email": user.email,
        "roles": user.roles,
    }

# Маршрут с ролевым контролем доступа (RBAC)
@app.post("/api/v1/admin/manage")
async def manage_resource(user: UserClaims = Depends(sso_sec.require_role("admin"))):
    return {"status": "ok", "operator": user.preferred_username}
```

### 2.3. Реализация потока единого входа (OIDC Authorization Code + PKCE)

Для клиентских веб-приложений (например, на FastAPI или Flask):

```python
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from alxprgs_sso import SSOClient

client = SSOClient(
    server_url="https://auth.alxprgs.tech",
    client_id="client_portal",
    client_secret="secure_client_secret_here",
    redirect_uri="https://portal.alxprgs.tech/callback",
)

@app.get("/login")
def login(request: Request):
    # Генерация авторизационного URL с PKCE S256
    auth_data = client.generate_authorization_url(state="random_state")
    
    # Сохраняем auth_data["code_verifier"] в сессии пользователя!
    request.session["pkce_verifier"] = auth_data["code_verifier"]
    
    return RedirectResponse(auth_data["url"])

@app.get("/callback")
async def callback(request: Request, code: str, state: str):
    verifier = request.session.get("pkce_verifier")
    
    # Обмен кода на токены с валидацией PKCE
    tokens = await client.exchange_code_for_tokens(code=code, code_verifier=verifier)
    
    # Валидация access токена по удаленному JWKS
    claims = await client.validate_access_token(tokens.access_token)
    
    return {"message": "Успешный вход в SSO", "username": claims.preferred_username}
```

---

## 3. Прямая интеграция по протоколу OpenID Connect

При использовании других языков программирования (Go, Node.js, Java) используйте стандартные библиотеки OpenID Connect:
1. Конфигурация: `GET https://auth.alxprgs.tech/.well-known/openid-configuration`
2. Открытые ключи: `GET https://auth.alxprgs.tech/jwks.json`
3. Авторизация: `GET https://auth.alxprgs.tech/oauth/authorize?response_type=code&client_id=...&code_challenge=...&code_challenge_method=S256`
4. Выпуск токенов: `POST https://auth.alxprgs.tech/oauth/token` (grant_type: `authorization_code` с `code_verifier`, либо `refresh_token`)
5. Данные профиля: `GET https://auth.alxprgs.tech/oauth/userinfo` с заголовком `Authorization: Bearer <access_token>`.

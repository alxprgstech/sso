# Руководство по интеграции через Python SDK `alxprgs-sso`

- **Версия пакета**: 0.1.0
- **Согласование с SemVer**: Версия пакета синхронизирована с корневым `VERSION`.
- **Лицензия**: Закрытая (Proprietary / In-house).

---

## 1. Общие сведения

Пакет `alxprgs-sso` представляет собой независимую клиентскую библиотеку на Python для интеграции веб-сервисов и API с сервером единого входа ALXPRGS SSO.

> **Ключевой архитектурный инвариант (Раздел 3 AGENTS.md)**:
> SDK не импортирует и не зависит от внутренних модулей сервера ALXPRGS SSO (`app.*`). Взаимодействие происходит исключительно по стандартизированным сетевым протоколам OpenID Connect и OAuth 2.0.

---

## 2. Установка

```bash
# Установка собранного wheel-пакета:
pip install packages/python-sdk/dist/alxprgs_sso-0.1.0-py3-none-any.whl

# Либо режим разработки:
pip install -e packages/python-sdk
```

Зависимости пакета:
- `httpx>=0.27.0` (асинхронные HTTP-запросы);
- `pyjwt[crypto]>=2.9.0` (криптографическая верификация RS256 JWT);
- `cryptography>=43.0.0` (работа с открытыми ключами JWKS);
- `pydantic>=2.8.0` (строгая типизация данных пользователя).

---

## 3. Архитектура и основные классы

### 3.1. Исключения (`alxprgs_sso.exceptions`)
- `SSOError`: базовый класс исключений библиотеки;
- `TokenExpiredError`: срок действия JWT токена истек (`exp`);
- `InvalidTokenError`: подпись неверна, некорректный эмитент (`iss`), несовпадающая аудитория (`aud`) или передан ID Token вместо Access Token;
- `ConfigurationError`: некорректная конфигурация клиента или недоступность эндпоинта JWKS;
- `InsufficientPermissionsError`: у пользователя отсутствует требуемая роль.

### 3.2. Модель данных пользователя (`alxprgs_sso.models.UserClaims`)
Pydantic-модель с проверенными утверждениями токена:
- `sub: str` — неизменяемый UUID идентификатор пользователя;
- `preferred_username: str` — имя пользователя (логин);
- `email: str` — адрес электронной почты;
- `email_verified: bool` — флаг подтверждения почты;
- `roles: list[str]` — назначенные роли пользователя (`admin`, `developer`, `analyst` и т.д.);
- `scope: str` — разрешенные скоупы;
- `aud: str` — аудитория токена.

### 3.3. Класс `SSOClient`
Основной клиент для взаимодействия с сервером:
- `validate_access_token(token: str) -> UserClaims`: кэширует JWKS с учетом TTL, проверяет криптографическую подпись RS256, срок жизни и отклоняет ID Token;
- `generate_authorization_url(...) -> dict`: генерирует адрес входа с автоматическим созданием криптографически стойкого PKCE S256 verifier/challenge;
- `exchange_code_for_tokens(code, code_verifier) -> TokenResponse`: обмен кода авторизации на Access и Refresh токены;
- `refresh_token(refresh_token) -> TokenResponse`: ротация refresh токена;
- `revoke_token(token, token_type_hint) -> bool`: отзыв токена по RFC 7009.

### 3.4. Защита FastAPI сервисов (`alxprgs_sso.fastapi.SSOFastAPISecurity`)
Вспомогательный класс для создания FastAPI-зависимостей проверки Bearer токенов:
- `get_current_user`: извлекает Bearer токен из заголовка `Authorization`, валидирует его и возвращает объект `UserClaims`;
- `require_role(required_role: str)`: проверяет наличие требуемой роли в клеймах токена и возвращает 403 Forbidden при её отсутствии.

---

## 4. Примеры интеграции

Подробные примеры работающих клиентов доступны в директории `examples/`:
- `examples/client1/app.py`: Демонстрационный веб-портал №1 (порт 8001);
- `examples/client2/app.py`: Демонстрационный веб-портал №2 (порт 8002);
- `examples/README.md`: Инструкция по одновременному запуску и проверке сквозного SSO.

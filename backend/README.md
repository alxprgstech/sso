# ALXPRGS SSO Backend

FastAPI/OIDC backend версии 0.2.0, PostgreSQL 16, SQLAlchemy async с psycopg. Пароли Argon2id, серверные сессии, CSRF/Origin, security revision и повторная аутентификация чувствительных операций.

## Возможности

Authorization Code + PKCE S256, discovery/JWKS, RS256 access/ID profiles, refresh rotation/replay, UserInfo, revocation и RP-initiated logout. Регистрация создаёт заявку, пользователь появляется после email-confirmation и согласий. TOTP/Passkey/Recovery default-off; email обязателен. Транспорт SMTP/SES/Resend. Privacy включает отложенное удаление и retention.

## Запуск

Из корня предпочтителен start.ps1/start.sh; нужен Git и Docker Compose. [README проекта](../README.md) описывает мастер администратора. Ручной запуск после установки зафиксированных зависимостей, безопасной конфигурации, отдельной PostgreSQL и миграций:

```bash
python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

Команда из корня. BASE_URL/FRONTEND_URL/OIDC_ISSUER и trusted proxies согласуются с выбранным профилем. Runtime роль не выполняет DDL. Backend/БД штатного Compose не публикуются.

[API](../docs/api.md), [конфигурация](../docs/configuration.md), [тестирование](../docs/testing/README.md), [эксплуатация](../docs/operations.md). Инструкция не является production-приёмкой.

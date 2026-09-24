# ALXPRGS SSO Backend

FastAPI бэкенд и OIDC-провайдер экосистемы ALXPRGS SSO.

## Возможности
- OpenID Connect 1.0 / OAuth 2.0 (Discovery, JWKS, Authorization Code + PKCE S256, Refresh Token Rotation, Revocation, UserInfo, RP-Initiated Logout)
- Безопасная аутентификация Argon2id, host-only сессионные cookies, CSRF защита
- Самостоятельная регистрация пользователей (режимы open / closed)
- Интерактивный CLI-мастер первичной инициализации первого администратора (`bootstrap_admin`)
- Защита от атак повторного использования (Replay Protection) и гонок на транзакциях PostgreSQL
- Четыре отложенных механизма (TOTP, WebAuthn Passkey, Recovery Codes, Email verification) с полным отключением по умолчанию

## Запуск
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

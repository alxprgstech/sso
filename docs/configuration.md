# Конфигурация ALXPRGS SSO

Продукт 0.2.0; сверка 06.10.2026. Источники: backend/app/config.py, .env.example, docker-compose.yml, start.ps1/start.sh. Таблица описывает literal defaults класса Settings, а не секреты локального .env.

## Профили и приоритет

Settings читает .env относительно рабочего каталога; environment имеет приоритет, неизвестные поля игнорируются. При запуске приложения из корня используется корневой .env. Контейнер получает только переменные из Compose environment; корневой .env служит подстановке Compose, но не передаётся целиком.

| Профиль | BASE_URL / FRONTEND_URL | БД | WebAuthn |
| --- | --- | --- | --- |
| Literal Settings development | http://localhost:8000 / http://localhost:5173 | example DSN на localhost | auth.alxprgs.tech / HTTPS origin |
| Штатный Compose | http://localhost:3000 / http://localhost:3000 | db:5432, sso_runtime | зависит от .env |
| Новый .env от start scripts | локальный gateway 3000 | отдельные owner/runtime/migrator passwords | localhost / http://localhost:3000 |
| Production | один точный HTTPS origin issuer/API/UI/WebAuthn | отдельные runtime/migrator роли | RP host совпадает с issuer |

Default OIDC_ISSUER Settings/Compose — проектный HTTPS адрес. Start scripts меняют BASE_URL/FRONTEND_URL/WebAuthn на localhost, но не переопределяют OIDC_ISSUER из .env.example: он остаётся https://auth.alxprgs.tech. Существующий .env не перезаписывается. SDK expected_issuer должен точно совпадать с OP, даже если transport server_url иной.

## Обязательные инварианты

Три MFA-флага default false; enabled выбирается явно. FEATURE_EMAIL_VERIFICATION_ENABLED=true всегда, false отвергается Settings. REQUIRE_VERIFIED_EMAIL регулирует вход старых/admin-created пользователей, не саморегистрацию. Recovery зависит от TOTP.

Production отвергает default/слабые session и Fernet secrets, отсутствие постоянного RSA≥2048/явного kid, несогласованные HTTPS origins, DEBUG, небезопасные TTL/cookie и SMTP без verified STARTTLS. Предыдущий RSA public key и kid задаются вместе, для production нужен timezone-aware retirement deadline.

SMTP по умолчанию; SES использует AWS credential chain; Resend требует RESEND_API_KEY и валидный SMTP_FROM_EMAIL. STARTTLS не отключает проверку сертификатов; CA-файл выбирается явно. Sentry выключен, rates 0; production Replay запрещён.

## Все поля Settings

Типы и ограничения Field/validators являются источником точной валидации. Secrets показаны без значений.

| Переменная | Тип | Literal default |
| --- | --- | --- |
| `ENVIRONMENT` | `Literal['development', 'testing', 'production']` | `'development'` |
| `DEBUG` | `bool` | `False` |
| `SENTRY_ENABLED` | `bool` | `False` |
| `SENTRY_DSN` | `str` | `''` |
| `SENTRY_FRONTEND_ENABLED` | `bool` | `False` |
| `SENTRY_FRONTEND_DSN` | `str` | `''` |
| `SENTRY_ENVIRONMENT` | `Literal['local', 'test', 'staging', 'production']  /  None` | `None` |
| `SENTRY_TRACES_SAMPLE_RATE` | `float` | `0` |
| `SENTRY_FRONTEND_TRACES_SAMPLE_RATE` | `float` | `0` |
| `SENTRY_REPLAY_ENABLED` | `bool` | `False` |
| `SENTRY_REPLAYS_SESSION_SAMPLE_RATE` | `float` | `0` |
| `SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE` | `float` | `0` |
| `HOST` | `str` | `'0.0.0.0'` |
| `PORT` | `int` | `8000` |
| `BASE_URL` | `str` | `'http://localhost:8000'` |
| `FRONTEND_URL` | `str` | `'http://localhost:5173'` |
| `TRUSTED_PROXIES` | `list[str]  /  str` | `['127.0.0.1', '::1']` |
| `OIDC_ISSUER` | `str` | `'https://auth.alxprgs.tech'` |
| `JWT_PRIVATE_KEY_PEM` | `str` | `пусто` |
| `JWT_KEY_ID` | `str` | `'default-rsa-key-1'` |
| `JWT_PREVIOUS_PUBLIC_KEY_PEM` | `str` | `пусто` |
| `JWT_PREVIOUS_KEY_ID` | `str` | `''` |
| `JWT_PREVIOUS_KEY_VALID_UNTIL` | `datetime  /  None` | `None` |
| `DATABASE_URL` | `str` | `dev/example; задайте безопасно` |
| `DATABASE_URL_SYNC` | `str` | `dev/example; задайте безопасно` |
| `SESSION_SECRET_KEY` | `str` | `dev/example; задайте безопасно` |
| `SESSION_COOKIE_NAME` | `str` | `'__Host-alx_session'` |
| `CSRF_HEADER_NAME` | `str` | `'X-CSRF-Token'` |
| `AUTH_CODE_TTL_SECONDS` | `int` | `60` |
| `ACCESS_TOKEN_TTL_SECONDS` | `int` | `300` |
| `REFRESH_TOKEN_TTL_SECONDS` | `int` | `604800` |
| `REFRESH_FAMILY_MAX_LIFETIME_SECONDS` | `int` | `2592000` |
| `SESSION_IDLE_TIMEOUT_SECONDS` | `int` | `43200` |
| `SESSION_ABSOLUTE_TIMEOUT_SECONDS` | `int` | `604800` |
| `MFA_STEP_TTL_SECONDS` | `int` | `300` |
| `FEATURE_TOTP_ENABLED` | `bool` | `False` |
| `FEATURE_PASSKEY_ENABLED` | `bool` | `False` |
| `FEATURE_RECOVERY_CODES_ENABLED` | `bool` | `False` |
| `FEATURE_EMAIL_VERIFICATION_ENABLED` | `bool` | `True` |
| `REQUIRE_VERIFIED_EMAIL` | `bool` | `False` |
| `TOTP_ENCRYPTION_KEY` | `str` | `dev/example; задайте безопасно` |
| `WEBAUTHN_RP_ID` | `str` | `'auth.alxprgs.tech'` |
| `WEBAUTHN_RP_NAME` | `str` | `'ALXPRGS SSO'` |
| `WEBAUTHN_ORIGIN` | `str` | `'https://auth.alxprgs.tech'` |
| `EMAIL_PROVIDER` | `Literal['smtp', 'ses', 'resend']` | `'smtp'` |
| `RESEND_API_KEY` | `SecretStr` | `пусто` |
| `SES_REGION` | `str` | `'us-east-1'` |
| `SES_FROM_EMAIL` | `str` | `'sso@alxprgs.tech'` |
| `SES_FROM_NAME` | `str` | `'ALXPRGS'` |
| `SMTP_HOST` | `str` | `'localhost'` |
| `SMTP_PORT` | `int` | `1025` |
| `SMTP_USER` | `str` | `пусто` |
| `SMTP_PASSWORD` | `str` | `пусто` |
| `SMTP_FROM_EMAIL` | `str` | `'no-reply@alxprgs.tech'` |
| `SMTP_USE_TLS` | `bool` | `False` |
| `SMTP_CA_FILE` | `str` | `''` |

## Compose, сборка и внешняя среда

POSTGRES_USER/POSTGRES_PASSWORD/POSTGRES_DB, SSO_RUNTIME_PASSWORD и SSO_MIGRATOR_PASSWORD относятся к инфраструктуре Compose. Runtime DSN Compose строит из отдельного пароля; migrate — из миграционного. DATABASE_URL из .env не переопределяет эти построенные DSN. Смена пароля .env не меняет уже инициализированный volume.

ALX_BUILD_SHA — полный проверенный SHA checkout, обязателен для source build. Start scripts требуют Git и задают его сами. Build identity не является гарантией clean дерева. Production custody ключей и source-map upload — отдельные процедуры.

Compose не передаёт произвольные Settings: в частности custom TTL, SESSION_COOKIE_NAME и CSRF_HEADER_NAME в текущем environment mapping отсутствуют. FEATURE_EMAIL_VERIFICATION_ENABLED также не передаётся, используется обязательный true. Для изменения неподдерживаемого mapping нужна отдельная правка конфигурации, а не только .env. TRUSTED_PROXIES в Compose закреплён на gateway 172.29.40.10.

TEST_DATABASE_URL, TESTMAIL_* и DEMO_* относятся к тестам/примерам; не являются серверными Settings. AWS credentials нужны только выбранному SES; локальный AWS_PROFILE сам по себе не монтирует credential files в контейнер. Никогда не помещайте upload tokens в VITE_* или runtime.

[Запуск и роли](operations.md), [миграция](migration.md), [email-тесты](testing/email.md), [SDK](sdk.md), [Sentry](observability.md).

Все *_SECONDS задаются в секундах. Production bounds: code≤60, access≤300, refresh≤604800, family≤2592000, session idle≤43200/absolute≤604800, MFA-step≤300; значения положительные, idle≤absolute. SENTRY_ENVIRONMENT при отсутствии override выводится из ENVIRONMENT; Compose/.env.example задают local, production/staging выбираются явно. HOST/PORT — Settings, фактический bind Uvicorn определяется его CLI/Docker CMD.

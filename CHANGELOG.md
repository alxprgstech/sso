# История изменений (Changelog) ALXPRGS SSO

Все заметные изменения в проекте ALXPRGS SSO документируются в этом файле.
Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/), и проект придерживается [Семантического версионирования](https://semver.org/lang/ru/).

---

## [Unreleased]

### Наблюдаемость

- Sentry errors/static traces с allowlist очисткой, default-off runtime flags и публичным frontend config endpoint.
- React ErrorBoundary, типизированные API errors и staging-only Replay с локальным worker; production Replay выключен.
- Общая VERSION/SHA identity, Debug IDs/private source maps и изолированный release upload без активного CD.
- Безопасные access/application logs, скрытие SQL parameters и отсутствие сырых readiness exception messages.

### Безопасность и ядро OIDC
- Обязательная аутентификация конфиденциальных клиентов по типу клиента в OIDC операциях (FINAL-01).
- Строгая проверка сессии и блокировки пользователя при авторизации (FINAL-02).
- Интеграция Authlib для Authorization Code + PKCE S256 и фильтрация claims по запрошенным scopes (FINAL-11).
- Ограничение абсолютного срока жизни семейств refresh-токенов (30 дней) и ротация RSA-ключей подписи с kid и окном перекрытия в JWKS (FINAL-11).
- Валидация redirect_uri и return_to для защиты от Open Redirect (FINAL-04).

### Python SDK и SSO-клиенты
- Строгая верификация JWT в SDK с проверкой token_use, audience и кэшированием JWKS (FINAL-03).
- Полноценные веб-хелперы `start_authorization`, `handle_web_callback`, `create_logout_url` и модель `WebSessionInfo` (FINAL-06).
- Безопасные демонстрационные клиенты `client1` и `client2` с HttpOnly сессиями и сквозной E2E тест `multi_client_sso.spec.ts` (FINAL-09).

### Пользовательский интерфейс (Frontend)
- Полноценные UI-компоненты управления TOTP, однократного выпуска кодов восстановления и подтверждения email при включенных флагах (FINAL-05).
- Устранение заглушек MFA на странице входа с поддержкой Passkey (FINAL-05).
- Фильтрация журнала аудита по событиям и IP адресам в панели администратора.

### CI/CD, Сборка и Релизы
- Фиксация воспроизводимых зависимостей Python в `requirements-lock.txt` (FINAL-08).
- Статический тайпчекинг Mypy, расширение Ruff и автоматический сканер секретов и зависимостей `scripts/scan_secrets_and_deps.py` (FINAL-08).
- Безопасный процесс подготовки релизов в GitHub Actions с чтением версии из точного commit SHA, draft-режимом и проверкой целостности артефактов (FINAL-07).

## [0.2.0] - 2026-09-24

### Добавлено
- Самостоятельная регистрация обычных пользователей (`POST /api/v1/auth/register`, React-страница `RegisterPage.tsx`, адаптивная ссылка на входе при открытом режиме).
- Модель состояния системы `SystemConfiguration` в PostgreSQL (singleton `id=1`, ADR 0005) с контролем `bootstrap_completed` и политики `registration_mode` (`closed` по умолчанию / `open`).
- Административная вкладка конфигурации системы на `AdminPage.tsx` с переключением режима регистрации и подтверждением пароля администратора (re-auth, REG-02).
- Межпроцессное ограничение частоты запросов регистрации (rate limiting) через аудит PostgreSQL и скользящее окно в памяти.
- Скрипты первичного запуска `./start.ps1` (PowerShell) и `./start.sh` (Bash) с автоматической безопасной генерацией `.env` без перезаписи, проверкой Docker/Compose и портов (SETUP-01..04).
- Интерактивный терминальный мастер `bootstrap_admin.py` со скрытым вводом пароля (`getpass`), выбором режима регистрации, запретом повышения существующих пользователей (SETUP-06) и безопасной идемпотентностью (SETUP-05).
- Изоляция портов Compose на loopback (`127.0.0.1:3000:80`) и закрытие порта PostgreSQL (5432) от внешнего доступа (SETUP-08).
- Миграция базы данных Alembic `0002_registration_and_system_configuration.py` с сохранением существующих аккаунтов.
- Комплексный набор тестов `tests/test_registration.py` и `tests/test_bootstrap_admin.py` (19 тестов).

---

## [0.1.0] - 2026-09-24

### Добавлено
- Начальная архитектура и каркас проекта ALXPRGS SSO.
- Документация требований, модели данных, модели угроз и профиля стандартов ЕСПД (ГОСТ 19).
- Единый источник версий (`VERSION`) и автоматизированный инструмент синхронизации версий `scripts/bump_version.py`.
- Пайплайны автоматической непрерывной интеграции (CI) и подготовки релизов в GitHub Actions.
- Закомментированный шаблон непрерывного развёртывания (CD) в `deploy/github-actions/cd.yml.example`.
- Сервер аутентификации на базе FastAPI с поддержкой OpenID Connect (OIDC Core 1.0, PKCE S256).
- Хранение учетных данных в PostgreSQL: хеширование паролей Argon2id, безопасные серверные сессии с Host-Only cookies.
- Полная реализация четырех отложенных возможностей с отключением по умолчанию: TOTP, Passkey (WebAuthn), Recovery codes, верификация email.
- Клиентская библиотека Python SDK `alxprgs-sso` с FastAPI-зависимостью и помощником входа через веб-интерфейс.
- Демонстрационные клиенты OIDC для проверки сквозного единого входа (SSO).
- Пользовательский интерфейс и административная панель на React + TypeScript.

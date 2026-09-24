# ALXPRGS Single Sign-On (SSO)

Закрытая программная система единого входа (Single Sign-On) и централизованной идентификации для инфраструктуры `alxprgs.tech`.

- **Целевой домен**: `alxprgs.tech`
- **Идентификатор поставщика (Issuer)**: `https://auth.alxprgs.tech`
- **Версия продукта**: `0.1.0` (SemVer, единый источник истины — `VERSION`)
- **Статус**: Готов к развёртыванию

---

## 1. Архитектура системы

Программный комплекс ALXPRGS SSO состоит из следующих компонентов:

1. **Сервер аутентификации и OIDC-провайдер** (`backend/`):
   - Python 3.13 + FastAPI;
   - Реляционная СУБД PostgreSQL 16 (асинхронный доступ через SQLAlchemy 2.0 и драйвер `psycopg`);
   - Управление миграциями схемы базы данных через Alembic;
   - Хеширование паролей алгоритмом Argon2id (RFC 9106);
   - Полноценный OIDC Provider: Discovery (`/.well-known/openid-configuration`), JWKS (`/jwks.json`), Authorization Code с обязательным PKCE S256 (RFC 7636), выпуск RS256 JWT (Access & ID Tokens), ротация Refresh Token с детектированием Replay (Token Family Replay Detection, SSO-05), UserInfo (с приемом только Access Token), отзыв токенов (RFC 7009) и RP-initiated Logout;
   - Серверный RBAC с разграничением прав суперпользователя и защитой последнего администратора (USR-08).

2. **Пользовательский и административный веб-интерфейс** (`frontend/`):
   - React 18, TypeScript, Vite;
   - Интерфейс безопасного парольного входа с поддержкой OIDC-параметра `return_to`;
   - Личный кабинет самообслуживания (профиль, смена пароля, мониторинг и мгновенный отзыв активных сессий);
   - Панель администратора: управление пользователями (создание, роли, блокировка, отзыв сессий), регистрация OIDC-клиентов с однократным показом секрета (USR-09) и журнал аудита безопасности в реальном времени.

3. **Библиотека интеграции Python SDK** (`packages/python-sdk` / `alxprgs-sso`):
   - Автономный пакет без зависимостей от внутренних модулей сервера;
   - Кэширование JWKS с TTL и криптографическая валидация токенов RS256;
   - Хелперы для генерации параметров PKCE S256 и авторизационного URL;
   - Защита маршрутов FastAPI (`SSOFastAPISecurity`, зависимости `get_current_user`, `require_role`);
   - Два готовых демонстрационных клиента в `examples/client1` и `examples/client2`, иллюстрирующих бесшовный единый вход между сервисами.

---

## 2. Обязательные инварианты и флаги отложенных возможностей

В соответствии с требованиями `GOAL.md` и `AGENTS.md`, функционал многофакторной аутентификации и подтверждения почты **полностью программно реализован**, но **жестко отключен по умолчанию** во всех поставляемых конфигурациях:

```env
FEATURE_TOTP_ENABLED=false
FEATURE_PASSKEY_ENABLED=false
FEATURE_RECOVERY_CODES_ENABLED=false
FEATURE_EMAIL_VERIFICATION_ENABLED=false
REQUIRE_VERIFIED_EMAIL=false
```

- При выключенных флагах обращение к эндпоинтам TOTP, Passkey, Recovery codes и Email verification возвращает HTTP 404 (`feature_disabled`);
- Фоновые рассылки писем не производятся (`sent_emails_sink`);
- Веб-интерфейс динамически опрашивает витрину возможностей `GET /api/v1/auth/capabilities` и адаптирует отображение, информируя пользователя о действующей политике безопасности.

---

## 3. Быстрый запуск

### 3.1. Запуск через Docker Compose (рекомендуемый способ)

```bash
# 1. Клонирование и переход в репозиторий
git clone https://github.com/alxprgs/sso.git
cd sso

# 2. Настройка переменных окружения
cp .env.example .env

# 3. Сборка и запуск контейнеров
docker compose up -d --build

# 4. Проверка состояния сервисов
docker compose ps
```

Сервисы будут доступны по адресам:
- Веб-интерфейс и Nginx Gateway: `http://localhost:3000` (в рабочей среде: `https://auth.alxprgs.tech`);
- API и OIDC эндпоинты: `http://localhost:8000`.

### 3.2. Инициализация первого администратора

Создайте учетную запись суперпользователя через CLI:

```bash
# Внутри Docker-контейнера:
docker compose exec backend python -m app.cli.bootstrap_admin --username admin --email admin@alxprgs.tech --password "YourStrongPassword123!"

# Либо локально:
alx-admin --username admin --email admin@alxprgs.tech --password "YourStrongPassword123!"
```

---

## 4. Тестирование и верификация

### 4.1. Автоматизированные тесты Backend и SDK (pytest)

```bash
# Запуск полного набора тестов (35 тестов)
pytest tests/ -v
```

Состав тестов:
- `test_main_endpoints.py`: Discovery, JWKS, базовые эндпоинты;
- `test_auth_and_sessions.py`: парольный вход Argon2id, сессии, CSRF-защита;
- `test_oidc_protocol.py`: валидация PKCE S256, сопоставление redirect_uri, UserInfo;
- `test_mfa_features.py`: проверка 4 механизмов MFA и их изоляции при `false`;
- `test_admin_api.py`: RBAC, защита последнего администратора, разовый показ секрета;
- `test_python_sdk.py`: верификация токенов по JWKS, хелпер PKCE, зависимости FastAPI;
- `test_sso_cross_clients.py`: сквозной единый вход между двумя приложениями;
- `test_security_and_negative_scenarios.py`: негативные тесты OIDC, replay кодов и токенов, гонки.

### 4.2. Сборка и typecheck Frontend

```bash
cd frontend
npm install
npx tsc --noEmit
npm run build
```

---

## 5. Демонстрационные клиенты единого входа

В каталоге `examples/` представлены два независимых клиентских сервиса:
- `examples/client1/app.py`: Портал аналитики (порт 8001);
- `examples/client2/app.py`: Портал документации (порт 8002).

Запуск и подробная инструкция описаны в [`examples/README.md`](examples/README.md). Авторизация в Портале аналитики обеспечивает мгновенный вход в Портал документации без повторного запроса учетных данных.

---

## 6. Эксплуатация и регламенты

- [Руководство по эксплуатации](docs/operations.md): миграции Alembic, мониторинг (health probes), запуск Compose;
- **Резервное копирование**: `python scripts/backup_db.py --docker --output-dir backups/` (контрольная сумма SHA-256);
- **Восстановление БД**: `python scripts/restore_db.py backups/<file>.sql --confirm --docker`;
- **Ротация ключей**: `python scripts/rotate_keys.py --output-dir keys/ --bits 2048`.

---

## 7. Комплект документации ЕСПД (ГОСТ 19.xxx)

1. [Техническое задание (ГОСТ 19.201-78)](docs/01-technical-specification.md)
2. [Описание программы (ГОСТ 19.402-78)](docs/02-program-description.md)
3. [Программа и методика испытаний (ГОСТ 19.301-79)](docs/03-test-procedure.md)
4. [Руководство оператора (ГОСТ 19.505-79)](docs/04-operator-guide.md)
5. [Руководство системного программиста (ГОСТ 19.503-79)](docs/05-system-programmer-guide.md)
6. [Руководство программиста (ГОСТ 19.504-79)](docs/06-programmer-guide.md)
7. [Спецификация API](docs/api.md)
8. [Руководство Python SDK](docs/sdk.md)
9. [Методология научных исследований](docs/research.md)
10. [Архитектурные решения (ADR)](docs/adr/)

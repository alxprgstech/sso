# Реестр дефектов и замечаний (Defect Registry)

Актуальный открытый дефект: DOC-DEF-01 (version metadata npm lock), отдельная planned задача DOC-VERSION-LOCK-01. Первоначальные BUG-записи ниже — исторический реестр, их результаты не повторены DOC-REFRESH-01. Новое замечание и воспроизведение находятся в конце файла.

- **Версия**: 1.0.0
- **Дата обновления**: 2026-09-24T18:10:00+03:00
- **Статус**: В работе
- **Формат**: Идентификатор, Название, Требование, Серьёзность (Critical / High / Medium / Low), Статус (Open / In_Progress / Fixed / Verified / Invalid), Описание, Шаги воспроизведения, Ожидаемое/Фактическое поведение, Исправление, Регрессионный тест.

---

## 1. Сводка дефектов

| ID | Название | Серьёзность | Статус | Связанное требование |
|---|---|---|---|---|
| **BUG-001** | `tests/conftest.py` глобально подменяет `get_db` на `AsyncMock`, маскируя отсутствие интеграции с PostgreSQL | Critical | Resolved | QA-01, QA-02 |
| **BUG-002** | `tests/test_python_sdk.py` импортирует внутренние модули сервера (`app.core.security`), нарушая изоляцию SDK | High | Resolved | QA-12, SDK-01 |
| **BUG-003** | CI шаг `sdk-build-and-test` запускает тесты из корня репозитория через общий `conftest.py`, нарушая чистоту проверки пакета | High | Resolved | QA-12, QA-14 |
| **BUG-004** | Отсутствуют реальные интеграционные тесты параллельного погашения токенов/кодов (гонки проверялись последовательным вызовом мока) | High | Resolved | QA-09, SEC Section 4(4) |
| **BUG-005** | Отсутствует конфигурация и скрипт E2E браузерного тестирования Playwright во фронтенде | Medium | Resolved | QA-11, TEST-UI-01 |
| **BUG-006** | Revision ID `0002_registration_and_system_configuration` (42 символа) превышает лимит `VARCHAR(32)` таблицы `alembic_version`, приводя к сбою накатывания миграций на PostgreSQL | Critical | Resolved | QA-02, QA-13 |
| **BUG-007** | Модель `SystemConfiguration` наследует `created_at` от `Base`, но в миграции 0002 эта колонка отсутствовала, вызывая ошибку `UndefinedColumn` при любых SQL-запросах к `system_configuration` | Critical | Resolved | QA-02, QA-03, QA-04 |
| **BUG-008** | В `backend/Dockerfile` отсутствовало копирование `README.md`, требуемого `pyproject.toml` | High | Resolved | QA-03, QA-04 |
| **BUG-009** | Несоответствие контракта параметров в `updateRegistrationMode` на фронтенде | Medium | Resolved | QA-05, REG-02 |
| **BUG-010** | `tests/conftest.py` выполняет TRUNCATE CASCADE на `DATABASE_URL` без проверки `TEST_DATABASE_URL` и маркера владения | Critical | Resolved | G4-DB, QA-02 |
| **BUG-011** | Неполнота сквозного жизненного цикла email verification и необходимость временного ослабления политик | High | Resolved | G4-EMAIL, SEC-FLAG-07 |
| **BUG-012** | Отсутствие реального браузерного тестирования Passkey (WebAuthn), потеря traces в Playwright | High | Resolved | G4-PASSKEY, QA-11 |
| **BUG-013** | Отсутствие проверки доверенных прокси (IP spoofing rate limit bypass) и межпроцессной валидации | High | Resolved | G4-LIMITS, QA-09 |
| **BUG-014** | Ошибки конфигурации GitHub Actions CI: сбой сбора тестов SDK, отсутствие миграций и TEST_DATABASE_URL | Critical | Resolved | G4-CI, QA-14 |
| **BUG-015** | Утечка enabled env в default-off тесты и отсутствие изоляции REQUIRE_VERIFIED_EMAIL в Passkey-тестах (6 failed в CI) | High | Fixed | G5-PROFILES, SEC-FLAG-01 |
| **BUG-016** | Рассинхронизация WebAuthn origin/RP ID (127.0.0.1 vs localhost) и сбой генерации ключей в CDP | High | Fixed | G5-E2E, QA-11 |
| **BUG-017** | Запуск E2E на неразделенном профиле, зависимость тестов от порядка выполнения и скрытие ошибок seed | High | Fixed | G5-E2E, QA-11 |


---

## 2. Подробное описание дефектов

### BUG-001: Глобальный autouse mock get_db маскирует реальное отсутствие обращений к PostgreSQL
- **Требование**: QA-01, QA-02, AGENTS.md Раздел 3 («Интеграционные тесты должны использовать PostgreSQL»).
- **Серьёзность**: Critical.
- **Статус**: Fixed.
- **Шаги воспроизведения**:
  1. Открыть `tests/conftest.py`.
  2. Обнаружить fixture `default_db_mock` с `autouse=True`, которая безусловно выполняет `app.dependency_overrides[get_db] = _mock_get_db`.
  3. Запустить `pytest tests/test_registration.py` при выключенной PostgreSQL: все тесты проходят, так как реального обращения к БД нет.
- **Ожидаемое поведение**: Интеграционные тесты должны требовать реального подключения к PostgreSQL и падать при её отсутствии. Unit-тесты должны использовать явные фикстуры моков без глобального захвата всех тестов.
- **Фактическое поведение**: Любой запуск pytest не касается PostgreSQL; 54 "passed" теста не проверяют работу SQL, миграций, индексов и ограничений PostgreSQL.
- **Исправление**:
  1. В `tests/conftest.py` убран `autouse=True` из `default_db_mock`.
  2. Добавлены фикстуры `pg_engine`, `pg_session`, `pg_client` для реального подключения к PostgreSQL (с таймаутом и явным `pytest.fail` при отсутствии БД).
  3. Добавлен маркер `@pytest.mark.postgres`.
  4. Проверено: при неверном адресе БД тесты падают с явным `Failed: ОШИБКА QA-02: Тестовая база данных PostgreSQL недоступна`; при рабочей БД тесты выполняются за <0.5 сек.

---

### BUG-006: Revision ID миграции 0002 превышает VARCHAR(32) в alembic_version
- **Требование**: QA-02, QA-13, ARCH-04.
- **Серьёзность**: Critical.
- **Статус**: Fixed.
- **Шаги воспроизведения**:
  1. Подключиться к пустой базе PostgreSQL 16.
  2. Запустить `alembic -c backend/alembic.ini upgrade head`.
  3. Падение с ошибкой `psycopg.errors.StringDataRightTruncation: value too long for type character varying(32)` при `UPDATE alembic_version SET version_num='0002_registration_and_system_configuration'`.
- **Ожидаемое поведение**: Миграция накатывается без ошибок на чистой базе.
- **Фактическое поведение**: Идентификатор ревизии имел 42 символа при стандартном ограничении 32 символа.
- **Исправление**:
  1. В `backend/alembic/versions/0002_registration_and_system_configuration.py` идентификатор ревизии сокращен до `0002_reg_system_config` (22 символа <= 32).
  2. В `backend/alembic.ini` исправлен `script_location = %(here)s/alembic`.
  3. Выполнен `alembic upgrade head`: обе ревизии (`0001_initial_schema`, `0002_reg_system_config`) успешно применены, созданы все 17 таблиц.

---

### BUG-007: Отсутствие колонки created_at в таблице system_configuration
- **Требование**: QA-02, QA-03, QA-04, ARCH-04.
- **Серьёзность**: Critical.
- **Статус**: Fixed.
- **Шаги воспроизведения**:
  1. Применить миграцию 0002 к реальной PostgreSQL.
  2. Выполнить `execute_bootstrap(...)` или любой SELECT запрос к `SystemConfiguration`.
  3. SQLAlchemy генерирует запрос с полем `created_at` (унаследованным от `Base`), что приводит к сбою: `psycopg.errors.UndefinedColumn: column system_configuration.created_at does not exist`.
- **Ожидаемое поведение**: Структура таблицы `system_configuration` в PostgreSQL полностью совпадает с SQLAlchemy-моделью `SystemConfiguration(Base)`.
- **Фактическое поведение**: Таблица была создана без колонки `created_at`.
- **Исправление**:
  1. В миграции `backend/alembic/versions/0002_registration_and_system_configuration.py` добавлена колонка `sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"))`.
  2. Миграция успешно перенакатана на PostgreSQL.
  3. Интеграционный тест `tests/integration/test_bootstrap_pg.py` успешно прошел (4 из 4 тестов).

---

### BUG-002: tests/test_python_sdk.py импортирует внутренние модули сервера
- **Требование**: QA-12, SDK-01, AGENTS.md Раздел 3 («SDK не импортирует внутренние модули сервера; его примеры проверяются после установки собранного пакета в чистую среду»).
- **Серьёзность**: High.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. Открыть `tests/test_python_sdk.py`, строка 16: `from app.core.security import create_jwt, get_jwks`.
  2. Запуск тестов в чистой среде, где установлен только wheel SDK и нет `backend/` в sys.path, упадет с `ModuleNotFoundError: No module named 'app'`.
- **Ожидаемое поведение**: Тесты SDK должны быть полностью автономными и использовать стандартные криптографические библиотеки (`cryptography` или `authlib`) для генерации тестовых RSA-ключей и JWKS, либо обращаться к живому тестовому серверу OIDC.
- **Фактическое поведение**: Тест SDK жестко завязан на исходники бэкенда.
- **Решение**:
  1. В `packages/python-sdk/tests/test_sdk_isolated.py` реализованы автономные тесты SDK с генерацией RSA ключей и JWKS через чистую `cryptography`, без единого импорта из `app` или сервера.
  2. `tests/test_python_sdk.py` также очищен от серверных импортов.
  3. Пакет `alxprgs-sso` собран в wheel (`alxprgs_sso-0.2.0-py3-none-any.whl`), развернут в чистое виртуальное окружение `.venv-sdk-test` и успешно протестирован (`3 passed`).
  4. Примеры `examples/client1/app.py` и `examples/client2/app.py` проверены на импорт и совместимость в чистом окружении.

---

### BUG-003: CI шаг sdk-build-and-test запускает тесты из корня репозитория
- **Требование**: QA-12, QA-14, Section 2 GOAL-03.
- **Серьёзность**: High.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. В `.github/workflows/ci.yml` строка 151: `./test_env/bin/pytest tests/test_python_sdk.py`.
  2. При запуске pytest подтягивает `tests/conftest.py`, который делает `sys.path.insert(0, os.path.abspath("backend"))`.
- **Ожидаемое поведение**: Тестирование установленного wheel-пакета SDK должно происходить вне дерева исходников сервера (например, запуск из отдельной временной директории с изолированным набором тестов SDK).
- **Фактическое поведение**: SDK не проверялся в настоящей изоляции в CI.
- **Решение**:
  1. Размещен автономный тестовый набор в `packages/python-sdk/tests/test_sdk_isolated.py`.
  2. В `.github/workflows/ci.yml` шаг запуска тестов SDK настроен на выполнение `pytest packages/python-sdk/tests/test_sdk_isolated.py` внутри изолированного каталога без захвата бэкенда.

---

### BUG-004: Отсутствуют реальные тесты гонок и параллельного исполнения на PostgreSQL
- **Требование**: QA-09, SEC Section 4(4).
- **Серьёзность**: High.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. Открыть `tests/test_security_and_negative_scenarios.py` строки 340-399.
  2. Гонка "проверяется" двумя последовательными вызовами `await OIDCService.exchange_code(...)` с моковым `code_state["used"] = True`.
- **Ожидаемое поведение**: Тест конкурентности должен запускать несколько параллельных асинхронных задач (`asyncio.gather`), использующих отдельные подключения к реальной PostgreSQL, и проверять, что ровно один запрос завершается успешно, а остальные отклоняются с ошибкой replay/duplicate.
- **Фактическое поведение**: Последовательный вызов мока с ручным переключением флага.
- **Решение**: Реализован `tests/integration/test_concurrency_pg.py`:
  - 5 параллельных запросов на погашение Authorization Code (`SELECT FOR UPDATE`) -> ровно 1 успешный обмен (200), 4 отказа (400 `invalid_grant`), аудит `auth_code_replay_detected`;
  - 2 одновременных запроса на регистрацию с одинаковыми username/email -> ровно 1 успешный (201), 1 отказ (409) благодаря `UNIQUE` ограничению PostgreSQL;
  - 2 одновременных запроса на погашение Recovery Code -> ровно 1 успех (200), 1 отказ (401) благодаря атомарному `UPDATE ... RETURNING`;
  - 2 параллельных запроса Refresh Token -> детекция Replay и отзыв семейства;
  - Межпроцессный rate limiting через PostgreSQL audit events -> HTTP 429 Too Many Requests.
  Все 5 тестов пройдены на живой PostgreSQL 16.

---

### BUG-005: Отсутствует инфраструктура E2E браузерных тестов Playwright
- **Требование**: QA-11, TEST-UI-01, Section 2 GOAL-03.
- **Серьёзность**: Medium.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. В `frontend/package.json` отсутствовали devDependencies `@playwright/test` и скрипт `test:e2e`.
- **Ожидаемое поведение**: Наличие воспроизводимого E2E-контура, проверяющего полный пользовательский сценарий (регистрация, логин, профиль, смена пароля, админ-панель) в настоящем браузере.
- **Фактическое поведение**: Браузерные тесты отсутствовали.
- **Решение**:
  1. Установлен `@playwright/test` v1.63.0 и Chromium.
  2. Настроен `frontend/playwright.config.ts` с таргетом `http://127.0.0.1:3000`.
  3. Разработан набор `frontend/e2e/sso.spec.ts` (4 сквозных сценария: проверка default-off профиля, вход администратора и переключение режима на `open` с re-auth паролем, самостоятельная регистрация нового пользователя и проверка RBAC изоляции админки, возврат режима в `closed`).
  4. Добавлен скрипт `npm run test:e2e`, все 4 теста успешно проходят.

---

### BUG-009: Несоответствие контракта параметров в updateRegistrationMode на фронтенде
- **Требование**: QA-05, REG-02.
- **Серьёзность**: Medium.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. Войти в админку на фронтенде, перейти на вкладку "Конфигурация".
  2. Выбрать режим регистрации "open", ввести пароль администратора и нажать "Применить режим регистрации".
  3. Бэкенд возвращает HTTP 422 Unprocessable Entity (`Field required: mode`, `Field required: current_admin_password`).
- **Ожидаемое поведение**: Режим регистрации успешно переключается с подтверждением пароля администратора.
- **Фактическое поведение**: `frontend/src/api/client.ts` отправлял `{ registration_mode, admin_password }`, тогда как схема FastAPI `RegistrationModeUpdateRequest` ожидала `{ mode, current_admin_password }`.
- **Решение**:
  1. В `frontend/src/api/client.ts` метод `updateRegistrationMode` переведён на отправку `{ mode, current_admin_password }`.
  2. В `backend/app/schemas/admin.py` в класс `RegistrationModeUpdateRequest` добавлен `@model_validator(mode="before")` для автоматической поддержки алиасов `registration_mode` и `admin_password`.
  3. В `frontend/src/context/AuthContext.tsx` добавлен метод `refreshCapabilities`, вызываемый при смене режима и выходе из системы для актуализации состояния флагов в SPA.
  4. Фронтенд пересобран в Docker Compose, сценарий подтверждён тестом `test:e2e`.

---

### BUG-010: tests/conftest.py выполняет TRUNCATE CASCADE на DATABASE_URL без проверки TEST_DATABASE_URL и маркера владения
- **Требование**: G4-DB, QA-02, AGENTS.md Разделы 1, 3.
- **Серьёзность**: Critical.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. Задать в окружении боевую строку подключения `DATABASE_URL=postgresql+psycopg://sso_user:...@localhost:5432/sso_db`.
  2. Запустить `pytest tests/integration/test_postgres_connection.py`.
  3. Фикстура `pg_session` выполняет `TRUNCATE TABLE users, sessions, ... CASCADE;` на указанной базе данных, безвозвратно удаляя рабочие данные.
- **Ожидаемое поведение**:
  1. Тестовый набор должен требовать переменную `TEST_DATABASE_URL` и категорически запрещать fallback на `DATABASE_URL`. При отсутствии `TEST_DATABASE_URL` выполнение должно немедленно прерываться до открытия соединений или выполнения запросов.
  2. Пароли в DSN должны маскироваться во всех логах и текстах исключений.
  3. Перед любыми операциями очистки (`TRUNCATE`, `DROP`) должна выполняться строгая валидация базы данных: наличие маркерной таблицы / записи владения тестовой средой (`test_database_marker`), подтверждающей принадлежность базы именно тестовому запуску. При отсутствии маркера любые деструктивные запросы блокируются.
- **Фактическое поведение**: `get_test_database_url()` считывал `os.environ.get("DATABASE_URL", ...)`, пароли выводились в открытом виде при ошибках подключения, очистка выполнялась безусловно.
- **Исправление**:
  1. Разработан модуль `tests/db_guard.py` с функцией `get_test_database_url()`, которая читает исключительно `TEST_DATABASE_URL` без fallback на `DATABASE_URL`, маскирует пароли через `mask_dsn()`, проверяет имя базы на запрещённые списки (`sso_db`, `postgres`, `prod`) и маркер `test`.
  2. Реализована функция `verify_test_database_marker` и `safe_truncate_test_tables`, которая перед выполнением TRUNCATE проверяет наличие маркерной таблицы `test_database_marker` со значением `is_safe_to_truncate=True` и `environment='alxprgs_sso_isolated_test'`.
  3. В `tests/conftest.py` фикстуры `pg_engine` и `pg_session` переведены на использование защитного модуля.
  4. Разработан регрессионный тестовый модуль `tests/test_database_guard.py` (14 тестов, все PASSED): проверены маскирование DSN, запрет fallback на `DATABASE_URL`, запрет запрещенных имен баз, отказ при отсутствии маркера с подтверждением сохранения данных в контрольной таблице, позитивный прогон в изолированном контуре. Проверена сохранность всех 6 пользователей в боевой БД `sso_db`.

---

### BUG-011: Неполнота сквозного жизненного цикла email verification и необходимость временного ослабления политик
- **Требование**: G4-EMAIL, SEC-FLAG-07, REG-09.
- **Серьёзность**: High.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. В `tests/integration/test_features_pg.py` метод `test_enabled_profile_email_verification_and_enforcement_pg` содержал временное ослабление политики (`overridden.REQUIRE_VERIFIED_EMAIL = False`), чтобы неподтверждённый пользователь мог войти и получить сессию для запроса ссылки подтверждения.
  2. Без сессии эндпоинт `/api/v1/mfa/email/request` требовал обязательной авторизации через `get_current_user`, что блокировало подтверждение email для обычного пользователя без вмешательства администратора.
  3. Отсутствовала проверка SMTP-доставки, устойчивости к сбоям SMTP с фиксацией аудита `email_delivery_failed`, аудита `email_verification_replay_detected` и `email_verification_expired`, а также rate-limit на отправку писем и защита от перебора учетных записей.
- **Ожидаемое поведение**:
  1. Неподтверждённый пользователь при `REQUIRE_VERIFIED_EMAIL=true` блокируется на входе с ошибкой `email_verification_required` (HTTP 401).
  2. Неподтверждённый пользователь может запросить ссылку подтверждения через `/api/v1/mfa/email/request` без сессии, указав email.
  3. Эндпоинт защищён от перебора (всегда возвращает 200 OK при корректном формате), а также от спама (rate limit на IP и email).
  4. Токены подтверждения одноразовые с атомарным погашением в транзакции PostgreSQL; повторное использование (replay) и истечение срока фиксируются в журнале аудита.
  5. При сбое SMTP ошибка протоколируется в аудите, но не роняет процесс; при работающем SMTP письмо реально отправляется.
- **Исправление**:
  1. Обновлена схема ошибок аутентификации в `backend/app/core/exceptions.py` и `backend/app/services/auth_service.py` с возвратом `error="email_verification_required"`.
  2. В `backend/app/api/deps.py` добавлен `get_optional_current_user`.
  3. В `backend/app/core/rate_limit.py` добавлен лимитер `check_email_request_rate_limit`.
  4. В `backend/app/services/mfa_service.py` `EmailVerificationService` расширен поддержкой реальной отправки через SMTP с тайм-аутом в отдельном потоке, логированием `email_delivery_failed`, аудитом `email_verification_replay_detected` и `email_verification_expired`.
  5. В `backend/app/api/mfa.py` эндпоинт `/api/v1/mfa/email/request` переведён на поддержку как авторизованных пользователей, так и неавторизованных неподтверждённых аккаунтов с защитой от перебора.
  6. В `tests/integration/test_features_pg.py` убран временный обход политики; разработан `tests/integration/test_email_verification_pg.py` с 4 подробными тестами (полный сквозной путь, SMTP mock + failure resilience, replay + expiration + rate limit, default-off). Все тесты пройдены (100% pass).

---

### BUG-012: Отсутствие реального браузерного тестирования Passkey (WebAuthn), потеря traces в Playwright и неполнота WebAuthn жизненного цикла
- **Требование**: G4-PASSKEY, QA-11, TEST-UI-01, SEC-FLAG-04.
- **Серьёзность**: High.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. В `frontend/playwright.config.ts` задан `trace: "on-first-retry"` при `retries: 0`, что приводило к потере trace-артефактов при любом падении тестов в CI/локально.
  2. В `frontend/src/pages/DashboardPage.tsx` отсутствовал интерактивный интерфейс управления Passkey (регистрация через `navigator.credentials.create`, листинг зарегистрированных ключей, удаление ключей).
  3. В `frontend/src/pages/LoginPage.tsx` отсутствовал сценарий входа по Passkey через WebAuthn API браузера и поддержка Passkey на шаге MFA.
  4. В `backend/app/services/mfa_service.py`:
     - `credential_id` декодировался через `.decode("utf-8", errors="ignore")`, что приводило к повреждению случайных бинарных последовательностей WebAuthn credential ID;
     - При верификации входа брался первый попавшийся ключ `creds[0]`, что делало невозможным использование нескольких ключей (Multi-device / multiple credentials);
     - Поиск challenge для входа был завязан строго на `user_id == user.id`, что препятствовало сопоставлению выданного challenge при входе без предварительной сессии.
  5. Отсутствовал сквозной браузерный E2E-тест с виртуальным аутентификатором WebAuthn (Playwright CDP session).
- **Ожидаемое поведение**:
  1. `trace: "retain-on-failure"` гарантирует сохранение архива trace при падении любого теста.
  2. В UI доступны регистрация, отображение и удаление Passkeys в Dashboard, а также вход по Passkey на странице входа и на шаге MFA.
  3. Бэкенд корректно хранит Base64URL-кодированные `credential_id`, поддерживает выбор точного ключа по `rawId` из assertion, проверяет challenge, RP ID, origin и удаление ключей.
  4. Playwright E2E-тест с виртуальным аутентификатором Chrome DevTools Protocol (`WebAuthn.enable`, `WebAuthn.addVirtualAuthenticator`) проверяет регистрацию двух ключей, вход по Passkey, удаление одного из ключей, проверку неработоспособности удалённого ключа и негативные сценарии (неверный challenge, неверный origin) без mock-заглушек бэкенда.
- **Исправление**:
  1. В `frontend/playwright.config.ts` установлен `trace: "retain-on-failure"`.
  2. В `backend/app/services/mfa_service.py` реализована поддержка безопасного кодирования Base64URL для `credential_id` (`_cred_id_to_bytes`), сопоставление ключей по `credential_id` из assertion среди всех ключей пользователя или всей базы при passwordless auth, атомарное погашение challenge при верификации, методы `list_credentials` и `delete_passkey`.
  3. В `backend/app/api/mfa.py` эндпоинты Passkey расширены поддержкой passwordless auth (поиск пользователя по ID ключа), верификации MFA шага, листинга `/credentials` (GET) и удаления `/credentials/{credential_id}` (DELETE).
  4. В `frontend/src/utils/webauthn.ts` реализованы утилиты конвертации WebAuthn бинарных буферов и Base64URL.
  5. В `frontend/src/api/client.ts`, `frontend/src/pages/DashboardPage.tsx` и `frontend/src/pages/LoginPage.tsx` реализован полноценный интерфейс регистрации, листинга и удаления ключей, а также входа по Passkey на главной странице и на шаге MFA.
  6. В `tests/integration/test_passkey_pg.py` реализованы 4 интеграционных теста на реальном PostgreSQL (изоляция default-off с HTTP 404, сохранение options/challenge, регистрация множественных ключей и удаление, отрицательные криптографические проверки WebAuthn без моков). Все 4 теста пройдены успешно (100% pass).
  7. В `frontend/e2e/passkey.spec.ts` реализованы 4 сквозных Playwright E2E-теста с виртуальным аутентификатором Chrome DevTools Protocol (`WebAuthn.enable`, `WebAuthn.addVirtualAuthenticator`), проверяющие видимость capabilities, регистрацию нескольких ключей на разных устройствах, беспарольный вход и отказ удалённого ключа. Все 4 теста пройдены успешно (100% pass).

---

### BUG-013: Отсутствие проверки доверенных прокси (IP spoofing rate limit bypass) и отсутствие межпроцессной валидации лимитов на независимых процессах
- **Требование**: G4-LIMITS, QA-09, SEC Section 4(4).
- **Серьёзность**: High.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. Функция `get_client_ip` в `backend/app/core/rate_limit.py` извлекала заголовок `X-Forwarded-For` без предварительной валидации доверенных прокси (`trusted proxies`). Недоверенный клиент мог слать произвольные значения заголовков `X-Forwarded-For` или `X-Real-IP`, подменять свой IP и неограниченно отправлять запросы в обход лимитера (rate limiting bypass via IP spoofing).
  2. В `tests/integration/test_concurrency_pg.py` тест распределённых лимитов выполнял последовательные запросы к одному ASGI-приложению через один экземпляр TestClient в памяти одного процесса, что не проверяло фактическое межпроцессное взаимодействие независимых процессов через PostgreSQL.
  3. При сбое сессии базы данных лимитеры не обеспечивали строгое поведение `fail-closed` (HTTP 503), допуская потенциальный пропуск нелимитированного трафика при сбоях СУБД.
- **Ожидаемое поведение**:
  1. `get_client_ip` принимает forwarding-заголовки (`X-Forwarded-For`, `X-Real-IP`) исключительно тогда, когда непосредственный сетевой пир (`client.host`) входит в список доверенных прокси (`TRUSTED_PROXIES`). Для недоверенных источников любые forwarding-заголовки игнорируются, а IP берётся строго из сокета.
  2. Межпроцессное ограничение проверяется на как минимум двух независимых процессах ОС (Uvicorn), подключенных к общей PostgreSQL.
  3. При сбое PostgreSQL лимитер переходит в режим `fail-closed` (HTTP 503 Service Unavailable).
- **Исправление**:
  1. В `backend/app/config.py` добавлена конфигурация `TRUSTED_PROXIES` со списком доверенных IP/CIDR и валидатором форматов IPv4/IPv6/сетей.
  2. В `backend/app/core/rate_limit.py` реализована функция `is_trusted_proxy` и обновлена `get_client_ip`: при недоверенном пире заголовок `X-Forwarded-For` отбрасывается.
  3. В `check_registration_rate_limit` и `check_email_request_rate_limit` реализован режим `fail-closed`: при исключениях базы данных возвращается `HTTP 503 Service Unavailable` с детализацией `audit_storage_unavailable`.
  4. Создан `tests/integration/test_distributed_rate_limiting_pg.py`:
     - `test_trusted_proxy_validation_and_spoofing_defense`: модульная проверка доверенных/недоверенных IP и CIDR;
     - `test_spoofed_headers_cannot_bypass_rate_limit_pg`: тест на PostgreSQL, доказывающий, что подделка заголовков не позволяет обойти блокировку HTTP 429;
     - `test_inter_process_distributed_rate_limiting_real_processes_pg`: запуск двух реальных независимых процессов Uvicorn (порты 8011 и 8012), использующих общую PostgreSQL. 5 запросов к Процессу 1 исчерпывают лимит; 6-й запрос к Процессу 2 немедленно отклоняется с кодом HTTP 429 (`rate_limit_exceeded`);
     - `test_fail_closed_on_database_failure`: подтверждение возврата HTTP 503 при разрыве соединения с базой.
     Все 4 теста успешно пройдены (100% pass).

---

### BUG-014: Ошибки конфигурации GitHub Actions CI: сбой сбора тестов SDK в бэкенд-джобе, отсутствие миграций, отсутствие переменной TEST_DATABASE_URL и роль 'root' в PostgreSQL healthcheck
- **Требование**: G4-CI, QA-14, Section 2 GOAL-03, Section 3 GOAL-04.
- **Серьёзность**: Critical.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. В подтверждённом baseline CI run [36027756634](https://github.com/alxprgstech/sso/actions/runs/36027756634) на коммите `2c1de5b668482d2bc11707fe565e3d1ab8711f4c` джоба `backend-lint-and-test` завершалась сбоем на этапе сбора тестов pytest с ошибкой `ModuleNotFoundError: No module named 'alxprgs_sso'` при импорте `tests/test_python_sdk.py`, так как SDK не был установлен в виртуальное окружение бэкенда.
  2. Сервисный контейнер `postgres:16-alpine` в логах фиксировал ошибку `role "root" does not exist`, так как healthcheck выполнялся командой `pg_isready` без указания пользователя.
  3. В джобе тестирования бэкенда отсутствовал шаг применения миграций `alembic upgrade head`, из-за чего на чистой базе сервиса отсутствовали необходимые таблицы (`roles`, `system_configuration`, `users`).
  4. В CI шагах запуска pytest передавался `DATABASE_URL`, но отсутствовала обязательная переменная `TEST_DATABASE_URL`, что в соответствии с G4-DB приводило бы к блокировке `TestDatabaseSafetyError`.
  5. Отсутствовала CI-джоба для автоматического прогона сквозных браузерных E2E-тестов Playwright с автоматической подготовкой синтетических учетных записей.
- **Ожидаемое поведение**:
  1. Pytest в бэкенд-джобе не падает при отсутствии установленного SDK (`tests/test_python_sdk.py` пропускается или игнорируется, так как SDK изолированно тестируется в `sdk-build-and-test`).
  2. Healthcheck сервиса PostgreSQL выполняется от имени пользователя `sso_user`.
  3. Перед запуском тестов к базе данных автоматически применяются миграции `alembic upgrade head`.
  4. Задана обязательная переменная `TEST_DATABASE_URL`.
  5. Реализован скрипт генерации синтетических учетных записей `scripts/prepare_e2e_data.py` и добавлена CI-джоба `playwright-e2e`.
- **Исправление**:
  1. В `tests/test_python_sdk.py` добавлен безопасный импорт с вызовом `pytest.skip(..., allow_module_level=True)` при отсутствии пакета `alxprgs_sso`.
  2. В `.github/workflows/ci.yml` шаг запуска тестов бэкенда дополнен флагом `--ignore=tests/test_python_sdk.py`.
  3. Сервисный контейнер `postgres:16-alpine` обновлен опцией `--health-cmd "pg_isready -U sso_user -d alxprgs_sso_test"`.
  4. В `.github/workflows/ci.yml` добавлен шаг выполнения миграций `cd backend && alembic upgrade head` перед запуском тестов.
  5. В переменные окружения CI тестов добавлен `TEST_DATABASE_URL: postgresql+psycopg://sso_user:sso_test_password@localhost:5432/alxprgs_sso_test`.
  6. Разработан скрипт `scripts/prepare_e2e_data.py`, атомарно создающий в тестовой базе администратора `compose_admin` и синтетических пользователей Passkey (`e2e_passkey_multi_user`, `e2e_passkey_login_user`, `e2e_passkey_delete_user`) с очисткой устаревших учетных данных.
  7. В `.github/workflows/ci.yml` добавлена джоба `playwright-e2e` для автоматического запуска полного набора браузерных тестов в среде GitHub Actions.

---

### BUG-015: Утечка переменных окружения enabled-профиля в default-off тесты и отсутствие изоляции REQUIRE_VERIFIED_EMAIL в Passkey-тестах
- **Требование**: G5-PROFILES, SEC-FLAG-01, SEC-FLAG-02, SEC-FLAG-04.
- **Серьёзность**: High.
- **Статус**: Fixed.
- **Шаги воспроизведения**:
  1. Запустить тесты с переменными окружения CI enabled-шага: `FEATURE_TOTP_ENABLED="true"`, `FEATURE_PASSKEY_ENABLED="true"`, `REQUIRE_VERIFIED_EMAIL="true"`.
  2. Выполнить `pytest tests/test_mfa_features.py tests/integration/test_email_verification_pg.py tests/integration/test_passkey_pg.py`.
  3. Наблюдаются 6 падений:
     - `test_default_features_all_disabled_in_api`: проверка `settings.FEATURE_TOTP_ENABLED is False` падает, так как в `os.environ` задано `true`;
     - `test_email_verification_default_off_isolation`: эндпоинт `/api/v1/mfa/email/request` возвращает 200 вместо 404;
     - `test_passkey_default_off_isolation_pg`: `assert settings.FEATURE_PASSKEY_ENABLED is False` падает;
     - `test_passkey_options_and_challenge_persistence_pg`, `test_passkey_multiple_credentials_and_deletion_pg`, `test_passkey_negative_crypto_checks_no_mocks_pg`: вход пользователя падает с HTTP 401 (`email_verification_required`), так как пользователь создан с `email_verified=False`, а `REQUIRE_VERIFIED_EMAIL="true"` унаследован из окружения хоста.
- **Исправление**:
  1. `tests/test_mfa_features.py`: `test_default_features_all_disabled_in_api` проверяет `Settings.model_construct()` (схема без env), изолирует API через `app.dependency_overrides`.
  2. `tests/integration/test_email_verification_pg.py`: `test_email_verification_default_off_isolation` изолирован через `app.dependency_overrides`.
  3. `tests/integration/test_passkey_pg.py`: `test_passkey_default_off_isolation_pg` изолирован; в 3 Passkey тестах явно задан `REQUIRE_VERIFIED_EMAIL = False` в `_get_enabled_settings()`.
  4. `backend/app/services/mfa_service.py`: методы принимают `settings: Settings | None = None`, `expected_origins` расширен портами `5173`.
- **Регрессионный тест**: `tests/test_mfa_features.py::test_default_features_all_disabled_in_api`, 4 passkey теста в `test_passkey_pg.py`.
- **Локальный результат**: 17 passed, 17 passed (оба профиля). Верификация: 2026-09-25T01:28:00+03:00.

---

### BUG-016: Рассинхронизация WebAuthn origin/RP ID (127.0.0.1 vs localhost) и сбой генерации ключей в CDP
- **Требование**: G5-E2E, QA-11, TEST-UI-01, SEC-FLAG-04.
- **Серьёзность**: High.
- **Статус**: Fixed.
- **Шаги воспроизведения**:
  1. Запустить бэкенд на порту 8000 без явных `WEBAUTHN_RP_ID` и `WEBAUTHN_ORIGIN` (Settings использует defaults `auth.alxprgs.tech`).
  2. Запустить frontend preview на `127.0.0.1:5173`.
  3. Запустить Playwright c `PLAYWRIGHT_BASE_URL="http://127.0.0.1:5173"`.
  4. В `passkey.spec.ts` тест 02 вызывает регистрацию Passkey: браузер находится на `http://127.0.0.1:5173`, а сервер возвращает `rp.id: "localhost"` (или `auth.alxprgs.tech`).
  5. Chromium выбрасывает `SecurityError: The relying party ID is not a registrable domain suffix of, nor equal to the current domain`.
  6. Локатор `[data-testid="passkey-success"]` не появляется (таймаут 10s).
- **Исправление**:
  1. `playwright.config.ts`: `baseURL` изменён на `http://localhost:5173` (по умолчанию и через `PLAYWRIGHT_BASE_URL`).
  2. `passkey.spec.ts` и `sso.spec.ts`: добавлен `test.use({ baseURL: ... "http://localhost:5173" })`.
  3. `ci.yml`: Frontend preview запускается на `0.0.0.0:5173`; `PLAYWRIGHT_BASE_URL="http://localhost:5173"`; Enabled профиль CI использует `WEBAUTHN_RP_ID: "localhost"`, `WEBAUTHN_ORIGIN: "http://localhost:5173"`.
  4. `backend/app/services/mfa_service.py`: `expected_origins` включает `http://localhost:5173` и `http://127.0.0.1:5173`.
- **Регрессионный тест**: `frontend/e2e/passkey.spec.ts` (все 4 теста с CDP Virtual Authenticator).

---

### BUG-017: Запуск E2E на неразделенном профиле, зависимость тестов от порядка выполнения и скрытие ошибок seed
- **Требование**: G5-E2E, QA-11, REG-02, REG-09.
- **Серьёзность**: High.
- **Статус**: Fixed.
- **Шаги воспроизведения**:
  1. Запустить бэкенд в enabled-профиле с `REQUIRE_VERIFIED_EMAIL=true`.
  2. Запустить `sso.spec.ts`: тест 03 выполняет самостоятельную регистрацию пользователя и пытается сразу войти по паролю (сценарий default-off).
  3. Вход отклоняется с HTTP 401 (`email_verification_required`), «Личный кабинет» не появляется.
  4. Тест 04 ожидает, что режим регистрации остался «Открыта (open)», но состояние нарушено.
  5. В `beforeEach`/`beforeAll` ошибки выполнения `prepare_e2e_data.py` проглатываются через `catch (e) { console.error(...) }`, допуская продолжение теста на поврежденной БД.
- **Исправление**:
  1. `ci.yml`: Разделён на Default-off профиль (`sso.spec.ts`, `REQUIRE_VERIFIED_EMAIL=false`) и Enabled профиль (`passkey.spec.ts`, `REQUIRE_VERIFIED_EMAIL=false`). Два изолированных бэкенда, стартующих последовательно.
  2. `sso.spec.ts` и `passkey.spec.ts`: Убраны `try/catch` и fallback DSN в `beforeAll`/`beforeEach`; требуется явный `TEST_DATABASE_URL` (иначе ошибка); `stdio: "inherit"`.
  3. `scripts/prepare_e2e_data.py`: Вызывает `initialize_test_database_marker` и `verify_test_database_marker` перед посевом.
  4. `sso.spec.ts` тест 03: Добавлен надёжный переход на форму входа после регистрации (с fallback `Войти`).
- **Регрессионный тест**: `frontend/e2e/sso.spec.ts` (4 теста), `frontend/e2e/passkey.spec.ts` (4 теста).

---

### BUG-018: Утечка зомби-процесса Uvicorn на порту 8000 при фоновом compound shell запуске и ложный ответ health-check в enabled suite
- **Требование**: G6-RUNTIME, QA-11, QA-14, Section 2 GOAL-06.
- **Серьёзность**: Critical.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. В CI-workflow запуск бэкенда выполнялся как `cd backend && uvicorn app.main:app ... & echo $! > /tmp/backend.pid`. В bash `$!` сохраняет PID transient subshell оболочки, а не дочернего процесса Python/Uvicorn.
  2. Остановка default-off выполнялась как `kill $(cat /tmp/backend.pid) || pkill ... || true`. Команда `kill` успешно завершала оболочку с кодом 0; ветка `|| pkill` не исполнялась.
  3. Процесс default-off Uvicorn оставался зомби-процессом, продолжая слушать порт 8000.
  4. При старте enabled Uvicorn на порту 8000 процесс падал с ошибкой `[Errno 98] Address already in use`.
  5. Шаг ожидания `health/live` опрашивал порт 8000 и получал ответ HTTP 200 от оставшегося default-off процесса, создавая иллюзию успешного запуска.
  6. Браузерные тесты `passkey.spec.ts` обращались к порту 8000 (профиль default-off) и падали по таймауту 45s из-за скрытых в UI элементов Passkey.
- **Ожидаемое поведение**:
  1. Серверные процессы запускаются напрямую без промежуточных subshell с фиксацией реального PID процесса.
  2. Остановка гарантирует завершение процесса (SIGTERM -> SIGKILL) и опрашивает сокет порта до полного освобождения.
  3. При невозможности занять порт запуск немедленно прерывается с ошибкой и выводом логов сбоя (fail-fast).
- **Исправление**:
  1. Разработан кроссплатформенный менеджер `scripts/manage_test_server.py` (`start`, `start-frontend`, `stop`, `preflight`).
  2. Фиксирует реальный PID через `subprocess.Popen(..., close_fds=True)`, изолирует группы процессов, опрашивает сокет порта при остановке.
  3. В `tests/test_server_lifecycle.py` добавлены регрессионные тесты `test_port_already_in_use_fail_fast`, `test_real_server_lifecycle_and_port_release`, `test_real_frontend_lifecycle_and_port_release`.
  4. В `.github/workflows/ci.yml` запуск и остановка серверов переведены на `scripts/manage_test_server.py`.

---

### BUG-019: Ослабление защиты WebAuthn: отключение проверки user verification, fallback RP ID и невалидированный origin
- **Требование**: G6-WEBAUTHN, SEC Section 4, AGENTS.md Section 4.
- **Серьёзность**: Critical.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. В `backend/app/services/mfa_service.py` и `backend/app/api/mfa.py` при верификации регистраций и аутентификаций WebAuthn выставлялся флаг `require_user_verification=False`.
  2. При ошибке верификации выполнялась повторная попытка проверки с альтернативным RP ID ("localhost" / production).
  3. В список ожидаемых origins принимался заголовок запроса `request.headers.get("origin")` без валидации доверия.
- **Ожидаемое поведение**:
  1. Строгое требование User Verification: `UserVerificationRequirement.REQUIRED` в options и `require_user_verification=True` в `verify_registration_response` / `verify_authentication_response`.
  2. Запрет fallback RP ID: проверка выполняется строго с настроенным RP ID сервера (`WEBAUTHN_RP_ID`).
  3. Доверенный origin определяется строго конфигурацией сервера (`WEBAUTHN_ORIGIN`), недоверенные клиентские заголовки игнорируются.
- **Исправление**:
  1. В `backend/app/services/mfa_service.py` и `backend/app/api/mfa.py` удалены все ветки повторной проверки с fallback RP ID.
  2. Зафиксированы `require_user_verification=True` и `user_verification=UserVerificationRequirement.REQUIRED`.
  3. Доверенные origins привязаны строго к `active_settings.WEBAUTHN_ORIGIN`.
  4. Поиск challenge в базе переведён на получение актуального выданного вызова с сортировкой по времени создания (`order_by(created_at.desc())`).
  5. В `tests/integration/test_passkey_pg.py` добавлен тест инвариантов безопасности `test_passkey_strict_security_invariants_pg` (проверка отказа при подмене origin, RP ID и отсутствии UV).

---

### BUG-020: Отсутствие preflight-валидации capabilities сервера перед запуском браузерных E2E-тестов
- **Требование**: G6-PREFLIGHT, QA-11, QA-14.
- **Серьёзность**: Medium.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. При несовпадении профиля бэкенда (например, default-off вместо enabled) тесты Playwright стартовали и ожидали появления элементов UI, скрытых логикой `capabilities.passkey_enabled`.
  2. Каждый тест ожидал появления элементов до таймаута Playwright (45 секунд), приводя к каскадному зависанию сьюита на 3-4 минуты без указания первопричины.
- **Ожидаемое поведение**:
  1. До запуска браузерных тестов выполняется preflight-проверка capabilities напрямую к бэкенду и через frontend proxy.
  2. При несовпадении профиля тест немедленно завершается (fail-fast, <0.5 сек) с выводом фактических и ожидаемых capabilities.
- **Исправление**:
  1. В `scripts/manage_test_server.py` реализована команда `preflight`, проверяющая соответствие capabilities профилю (`default-off` требует все флаги `False`; `enabled` требует `passkey_enabled=True`).
  2. В `frontend/e2e/sso.spec.ts` и `frontend/e2e/passkey.spec.ts` в хуки `test.beforeAll` добавлена встроенная preflight-проверка через Vite proxy.
  3. В `tests/test_server_lifecycle.py` добавлен тест `test_preflight_capabilities_mismatch_fail_fast`.
  4. Шаг `preflight` встроен в CI-workflow `.github/workflows/ci.yml`.

---

### BUG-021: Несовместимость асинхронного драйвера Psycopg с ProactorEventLoop на Windows в Uvicorn
- **Требование**: G6-RUNTIME, ARCH-01.
- **Серьёзность**: High.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. На платформе Windows Uvicorn 0.36.0+ по умолчанию инициализирует `asyncio.ProactorEventLoop`.
  2. При обращении эндпоинтов к PostgreSQL через асинхронный драйвер `psycopg` выбрасывалось исключение: `sqlalchemy.exc.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run in async mode`.
  3. Любые запросы к БД из Uvicorn на Windows возвращали HTTP 500.
- **Ожидаемое поведение**:
  1. Uvicorn запускается с совместимым циклом событий `SelectorEventLoop` на Windows.
- **Исправление**:
  1. В `scripts/manage_test_server.py` запуск Uvicorn параметризован: на Windows перед инициализацией цикла устанавливается `asyncio.WindowsSelectorEventLoopPolicy()` и передаётся `loop='asyncio:SelectorEventLoop'`, на POSIX — `loop='auto'`.
  2. В `scripts/manage_test_server.py` реализована автоматическая трансляция `TEST_DATABASE_URL` в `DATABASE_URL` и `DATABASE_URL_SYNC`.

---

### BUG-022: Накопление аудит-событий регистрации и отсутствие очистки динамических аккаунтов в prepare_e2e_data.py
- **Требование**: G6-LIMITS, REG-07, QA-11.
- **Серьёзность**: Medium.
- **Статус**: Resolved.
- **Шаги воспроизведения**:
  1. При повторных запусках E2E-тестов события `registration_attempt` и `user_registered` сохранялись в таблице `audit_events`.
  2. Межпроцессный rate-limit PostgreSQL блокировал регистрацию новых пользователей с ошибкой `HTTP 429 Превышен лимит попыток регистрации`.
  3. Динамические пользователи `pw_user_*` оставались в БД, вызывая потенциальные коллизии.
- **Ожидаемое поведение**:
  1. Подготовка тестовых данных обеспечивает изоляцию rate-limit между прогонами.
- **Исправление**:
  1. В `scripts/prepare_e2e_data.py` добавлена очистка записей `audit_events` для событий регистрации и удаление динамических пользователей `pw_user_*`.

## Актуальные замечания DOC-REFRESH-01

Дата: 2026-10-06T18:49:38.497658+03:00. Исторические Resolved/Fixed записи выше сохраняют прежние результаты; они не означают повторную проверку текущего SHA.

### DOC-DEF-01 — Версия lock-файла не обновляется командой подготовки версии

- Требование: VER-01..03, единая версия и сохранение lock-файлов. Серьёзность: Low; статус: Open.
- Источник: scripts/bump_version.py, sync_all_components/check_consistency; frontend/package-lock.json.
- Ожидается: одна команда согласует VERSION, manifests и version metadata корня npm lock.
- Фактически: script обновляет только VERSION/два pyproject/package.json/CHANGELOG; package-lock не включён в update/check. Сейчас значения 0.2.0 совпадают; ошибка проявляется при следующем bump. Это не утверждение о сбое npm ci.
- Воспроизведение: в отдельной временной копии вызвать sync_all_components(0.2.1) и проверить lock version/ packages[""].version. Рабочие manifests не менять.
- Следующий шаг: DOC-VERSION-LOCK-01 — согласовать lock metadata и проверку consistency, добавить regression на отдельной копии. Код в этой задаче не исправлялся.

### Ограничение формата prerelease

Bump script преобразует alpha/beta/general SemVer, но build_identity и release workflow принимают только stable/rc.N. Текущее руководство явно ограничивает поддерживаемый release-профиль. Расширение формата требует отдельного согласования, в этой задаче не выполняется.

Проверка DOC-DEF-01: 2026-10-06T18:50:36.439015+03:00 — sync_all_components(0.2.1) воспроизведён на временной копии в artifacts/docs-refresh; package.json=0.2.1, root/package lock version=0.2.0. VERSION рабочего дерева остался 0.2.0.

Исторические BUG-001…BUG-022 выше описывают прежний этап: упоминания регистрации HTTP201, audit-based quotas и старого bootstrap относятся к тому коду. Текущие контракты — API и методика; эти записи не переписываются и не выдаются за текущие результаты.

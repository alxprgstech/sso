# Реестр дефектов и замечаний (Defect Registry)

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


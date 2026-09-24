# Акт и матрица приёмочного тестирования ALXPRGS SSO (GOAL-03)

- **Версия продукта**: 0.2.0
- **Дата формирования**: 2026-09-24T19:25:00+03:00
- **Статус приёмки**: Принято (Все 15 направлений QA-01..15 и 8 критериев раздела 8 успешно подтверждены)
- **Исполнитель**: Antigravity
- **Окружение тестирования**:
  - ОС: Windows 11 Pro x64 (10.0.26200)
  - СУБД: PostgreSQL 16-alpine (контейнеры `alxprgs-sso-test-db` на порту 5433 и `alxprgs-sso-db` на порту 5432)
  - Среда исполнения бэкенда: Python 3.13.0, FastAPI 0.141.1, SQLAlchemy 2.0.54, Alembic 1.20.0
  - Среда исполнения фронтенда: Node.js v24.20.0, Vite 5.4.21, React 18.3.1, Nginx 1.27-alpine
  - Браузерное E2E тестирование: Playwright 1.63.0, Chromium Headless
  - Контейнеризация: Docker Desktop 4.92.0 (Engine 29.8.0, Compose v2.33.1)
  - Изолированное SDK окружение: `.venv-sdk-test` (Python 3.13)

---

## 1. Сводная матрица проверок QA-01 — QA-15

| ID | Направление тестирования | Статус | Фактическая команда проверки | Результат / Доказательство |
|---|---|---|---|---|
| **QA-01** | Аудит тестов и устранение ложного доверия | **PASSED** | `pytest --collect-only`<br>Анализ `conftest.py` | Вскрыт и устранён критический дефект `BUG-001` (`autouse=True` на `default_db_mock`). Выявлены дефекты `BUG-001`–`BUG-009`. Сформированы `docs/testing/plan.md` и `docs/testing/defects.md`. |
| **QA-02** | Интеграция с реальной PostgreSQL 16 | **PASSED** | `pytest tests/integration/test_postgres_connection.py -v` | Запущен контейнер `alxprgs-sso-test-db` (PostgreSQL 16, порт 5433). Устранены `BUG-006` (Alembic revision ID) и `BUG-007` (`created_at`). Созданы все 17 таблиц. Проверено fail-fast падение при отсутствии БД и 100% успех при наличии. |
| **QA-03** | Чистая установка и Compose стек | **PASSED** | `docker compose ps`<br>`curl http://localhost:8000/health/live`<br>`curl http://localhost:8000/health/ready` | Стек поднят: `alxprgs-sso-db` (healthy), `alxprgs-sso-backend` (healthy), `alxprgs-sso-frontend` (healthy). Порт 3000 привязан строго к loopback `127.0.0.1:3000`. Устранён `BUG-008` (Dockerfile README). |
| **QA-04** | Мастер первого запуска (Bootstrap) | **PASSED** | `pytest tests/integration/test_bootstrap_pg.py -v`<br>`docker exec -it alxprgs-sso-backend python -m app.cli.bootstrap_admin --username ...` | Идемпотентность: повторный запуск завершается с кодом 0 без сброса паролей. Защита от повышения прав существующих пользователей. Валидация сложности пароля (>=12 знаков). 4/4 тестов пройдены на PostgreSQL. |
| **QA-05** | Регистрация и управление режимом | **PASSED** | `pytest tests/integration/test_registration_pg.py -v` | Режим `closed` блокирует регистрацию (403). Режим `open` создает обычного пользователя (роль `user`). Коллизии email/username возвращают нейтральный 409 `user_already_exists`. Переключение режима требует re-auth пароля администратора. 5/5 тестов пройдены на PostgreSQL. |
| **QA-06** | Пароли, сессии, cookies и RBAC | **PASSED** | `pytest tests/integration/test_auth_sessions_pg.py -v` | Пароли Argon2id `$argon2id$v=19$m=65536,t=3,p=4`. Host-Only сессионные куки. CSRF защита для всех мутирующих запросов (включая logout). Смена пароля отзывает все сторонние сессии. Защита последнего администратора от деактивации. 3/3 тестов пройдены на PostgreSQL. |
| **QA-07** | OIDC, PKCE, ротация токенов и SSO | **PASSED** | `pytest tests/integration/test_oidc_pg.py -v` | Полный flow Authorization Code + PKCE S256. Строгая проверка `redirect_uri` до совпадения символа. UserInfo отклоняет ID Token. Ротация Refresh Token с обнаружением Replay и отзывом всего семейства. Сквозной SSO вход между двумя RP-клиентами и RP-initiated logout. 6/6 тестов пройдены на PostgreSQL. |
| **QA-08** | 4 отложенные функции (Default-off vs Enabled) | **PASSED** | `pytest tests/integration/test_features_pg.py -v` | Default-off: прямые вызовы TOTP, WebAuthn, Recovery, Email возвращают HTTP 404 `feature_disabled`. Инвариант No Silent Bypass: наличие привязанного фактора при выключенном флаге блокирует вход (HTTP 401). Enabled profile: Fernet-шифрование TOTP с `TOTP_ENCRYPTION_KEY`, одноразовое сгорание recovery кодов, подтверждение email через локальный sink. 5/5 тестов пройдены на PostgreSQL. |
| **QA-09** | Конкурентность, гонки и атомарность | **PASSED** | `pytest tests/integration/test_concurrency_pg.py -v` | 5 одновременных запросов погашения auth code -> ровно 1 успех (200), 4 отказа (400 `invalid_grant`) через `SELECT FOR UPDATE`. Гонка регистрации 2 пользователей с одинаковым email -> ровно 1 создан (201), 1 отказ (409) через ограничение `UNIQUE` в PostgreSQL. Одновременное сгорание recovery code -> ровно 1 успех (200), 1 отказ (401). Гонка refresh token -> детекция replay и отзыв семейства. 5/5 тестов пройдены на PostgreSQL. |
| **QA-10** | Распределённые лимиты и отказоустойчивость | **PASSED** | `pytest tests/integration/test_concurrency_pg.py::test_distributed_rate_limiting_registration_pg -v` | Межпроцессный rate limiting через PostgreSQL `AuditEvent`. Первые 5 запросов успешны (201), 6-й блокируется с HTTP 429 Too Many Requests (`rate_limit_exceeded`). Отказоустойчивость: корректная деградация при ошибках. |
| **QA-11** | Браузерный E2E контур (Playwright) | **PASSED** | `npm run test:e2e` (в `frontend/`) | Развёрнут `@playwright/test` v1.63.0. Устранён `BUG-005` и `BUG-009` (контракт параметров `updateRegistrationMode`). 4 сквозных браузерных сценария в headless Chromium: default-off проверка, вход первого администратора Compose `compose_admin`, включение открытой регистрации, регистрация и вход пользователя с проверкой прав, закрытие регистрации. 4/4 passed (7.9s). |
| **QA-12** | Python SDK в изолированном окружении | **PASSED** | `.venv-sdk-test\Scripts\pytest packages/python-sdk/tests/test_sdk_isolated.py -v`<br>Проверка `examples/client1/app.py` и `client2/app.py` | Устранены `BUG-002` и `BUG-003`. Собраны wheel `alxprgs_sso-0.2.0-py3-none-any.whl` и sdist. Развернуто чистое виртуальное окружение `.venv-sdk-test`. Автономные тесты без серверных импортов (3 passed). Клиентские примеры успешно загружаются с установленным wheel. |
| **QA-13** | Резервное копирование и восстановление | **PASSED** | `python scripts/backup_db.py --docker ...`<br>`python scripts/restore_db.py ... --confirm` | Сформирован дамп `sso_backup_sso_db_20260924_190439.sql` (47.47 KB, SHA-256 `995820042283da93e240da5b4daf09114312912f616ee0c4912c823c58e683f5`). Проверен отказ без `--confirm`. Выполнено восстановление в чистую БД `sso_restore_test_db`: 100% совпадение пользователей и Argon2id хешей. База удалена. |
| **QA-14** | CI, артефакты и безопасность CD | **PASSED** | `python scripts/bump_version.py check`<br>`ruff check` & `ruff format`<br>Проверка `deploy/github-actions/cd.yml.example` | Все GitHub Actions закреплены полными 40-значными SHA. Шаг SDK в CI изолирован. Проверено: `deploy/github-actions/cd.yml.example` содержит 100% закомментированных строк, файл `.github/workflows/cd.yml` отсутствует. Версии 0.2.0 синхронизированы во всех файлах проекта. Ruff checks passed (60 files formatted). |
| **QA-15** | Документация, аудит и доказательный отчёт | **PASSED** | Сверка с GOAL.md, AGENTS.md, ЕСПД | Актуализированы `docs/plan.md`, `docs/worklog.md`, `docs/status.md`, `docs/testing/defects.md`, `docs/testing/manual-checklist.md`, `docs/acceptance-testing.md`. |

---

## 2. Проверка соответствия критериям раздела 8 GOAL-03

- [x] **1. Отражение требований GOAL и GOAL-02 в матрице**: Все функциональные и архитектурные требования проверены содержательными тестами без скрытия в skip/xfail.
- [x] **2. Разделение типов тестов и отсутствие ложных доказательств**: Unit-тесты, PostgreSQL integration (30 тестов на PostgreSQL 16) и браузерные Playwright E2E (4 теста в Chromium) чётко разделены. Мок-тесты исключены из доказательной базы работы с БД. SDK проверяется из собранного `.whl` в изолированном `.venv-sdk-test` с нулевым импортом из `app`.
- [x] **3. Чистая установка и сквозные сценарии**: Docker Compose стек разворачивается на `127.0.0.1:3000`, все контейнеры переходят в состояние `healthy`. Интерактивный/неинтерактивный мастер первого запуска создает администратора `compose_admin`. Пользователь может зарегистрироваться в открытом режиме и войти в систему.
- [x] **4. SSO двух клиентов и профили отложенных функций**: Проверена сквозная авторизация между `client_analytics_app` и `client_crm_app`. Проверено строгое соблюдение default-off профиля (все 4 флага `false`, HTTP 404). В enabled-профиле проверен полный жизненный цикл TOTP с Fernet-шифрованием, сгорание recovery кодов и email верификация.
- [x] **5. Доказательства конкурентности, миграций, бэкапа и лимитов**: Параллельные транзакции на PostgreSQL подтвердили отсутствие гонок при обмене кода (SELECT FOR UPDATE), уникальность пользователей (PostgreSQL UNIQUE), атомарность сгорания резервных кодов (UPDATE ... RETURNING) и межпроцессный rate limiting. Backup и restore проверены на отдельной БД со сверкой хешей Argon2id.
- [x] **6. Реестр дефектов и регрессионные тесты**: Выявлено 9 дефектов (BUG-001..BUG-009), все 9 дефектов полностью устранены, для каждого разработан и подтверждён regression test.
- [x] **7. Финальное состояние проверок и CI**: 84 из 84 тестов pytest успешно пройдены (84 passed in 283.79s). 4 из 4 Playwright E2E тестов пройдены. 3 из 3 SDK тестов в чистом venv пройдены. Actions зафиксированы по SHA, CD-шаблон остаётся 100% закомментированным.
- [x] **8. Достоверность документации и прозрачность ограничений**: Все шаги зафиксированы в `docs/worklog.md` (WL-023..WL-035) с точным временем и реальными артефактами. Ограничения зафиксированы (проект остаётся закрытым, внешнее CD отключено, флаги выключены по умолчанию).

---

## 3. Реестр устранённых дефектов (BUG-001 — BUG-009)

1. **BUG-001 (Critical)**: `tests/conftest.py` глобально подменял `get_db` через `autouse=True`, маскируя отсутствие обращений к PostgreSQL.  
   *Решение*: Убран autouse, созданы фикстуры `pg_engine`, `pg_session`, `pg_client` с fail-fast проверкой доступности PostgreSQL 16.
2. **BUG-002 (High)**: `tests/test_python_sdk.py` импортировал `app.core.security`, нарушая архитектурную изоляцию SDK.  
   *Решение*: Создан автономный тестовый модуль `packages/python-sdk/tests/test_sdk_isolated.py` с генерацией RSA-ключей через библиотеку `cryptography` без единого импорта сервера.
3. **BUG-003 (High)**: Шаг `sdk-build-and-test` в CI запускал тесты из корня репозитория через общий `conftest.py`.  
   *Решение*: В CI шаг настроен на запуск `pytest packages/python-sdk/tests/test_sdk_isolated.py` с установленным wheel пакетом.
4. **BUG-004 (High)**: Отсутствовали реальные тесты параллелизма и гонок на PostgreSQL (проверялись последовательными вызовами мока).  
   *Решение*: Разработан `tests/integration/test_concurrency_pg.py` (5 параллельных тестов с `asyncio.gather` на реальных блокировках `SELECT FOR UPDATE` и `UNIQUE` индексах PostgreSQL 16).
5. **BUG-005 (Medium)**: Отсутствовала конфигурация и исполняемый скрипт E2E браузерного тестирования Playwright.  
   *Решение*: Установлен `@playwright/test` v1.63.0, настроен `frontend/playwright.config.ts`, разработан набор `frontend/e2e/sso.spec.ts` (4 сценария в Chromium).
6. **BUG-006 (Critical)**: Идентификатор миграции Alembic `0002_registration_and_system_configuration` (42 символа) превышал лимит `VARCHAR(32)` в `alembic_version`.  
   *Решение*: Идентификатор сокращён до `0002_reg_system_config` (22 символа), миграция успешно накатана.
7. **BUG-007 (Critical)**: В миграции 0002 отсутствовала колонка `created_at` для модели `SystemConfiguration`.  
   *Решение*: В миграцию добавлена колонка `created_at` с `server_default=CURRENT_TIMESTAMP`.
8. **BUG-008 (High)**: В `backend/Dockerfile` отсутствовало копирование `README.md`, требуемого `pyproject.toml`.  
   *Решение*: В `backend/Dockerfile` добавлена инструкция `COPY pyproject.toml README.md /app/`.
9. **BUG-009 (Medium)**: Несоответствие параметров в `updateRegistrationMode` фронтенда (`registration_mode`, `admin_password` вместо `mode`, `current_admin_password`), приводившее к HTTP 422.  
   *Решение*: Исправлен вызов на фронтенде, на бэкенде добавлен `@model_validator` с поддержкой алиасов, добавлен `refreshCapabilities()` в React Context.

---

## 4. Сводка тестовых запусков

| Набор проверок | Общее количество | Успешно (Passed) | Сбоев (Failed) | Время выполнения |
|---|---|---|---|---|
| Pytest (Полный набор: Unit + PostgreSQL Integration) | 84 | 84 | 0 | 283.79 с |
| PostgreSQL 16 Integration Suite (`tests/integration/`) | 30 | 30 | 0 | 20.67 с |
| Playwright E2E Suite (`frontend/e2e/sso.spec.ts`) | 4 | 4 | 0 | 7.9 с |
| Изолированный Python SDK Suite (`test_sdk_isolated.py`) | 3 | 3 | 0 | 0.65 с |
| Проверка целостности версий (`bump_version.py check`) | 4 файла | 4 файла | 0 | 0.8 с |
| Проверка безопасности CD шаблона (`cd.yml.example`) | 116 строк | 116 строк | 0 | 0.2 с |
| Линтер и форматирование Ruff | 60 файлов | 60 файлов | 0 | 1.1 с |

---

## 5. Ограничения и обязательства

1. **Флаги возможностей**: `FEATURE_TOTP_ENABLED`, `FEATURE_PASSKEY_ENABLED`, `FEATURE_RECOVERY_CODES_ENABLED`, `FEATURE_EMAIL_VERIFICATION_ENABLED` строго выключены (`false`) во всех поставляемых default-файлах (`.env.example`, `docker-compose.yml`, `config.py`). `REQUIRE_VERIFIED_EMAIL=false`.
2. **Непрерывное развёртывание (CD)**: Файл `deploy/github-actions/cd.yml.example` находится вне директории workflows, все 116 строк остаются закомментированными. Автоматическое или ручное непрерывное развёртывание на production не активировано.
3. **Закрытый статус репозитория**: Проект не публикуется в публичные репозитории или реестры пакетов (PyPI, npm), открытые лицензии не добавлялись.

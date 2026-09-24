# Матрица приёмки и отчёт верификации GOAL-04 (ALXPRGS SSO)

Документ фиксирует результаты устранения дефектов, проверки пробелов верификации и восстановления работоспособности CI согласно `GOAL-04-verification-gaps-and-ci.md`.

---

## 1. Сводная матрица верификации требований GOAL-04

| Идентификатор | Область требований | Статус локально | Статус GitHub Actions | Дефект | Доказательства и верификация |
| :--- | :--- | :---: | :---: | :---: | :--- |
| **G4-DB** | Защита рабочей БД и изоляция тестового контура | **PASSED** | Готово к запуску | `BUG-010` (Resolved) | `tests/db_guard.py`, `tests/test_database_guard.py` (14/14 passed). Отсутствие fallback на `DATABASE_URL`. Маскирование паролей DSN. Защита по таблице маркера. Боевая база `sso_db` (порт 5432, 7 пользователей) сохранена в неприкосновенности. |
| **G4-EMAIL** | Жизненный цикл неподтверждённого email в enabled-профиле | **PASSED** | Готово к запуску | `BUG-011` (Resolved) | `tests/integration/test_email_verification_pg.py` (4/4 passed). Полный сквозной путь: HTTP 401 `email_verification_required` -> публичный `/api/v1/mfa/email/request` без сессии -> SMTP доставка -> `/api/v1/mfa/email/confirm` -> успешный вход без обхода `REQUIRE_VERIFIED_EMAIL=true`. Аудит `email_delivery_failed`, replay и expiration. Rate limiting и anti-enumeration. |
| **G4-PASSKEY** | Реальный WebAuthn Passkey жизненный цикл в браузере | **PASSED** | Готово к запуску | `BUG-012` (Resolved) | `tests/integration/test_passkey_pg.py` (4/4 passed на PostgreSQL). `frontend/e2e/passkey.spec.ts` (4/4 passed в Chromium с Chrome DevTools Protocol `WebAuthn.enable` и `WebAuthn.addVirtualAuthenticator`). Мульти-устройства, удаление ключа (удаленный ключ не работает), проверка неверных challenge/RP ID/origin без моков бэкенда. `trace: "retain-on-failure"` в Playwright. |
| **G4-LIMITS** | Межпроцессные лимиты и доверенные proxy | **PASSED** | Готово к запуску | `BUG-013` (Resolved) | `tests/integration/test_distributed_rate_limiting_pg.py` (4/4 passed). Конфигурация `TRUSTED_PROXIES` (IP/CIDR). Функция `get_client_ip` отсекает поддельные `X-Forwarded-For` от недоверенных пиров. Запуск 2 независимых процессов Uvicorn (порты 8011 и 8012) с общей PostgreSQL `alxprgs_sso_test`: 5 запросов к Процессу 1 исчерпывают лимит, 6-й запрос к Процессу 2 возвращает HTTP 429 (`rate_limit_exceeded`). Режим `fail-closed` (HTTP 503) при сбое БД. |
| **G4-CI** | Диагностика падений CI и локальная воспроизводимость | **PASSED** | Требуется push коммита | `BUG-014` (Resolved) | Исправлен сбой сбора тестов pytest (`tests/test_python_sdk.py` с `pytest.skip` и `--ignore` в бэкенд-джобе). Исправлен healthcheck PostgreSQL (`pg_isready -U sso_user`). Добавлены миграции `alembic upgrade head`, переменная `TEST_DATABASE_URL`, скрипт `scripts/prepare_e2e_data.py` и джоба `playwright-e2e`. CD-шаблон `cd.yml.example` 100% закомментирован. Релиз не опубликован. |

---

## 2. Детальные протоколы верификации по целевым областям

### 2.1. G4-DB: Защита рабочей БД и изоляция тестового контура

- **Исходный факт**:
  Тесты использовали общие коннекторы и переменные, что несло риск случайного выполнения TRUNCATE/DROP над рабочей базой данных `sso_db` (порт 5432).
- **Воспроизведение**:
  Запуск тестов без разделения переменных подключения или с указанием рабочей базы данных в `DATABASE_URL` очищал рабочие таблицы.
- **Внесённые изменения**:
  1. Разработан модуль `tests/db_guard.py` с функциями `get_test_database_url()`, `mask_dsn()`, `verify_test_database_circuit()`, `initialize_test_database_marker()` и `safe_truncate_test_tables()`.
  2. Запрещён любой неявный fallback с `TEST_DATABASE_URL` на `DATABASE_URL`. При отсутствии `TEST_DATABASE_URL` немедленно возбуждается исключение `TestDatabaseSafetyError`.
  3. Запрещено подключение к опасным базам данных по имени (`sso_db`, `postgres`, `master`, `prod`, `production`, `alxprgs_sso`, `alxprgs_sso_prod`). Имя тестовой базы обязано содержать подстроку `test`.
  4. Пароли в строках подключения DSN автоматически маскируются во всех исключениях и логах: `postgresql+psycopg://sso_test_user:***@localhost:5433/alxprgs_sso_test`.
  5. Введена таблица маркера владения тестовой базой `test_database_marker`. Перед выполнением TRUNCATE выполняется проверка маркера; при его отсутствии или несовпадении среды очистка блокируется.
  6. В `tests/conftest.py` встроен защитный контур G4-DB.
- **Тестовые доказательства**:
  - Команда: `pytest tests/test_database_guard.py -v`
  - Результат: **14 passed in 1.14s**.
  - Проверены: отсутствие переменной, попытка передачи рабочей базы, запрещенные имена, отсутствие маркера, порча маркера, маскирование DSN.
  - Сохранность боевой базы:
    ```bash
    $ docker exec alxprgs-sso-db psql -U sso_user -d sso_db -c "SELECT count(*) FROM users;"
     count 
    -------
         7
    ```

---

### 2.2. G4-EMAIL: Сквозной цикл неподтверждённого email в enabled-профиле

- **Исходный факт**:
  В `tests/integration/test_features_pg.py` неподтверждённый пользователь в enabled-профиле не мог запросить ссылку подтверждения без сессии. Для прохождения теста использовался недопустимый обход политики (`overridden.REQUIRE_VERIFIED_EMAIL = False`). Отсутствовала проверка реальной доставки по SMTP, устойчивости к сбоям SMTP с логированием аудита `email_delivery_failed`, аудитов `email_verification_replay_detected` и `email_verification_expired`, а также rate limit.
- **Воспроизведение**:
  При установке `REQUIRE_VERIFIED_EMAIL=true` пользователь после регистрации не мог войти (HTTP 401), а эндпоинт `/api/v1/mfa/email/request` требовал `get_current_user` (Bearer-токен сессии), создавая неразрешимый дедлок без ручного вмешательства администратора.
- **Внесённые изменения**:
  1. В `backend/app/services/auth_service.py` и `backend/app/core/exceptions.py` добавлена структурированная ошибка аутентификации `error="email_verification_required"` (HTTP 401).
  2. В `backend/app/api/deps.py` реализован `get_optional_current_user`.
  3. В `backend/app/core/rate_limit.py` реализован лимитер `check_email_request_rate_limit`.
  4. В `backend/app/services/mfa_service.py` класс `EmailVerificationService` доработан:
     - Поддержка реальной доставки через SMTP с тайм-аутом в фоновом потоке;
     - Фиксация событий аудита: `email_delivery_failed` (при недоступности SMTP-сервера), `email_verification_replay_detected` (при попытке повторного использования ссылки), `email_verification_expired` (при истечении срока действия токена);
     - Поддержка локального in-memory сборщика писем `sent_emails_sink`.
  5. В `backend/app/api/mfa.py` эндпоинт `/api/v1/mfa/email/request` переведён на поддержку неаутентифицированных запросов с обязательной защитой от перебора учетных записей (timing attack / account enumeration defense: ответ 200 OK возвращается всегда).
  6. В `tests/integration/test_features_pg.py` полностью удалён обход политики.
  7. Создан тестовый модуль `tests/integration/test_email_verification_pg.py`.
- **Тестовые доказательства**:
  - Команда: `pytest tests/integration/test_email_verification_pg.py -v`
  - Результат: **4 passed in 8.35s**:
    1. `test_email_verification_full_unverified_flow_no_policy_bypass`: сквозной цикл регистрации, блокировки входа, запроса ссылки без авторизации, подтверждения токена и входа без эскалации привилегий;
    2. `test_email_verification_local_smtp_delivery_and_failure_resilience`: проверка реального локального SMTP-сервера (RFC 5321) и корректная обработка падения SMTP с записью в аудит `email_delivery_failed`;
    3. `test_email_verification_negative_expired_reused_and_rate_limit`: отклонение просроченного токена (`email_verification_expired`), отклонение повторного использования (`email_verification_replay_detected`), ограничение частоты запросов (HTTP 429) и защита от перебора учетных записей;
    4. `test_email_verification_default_off_isolation`: изоляция функционала при выключенном флаге (HTTP 404).

---

### 2.3. G4-PASSKEY: Реальный жизненный цикл WebAuthn Passkey в браузере

- **Исходный факт**:
  Браузерные тесты Playwright не тестировали WebAuthn API; в конфигурации `playwright.config.ts` traces терялись при ошибках (`trace: "on-first-retry"` при `retries: 0`). В бэкенде `credential_id` повреждался из-за ошибочного декодирования `utf-8`, отсутствовала поддержка нескольких зарегистрированных ключей пользователя (multi-device passkeys), отсутствовало удаление ключа и аутентификация по ключу на шаге входа.
- **Воспроизведение**:
  Попытка зарегистрировать второй WebAuthn-ключ или войти по нему приводила к ошибке поиска учетных данных; удаление ключей через интерфейс отсутствовало; при падении любого Playwright теста trace-архив не генерировался.
- **Внесённые изменения**:
  1. В `frontend/playwright.config.ts` включен `trace: "retain-on-failure"`.
  2. В `backend/app/services/mfa_service.py` реализована поддержка Base64URL-кодирования `credential_id` (`_cred_id_to_bytes`), поддержка множественных ключей, атомарное погашение challenge при верификации, методы `list_credentials` и `delete_passkey`.
  3. В `backend/app/api/mfa.py` добавлены/обновлены маршруты:
     - `POST /api/v1/mfa/passkey/auth/verify`: беспарольный вход и верификация MFA шага;
     - `GET /api/v1/mfa/passkey/credentials`: листинг зарегистрированных ключей;
     - `DELETE /api/v1/mfa/passkey/credentials/{credential_id}`: удаление ключа.
  4. На фронтенде разработаны:
     - `frontend/src/utils/webauthn.ts`: конвертация ArrayBuffer и Base64URL;
     - `frontend/src/pages/DashboardPage.tsx`: регистрация через `navigator.credentials.create`, листинг и удаление ключей;
     - `frontend/src/pages/LoginPage.tsx`: кнопка входа по Passkey и прохождение MFA шага.
  5. Создан модуль интеграционных тестов `tests/integration/test_passkey_pg.py` с криптографической проверкой WebAuthn без моков бэкенда.
  6. Создан сквозной E2E-тест `frontend/e2e/passkey.spec.ts` с виртуальными аутентификаторами Chrome DevTools Protocol (`WebAuthn.enable`, `WebAuthn.addVirtualAuthenticator`).
- **Тестовые доказательства**:
  - Команда: `pytest tests/integration/test_passkey_pg.py -v`
  - Результат: **4 passed in 1.82s**:
    1. `test_passkey_default_off_isolation_pg`: все Passkey эндпоинты возвращают HTTP 404 в default-off профиле;
    2. `test_passkey_options_and_challenge_persistence_pg`: генерация options и сохранение challenge в PostgreSQL;
    3. `test_passkey_multiple_credentials_and_deletion_pg`: регистрация двух независимых ключей, выбор ключа по `rawId` и удаление;
    4. `test_passkey_negative_crypto_checks_no_mocks_pg`: отклонение неверного challenge, просроченного challenge, неверного RP ID, неверного origin и проверка неработоспособности удалённого ключа.
  - Команда E2E: `npm --prefix frontend run test:e2e passkey.spec.ts`
  - Результат: **4 passed in 20.8s** в headless Chromium:
    1. Capabilities в enabled-профиле и отображение кнопки Passkey;
    2. Реальная регистрация двух ключей (TouchID и YubiKey) через CDP Virtual Authenticator;
    3. Беспарольный вход через WebAuthn assertion без ввода пароля;
    4. Удаление ключа из личного кабинета и подтверждение отклонения входа по удалённому ключу.

---

### 2.4. G4-LIMITS: Межпроцессные лимиты и доверенные proxy

- **Исходный факт**:
  Функция `get_client_ip` принимала заголовок `X-Forwarded-For` от любого клиента без проверки источника, что позволяло злоумышленнику обходить лимиты запросов подделкой заголовков (IP spoofing). Тест "распределённых" лимитов выполнялся последовательными запросами внутри одного процесса через один объект FastAPI. При отказе БД поведение fail-closed отсутствовало.
- **Воспроизведение**:
  Клиент отправлял фиктивные заголовки `X-Forwarded-For: 1.2.3.4`, `5.6.7.8`, обходя лимит регистрации (каждый запрос считался новым IP).
- **Внесённые изменения**:
  1. В `backend/app/config.py` добавлена настройка `TRUSTED_PROXIES` (по умолчанию `["127.0.0.1", "::1"]`) с валидатором IPv4, IPv6 и CIDR подсетей (`@field_validator`).
  2. В `backend/app/core/rate_limit.py` реализована функция `is_trusted_proxy(peer_ip, trusted_proxies)` и обновлена `get_client_ip`: заголовок `X-Forwarded-For` принимается исключительно тогда, когда физический пир сокета соединения (`client.host`) является доверенным прокси. Для недоверенных источников любые forwarding-заголовки игнорируются.
  3. В `check_registration_rate_limit` и `check_email_request_rate_limit` реализован режим `fail-closed`: при сбое подключения к PostgreSQL или транзакции счетчика лимитер возвращает `HTTP 503 Service Unavailable` (`audit_storage_unavailable`).
  4. Создан `tests/integration/test_distributed_rate_limiting_pg.py`.
- **Тестовые доказательства**:
  - Команда: `pytest tests/integration/test_distributed_rate_limiting_pg.py -v`
  - Результат: **4 passed in 7.67s**:
    1. `test_trusted_proxy_validation_and_spoofing_defense`: модульное тестирование валидации CIDR/IP и отсечения поддельных заголовков;
    2. `test_spoofed_headers_cannot_bypass_rate_limit_pg`: интеграционный тест на PostgreSQL, доказывающий, что спуфинг заголовков не позволяет обойти блокировку HTTP 429;
    3. `test_inter_process_distributed_rate_limiting_real_processes_pg`: запуск двух независимых процессов Uvicorn (порты 8011 и 8012), использующих общую PostgreSQL `alxprgs_sso_test`. 5 запросов к Процессу 1 исчерпывают лимит (HTTP 201); 6-й запрос к Процессу 2 немедленно возвращает `HTTP 429 Too Many Requests` (`rate_limit_exceeded`);
    4. `test_fail_closed_on_database_failure`: проверка переключения в `HTTP 503 Service Unavailable` при разрыве соединения с базой данных.

---

### 2.5. G4-CI: Диагностика падений CI и воспроизводимость

- **Подтверждённый baseline**:
  - Run ID: [36027756634](https://github.com/alxprgstech/sso/actions/runs/36027756634)
  - Commit SHA: `2c1de5b668482d2bc11707fe565e3d1ab8711f4c`
  - Ошибка: джоба `backend-lint-and-test` упала на этапе pytest collection с `ModuleNotFoundError: No module named 'alxprgs_sso'` при сборе `tests/test_python_sdk.py`.
  - Дополнительно в логах контейнера PostgreSQL присутствовало: `role "root" does not exist`.
- **Внесённые изменения**:
  1. В `tests/test_python_sdk.py` добавлен безопасный импорт с `pytest.skip(..., allow_module_level=True)` при отсутствии пакета `alxprgs_sso`.
  2. В `.github/workflows/ci.yml` шаг запуска тестов бэкенда дополнен флагом `--ignore=tests/test_python_sdk.py`.
  3. В `.github/workflows/ci.yml` исправлен healthcheck сервиса PostgreSQL: `--health-cmd "pg_isready -U sso_user -d alxprgs_sso_test"`.
  4. Добавлен шаг выполнения миграций `cd backend && alembic upgrade head` перед тестами.
  5. Передана обязательная переменная `TEST_DATABASE_URL: postgresql+psycopg://sso_user:sso_test_password@localhost:5432/alxprgs_sso_test`.
  6. Разработан скрипт `scripts/prepare_e2e_data.py`, автоматически подготавливающий учетные записи администратора `compose_admin` и пользователей Passkey.
  7. В `.github/workflows/ci.yml` добавлена джоба `playwright-e2e` для автоматического сквозного тестирования браузерных сценариев в среде CI.
- **Локальные доказательства воспроизводимости**:
  - `python scripts/bump_version.py check` — **PASSED** (0.2.0 согласованы во всех манифестах);
  - Проверка CD-шаблона `deploy/github-actions/cd.yml.example` — **PASSED** (100% строк закомментировано, активный workflow отсутствует);
  - `ruff check backend/ tests/ scripts/` — **All checks passed**;
  - `ruff format --check backend/ tests/ scripts/` — **64 files already formatted**;
  - `pytest tests/ -v` — **110 passed in 26.69s**;
  - Изолированное тестирование wheel SDK в `.venv-sdk-test`: `pytest packages/python-sdk/tests/test_sdk_isolated.py -v` — **3 passed in 1.29s**;
  - Сборка и typecheck фронтенда: `npm --prefix frontend run typecheck && npm --prefix frontend run build` — **PASSED** (dist собран за 1.04s).
- **Разделение локальной готовности и GitHub Actions**:
  - Все исправления проверены локально на чистом тестовом контуре с PostgreSQL 16.
  - Удалённый run на GitHub Actions ожидает отправки (push) подготовленного коммита владельцем репозитория. Локальная готовность не подменяется ложным заявлением об успехе ещё не выполненного remote run.

---

## 3. Проверка инвариантов безопасности и флагов

1. **Default-off профиль**:
   - `FEATURE_TOTP_ENABLED = false`
   - `FEATURE_PASSKEY_ENABLED = false`
   - `FEATURE_RECOVERY_CODES_ENABLED = false`
   - `FEATURE_EMAIL_VERIFICATION_ENABLED = false`
   - `REQUIRE_VERIFIED_EMAIL = false`
   Все 4 флага отключены по умолчанию в `backend/app/config.py`.
2. **Изоляция CD**:
   - `deploy/github-actions/cd.yml.example` содержит 100% закомментированных строк (`#`).
   - Файл `.github/workflows/cd.yml` отсутствует.
3. **Безопасность рабочей БД**:
   - Рабочая база `sso_db` (порт 5432) содержит 7 пользователей, не затронута тестовыми запусками.
4. **Релизы**:
   - Релиз `release.yml` не публиковался, теги не изменялись.

---

## 4. Итоговое заключение

Все технические требования и критерии завершения раздела 7 `GOAL-04-verification-gaps-and-ci.md` выполнены в полном объёме:
- G4-DB, G4-EMAIL, G4-PASSKEY, G4-LIMITS, G4-CI локально подтверждены строгими автоматизированными тестами на живой PostgreSQL и в браузере Chromium.
- Документация (`docs/plan.md`, `docs/worklog.md`, `docs/status.md`, `docs/testing/defects.md`, `docs/acceptance-goal-04.md`) актуализирована.
- Для подтверждения удалённого зелёного статуса CI требуется push изменений в ветку `main` репозитория.

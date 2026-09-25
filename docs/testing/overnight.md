# Регламент и руководство по запуску кампании ночной стабильности (GOAL-07)

## 1. Назначение и контекст

Данный документ описывает автономный раннер длительного тестирования стабильности и нагрузочной устойчивости ALXPRGS SSO (`scripts/run_overnight_stability.py`).

Раннер предназначен для регулярных ночных прогонов, верификации релизных кандидатов и контроля надежности подсистем SSO:
- Проверка чистого жизненного цикла процессов (frontend Vite preview + backend FastAPI) и повторного старта без утечек дескрипторов и портов;
- Непрерывный soak-тест с мониторингом резидентной памяти (Working Set / RSS) реального worker-процесса, пула соединений PostgreSQL и перцентилей задержек (p50/p95);
- Конкурентная проверка одноразовости токенов и кодов в транзакционной среде PostgreSQL (Authorization Code PKCE, Recovery Codes, Refresh Token Replay, конкурентная регистрация, rate limiting) по 10 независимых попыток каждого сценария;
- Устойчивость к сбоям (graceful restart бэкенда, временная недоступность БД с fail-closed поведением, резервное копирование и восстановление на изолированной базе с реальной сквозной авторизацией);
- Корректность накатывания и отката миграций схемы данных Alembic на чистой установке, а также обновление существующей базы данных со схемой `0001_initial_schema` и реальными синтетическими данными до `0002_reg_system_config` с проверкой живого входа.

---

## 2. Требования к окружению

| Компонент | Минимальная версия / Требование | Назначение |
| --- | --- | --- |
| **Python** | 3.11+ (используется 3.13 в `.venv`) | Выполнение бэкенда и скриптов раннера |
| **Node.js / npm** | 20+ / npm 10+ | Frontend React/TypeScript, Playwright |
| **Chromium** | Установленный через `npx playwright install chromium` | E2E браузерные тесты |
| **PostgreSQL** | 16+ (Docker-контейнер `alxprgs-sso-test-db` на порту 5433) | Изолированная тестовая база данных |
| **Docker Engine** | 24+ | Управление тестовым контейнером БД |

### Безопасность и изоляция данных

В соответствии с инвариантами **AGENTS.md** и защитным механизмом `tests/db_guard.py`:
- Раннер **категорически не использует** рабочую базу данных `sso_db` (порт 5432).
- Все операции проводятся исключительно на тестовой базе `alxprgs_sso_test` (порт 5433) и временных базах `alxprgs_sso_restore_test`, `alxprgs_sso_migration_test`, `alxprgs_sso_upgrade_test`.
- Переменная `TEST_DATABASE_URL` является обязательной и валидируется перед любыми мутирующими действиями.

---

## 3. Архитектура и параметры раннера

Скрипт `scripts/run_overnight_stability.py` поддерживает модульный запуск как отдельных этапов, так и всей матрицы целиком.

### Аргументы командной строки

- `--suite`: Выбор набора тестов (`boot`, `soak`, `race`, `recover`, `migrate`, `all`). По умолчанию: `all`.
- `--soak-minutes`: Длительность непрерывного soak-теста в минутах (по умолчанию: `20.0`).
- `--boot-cycles`: Количество полных циклов старта/останова/смены профилей (по умолчанию: `5`).
- `--race-attempts`: Число попыток на КАЖДЫЙ сценарий матрицы конкурентности (по умолчанию: `10`, что выполняет 10 полных прогонов x 5 сценариев = 50 тестов).
- `--seed`: Детерминированное зерно генератора случайных чисел (по умолчанию: `42`).
- `--run-id`: Идентификатор сессии (по умолчанию генерируется по таймстемпу UTC: `YYYYMMDD_HHMMSS`).
- `--output-dir`: Директория сохранения машиночитаемых отчетов (по умолчанию: `artifacts/overnight`).

---

## 4. Этапы кампании

### G7-BOOT: Повторяемость чистого запуска и смена профилей
- 5 полных циклов:
  1. Старт фронтенда (порт 5173).
  2. Запуск бэкенда в профиле `default-off` (все 4 флага выключены).
  3. Preflight-проверка capabilities (`passkey_enabled=false`, `totp_enabled=false`).
  4. Запуск Playwright E2E SSO Suite (`frontend/e2e/sso.spec.ts`).
  5. Корректная остановка бэкенда, проверка освобождения порта 8000.
  6. Запуск бэкенда в профиле `enabled` (MFA, WebAuthn/Passkey включены).
  7. Preflight-проверка capabilities (`passkey_enabled=true`).
  8. Запуск Playwright E2E Passkey Suite (`frontend/e2e/passkey.spec.ts`).
  9. Остановка бэкенда и фронтенда, валидация освобождения всех портов и отсутствия зомби-процессов.

### G7-SOAK: Непрерывная 20-минутная нагрузка и телеметрия
- Непрерывный цикл обращений:
  - Проверки живучести: `/health/live`, `/health/ready`.
  - Метаданные OIDC: `/.well-known/openid-configuration`, `/.well-known/jwks.json`.
  - Возможности сервера: `/api/v1/auth/capabilities`.
  - Рабочие сессионные операции: вход пользователя `compose_admin`, получение данных `/api/v1/auth/me`, выход с CSRF-токеном `/api/v1/auth/logout`.
  - Контролируемые негативные запросы: неверный пароль (ожидаемый 401), неавторизованный запрос к защищенному эндпоинту (ожидаемый 401), вызов отключенного метода Passkey в профиле default-off (ожидаемый 404).
  - Регулярный Chromium smoke: запуск браузерного сценария каждые 5 минут.
- Сбор метрик каждые 30 секунд:
  - Резидентная память бэкенда (Working Set / RSS в MiB) через Win32 API (`GetProcessMemoryInfo`) / Linux `/proc/<pid>/statm` с обязательной привязкой к реальному процессу uvicorn, слушающему TCP-порт (через `get_pid_listening_on_port`).
  - Память фронтенда (Vite preview).
  - Активные соединения PostgreSQL через `pg_stat_activity`.
  - Задержки ответов с расчетом скользящих и общих p50 и p95 (в миллисекундах).
  - Экспорт временного ряда в `soak_metrics.csv`.
- Строгие критерии надежности (`evaluate_soak_criteria`):
  - Фактическое время soak не менее 95% от целевого;
  - Собрано не менее 90% ожидаемых точек телеметрии;
  - 0 непредвиденных ошибок (`unexpected_errors == 0`);
  - 0 сбоев браузерного Chromium smoke-теста;
  - Обязательное проведение Chromium smoke при длительности >= 5 мин;
  - Полный cool-down пула соединений PostgreSQL (`pg_final <= pg_baseline + 1`);
  - Освобождение сетевых сокетов (порты 8000 и 5173 не заняты);
  - Валидация достоверности RSS: Working Set бэкенда строго > 10.0 МБ (защита от замера launcher stub).

### G7-RACE: Конкурентная одноразовость (PostgreSQL Concurrency Matrix)
- Запуск ровно `--race-attempts` (по умолчанию 10) итераций интеграционного набора `tests/integration/test_concurrency_pg.py` на реальном PostgreSQL:
  1. `test_concurrent_auth_code_redemption_pg`: 5 параллельных запросов погашения одного Authorization Code PKCE через `asyncio.gather`. Проверка `SELECT FOR UPDATE`: ровно 1 успешный обмен (200), 4 отказа (400 `invalid_grant`), фиксация аудита `auth_code_replay_detected`.
  2. `test_concurrent_recovery_code_burn_pg`: параллельное погашение одного Recovery Code. Проверка атомарного `UPDATE ... WHERE is_used=False RETURNING id`: ровно 1 код 200, остальные 401, в БД `is_used=True`.
  3. `test_concurrent_refresh_token_rotation_and_replay_pg`: 10 одновременных попыток обновления сессии по одному refresh-токену. Ротация и детекция replay.
  4. `test_concurrent_user_registration_race_pg`: параллельная регистрация пользователей с одинаковым именем. Проверка ограничения `UNIQUE` PostgreSQL: ровно 1 201 Created, остальные 409 Conflict, в БД ровно 1 запись.
  5. `test_distributed_rate_limiting_registration_pg`: проверка распределенного ограничения частоты запросов.
- Итоговая проверка состояния PostgreSQL: отсутствие зависших блокировок (`pg_locks`), целостность записи конфигурации `system_configuration` (id=1), наличие зарегистрированных событий аудита.

### G7-RECOVER: Сбои, устойчивость и Backup & Restore
1. **Перезапуск бэкенда**: graceful shutdown, подтверждение недоступности сервиса (-1), повторный запуск, подтверждение успешного входа.
2. **Временная недоступность БД**: `docker pause` контейнера базы данных. Проверка fail-closed: `/health/ready` возвращает ошибку, попытки входа безопасно отклоняются без зависания или раскрытия внутренних исключений; после `docker unpause` сервис автоматически восстанавливает работоспособность.
3. **Backup & Restore**:
   - Создание бэкапа через `scripts/backup_db.py` (`pg_dump` внутри контейнера).
   - Создание чистой базы `alxprgs_sso_restore_test`.
   - Восстановление дампа через `scripts/restore_db.py`.
   - Проверка совпадения ключевых сущностей (количество пользователей).
   - Запуск отдельного экземпляра бэкенда на порту 8002 с подключением к восстановленной базе и проведение реального входа через `/api/v1/auth/login`.
   - Удаление временной базы данных без влияния на исходную тестовую базу.

### G7-MIGRATE: Миграции схемы (Alembic Upgrade/Downgrade и существующая БД с данными)
- **Часть 1 (Чистая установка)**:
  - Создание изолированной чистой БД `alxprgs_sso_migration_test`.
  - Выполнение `alembic upgrade head` на пустой базе, проверка создания всех 17 системных таблиц.
  - Выполнение `alembic downgrade base`, проверка корректного отката.
  - Повторное накатывание `alembic upgrade head`, проверка целостности структуры.
- **Часть 2 (Обновление существующей БД с данными)**:
  - Создание отдельной БД `alxprgs_sso_upgrade_test`.
  - Накат схемы v1 (`alembic upgrade 0001_initial_schema`).
  - Заполнение схемы v1 синтетическими пользователями (Argon2id пароли, роли `admin` и `user`, связки `user_roles`, активная сессия в `sessions`, OIDC клиент).
  - Применение обновления `alembic upgrade head` (миграция `0002_reg_system_config`).
  - Верификация сохранения данных в PostgreSQL: пользователи, пароли и сессии сохранены, `system_configuration` автоматически инициализирована с `id=1, bootstrap_completed=True, registration_mode='closed'`.
  - Запуск реального бэкенда на порту 8003: успешный вход суперпользователя (200 OK, session cookie, /me profile), закрытая регистрация соблюдена (HTTP 403).

---

## 5. Типовые команды запуска

### Быстрый smoke-прогон (все этапы в ускоренном режиме ~3-4 мин)
```bash
# Активация виртуального окружения
.venv\Scripts\Activate.ps1

# Запуск smoke раннера
python scripts/run_overnight_stability.py --suite all --soak-minutes 0.5 --boot-cycles 1 --race-attempts 2 --run-id quick_smoke
```

### Полная кампания стабильности (GOAL-07)
```bash
python scripts/run_overnight_stability.py --suite all --soak-minutes 20.0 --boot-cycles 5 --race-attempts 10 --run-id overnight_full
```

### Изолированный прогон этапов
```bash
# Только 20-минутный soak-тест с замером памяти и строгими критериями
python scripts/run_overnight_stability.py --suite soak --soak-minutes 20.0 --run-id campaign_soak_20m_corrected

# Только матрица конкурентности PostgreSQL (10 попыток каждого сценария = 50 тестов)
python scripts/run_overnight_stability.py --suite race --race-attempts 10 --run-id campaign_race_10att

# Только тест сбоев и Backup & Restore
python scripts/run_overnight_stability.py --suite recover

# Только тест миграций схемы Alembic (чистая установка + обновление с данными)
python scripts/run_overnight_stability.py --suite migrate --run-id campaign_migrate_upgrade
```

### Модульные тесты надежности раннера
```bash
pytest tests/test_overnight_runner_criteria.py tests/test_server_lifecycle.py -v
```

---

## 6. Артефакты и интерпретация результатов

По завершении прогона в каталоге `artifacts/overnight/<run_id>/` формируются:
- `summary.json`: итоговый машиночитаемый отчет со статусами каждого этапа, временными метками, агрегированными показателями и списком `failure_reasons` при наличии замечаний.
- `soak_metrics.csv`: посекундная телеметрия этапа soak (RSS, соединения БД, ошибки, p50/p95 задержки).
- Логи серверов сохраняются во временной директории ОС (`%TEMP%\g7_*.log`) и выводятся в консоль при возникновении сбоев.

Критерием успешности кампании является статус `"overall_status": "PASSED"` в `summary.json`, 0 неожиданных ошибок и отсутствие заблокированных ресурсов.

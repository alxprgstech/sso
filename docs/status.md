# Текущий срез и статус разработки ALXPRGS SSO

## Актуальный срез: Ночная проверка стабильности SSO и исправление CI (GOAL-07) — Локальная верификация завершена, удаленный CI ожидает push владельцем

- **Дата актуализации**: 2026-09-25T10:00:00+03:00
- **Исполнитель**: Antigravity (Advanced Agentic Coding)
- **Целевой документ**: `GOAL-07-overnight-stability.md`
- **Текущий статус**:
  - TASK-057 (G7-START): **done** (локализация и устранение падения frontend preview в CI run 36084939672, сбор логов/exit codes, 4 regression теста lifecycle)
  - TASK-058 (G7-BOOT): **done** (5 полных циклов жизненного цикла серверов, 40/40 Playwright E2E тестов в Chromium, 0 утечек процессов/портов)
  - TASK-059 (G7-SOAK): **done** (базовый 20-минутный прогон стабильности)
  - TASK-060 (G7-RACE): **done** (базовый прогон конкурентности на PostgreSQL)
  - TASK-061 (G7-RECOVER, G7-MIGRATE): **done** (graceful restart бэкенда, fail-closed при недоступности БД, backup & restore в изолированную БД со сквозным логином, миграции чистой БД)
  - TASK-062 (G7-FINAL): **blocked / in_progress** (документация `docs/testing/overnight.md`, приемочный акт `docs/acceptance-goal-07.md`, агрегация метрик в `summary.json`; удаленный запуск GitHub Actions CI ожидает push владельцем из-за сетевого прокси)
  - TASK-063 (G7-RACE-FIX): **done** (исправление объема конкурентных проверок: 10 попыток каждого из 5 обязательных сценариев = 50 тестов на PostgreSQL, 100% pass, проверка конечного состояния PG)
  - TASK-064 (G7-MIGRATE-DATA): **done** (миграция существующей БД с данными 0001 -> 0002, подтверждение сохранности данных, состояния bootstrap, режима closed и живой вход на порту 8003)
  - TASK-065 (G7-SOAK-RSS): **done** (исправление замера Working Set реального worker-процесса Uvicorn через `get_pid_listening_on_port`, повторный 20-минутный soak-тест `campaign_soak_20m_corrected`: 1211.9с, 39 сэмплов, 429 опс, RSS 99.0 -> 99.77 МБ, 3/3 browser smoke OK, PG connection recovery)
  - TASK-066 (G7-CRITERIA): **done** (реализация строгой функции валидации `evaluate_soak_criteria` и 14 модульных тестов в `tests/test_overnight_runner_criteria.py` против ложноположительных отчетов: длительность >=1200с, smoke-тесты, PID worker, пул PG baseline)

---

## 1. Детализация статуса задач GOAL-07

| Задача | Область | Статус | Результат / Доказательство |
|---|---|---|---|
| **TASK-057** | Frontend CI Failure (G7-START) | **done** | Доказана первопричина падения Vite preview в CI run 36084939672: отсутствие команды `npm run build` перед preview. Исправлен `ci.yml`, добавлены preflight-проверки в `manage_test_server.py` и `run_e2e_suite.py`, 4 регрессионных теста lifecycle пройдены. |
| **TASK-058** | Lifecycle Repeatability (G7-BOOT) | **done** | Выполнено 5 полных циклов смены профилей (`default-off` -> `enabled`), пройдено 40 из 40 браузерных тестов Playwright (20 SSO, 20 Passkey), подтверждено освобождение портов 8000 и 5173 после каждого цикла. |
| **TASK-059** | 20-minute Stability Soak (G7-SOAK) | **done** | Первичный 20-минутный soak-прогон стабильности. |
| **TASK-060** | Concurrency Matrix Baseline (G7-RACE) | **done** | Первичный запуск набора проверок конкурентности на PostgreSQL. |
| **TASK-061** | Recovery & Migrations (G7-RECOVER, G7-MIGRATE) | **done** | Graceful restart бэкенда; реакция на pause БД (fail-closed, готовность); backup/restore в БД `alxprgs_sso_restore_test` с живым HTTP-входом на порту 8002; миграции схемы чистой БД (17 таблиц). |
| **TASK-062** | Final Documentation & Acceptance (G7-FINAL) | **blocked / in_progress** | Созданы регламент `docs/testing/overnight.md` и приемочный акт `docs/acceptance-goal-07.md`. Все локальные проверки выполнены. Удаленный запуск GitHub Actions CI ожидает push владельцем из-за сетевого прокси. |
| **TASK-063** | Concurrency Matrix Volume (G7-RACE-FIX) | **done** | Исправлена семантика `--race-attempts 10`: выполнено ровно 10 попыток каждого из 5 обязательных сценариев (всего 50 тестов, 50 passed): auth code race, recovery code burn, refresh replay, concurrent registration, distributed rate limit. Проверено состояние PG (0 ungranted locks). |
| **TASK-064** | Existing DB Upgrade with Data (G7-MIGRATE-DATA) | **done** | Развернута тестовая БД на схеме `0001_initial_schema`, засеяны 2 пользователя с Argon2id, роли, сессия, OIDC клиент. Выполнен `alembic upgrade head` (`0002_reg_system_config`). Данные полностью сохранены, `bootstrap_completed=True`, `registration_mode='closed'`. Подтвержден живой HTTP-вход на порту 8003 и отказ регистрации (403). |
| **TASK-065** | Working Set RSS Fix & Soak (G7-SOAK-RSS) | **done** | Локализована причина замера 4.5 МБ RSS (замер launcher stub на Windows). Реализован `get_pid_listening_on_port`, выполнен повторный 20-минутный soak `campaign_soak_20m_corrected` (1211.9с, 39 сэмплов, 429 опс, 0 ошибок, latency p50=11.0ms, p95=144.1ms, Working Set 99.0 -> 99.77 МБ, 3/3 Chromium smoke, возврат соединений PG к baseline 1). |
| **TASK-066** | Runner Strict Criteria & Tests (G7-CRITERIA) | **done** | Реализована функция `evaluate_soak_criteria` в `scripts/run_overnight_stability.py` (контроль времени >=1200с, сэмплов >=90%, ошибок ==0, всех 3 smoke-тестов, пула PG baseline, портов, верифицированного PID worker на порту 8000). В `tests/test_overnight_runner_criteria.py` созданы и пройдены 14 модульных тестов. |

---

## 2. Сводная матрица проверок GOAL-07

| Контур / Инструмент | Статус | Метрика / Результат | Время выполнения |
|---|---|---|---|
| **Frontend CI Failure Reproduction & Lifecycle Regression** | **PASSED** | 7 passed / 0 failed (`tests/test_server_lifecycle.py`) | 7.1 с |
| **Playwright Chromium E2E (SSO Suite)** | **PASSED** | 4 passed / 0 failed (default-off profile) | 10.8 с |
| **Playwright Chromium E2E (Passkey Suite)** | **PASSED** | 4 passed / 0 failed (enabled profile, virtual authenticators) | 14.0 с |
| **G7-BOOT 5-Cycle Lifecycle Matrix** | **PASSED** | 5/5 циклов завершены, 40/40 E2E проверок пройдено, порты свободны | ~4 мин |
| **PostgreSQL Concurrency Matrix (50 проверок: 10 attempts x 5 scenarios)** | **PASSED** | 50 passed / 0 failed (auth code, recovery code, refresh replay, reg, limits; PG locks = 0) | ~50 с |
| **Failure Recovery & Backup/Restore (G7-RECOVER)** | **PASSED** | Restart OK, pause fail-closed OK, backup/restore live login OK | ~30 с |
| **Alembic Schema Migrations: Fresh Install (G7-MIGRATE)** | **PASSED** | 17 таблиц, upgrade head -> downgrade base -> upgrade head OK | 5.2 с |
| **Alembic Schema Migrations: Upgrade Existing DB with Data** | **PASSED** | 0001 -> 0002: данные сохранены, bootstrap OK, closed OK, HTTP login OK (port 8003) | ~15 с |
| **20-Minute Continuous Soak Test (Corrected Worker RSS & Re-evaluation)** | **PASSED** | 1211.9s, 429 ops, 0 unexpected errors, p50=11.0ms, p95=144.1ms, RSS 99.0->99.77 MB, PG baseline OK | 20.2 мин |
| **Runner Reliability Criteria Unit Tests** | **PASSED** | 14 passed / 0 failed (`tests/test_overnight_runner_criteria.py`) | 0.10 с |

---

## 3. Завершение и передача результата

1. Локальная часть программы `GOAL-07-overnight-stability.md` выполнена в полном объеме (G7-START, G7-BOOT, G7-SOAK, G7-RACE, G7-RECOVER, G7-MIGRATE, G7-CRITERIA).
2. Все выявленные замечания устранены:
   - Объем конкурентных проверок доведен до 10 попыток на каждый сценарий (50 тестов, 100% pass);
   - Обновление существующей базы с данными верифицировано со сквозным входом через HTTP;
   - Замер памяти скорректирован на реальный worker uvicorn (99.0 -> 99.77 МБ Working Set), проведен повторный 20-минутный прогон, данные переоценены по новым строгим критериям;
   - Внедрены строгие критерии надежности раннера (длительность >=1200с, обязательные smoke-прогоны, верификация PID, строгий PG baseline) и 14 модульных тестов;
   - Документация приведена в строгое соответствие с машинными артефактами (`summary.json`, `soak_metrics.csv`).
3. Создан автономный воспроизводимый раннер `scripts/run_overnight_stability.py` и регламент `docs/testing/overnight.md`.
4. Составлен подробный приёмочный акт `docs/acceptance-goal-07.md`.
5. Инварианты безопасности строго соблюдены: 4 отложенные возможности выключены по умолчанию (`false`), защита приложения не ослаблялась, шаблон CD закомментирован, рабочая БД `sso_db` не затрагивалась.
6. Статус G7-FINAL и общей цели: **BLOCKED / IN_PROGRESS** из-за недоступности push в удаленный репозиторий GitHub Actions (сетевой прокси прерывает CONNECT). Ожидается push владельцем для финального запуска CI на ветке `main`.

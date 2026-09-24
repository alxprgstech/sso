# Текущий срез и статус разработки ALXPRGS SSO

## Статус этапа: GOAL-04 (Закрытие пробелов проверки и исправление CI) — ЗАВЕРШЁН ЛОКАЛЬНО

25.09.2026: Выполнен `GOAL-04-verification-gaps-and-ci.md`. Все пять целевых областей (G4-DB, G4-EMAIL, G4-PASSKEY, G4-LIMITS, G4-CI) полностью реализованы, дефекты BUG-010..BUG-014 устранены с regression tests, документация обновлена.

- **Дата актуализации**: 2026-09-25T00:23:00+03:00
- **Исполнитель**: Antigravity
- **Текущий статус**: Все задачи TASK-037 .. TASK-042 переведены в статус `done`.
- **Активные дефекты**: Нет.
- **Закрытые дефекты**: BUG-001 .. BUG-014 (Resolved).
- **Матрица приёмки**: `docs/acceptance-goal-04.md`.

---

## 1. Завершённые задачи этапа GOAL-04

- **TASK-037 (G4-DB)**: Изоляция тестовой базы и защита боевой базы данных `sso_db` (порт 5432). Реализован `tests/db_guard.py` (запрет fallback на `DATABASE_URL`, маскирование паролей DSN, таблица маркера владения `test_database_marker`, запрет деструктивных операций без маркера). Создан `tests/test_database_guard.py` (14 тестов, 100% pass). Боевая база с 7 пользователями осталась нетронутой. Дефект BUG-010 закрыт.
- **TASK-038 (G4-EMAIL)**: Сквозной цикл неподтверждённого email в enabled-профиле без обходов политики или вмешательства администратора. Неподтверждённый пользователь блокируется на входе (HTTP 401 `email_verification_required`), запрашивает ссылку через `/api/v1/mfa/email/request` без сессии, получает письмо по локальному SMTP, подтверждает по токену и входит. Аудит `email_delivery_failed`, replay и expiration, rate limits, anti-enumeration. `tests/integration/test_email_verification_pg.py` (4 теста, 100% pass). Дефект BUG-011 закрыт.
- **TASK-039 (G4-PASSKEY)**: Реальный браузерный цикл WebAuthn Passkey (W3C Level 3) с Chrome DevTools Protocol (`WebAuthn.enable`, `WebAuthn.addVirtualAuthenticator`). Мульти-устройства, удаление ключа (удалённый ключ больше не работает), проверка неверных challenge/RP ID/origin без моков бэкенда. На фронтенде реализован полный UI регистрации, листинга и удаления ключей в Dashboard и вход по Passkey. `trace: "retain-on-failure"` в Playwright. `tests/integration/test_passkey_pg.py` (4 теста) и `frontend/e2e/passkey.spec.ts` (4 теста в Chromium) — 100% pass. Дефект BUG-012 закрыт.
- **TASK-040 (G4-LIMITS)**: Распределённые лимиты запросов между двумя независимыми процессами Uvicorn (порты 8011 и 8012) с общей PostgreSQL `alxprgs_sso_test`. Конфигурация `TRUSTED_PROXIES` (IP/CIDR) и проверка источника сокета в `get_client_ip`: недоверенные клиенты не могут обходить лимиты подделкой `X-Forwarded-For`. Режим `fail-closed` (HTTP 503) при сбоях СУБД. `tests/integration/test_distributed_rate_limiting_pg.py` (4 теста, 100% pass). Дефект BUG-013 закрыт.
- **TASK-041 (G4-CI)**: Локализован и устранен сбой CI baseline (run 36027756634 на коммите `2c1de5b668482d2bc11707fe565e3d1ab8711f4c`): безопасный `pytest.skip` в `tests/test_python_sdk.py`, флаг `--ignore=tests/test_python_sdk.py` в CI бэкенд-джобе, healthcheck сервиса PostgreSQL `pg_isready -U sso_user`, накат миграций `alembic upgrade head`, переменная `TEST_DATABASE_URL`, скрипт генерации синтетических пользователей `scripts/prepare_e2e_data.py`, новая CI-джоба `playwright-e2e`. CD-шаблон `cd.yml.example` 100% закомментирован. Дефект BUG-014 закрыт.
- **TASK-042**: Оформление доказательного отчёта приёмки `docs/acceptance-goal-04.md` со сквозными доказательствами, разделением локальной готовности и удалённого CI, проверкой инвариантов и сохранением всех пользовательских данных.

---

## 2. Сводка статуса тестов

| Контур | Статус | Метрика |
|---|---|---|
| Полный pytest suite (PostgreSQL) | **PASSED** | 110 passed / 0 failed (26.69 с) |
| Database Guard Suite | **PASSED** | 14 passed / 0 failed (1.14 с) |
| Email Verification Integration Suite | **PASSED** | 4 passed / 0 failed (8.35 с) |
| Passkey Integration Suite | **PASSED** | 4 passed / 0 failed (1.82 с) |
| Playwright Passkey Browser E2E | **PASSED** | 4 passed / 0 failed (20.8 с) |
| Distributed Rate Limiting Suite | **PASSED** | 4 passed / 0 failed (7.67 с) |
| Python SDK в чистом окружении | **PASSED** | 3 passed / 0 failed (1.29 с) |
| Frontend Typecheck & Build | **PASSED** | 0 errors, production build 1.04 с |
| Linter & Formatter Ruff | **CLEAN** | 0 errors, 64 files formatted |
| Версионирование SemVer / PEP 440 | **VALID** | Версия 0.2.0 синхронизирована |
| Дефекты BUG-001..BUG-014 | **RESOLVED** | 14/14 исправлены с regression tests |

---

## 3. Разделение локальной готовности и GitHub Actions

- **Локальная готовность**: Все исправления, миграции, тесты и сборки воспроизведены и подтверждены локально со 100% успехом на PostgreSQL 16. Сформирован локальный коммит `27bf575` (`fix(g4): resolve verification gaps, database guard, and ci workflows (BUG-010..BUG-014)`).
- **Удалённый CI (GitHub Actions)**: При попытке `git push` зафиксирована сетевая ошибка среды (`fatal: unable to access 'https://github.com/alxprgstech/sso/': Recv failure: Connection was reset`). Локальный успех честно отделён от удалённого прогона; ложный зелёный статус до реального запуска в GitHub Actions не заявляется.

---

## 4. Блокер и минимальное условие разблокировки

- **Блокер**: Отсутствие прямого сетевого доступа к `github.com` из среды выполнения агента для отправки коммита в удалённый репозиторий.
- **Минимальное условие разблокировки**: Пользователю достаточно выполнить команду `git push origin main` из своего терминала с настроенным доступом к GitHub, после чего GitHub Actions автоматически выполнит обновленный воркфлоу `.github/workflows/ci.yml` (включая unit/integration на PostgreSQL, SDK и Playwright E2E).


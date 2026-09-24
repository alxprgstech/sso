# Текущий срез и статус разработки ALXPRGS SSO

## Дополнение Codex: следующий этап

24.09.2026: подготовлен `GOAL-04-verification-gaps-and-ci.md` по защите тестовой БД, email, Passkey, межпроцессным лимитам и CI. Полное завершение прошлой цели не означает закрытие этих обнаруженных пробелов. Владелец поручил commit/push накопленных изменений; CI/release остаются активными, CD отключён. Новая цель ещё не выполнялась; предыдущая сводка ниже сохранена как историческое заявление исполнителя.

- **Дата актуализации**: 2026-09-24T19:25:00+03:00
- **Исполнитель**: Antigravity
- **Текущая фаза**: Выполнение `GOAL-03-testing-and-fixes.md` полностью завершено! Все 13 задач (TASK-023..TASK-035) выполнены в статусе `done`. Проведены независимые проверки на живой PostgreSQL 16 (порт 5433), Docker Compose стеке (127.0.0.1:3000), браузере Chromium (Playwright E2E) и изолированном виртуальном окружении SDK (`.venv-sdk-test`). Устранены все 9 выявленных дефектов (BUG-001..BUG-009). Сформирован доказательный акт приёмки `docs/acceptance-testing.md`.

---

## 1. Завершённые задачи

- **TASK-001** .. **TASK-014**: Выполнены в рамках базового GOAL.md (версия 0.1.0).
- **TASK-015** .. **TASK-022**: Выполнены в рамках GOAL-02 (версия 0.2.0: саморегистрация, мастер запуска, Compose, скрипты `start.ps1`/`start.sh`).
- **TASK-023**: Постановка и план тестирования GOAL-03 (QA-01), матрица QA-01..15.
- **TASK-024**: Реестр дефектов BUG-001..BUG-009, `docs/testing/manual-checklist.md`, `docs/acceptance-testing.md`.
- **TASK-025**: Изолированная тестовая БД PostgreSQL 16 (`alxprgs-sso-test-db`, порт 5433). Устранены BUG-001, BUG-006, BUG-007. Накат 17 таблиц миграций без ошибок. Фикстуры `pg_engine`, `pg_session`, `pg_client` с fail-fast.
- **TASK-026**: Проверка Docker Compose стека (`sso-backend`, `sso-frontend`, `sso-db`). Устранен BUG-008. Проверены `/health/live`, `/health/ready` (db connected), `/`. Выполнен контейнерный bootstrap первого администратора `compose_admin` и проверена идемпотентность (код 0). Написаны `test_bootstrap_pg.py` (4 теста) и `test_auth_sessions_pg.py` (3 теста). Усилена защита `logout` проверкой CSRF.
- **TASK-027**: Интеграционные тесты регистрации и управления режимом на PostgreSQL (`tests/integration/test_registration_pg.py`, 5 тестов): закрытый режим (403), незавершенный bootstrap (403), открытый режим с Argon2id и ролью user (201), нейтральные коллизии username/email (409), смена режима администратором с re-auth паролем.
- **TASK-028**: Интеграционные тесты OIDC, PKCE, ротации токенов и SSO 2 клиентов (`tests/integration/test_oidc_pg.py`, 6 тестов): Discovery, JWKS, регистрация клиента со строгим redirect_uri, Authorization Code + PKCE S256, UserInfo с отклонением ID Token (401), ротация refresh токенов и отзыв всего семейства в PostgreSQL при replay, бесшовный SSO между 2 клиентами и RP logout.
- **TASK-029**: Тестирование 4 отложенных возможностей в default-off и enabled профилях (`tests/integration/test_features_pg.py`, 5 тестов): default-off capabilities и 404 для TOTP/Passkey/Recovery codes/Email, инвариант No Silent Bypass (401 при выключенном флаге), жизненный цикл TOTP с шифрованием Fernet и TOTP_ENCRYPTION_KEY, генерация 10 recovery codes и одноразовое сгорание с защитой от replay, блокировка неподтвержденного email при REQUIRE_VERIFIED_EMAIL=true без отправки реальных писем.
- **TASK-030**: Тестирование параллелизма, гонок и лимитов на PostgreSQL (`tests/integration/test_concurrency_pg.py`, 5 тестов): конкурентное погашение auth code (SELECT FOR UPDATE -> 1x 200, 4x 400 invalid_grant), гонка одновременной регистрации (PostgreSQL UNIQUE -> 1x 201, 1x 409), атомарное сгорание recovery codes (UPDATE ... RETURNING -> 1x 200, 1x 401), гонка refresh token с отзывом семейства, распределенный rate limiting через PostgreSQL `AuditEvent` (HTTP 429).
- **TASK-031**: E2E Playwright тесты в браузере (`frontend/e2e/sso.spec.ts`, 4 теста в Chromium): проверка default-off профиля, вход администратора `compose_admin`, переключение режима на `open` с подтверждением пароля, регистрация нового пользователя и проверка RBAC, возврат режима в `closed`. Устранены BUG-005, BUG-009.
- **TASK-032**: Изоляция и проверка Python SDK в чистом виртуальном окружении `.venv-sdk-test` (`packages/python-sdk/tests/test_sdk_isolated.py`, 3 теста): чистая сборка wheel `alxprgs_sso-0.2.0-py3-none-any.whl`, установка в чистое окружение, генерация RSA ключей и JWKS через `cryptography` без единого серверного импорта. Проверена совместимость примеров `examples/client1/app.py` и `client2/app.py`. Устранены BUG-002, BUG-003.
- **TASK-033**: Проверка резервного копирования и восстановления PostgreSQL: `scripts/backup_db.py` создал валидный дамп `sso_backup_sso_db_20260924_190439.sql` (47.47 KB, SHA-256 `995820042283da93e240da5b4daf09114312912f616ee0c4912c823c58e683f5`). Проверен предохранитель `scripts/restore_db.py` (код 1 без `--confirm`). Выполнено восстановление в чистую тестовую БД `sso_restore_test_db`, подтверждена 100% идентичность пользователей и Argon2id хешей. База безопасно удалена.
- **TASK-034**: Аудит CI, сборки артефактов и безопасность CD: проверка SHA закрепления всех GitHub Actions, изоляция шага SDK в CI, проверка шаблона `deploy/github-actions/cd.yml.example` (100% закомментирован), проверка согласованности версий 0.2.0 (`scripts/bump_version.py check`), полный прогон Ruff (`All checks passed! 60 files already formatted`).
- **TASK-035**: Финальная приёмка и доказательный отчёт (QA-15): оформлен `docs/acceptance-testing.md`, подтверждены все 16 критериев раздела 8 `GOAL-03-testing-and-fixes.md`.

---

## 2. Сводка статуса тестов

| Контур | Статус | Метрика |
|---|---|---|
| Полный pytest suite | **PASSED** | 84 passed / 0 failed (283.79 с) |
| PostgreSQL 16 Integration Suite | **PASSED** | 30 passed / 0 failed (20.67 с) |
| Playwright E2E Suite (Chromium) | **PASSED** | 4 passed / 0 failed (7.9 с) |
| Python SDK в чистом окружении | **PASSED** | 3 passed / 0 failed (0.65 с) |
| Compose Stack (127.0.0.1:3000) | **HEALTHY** | 3/3 контейнеров `healthy` |
| Версионирование SemVer / PEP 440 | **VALID** | Версия 0.2.0 синхронизирована |
| Linter & Formatter Ruff | **CLEAN** | 0 warnings, 0 errors, 60 files formatted |
| Дефекты BUG-001..BUG-009 | **RESOLVED** | 9/9 исправлены с regression tests |

---

## 3. Блокеры и нерешённые вопросы

- **Отсутствуют**. Все запланированные функциональные, интеграционные, нагрузочные/конкурентные и E2E сценарии выполнены и подтверждены на реальных компонентах.

---

## 4. Следующие шаги

- Передача отчёта пользователю.
- Готовность репозитория к дальнейшим этапам развития проекта ALXPRGS SSO.

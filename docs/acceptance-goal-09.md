# GOAL-09 — текущий протокол проверки

Дополнение 2026-09-28T21:33:49+03:00: [CI 36445914754](https://github.com/alxprgstech/sso/actions/runs/36445914754) на `3715b5e` завершился failure: secret scan 116/55, backend default-off два тестовых отказа, Playwright default-off один тестовый отказ. Ruff и шаг маркера БД прошли. Причина 55 сигналов — пропуск UTF-8 файлов с кириллицей при Windows-кодировке; запуск сканера с `PYTHONUTF8=1` точно воспроизвёл Linux результат. Все 55 новых сигналов разобраны как локальные/example DSN, примеры документации и синтетические тестовые данные; baseline теперь 116 fingerprint в 39 файлах, скан 116/0. Регрессионный UTF-8 тест и safety unit — 25 passed, полный Ruff — 100 файлов. Повторный CI на новом commit ещё не выполнен. Первоначальные 58 сигналов и общая приёмка остаются `blocked`.

Дополнение 2026-09-28T18:37:22+03:00: TASK-092 локально устранил три сообщения CI PR #9. Ruff 0.16.8 `check` и `format --check` прошли на полном Python-наборе (99 файлов); затронутые MFA/PowerShell/Bash тесты — 14 passed и 2 subtests; safety unit — 24 passed. `detect-secrets==1.5.0` показывает 61 кандидат и 0 новых к baseline после проверки публичного SHA, синтетический контроль обнаружен; отдельная новая синтетическая находка отклонена без вывода значения. Запуск `python -m scripts.init_fresh_ci_test_marker` без `TEST_DATABASE_URL` завершился ожидаемым `OpsSafetyError` до подключения к БД. PostgreSQL-тест нового аудита и повторный удалённый Linux CI на итоговом SHA ещё не выполнены; прежний лог CI 117/56 остаётся расхождением до этого прогона. Статус C9-04 и общей приёмки остаётся `blocked`.

Дополнение 2026-09-28T16:52:45+03:00: компонентные проверки TASK-090 теперь 10/10, включая отсутствие QR и секрета при default-off. Browser/Compose приёмка не проводилась.

Дополнение 2026-09-28T16:46:16+03:00: TASK-090 — QR-код TOTP и копирование секрета локально проверены (frontend component 9/9, backend unit 7/7, lint/typechecks/build/Ruff, npm audit при установке 0 находок). Полный browser/Compose enabled-профиль не запускался; критерий GOAL §8 по MFA остаётся `blocked`.

Дополнение 2026-09-28T16:13:49+03:00: после проверки точной передачи WebAuthn origin затронутый backend unit набор — 12/12. Это не заменяет PostgreSQL или браузерную проверку.

## Дополнение 2026-09-28T16:10:53+03:00 — TASK-089

Исправления счётчиков состояния, конфигурации enabled MFA, локального WebAuthn origin, модальной смены пароля и аудита внесены в рабочее дерево. API аудита теперь поддерживает серверный `q` (подстрока типа события/IP) и `/api/v1/admin/audit/export?format=jsonl|csv` со всеми событиями текущего фильтра. Оба endpoint состояния возвращают `total_users` и `total_active_admins`. Default-флаги остались `false`.

Доказано локально: backend unit 11/11, генерация `.env` 3/3, frontend component 8/8, Ruff check/format, frontend lint/typecheck/typecheck:tests/build — exit 0. PostgreSQL regression `test_admin_status_audit_pg.py` и `test_features_pg.py` запущены, но завершились 6 ошибками setup: `TEST_DATABASE_URL` не задан; проверки SQL/HTTP не выполнялись. Docker/Compose и браузер с виртуальным WebAuthn не запускались. Частичный результат не меняет статусы критериев §8: пункты 4, 5, 6 и 7 остаются `blocked`. Mypy затронутых backend-модулей выявил только прежние ошибки `app/models/system.py:24` и `app/core/security.py:15`; exit 1. Общая приёмка остаётся `blocked`.

Обновлено: 2026-09-26T23:12:29+03:00, Codex. База: HEAD `4f7537bd7c9d88149b1e909bc6c52167714ecb31`, рабочее дерево изменено; hash исходного пользовательского diff документов `66c2a16e776a4b35540f383983f4913feab4220f`. Итогового SHA нет. Общая приёмка: **blocked**. [Акт GOAL-08](acceptance-goal-08.md) и [JSON](acceptance-goal-08.json) исторические; их `16/16` и `local_test_coverage_rate: 1.0` не доказаны для текущего дерева. `tests/test_db_guard.py` не существует; действительный путь — `tests/test_database_guard.py`. Текущий [машинный отчёт](acceptance-goal-09.json) содержит только фактические результаты.

## Пакеты C9

| ID | Реализация / проверка | Факт | Статус |
| --- | --- | --- | --- |
| C9-01 | `tests/test_ops_backup_restore_totp.py`, `test_ops_safety_unit.py`, `tests/db_guard.py`, `scripts/backup_db.py`, `restore_db.py` | Изолированные БД/маркеры, отказ до destructive SQL, нет FORCE/Docker fallback; fixture/seed больше не создают маркер до TRUNCATE. Safety unit прошли. PostgreSQL/HTTP/TOTP restore не запускался. | `blocked` |
| C9-02 | SDK, `examples/demo_app.py`, `demo_sessions.py`, OIDC logout | Unit и 3 isolated wheel tests прошли; nonce/issuer/ID token обязательны, demo session непрозрачна и серверная. HTTP logout на PostgreSQL не проверен. | `in_progress` |
| C9-03 | `frontend/e2e/multi_client_sso.spec.ts` | Typecheck и Playwright test discovery прошли; настоящий browser E2E не запускался. | `blocked` |
| C9-04 | lock, ESLint/component, pip/npm audit, detect-secrets, CI | Локально Ruff и secret scan 116/0 прошли после разбора 55 UTF-8 находок; удалённый [CI 36445914754](https://github.com/alxprgstech/sso/actions/runs/36445914754) failed до нового исправления. Первоначальные 58 сигналов ожидают приватной оценки, повторный CI ещё не запущен. | `blocked` |
| C9-05 | Reusable CI SHA, release bundle, draft checks | Локальный нетегированный build/verify и негативные unit прошли; manifest имеет `source_tree_dirty=true`. Тегового remote dry-run нет. | `blocked` |
| C9-06 | Этот акт, JSON, plan/status/worklog | Исторические заявления исправлены; полная матрица и доказательства ещё не завершены. | `in_progress` |

## Все 16 критериев GOAL.md §8

`passed` не присвоен ни одному полному критерию: частичный локальный тест не равен обязательной общей проверке.

| № | ID, реализация и проверка | Текущий факт / необходимая команда | Статус |
| --- | --- | --- | --- |
| 1 | ARCH/SETUP/OPS; Compose, Alembic, `tests/integration/test_migrations_pg.py` | Чистый Compose и миграции пустой/старой схемы на нынешнем дереве не запускались. | `blocked` |
| 2 | SSO-01..07, SDK, FINAL-01..04/11; `test_oidc_pg.py`, двухклиентский Playwright | SDK unit прошёл; PG/OIDC и browser не запускались. | `blocked` |
| 3 | USR-01, SEC-FLAG; `test_auth_and_sessions.py`, PG HTTP login | Unit в широком прогоне, но весь прогон exit 1; PG login отсутствует. | `blocked` |
| 4 | SEC-FLAG-01..07, USR-04..06, UI-01; MFA unit/PG/browser | MFA unit в широком прогоне; enabled/default-off HTTP/PG/browser нет. Defaults сохранены. | `blocked` |
| 5 | SEC/SSO/WebAuthn; PG concurrency, виртуальный authenticator | Гонки и browser WebAuthn не запускались. | `blocked` |
| 6 | USR/SEC; RBAC/IDOR/CSRF/reauth/admin tests | Часть unit прошла; полный PG/browser набор отсутствует. | `blocked` |
| 7 | UI-01..04, FINAL-05/09; React и E2E | ESLint, оба typecheck, component 6/6, build exit 0; browser и visual QA отсутствуют. | `blocked` |
| 8 | SDK-01..06, FINAL-03/06; wheel/sdist и demo | Wheel/sdist и 3 isolated tests прошли; demo HTTP/SSO с PG нет. | `blocked` |
| 9 | CI/SEC; `.github/workflows/ci.yml`, audits | pip/npm audit локально exit 0; remote CI на `3715b5e` failed, повторный запуск после UTF-8 исправления ожидается; 58 первоначальных secret кандидатов ждут оценки. | `blocked` |
| 10 | VER/CI; version script, PR/main workflows | `bump_version.py check` exit 0; remote CI итогового SHA и тег отсутствуют. | `blocked` |
| 11 | REL, FINAL-07; release bundle/workflow | Нетегированный build/verify и 15 release/lifecycle unit прошли; full SHA gate и remote dry-run отсутствуют. | `blocked` |
| 12 | CD; закомментированный template и invariant scanner | Локальный scanner прошёл, remote CI gate отсутствует. | `blocked` |
| 13 | OPS; отдельный backup/restore, TOTP, logout | Safety unit есть; реальный PG restore и вход отсутствуют. | `blocked` |
| 14 | DOC-TRACK, FINAL-10; README/ЕСПД/docs | Матрица создана; полная сверка ссылок, команд и документов не завершена. | `in_progress` |
| 15 | DOC-TRACK-01..07; plan/worklog/status | Учёт ведётся; задача не завершена. | `in_progress` |
| 16 | Итоговый отчёт и приёмка | Отчёт различает локальное и blocked; обязательные пункты остаются. | `blocked` |

## Исходные FINAL-01..11

По [первоначальному аудиту](final-gap-audit.md): FINAL-01 — confidential client; 02 — действительная SSO-сессия на authorize; 03 — строгая проверка токена SDK; 04 — безопасный login continuation; 05 — полный UI; 06 — SDK web flow; 07 — release; 08 — CI; 09 — два настоящих клиента; 10 — документация; 11 — OIDC. Исторический JSON переименовал 02/03 ошибочно. FINAL-01/02/04/05/11 ожидают PG/browser; 03/06 имеют частичные SDK/wheel результаты; 07/08 имеют локальные частичные результаты, remote gate отсутствует; 09 не прошёл browser; 10 в работе. Ни один FINAL не принят полностью на нынешней ревизии.

## Инвентарь исходных ID

Матрица §8 группирует требования по критерию. Следующие исходные ID остаются не принятыми полностью на этой ревизии: `ARCH-01`..`ARCH-06`, `SSO-01`..`SSO-08`, `USR-01`..`USR-03`, `SEC-FLAG-01`..`SEC-FLAG-07`, `UI-01`..`UI-04`, `SDK-01`..`SDK-06`, `VER-01`..`VER-03`, `CI-01`..`CI-02`, `REL-01`..`REL-03`, `CD-01`..`CD-03`; для `DOC-TRACK-01`..`DOC-TRACK-07` работа продолжается. Дополнение [GOAL-02](../GOAL-02-registration-and-setup.md) и [GOAL-08](../GOAL-08-final-completion.md) сохраняет силу: bootstrap/registration, полный UI, эксплуатационные 5 циклов, 50 гонок и soak текущего дерева ожидают проверки. Группировка не означает, что все ID покрыты одним unit-тестом.

## Проверки и границы

- Python 3.12.14 из bundled runtime, Node 24.20.0. Чистый venv из `requirements-lock.txt` и editable backend/SDK `--no-deps --no-build-isolation`, `pip check` — exit 0; отдельный SDK wheel venv — 3/3. Последний затронутый unit subset — 52 passed; release/lifecycle subset после исправления — 15 passed. Ruff — exit 0; format — 94 файла; mypy — 35 файлов без ошибок. Frontend lint, два typecheck, 7 utility, 6 component, build — exit 0. `pip-audit --strict -r requirements-lock.txt` и `npm audit --audit-level=high` — exit 0, 0 известных находок на момент прогона. `detect-secrets 1.5.0`: 61 кандидат в 17 файлах, 0 новых к baseline, синтетический контроль обнаружен; 3 новых ложноположительных строки разобраны, первоначальные 58 ещё требуют приватной проверки.
- Широкий pytest без integration/restore — **exit 1**: 126 passed, 12 errors без `TEST_DATABASE_URL`/PostgreSQL и 2 Windows lifecycle stop/port failures. После этого риск завершения чужого listener исправлен и проверен unit, реальный lifecycle не повторён. Старые PG/soak результаты не относятся к нынешнему runtime-коду.
- PostgreSQL, pg_dump, psql, Docker не найдены в PATH; `TEST_DATABASE_URL` не задан. Пользовательская БД не использовалась. Требуется отдельный PostgreSQL 16 с явным test DSN и client tools. Затем migrations на доказанно пустой БД → `python -m scripts.init_fresh_ci_test_marker --local-fresh` для точного localhost:5433 test service → safety unit → `test_ops_backup_restore_totp.py` → полный PG pytest → browser default-off/enabled → 5 lifecycle cycles, 10×5 races и непрерывный soak ≥1200 с. Провал требует диагностики до повторения.
- Ветка `codex/ci-repair-pr9` отправлена по текущему поручению; удалённый [CI 36445914754](https://github.com/alxprgstech/sso/actions/runs/36445914754) на `3715b5e` failed. После исправления UTF-8 нужен новый commit и повторный запуск по его SHA. Фактический выпуск, теги и production не выполнялись. До успешных обязательных проверок и приватного разбора первоначальных 58 secret-сигналов общая цель не `done`.

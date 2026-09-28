# GOAL-09 — текущий протокол проверки

Обновлено: 2026-09-26T23:12:29+03:00, Codex. База: HEAD `4f7537bd7c9d88149b1e909bc6c52167714ecb31`, рабочее дерево изменено; hash исходного пользовательского diff документов `66c2a16e776a4b35540f383983f4913feab4220f`. Итогового SHA нет. Общая приёмка: **blocked**. [Акт GOAL-08](acceptance-goal-08.md) и [JSON](acceptance-goal-08.json) исторические; их `16/16` и `local_test_coverage_rate: 1.0` не доказаны для текущего дерева. `tests/test_db_guard.py` не существует; действительный путь — `tests/test_database_guard.py`. Текущий [машинный отчёт](acceptance-goal-09.json) содержит только фактические результаты.

## Пакеты C9

| ID | Реализация / проверка | Факт | Статус |
| --- | --- | --- | --- |
| C9-01 | `tests/test_ops_backup_restore_totp.py`, `test_ops_safety_unit.py`, `tests/db_guard.py`, `scripts/backup_db.py`, `restore_db.py` | Изолированные БД/маркеры, отказ до destructive SQL, нет FORCE/Docker fallback; fixture/seed больше не создают маркер до TRUNCATE. Safety unit прошли. PostgreSQL/HTTP/TOTP restore не запускался. | `blocked` |
| C9-02 | SDK, `examples/demo_app.py`, `demo_sessions.py`, OIDC logout | Unit и 3 isolated wheel tests прошли; nonce/issuer/ID token обязательны, demo session непрозрачна и серверная. HTTP logout на PostgreSQL не проверен. | `in_progress` |
| C9-03 | `frontend/e2e/multi_client_sso.spec.ts` | Typecheck и Playwright test discovery прошли; настоящий browser E2E не запускался. | `blocked` |
| C9-04 | lock, ESLint/component, pip/npm audit, detect-secrets, CI | Lock install/pip check, Ruff/mypy, lint/typecheck/component/build и audits прошли локально; 58 первоначальных secret кандидатов ожидают приватной оценки, ещё 3 новых ложноположительных строки разобраны; remote CI не запускался. | `blocked` |
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
| 9 | CI/SEC; `.github/workflows/ci.yml`, audits | pip/npm audit exit 0; full CI не выполнен, 58 первоначальных secret кандидатов ждут оценки. | `blocked` |
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
- PostgreSQL, pg_dump, psql, Docker не найдены в PATH; `TEST_DATABASE_URL` не задан. Пользовательская БД не использовалась. Требуется отдельный PostgreSQL 16 с явным test DSN и client tools. Затем migrations на доказанно пустой БД → `python scripts/init_fresh_ci_test_marker.py --local-fresh` для точного localhost:5433 test service → safety unit → `test_ops_backup_restore_totp.py` → полный PG pytest → browser default-off/enabled → 5 lifecycle cycles, 10×5 races и непрерывный soak ≥1200 с. Провал требует диагностики до повторения.
- Для remote CI по итоговому SHA нужен будущий commit и разрешённый push/remote запуск владельцем. Текущее поручение запрещает push, публикацию и теги. CI URL нет. До реального CI и разрешения secret baseline общая цель не `done`.

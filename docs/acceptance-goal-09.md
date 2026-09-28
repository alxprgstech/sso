# GOAL-09 — текущий протокол проверки

Дополнение 2026-09-28T22:07:51+03:00: [CI 36469783369](https://github.com/alxprgstech/sso/actions/runs/36469783369) на документационном `84ad9aa` прошёл все семь заданий повторно. TASK-092/093 `done`; итоговая приёмка GOAL-09 остаётся `blocked` до отдельных обязательных проверок и приватного разбора первоначальных 58 secret-сигналов.

Дополнение 2026-09-28T22:00:44+03:00: [CI 36468921940](https://github.com/alxprgstech/sso/actions/runs/36468921940) на `e44c57e` завершился success по всем семи заданиям. Backend PostgreSQL default-off: 199 passed, 7 skipped; enabled: 20 passed. Playwright Chromium default-off: 5 passed; enabled: 4 passed. Security scan, Ruff, оба вызова маркера, frontend, SDK, version и CD-template прошли. TASK-092/093 завершены. Этот акт фиксируется отдельным документационным commit; его SHA ещё требует CI. Первоначальные 58 baseline-сигналов ожидают приватного обзора владельца; общая приёмка GOAL-09 остаётся `blocked`.

Дополнение 2026-09-28T21:56:28+03:00: [CI 36468328992](https://github.com/alxprgstech/sso/actions/runs/36468328992) на `68cde86` снова подтвердил backend PostgreSQL, security и прочие задания, но браузерный nonce-перехват не сработал. Причина: Playwright route обрабатывает первый URL при редиректе, тогда как тест начинал с `/login`. Три отрицательных сценария теперь берут настоящий `/login` редирект через общий browser request-контекст без follow redirects и открывают изменённый `/oauth/authorize` в той же странице. Повторный CI ожидается; общая приёмка `blocked`.

Дополнение 2026-09-28T21:51:23+03:00: [CI 36467660052](https://github.com/alxprgstech/sso/actions/runs/36467660052) на `d85e998` подтвердил полный backend PostgreSQL job, Security & Dependencies Scan и остальные четыре задания. Playwright default-off failed на диагностике: nonce-подмена не выполнилась (`nonceTampered=false`), поэтому прежний результат 200 не является доказательством дефекта SDK. E2E-перехват nonce/PKCE/redirect уточнён по точному pathname `/oauth/authorize`; отрицательные проверки сохранены, повторный browser CI ожидается. Общая приёмка `blocked`.

Дополнение 2026-09-28T21:44:54+03:00: повторный [CI 36466541048](https://github.com/alxprgstech/sso/actions/runs/36466541048) на `0d5ae4d` завершился. Security & Dependencies Scan, Ruff и оба запуска маркера прошли: три исходных сбоя TASK-092 устранены. Backend default-off: 197 passed, 7 skipped, 2 failed (refresh rotation запрашивал неподдерживаемый `offline_access`; backup/restore fixture не задавала обязательный `user_roles.id`). Playwright default-off: один отказ отрицательного nonce сценария, навигация завершилась HTTP 200 вместо 400. TASK-093 исправляет первопричины и повторяет CI; общая приёмка остаётся `blocked`.

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
| C9-01 | `tests/test_ops_backup_restore_totp.py`, `test_ops_safety_unit.py`, `tests/db_guard.py`, `scripts/backup_db.py`, `restore_db.py` | [CI 36467660052](https://github.com/alxprgstech/sso/actions/runs/36467660052) подтвердил полный backend PostgreSQL job после исправления fixture. Остальная приёмка C9-01 по матрице ещё не закрыта. | `blocked` |
| C9-02 | SDK, `examples/demo_app.py`, `demo_sessions.py`, OIDC logout | Unit и isolated wheel tests прошли; CI 36468921940 проверил настоящий двухклиентский Chromium/SSO logout. Остальная приёмка пакета не закрыта. | `in_progress` |
| C9-03 | `frontend/e2e/multi_client_sso.spec.ts` | [CI 36468921940](https://github.com/alxprgstech/sso/actions/runs/36468921940) подтвердил реальный Chromium default-off 5/5 и enabled 4/4, включая nonce/PKCE/redirect отрицательные сценарии. Остальные критерии пакета сверяются отдельно. | `in_progress` |
| C9-04 | lock, ESLint/component, pip/npm audit, detect-secrets, CI | [CI 36468921940](https://github.com/alxprgstech/sso/actions/runs/36468921940) прошёл все семь заданий; исходные secret/Ruff/маркер сбои устранены. Первоначальные 58 сигналов baseline ожидают приватной оценки. | `blocked` |
| C9-05 | Reusable CI SHA, release bundle, draft checks | Локальный нетегированный build/verify и негативные unit прошли; manifest имеет `source_tree_dirty=true`. Тегового remote dry-run нет. | `blocked` |
| C9-06 | Этот акт, JSON, plan/status/worklog | Исторические заявления исправлены; полная матрица и доказательства ещё не завершены. | `in_progress` |

## Все 16 критериев GOAL.md §8

`passed` не присвоен ни одному полному критерию: успешный CI не заменяет остальные обязательные проверки GOAL.md §8.

| № | ID, реализация и проверка | Текущий факт / необходимая команда | Статус |
| --- | --- | --- | --- |
| 1 | ARCH/SETUP/OPS; Compose, Alembic, `tests/integration/test_migrations_pg.py` | Чистый Compose и миграции пустой/старой схемы на нынешнем дереве не запускались. | `blocked` |
| 2 | SSO-01..07, SDK, FINAL-01..04/11; `test_oidc_pg.py`, двухклиентский Playwright | CI PostgreSQL OIDC и двухклиентский Chromium прошли; прочая сквозная приёмка ожидается. | `blocked` |
| 3 | USR-01, SEC-FLAG; `test_auth_and_sessions.py`, PG HTTP login | CI default-off backend PostgreSQL и Chromium login прошли; полный критерий сверяется отдельно. | `blocked` |
| 4 | SEC-FLAG-01..07, USR-04..06, UI-01; MFA unit/PG/browser | CI default-off и enabled backend/browser прошли; полная матрица возможностей не закрыта. | `blocked` |
| 5 | SEC/SSO/WebAuthn; PG concurrency, виртуальный authenticator | CI выполнил PG и enabled browser passkey; длительные гонки/soak ещё не подтверждены. | `blocked` |
| 6 | USR/SEC; RBAC/IDOR/CSRF/reauth/admin tests | CI backend/browser наборы прошли; полная приёмка отрицательных сценариев ожидается. | `blocked` |
| 7 | UI-01..04, FINAL-05/09; React и E2E | Frontend CI и Chromium default-off/enabled прошли; visual QA и прочие критерии UI не закрыты. | `blocked` |
| 8 | SDK-01..06, FINAL-03/06; wheel/sdist и demo | CI SDK clean install и двухклиентский Chromium прошли; остальная приёмка пакета ожидается. | `blocked` |
| 9 | CI/SEC; `.github/workflows/ci.yml`, audits | CI 36468921940 прошёл все семь заданий; 58 первоначальных secret кандидатов ждут приватной оценки. | `blocked` |
| 10 | VER/CI; version script, PR/main workflows | Version и весь CI на `e44c57e` и `84ad9aa` прошли; релизный тег и прочая приёмка ожидают проверки. | `blocked` |
| 11 | REL, FINAL-07; release bundle/workflow | Нетегированный build/verify и 15 release/lifecycle unit прошли; full SHA gate и remote dry-run отсутствуют. | `blocked` |
| 12 | CD; закомментированный template и invariant scanner | Локальный и удалённый comment-only gate прошли; активация CD не запрошена. | `blocked` |
| 13 | OPS; отдельный backup/restore, TOTP, logout | Safety unit и PG restore тест прошли в CI; эксплуатационные циклы не завершены. | `blocked` |
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

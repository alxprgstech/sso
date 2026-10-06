# PROJECT-PR-01: commit и PR полного проекта

Начало: 2026-10-05T19:04:38+03:00, Codex; ветка `new/frontend-redesign`. Поручение: сохранить все рабочие изменения, создать PR в main и проверить CI. Merge/release/deployment не входят в поручение.

## Локальные проверки перед commit

2026-10-05T19:14:45+03:00, рабочий diff после `35dca486a8381f9b15e1560e4a8520349aeb5382`:

| Область | Команда | Результат |
| --- | --- | --- |
| Python | `python -m ruff check backend/ tests/ packages/python-sdk/ scripts/ examples/`; `python -m ruff format --check` с теми же путями | PASS; 212 файлов форматирования |
| Types | `python -m mypy --explicit-package-bases packages/python-sdk/alxprgs_sso backend/app --ignore-missing-imports` | PASS; 68 файлов |
| Bootstrap и Windows | `python -m pytest tests/test_bootstrap_admin.py tests/test_start_ps1.py tests/test_reset_local_ps1.py -m "not postgres" -q` | 27 PASS, 4 subtests PASS, 37.52 s |
| Frontend static | `npm run lint`; `npm run typecheck`; `npm run typecheck:tests` | PASS |
| Frontend unit | `npm run test:unit` | 13 PASS |
| Frontend components | `npm run test:components` | 37 PASS, 3 files, 6.89 s; exit 0 |
| Frontend build | `npm run build` | PASS; Vite 8.3.1, 2697 modules, 19.61 s |
| Secrets | `python scripts/check_secret_scan.py --self-test` | 136 candidates, 0 new; synthetic control rejected |
| Config/CD/locks | `python scripts/scan_secrets_and_deps.py` | PASS; ограниченные инварианты, не CVE-аудит |
| Version | `python scripts/bump_version.py check` | PASS; SemVer/PEP440 0.2.0 |
| Документы | UTF-8 и существование локальных Markdown-ссылок всего diff относительно main | 18 документов, 120 ссылок, 0 missing до добавления этой матрицы |
| Whitespace | `git diff --check` | PASS |

Node и Python запускались по абсолютным путям, frontend scripts эквивалентно через их установленный CLI. Python 3.13 из проектного `.venv`; для отсутствующего в нём `sentry_sdk` использован существующий `.venv-sentry/Lib/site-packages` после основного site-packages в `PYTHONPATH`. Нативные зависимости основного окружения и политика приложения сохранены. Windows Docker calls mocked: это regression поведения скриптов, не реальный Compose. PostgreSQL/браузерные auth E2E/real mail этим локальным набором не проверены; их remote evidence фиксируется отдельно.

## История отказов

Первые pytest: `ModuleNotFoundError: sentry_sdk`; sandbox unittest: отказ temp filesystem; sandbox Vitest: temp `ENOENT`. После разрешённого запуска вне sandbox компоненты имели 37 passed, но exit 1 из-за необработанного Promise rejection в Passkey fixture. Mock Promise теперь создаётся при вызове API; тест ждёт фактический запрос перед reject и сохраняет loading/error/retry assertions. Повтор дал 37 PASS и exit 0; настройки Vitest и security не ослаблены. Ошибочная команда `bump_version.py --check` отклонена argparse, правильный subcommand `check` прошёл.

## Удалённые результаты

Ссылки, SHA и outcomes сохраняются в хронологии ниже по мере фактического исполнения; локальный PASS не подменяет remote CI. GitHub connector HTTP403 заменён работающим Git/API с существующей авторизацией; visibility репозитория не изменялась. `.env`, credentials, ignored build/test artifacts не входят в commit.

2026-10-05T19:20:50+03:00: создан [PR7](https://github.com/alxprgstech/sso/pull/7), source089ed932ae28deb024c6ce0da28c45a1dbc6be46. [CI37339819853](https://github.com/alxprgstech/sso/actions/runs/37339819853) и CodeScene7818274 ещё выполняются;2externalSESjobs skipped по PR policy/CI03, не live delivery. Финальный local docs gate18UTF8/123links/0missing/whitespacePASS.

2026-10-05T19:52:58+03:00: первый CI089ed93 завершился6requiredPASS/3FAIL/2SESskip; CodeScene7818274 failed3gates. Windows короткийTEMP path исправлен canonical resolve; PG assertion обновлён под15..128 и4invalid/no-write cases; SVG -text с CR-at-EOL и scoped re-add сохраняют exact4indexblob/manifest/worktree. UI разделён на используемые секции/lifecycle/sorting/request helpers, geometry сохраняет legacy paths и прежние4viewports/assertions. Final local lint/types/test-types, components37/17.55s/exit0, unit13, build2.61s, Windows/bootstrap27+4subtests/44.40s, full37browserUI/2.8m/exit0, Ruff/scanner135/0new/control rejected и docs links PASS. PG new regression пока не исполнялся локально; обязательный remote job проверит его. CodeScene profile/suppressions/thresholds и security invariants сохранены.

2026-10-05T20:08:20+03:00: [CI37344305700](https://github.com/alxprgstech/sso/actions/runs/37344305700) на08284248a5410603028eb03f676d4c370daeaed3 — все9requiredjobsPASS;2SESskip. Backend621PASS/14subtests/106.74s,20enabledPASS/12.85s; default47browserPASS/1.3m,enabled9PASS/1.4m. Linux16Windows skips покрыты separate required Windows job,5external-email deselected — не live delivery. [CodeScene7818690](https://codescene.io/projects/85555/delta/results/7818690):2gatesPASS,1FAIL только2dup files. После общих feature-card/secret-display helpers localcomponents37/12.42s, lint/types/build3.06s и targetedbrowser2/7.4sPASS; finalremoteSHA ещё проверяется. Наборы не суммируются.

2026-10-06T02:49:38.3108298+03:00: перед локальным commit lint/typecheck PASS, components37PASS вне sandbox (исходный запуск: ENOENT sandbox temp в2suites), secret scan135/0newPASS и ограниченные security invariants PASS. Build на этих исходниках PASS в WEB-ROBOTS-01; новые remote CI/CodeScene/browser E2E не запускались.

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

PR и Actions пока не созданы. Итоговый SHA, ссылка, обязательные jobs, внешние checks и ограничения будут добавлены после фактического исполнения. GitHub connector HTTP403 заменён работающим Git/API с существующей авторизацией; visibility репозитория не изменялась. `.env`, credentials, ignored build/test artifacts не входят в commit.

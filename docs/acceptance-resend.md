# Приёмка EMAIL-RESEND-01

Начало: 2026-10-05T00:02:13.6796764+03:00; исполнитель Codex. Ветка `new/resend-email-provider`, исходный SHA `74cdcf602748eb1ffff759f6ab6922597d9dbb79`. Изменения пока локальные; новый commit/remote CI не заявлены. Решение: [ADR 0020](adr/0020-resend-email-provider.md).

## Матрица

| Критерий | Проверка | Результат |
| --- | --- | --- |
| Selection/env/key/sender, backward compatibility | offline Settings/dispatch tests | PASS |
| Native payload, Unicode, text/HTML, escaping/Schema.org | HTTPX MockTransport, оригинальное MIME | PASS |
| API errors/429/network/timeout/invalid ID/no retries/no fallback | offline HTTP contract tests | PASS |
| Async cancellation и cleanup | Event-controlled coroutine/owned-client test | PASS |
| Key/OTP/link redaction, audit and Sentry | actual serialized SDK envelopes и actual PG audit | PASS |
| Registration/confirmation/replay/resend | real guarded PostgreSQL + fake provider HTTP | PASS |
| 503/pending при отказе; neutral existing-account response | real guarded PostgreSQL + fake provider HTTP | PASS |
| Прежние SES/SMTP/STARTTLS/template/telemetry | targeted regression | PASS |
| Полный/default и enabled backend набор | обязательный pytest на выделенной PostgreSQL | PASS |
| Ruff/mypy/dependencies/locks/security/build/docs | проверки ниже | PASS; Docker runtime не проверен |

## Выполненные проверки

`python` ниже — имеющийся `.venv-sentry/Scripts/python.exe` (CPython 3.12); для PG команда предваряется `artifacts/remediation/run_with_pg.py`, читающим приватный DSN без вывода. Тестовая БД на loopback5433 проверяется действующим `tests/db_guard.py`; guard/marker и политики не менялись. Все Resend HTTP responses синтетические; PostgreSQL и SMTP/STARTTLS regression реальные локальные.

- `python -m pytest tests/test_resend_email.py tests/test_ses_email.py tests/test_verification_email.py tests/test_smtp_tls.py tests/test_sentry.py -q -p no:cacheprovider --basetemp=artifacts/resend/unit-tmp02`: 99 passed, 9.80s.
- PG harness `-m pytest tests/integration/test_resend_email_pg.py tests/test_resend_email.py tests/test_ses_email.py tests/test_verification_email.py tests/test_smtp_tls.py tests/test_sentry.py -q -p no:cacheprovider --tb=short --basetemp=artifacts/resend/targeted-tmp03`: 105 passed, 13.68s.
- `python -m ruff check backend/ tests/ packages/python-sdk/ scripts/ examples/`: PASS после исправления двух import-order ошибок новых тестов.
- `python -m ruff format --check backend/ tests/ packages/python-sdk/ scripts/ examples/`: 211 files formatted.
- `python -m mypy --explicit-package-bases packages/python-sdk/alxprgs_sso backend/app --ignore-missing-imports`: 68 source files, PASS.
- `python -m pip check`: no broken requirements; `python scripts/runtime_lock.py --check`: PASS. Новых dependency/lock изменений нет.
- Первый полный обычный PG run: `-m pytest tests/ -q -p no:cacheprovider --tb=short --basetemp=artifacts/resend/full-tmp01 --junitxml=artifacts/resend/full.xml`: 621 passed, 5 external deselected, 16 subtests passed, 307.71s.
- Окончательный полный run после строгого sender validation и трёх дополнительных отрицательных tests, та же команда с `--basetemp=artifacts/resend/full-tmp02 --junitxml=artifacts/resend/full-final.xml`: **624 passed, 5 external deselected, 16 subtests passed, 308.83s**. Failed tests нет. Один существующий StarletteDeprecationWarning: FastAPI TestClient/httpx; зависимости ради предупреждения не обновлялись.
- Enabled-профиль существующего CI (`REMEDIATION_TEST_PROFILE=enabled`, PG harness): `-m pytest tests/test_mfa_features.py tests/integration/test_email_verification_pg.py tests/integration/test_passkey_pg.py tests/integration/test_distributed_rate_limiting_pg.py -q -p no:cacheprovider --tb=short --basetemp=artifacts/resend/enabled-tmp01 --junitxml=artifacts/resend/enabled.xml`: 20 passed, 36.51s.
- `python scripts/scan_secrets_and_deps.py`: PASS; `python scripts/check_secret_scan.py --self-test`: 137 historical candidates, 0 new, synthetic secret rejected. Одна новая находка проверена как синтетический signup password; точечная `pragma: allowlist secret` на этой строке, без обновления baseline или ослабления scanner. Неиспользованный pragma на ключе удалён.
- `artifacts/remediation/audit-tools/Scripts/python.exe -m pip_audit --strict -r requirements-lock.txt --cache-dir artifacts/resend/audit-cache`: PASS, no known vulnerabilities found. Первые sandbox-попытки заблокированы сетью WinError10013; повтор с разрешённым доступом PyPI завершён успешно. CPython 3.12, pip-audit 2.10.1.
- `python -m build --no-isolation --outdir artifacts/resend/dist backend`: wheel и sdist 0.2.0 построены, проверено наличие adapter и Settings в wheel. Это локальная сборка текущей ревизии с изменениями, не опубликованный release.
- `PYTHONPATH=backend python artifacts/resend/check_final.py`: PASS — UTF-8 и новые local Markdown links, YAML/Compose anchor inheritance/empty key default, три Settings profiles/missing key rejection, AST-equivalence SES/SMTP/template/security helpers, неизменность SES source, dependency files и CI. Docker отсутствует: настоящий `docker compose config/build/up` не выполнялся.

## Изменённые файлы и проектные решения

`config.py`, новый `services/resend_email.py`, одна ветка `services/verification_email.py`; finite allowlists `telemetry.py` и `services/audit_service.py`. `.env.example` и `docker-compose.yml` передают только новое имя переменной. Новые unit/PG tests и два дополнительных Sentry-envelope cases; прежние SES/SMTP assertions сохраняются. README/backend README, GOAL, architecture/operations/testing, ADR, acceptance matrix и plan/worklog/status обновлены. Dependencies/locks, auth business logic, DB schema и workflows не менялись.

Ключ защищён SecretStr и исключён из repr/serialization, provider response/error/body не логируется. HTTPX выбран как уже используемый async HTTP client без дополнительной SDK dependency. Mapping передаёт text/HTML оригинального MIME, timeout/TLS/cancellation сохраняются; API ID проверяется как UUID, успешный submission не объявляется доставкой. Синхронные SES/SMTP по-прежнему вызываются через to_thread, retry SES остаётся настройкой SDK.

## Неуспешные промежуточные запуски

94 PASS/5 setup errors: не существовал parent basetemp; создан новый test artifact directory, без удаления чужих файлов. Первый PG run — 4 setup errors: pg_ctl default5432 не соответствовал harness5433. Проверены собственные PID/executable/data и отсутствие TCP клиентов, выполнен штатный restart на127.0.0.1:5433. Следующий PG run — 2PASS/2FAIL: новый тест ошибочно ожидал верхний error вместо существующего detail, audit scrubbing не допускал Resend и добавлял request_id. API не менялся; точные assertions исправлены, finite allowlist дополнен и проверен. Эти запуски не объявлены PASS.

## Ограничения

Реальная доставка Resend и настройка домена не проверены: реальные API keys/письма не нужны для разработки и не входят в поручение. Общая production-приёмка GOAL-09 не закрывается этой интеграцией. SES/testmail opt-in, main/release правила и закомментированный CD сохраняются. Для активации владелец задаёт `EMAIL_PROVIDER=resend`, настоящий `RESEND_API_KEY` и проверенный домен `SMTP_FROM_EMAIL`. AMP в native Resend API отсутствует; SES/SMTP MIME сохраняется.

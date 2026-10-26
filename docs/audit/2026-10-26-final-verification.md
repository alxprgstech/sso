# Финальная независимая проверка — 26/27.10.2026

Повторный прогон после всех исправлений, на чистом локальном контуре (PostgreSQL 16.10 в отдельном контейнере, `127.0.0.1:5433`, safety marker; backend/frontend из рабочего дерева; Chromium). Числа ниже — фактические, без переноса результатов других ревизий.

## 1. Backend (PostgreSQL, default-on профиль)

Команда (Windows/Python 3.13.0, CI-профиль флагов):

```powershell
pytest -v tests/ --basetemp artifacts/audit/pytest-final --junitxml=artifacts/audit/pytest-final.xml
```

Результат: **821 passed, 2 failed, 5 deselected, 18 subtests passed, 635.01 s**.

Оставшиеся 2 failed — только отсутствие PostgreSQL client binaries на Windows-стенде:

| Тест | Причина | Статус |
| --- | --- | --- |
| `test_migration_upgrade_roles_pg.py::test_fresh_previous_upgrade_and_runtime_role_cannot_ddl` | `shutil.which("psql") is None` | выполняется в Linux CI (postgresql-client-16) |
| `test_ops_backup_restore_totp.py::test_backup_restore_and_totp_key_recovery` | нет `pg_dump`/`psql` | выполняется в Linux CI |

Baseline до изменений: 803 passed, 6 failed (те же 2 env + отсутствие hatchling для `test_build_lock` ×2 + import `app` в independent worker + SMTP CA на OpenSSL 3.x). После установки build-lock/editable backend и исправления сертификатов: 3 env-only; после аудита — 2 env-only. Новые тесты добавили 18 passing-кейсов; ни одно функциональное падение не замаскировано.

Повторно после финальных правок (литералы паролей заменены на генерируемые): `test_totp_reauth_replay_pg.py`, `test_admin_authorization_order_pg.py`, `test_registration_mode_reauth_pg.py`, `test_totp_policy.py`, `test_smtp_tls.py` → **19 passed**.

## 2. Статический анализ

| Проверка | Результат |
| --- | --- |
| `ruff check backend/ tests/ packages/python-sdk/ scripts/ examples/` | All checks passed (271 файл) |
| `ruff format --check ...` | 271 files already formatted |
| `mypy --explicit-package-bases packages/python-sdk/alxprgs_sso backend/app --ignore-missing-imports` | Success, 84 source files |
| `scripts/bump_version.py check` | SUCCESS, 0.3.0 согласован |
| `scripts/hashed_locks.py` | Hash companions match all three version locks |
| `scripts/runtime_lock.py --check`, `scripts/build_lock.py --check` | PASS |
| `pip-audit --strict -r requirements-lock.txt` | No known vulnerabilities found |
| `scripts/check_secret_scan.py --self-test` | Synthetic control rejected; 133 candidates; **0 new** |
| `git diff --check` | PASS (перед commit) |

## 3. Frontend

| Проверка | Результат |
| --- | --- |
| `npm ci` | PASS |
| `npm audit --audit-level=high` | `found 0 vulnerabilities` |
| `npm run lint` | PASS |
| `npm run typecheck` | PASS |
| `npm run typecheck:tests` | PASS |
| `npm run test:unit` | 14 passed |
| `npm run test:components` | 51 passed (7 files) |
| `npm run build` | PASS |
| `ALX_RELEASE_BUILD=1 npm run build` + `scripts/check_sentry_build.py` | Debug IDs/private maps validated; deployment dist без source maps |

## 4. Browser E2E (реальный backend + PostgreSQL)

| Профиль | Спеки | Результат |
| --- | --- | --- |
| default-off | sso (6), multi_client_sso, protocol_lifecycle, telemetry, privacy, appearance, step_up | **50 passed** (2.1 мин) |
| enabled | passkey, totp, privacy, telemetry | **9 passed** (1.7 мин) |

Новые/обновлённые регрессии прошли: отсутствие второго password-поля и один диалог при смене режима (`sso` 02/04); сохранение read grant через reload и очистка при logout (`sso` 06); реальный TOTP lifecycle с двумя окнами (`totp`); passkey UV/origin/RP; viewport 375 в appearance.

## 5. API inventory и матрицы

- 73 фактических method/path = 73 в `docs/api-routes.json` = все пути в `docs/api.md`; `test_documented_api_contract.py` PASS.
- Anonymous: 73 маршрута — 8×200, 2×302, 4×400, 40×401, 6×404 (disabled step-up), 13×422; защищённых 200 нет.
- Regular (`e2e_sso_user`): 37 маршрутов — 3×200, 11×401, 15×403, 8×422; все admin-маршруты 403.
- Admin (`compose_admin` + TOTP assurance): 37 маршрутов — 8×200 (чтения), 19×401 (mutations без proof), 1×403 (нет passkey для elevation options), 1×404 (несуществующий user), 8×422.
- Подробно — [api-coverage](2026-10-26-api-coverage.md), JSON-матрицы в ignored `artifacts/audit/`.

## 6. SDK

- `python -m build --no-isolation packages/python-sdk` → wheel + sdist 0.3.0.
- Чистая venv (`artifacts/audit/sdk-env`), установлен full hash-lock и wheel с `--no-deps`; `pip check` — No broken requirements.
- `pytest packages/python-sdk/tests/ tests/test_python_sdk.py tests/test_sdk_freshness_and_jwks.py` → **33 passed**; `alxprgs_sso.__version__ == 0.3.0`; пакет из site-packages; backend `app` не импортирован.

## 7. Containers

| Проверка | Результат |
| --- | --- |
| `docker build backend/Dockerfile` (ALX_BUILD_SHA = HEAD) | PASS |
| `docker build frontend/Dockerfile` | PASS |
| Trivy 0.75.0 backend, HIGH/CRITICAL | **0** |
| Trivy 0.75.0 frontend, HIGH/CRITICAL | **0** (nginx 1.30.6-r1, curl 8.23.0-r0, brotli-libs 1.2.1-r0) |
| `nginx -t` read-only + cap-drop ALL + no-new-privileges, uid 101 | PASS |
| `scripts/check_container_runtime.py` (own Compose project, synthetic volumes) | PASS: non-root/read-only/capabilities/resources/runtime DB role, 3 CSP browser tests, DB outage/recovery; owned cleanup подтверждён |

## 8. Что не проверено

- GitHub Actions на финальном HEAD — после push; локальные результаты его не заменяют.
- Внешние SES/Resend/Gmail/Sentry, публичный TLS/DNS/edge, production backup/restore, OIF/multi-replica load, HSM/key custody.
- Firefox/WebKit; CodeScene live-gates; полный ASVS L2/L3.
- `psql`/`pg_dump`-зависимые тесты локально (Linux CI).

## 9. Вердикт

Все подтверждённые дефекты исправлены и покрыты регрессиями; TOTP replay protection не ослаблена; необоснованные повторные подтверждения устранены; API/frontend/container/supply-chain проверки пройдены локально. **READY FOR REVIEW** — при условии успешного GitHub CI на точном HEAD ветки; production-приёмка остаётся открытой.

## 10. Первый PR run и исправления

Run `40404078649` (HEAD `0342046`): Security/SDK/Containers/CD/Windows/Version/Playwright — success; backend — 1 failed тест, frontend — cancelled по timeout. Причины и исправления: [CI remediation](2026-10-26-ci-remediation.md#первый-pr-run-40404078649-head-0342046). После правки теста (фиксация exact TOTP step) и увеличения job-timeout (без изменения гейтов) выполнен повторный run на новом HEAD; его результат фиксируется в PR.

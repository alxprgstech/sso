# Покрытие HTTP API — аудит 26.10.2026

## 1. Inventory и сверка

- Фактический источник: `app.openapi()["paths"]` (FastAPI, включая подключённые routers) — **73** пары method/path.
- `docs/api-routes.json` — **73** пары, полное совпадение; `tests/test_documented_api_contract.py` сравнивает snapshot с приложением и требует наличие каждого пути в `docs/api.md`.
- SDK сверяется отдельно (`packages/python-sdk/tests/`, `tests/test_python_sdk.py`): SDK не импортирует server-модули.
- Inventory снят на ревизии ветки после изменений; при добавлении маршрута snapshot-тест падает до обновления документации.

## 2. Методика матрицы

Матрица получена реальными HTTP-запросами к локальному backend (PostgreSQL 16, default-on профиль):

1. **Anonymous:** каждый из 73 маршрутов, path-параметры заменены случайным UUID, тело отсутствует, `Origin: http://localhost:5173`.
2. **Regular:** `e2e_sso_user` (без MFA), cookie + CSRF, те же маршруты; GET проверяются на 200/403, mutations — на отказ без proof; для admin-маршрутов ожидается 403.
3. **Admin:** `compose_admin` с TOTP-login и assurance; проверяется, что чтения admin API доступны, а mutations без свежего proof дают 401 `reauthentication_required`.
4. Позитивные сценарии mutations проверяются отдельными integration-тестами (`tests/integration/*_pg.py`), где создаются реальные объекты и проверяется эффект/rollback; гонки — `test_concurrency_pg.py`, `test_external_step_up_pg.py`, `test_totp_reauth_replay_pg.py`.

Легенда: `Anonymous`/`Regular`/`Admin` — фактический статус без proof (для admin — без `X-Reauthentication`). `—` — маршрут не входит в аутентифицированную выборку (публичный или logout).

Сводка: anonymous — 200×8, 302×2, 400×4, 401×40, 404×6, 422×13; regular — 200×3, 401×11, 403×15, 422×8; admin — 200×8, 401×19, 403×1, 404×1, 422×8. Ни один защищённый маршрут не вернул 200 анонимно; ни один admin-маршрут не вернул 200 regular-пользователю.

## 3. Матрица

| Area | Path | Method | Anonymous | Regular | Admin |
| --- | --- | --- | --- | --- | --- |
| ADMIN | `/api/v1/admin/audit/export` | GET | 401 | 403 | 200 |
| ADMIN | `/api/v1/admin/audit` | GET | 401 | 403 | 200 |
| ADMIN | `/api/v1/admin/clients/{client_id}/rotate-secret` | POST | 401 | 403 | 401 |
| ADMIN | `/api/v1/admin/clients/{client_id}/step-up` | PATCH | 401 | 403 | 401 |
| ADMIN | `/api/v1/admin/clients/{client_id}` | DELETE | 401 | 403 | 401 |
| ADMIN | `/api/v1/admin/clients` | GET | 401 | 403 | 200 |
| ADMIN | `/api/v1/admin/clients` | POST | 401 | 403 | 401 |
| ADMIN | `/api/v1/admin/system/registration-mode` | POST | 401 | 403 | 401 |
| ADMIN | `/api/v1/admin/system/status` | GET | 401 | 403 | 200 |
| ADMIN | `/api/v1/admin/users/{user_id}/sessions/revoke` | POST | 401 | 403 | 401 |
| ADMIN | `/api/v1/admin/users/{user_id}` | GET | 401 | 403 | 404 |
| ADMIN | `/api/v1/admin/users/{user_id}` | PATCH | 401 | 403 | 401 |
| ADMIN | `/api/v1/admin/users` | GET | 401 | 403 | 200 |
| ADMIN | `/api/v1/admin/users` | POST | 401 | 403 | 401 |
| AUTH | `/api/v1/auth/capabilities` | GET | 200 | — | — |
| AUTH | `/api/v1/auth/change-password` | POST | 401 | 401 | 401 |
| AUTH | `/api/v1/auth/legal-acceptance` | POST | 401 | 422 | 422 |
| AUTH | `/api/v1/auth/login` | POST | 422 | — | — |
| AUTH | `/api/v1/auth/logout` | POST | 401 | — | — |
| AUTH | `/api/v1/auth/me` | GET | 401 | 200 | 200 |
| AUTH | `/api/v1/auth/reauthentication/factor` | POST | 401 | 422 | 422 |
| AUTH | `/api/v1/auth/reauthentication` | POST | 401 | 422 | 422 |
| AUTH | `/api/v1/auth/register/confirm-code` | POST | 422 | — | — |
| AUTH | `/api/v1/auth/register/confirm-gmail` | POST | 422 | — | — |
| AUTH | `/api/v1/auth/register/confirm-link` | POST | 422 | — | — |
| AUTH | `/api/v1/auth/register/preview-link` | POST | 422 | — | — |
| AUTH | `/api/v1/auth/register/resend` | POST | 422 | — | — |
| AUTH | `/api/v1/auth/register` | POST | 422 | — | — |
| AUTH | `/api/v1/auth/session/elevate/passkey/options` | POST | 401 | 403 | 403 |
| AUTH | `/api/v1/auth/session/elevate` | POST | 401 | 422 | 422 |
| AUTH | `/api/v1/auth/sessions/{session_id}` | DELETE | 401 | 401 | 401 |
| AUTH | `/api/v1/auth/sessions` | DELETE | 401 | 401 | 401 |
| AUTH | `/api/v1/auth/sessions` | GET | 401 | 401 | 401 |
| AUTH | `/api/v1/auth/telemetry-config` | GET | 200 | — | — |
| AUTH | `/api/v1/mfa/email/confirm-code` | POST | 422 | — | — |
| AUTH | `/api/v1/mfa/email/confirm` | POST | 422 | — | — |
| AUTH | `/api/v1/mfa/email/request` | POST | 422 | — | — |
| AUTH | `/api/v1/mfa/passkey/auth/options` | POST | 200 | — | — |
| AUTH | `/api/v1/mfa/passkey/auth/verify` | POST | 422 | — | — |
| AUTH | `/api/v1/mfa/passkey/credentials/{credential_id}` | DELETE | 401 | 401 | 401 |
| AUTH | `/api/v1/mfa/passkey/credentials` | GET | 401 | 200 | 200 |
| AUTH | `/api/v1/mfa/passkey/register/options` | POST | 401 | 401 | 401 |
| AUTH | `/api/v1/mfa/passkey/register/verify` | POST | 401 | 401 | 401 |
| AUTH | `/api/v1/mfa/recovery-codes/generate` | POST | 401 | 401 | 401 |
| AUTH | `/api/v1/mfa/recovery-codes/verify` | POST | 422 | — | — |
| AUTH | `/api/v1/mfa/totp/confirm` | POST | 401 | 401 | 401 |
| AUTH | `/api/v1/mfa/totp/setup` | POST | 401 | 401 | 401 |
| AUTH | `/api/v1/mfa/totp/verify` | POST | 422 | — | — |
| AUTH | `/api/v1/mfa/totp` | DELETE | 401 | 401 | 401 |
| HEALTH | `/health/live` | GET | 200 | — | — |
| HEALTH | `/health/ready` | GET | 200 | — | — |
| OIDC | `/.well-known/jwks.json` | GET | 200 | — | — |
| OIDC | `/.well-known/openid-configuration` | GET | 200 | — | — |
| OIDC | `/oauth/authorize` | GET | 400 | — | — |
| OIDC | `/oauth/client-context` | GET | 400 | — | — |
| OIDC | `/oauth/logout` | GET | 302 | — | — |
| OIDC | `/oauth/logout` | POST | 302 | — | — |
| OIDC | `/oauth/revoke` | POST | 400 | — | — |
| OIDC | `/oauth/token` | POST | 400 | — | — |
| OIDC | `/oauth/userinfo` | GET | 401 | — | — |
| OIDC | `/oauth/userinfo` | POST | 401 | — | — |
| PRIVACY | `/api/v1/auth/account-deletion/confirm-factor` | POST | 401 | 422 | 422 |
| PRIVACY | `/api/v1/auth/account-deletion/reauthenticate` | POST | 401 | 422 | 422 |
| PRIVACY | `/api/v1/auth/account-deletion` | DELETE | 401 | 422 | 422 |
| PRIVACY | `/api/v1/auth/account-deletion` | GET | 401 | 200 | 200 |
| PRIVACY | `/api/v1/auth/account-deletion` | POST | 401 | 422 | 422 |
| PRIVACY | `/api/v1/legal/documents` | GET | 200 | — | — |
| STEP-UP | `/api/v1/step-up/redeem` | POST | 404 | — | — |
| STEP-UP | `/api/v1/step-up/requests/{request_token}/deny` | POST | 404 | — | — |
| STEP-UP | `/api/v1/step-up/requests/{request_token}/passkey/options` | POST | 404 | — | — |
| STEP-UP | `/api/v1/step-up/requests/{request_token}/verify` | POST | 404 | — | — |
| STEP-UP | `/api/v1/step-up/requests/{request_token}` | GET | 404 | — | — |
| STEP-UP | `/api/v1/step-up/requests` | POST | 404 | — | — |


## 4. Покрытие по областям

| Область | Позитивные | Негативные | Гонки/повтор |
| --- | --- | --- | --- |
| AUTH login/session/logout | 	est_auth_sessions_pg.py, 	est_login_source_budget_pg.py, 	est_security_and_negative_scenarios.py | неверный пароль/CSRF/Origin/429; 	est_distributed_auth_quota_pg.py | 	est_concurrency_pg.py, 	est_security_event_races_pg.py |
| MFA TOTP/Passkey/Recovery | 	est_features_pg.py, 	est_passkey_pg.py, 	est_mfa_assurance_pg.py | replay, disabled, pending, cross-user, UV/origin/RP | 	est_totp_reauth_replay_pg.py (same-step race), 	est_concurrency_pg.py |
| Reauth/sessions read | 	est_reauthentication_pg.py, 	est_registration_mode_reauth_pg.py | expired/foreign/action/body mismatch, mutation с read-grant | 	est_reauth_*, новый queue/coalescing component test |
| Registration | 	est_registration_pg.py, 	est_registration_uniform_path_pg.py | closed mode, collision, rate limit, resend, legacy binding | 	est_gmail_action_binding_pg.py |
| Admin/RBAC/audit | 	est_admin_status_audit_pg.py, 	est_admin_api.py, 	est_admin_mfa_pg.py | non-admin 403, no assurance 403, last-admin invariant, IDOR | 	est_admin_authorization_order_pg.py, 	est_security_event_races_pg.py |
| OIDC/OAuth | 	est_oidc_pg.py, 	est_oidc_contract_remediation_pg.py, 	est_signed_token_profiles.py | replay, PKCE, redirect, audience/issuer, refresh family | 	est_concurrency_pg.py, 	est_security_event_races_pg.py |
| Step-up | 	est_external_step_up_pg.py, 	est_step_up_policy.py, SDK tests | cross-client, PKCE, redirect removal, session/revision/expiry, feature off | concurrent redemption (ровно один winner) |
| Privacy/deletion/legal | 	est_privacy_pg.py, 	est_email_identity_uniqueness_pg.py, 	est_privacy.py | consent, retention, deletion cancel, unauthorized access | 	est_privacy_races_pg.py (где применимо) |
| Health/discovery/legal docs | 	est_public_readiness.py, 	est_documented_api_contract.py, E2E | malformed/oversized, method not allowed | — |

## 5. Наблюдения и вердикт

- Публичными являются только health, discovery/JWKS, capabilities, telemetry-config, legal documents, login/register validation и предполётные MFA-challenge endpoints (passkey/auth/options), что соответствует протоколу: challenge выдаётся до аутентификации и связывается сервером.
- Step-up endpoints при выключенном флаге возвращают 404 eature_disabled (fail-closed), а не 401/500.
- Admin API: после AUD-2026-05 regular user получает 403 до reauth; assured admin без proof — 401; аноним — 401.
- GET /api/v1/auth/sessions без read grant — 401; с grant — 200; mutation с read grant — 401 (action binding).
- Ошибок 5xx в матрице нет; исключения не отражаются в теле (стабильные rror коды).
- Ограничения: OIDC-потоки требуют RP-клиента и проверяются integration/E2E, а не матрицей; step-up в матрице выключен (opt-in feature) и проверяется отдельным включённым профилем; внешние SES/Resend/Gmail/Sentry не вызываются.

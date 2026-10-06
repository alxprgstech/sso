# Модель угроз и политики безопасности ALXPRGS SSO

Сверка документации: 06.10.2026, продукт 0.2.0. [Реестр и границы](index.md), [статус](status.md). Прежние измерения/PASS относятся к указанным датам и ревизиям.

Версия продукта 0.2.0; актуализировано 04.10.2026 по F-01…F-27. Документ описывает реализацию, а не сертификацию. Доказательства и ограничения: [приёмка](acceptance.md), [аудит](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/PRODUCTION_READINESS_AUDIT.md).

| Угроза | Реализованная защита | Проверки |
| --- | --- | --- |
| Перебор и CPU exhaustion | PostgreSQL quotas по источнику/account/challenge/client, HMAC идентификаторы; DB failure fail-closed; Argon2 executor2/inflight4, overload503 | `test_distributed_auth_quota_pg.py`, `test_password_work_budget.py` |
| Кража/фиксация сессии | Новый случайный секрет на login, в БД hash; host-only HttpOnly/SameSite; production `__Host-`/Secure; абсолютный/idle TTL | `test_auth_sessions_pg.py`, `test_security_revision_pg.py` |
| CSRF/XSS | Cookie mutations требуют Origin/CSRF; enforced CSP у Nginx; bearer/refresh не хранятся в browser storage | `test_security_and_negative_scenarios.py`, `frontend/e2e/csp.spec.ts` |
| Code/refresh replay | PKCE S256 с точной ASCII syntax, redirect exact; User-first locks, одноразовый code, rotation/replay семейства | `test_concurrency_pg.py`, `test_oidc_contract_remediation_pg.py` |
| Подмена JWT | Отдельные server/SDK profiles, RS256-only, issuer/audience/claims types/use/time/nonce; bounded kid до JWKS lookup | `test_signed_token_profiles.py`, `test_python_sdk.py` |
| RBAC/IDOR/stale grants | Серверные права, last-admin invariant, account security revision и атомарный отзыв | `test_admin_status_audit_pg.py`, `test_security_revision_pg.py` |
| MFA bypass/замена фактора | Fresh password + configured MFA, одноразовый session/action/body-bound proof5min; pending TOTP не заменяет active; UV/origin/RP/signature/challenge обязательны | `test_reauthentication_pg.py`, `test_passkey_pg.py`, `frontend/e2e/passkey.spec.ts` |
| Identity/email spoofing | Самостоятельная регистрация только после email; exact-address/revision tokens; admin change очищает verified, отзывает grants; централизованный входной policy | `test_registration_pg.py`, `test_verified_email_policy_pg.py`, `test_email_verification_pg.py` |
| Подделка proxy/утечка логов | Exact trusted peers, right-to-left chain, stripped incoming forwarding headers; finite operation/reason + bounded UUID correlation, nested redaction | `test_distributed_rate_limiting_pg.py`, `test_diagnostic_codes.py` |

Новые пароли: 15–128 Unicode символов, без обязательного состава или периодической смены. Whole-password common blocklist и повторяющиеся строки отклоняются; источник/лицензия офлайн-списка хранятся в `backend/app/data`. Argon2id: memory65536KiB/time3/parallelism4/salt16/hash32. Dummy для неизвестного пользователя — действительный hash с теми же параметрами; ошибки входа одинаковы. Ограниченный timing experiment проверяет только грубое различие, не доказывает невозможность любого enumeration.

Recovery codes:32 случайных символа A–Z/0–9 (около165бит), отображение четырьмя группами, хранение SHA-256 и атомарное одноразовое погашение. Они заменяют второй фактор после пароля, не самостоятельный login. TOTP secrets и pending enrollment — Fernet с отдельным ключом. Ротация этого ключа требует предварительной транзакционной миграции всех ciphertext, см. [operations](operations.md).

Production validation до traffic требует постоянный RSA≥2048, явный kid, сильный SESSION_SECRET_KEY и TOTP_ENCRYPTION_KEY, согласованные точные HTTPS origins/issuer, безопасные TTL, DEBUG=false, runtime роль БД без superuser/ownership/DDL и актуальный schema head. Tool-generated RSA3072; ephemeral RSA допустим только в development/testing. Previous RSA публикуется только до явного UTC deadline. SMTP STARTTLS использует verified context, hostname check и не допускает plaintext fallback/credentials до TLS.

Security revision изменяется при password/reset/block/role/email/factor и критических recovery events. Она отзывает browser sessions, codes, refresh, MFA-step, pending enrollment/actions/email; некоторые self-service изменения сохраняют только текущую сессию с новой revision. Старые grants не оживают после unblock. Admin-created/reset password — временный15min/одноразовый: только limited password-change session10min, без OAuth grants; после смены нужен новый login. Эти события не обещают мгновенную инвалидность уже выданного JWT у автономного RP, который проверяет его offline до TTL.

Default flags: `FEATURE_TOTP_ENABLED=false`, `FEATURE_PASSKEY_ENABLED=false`, `FEATURE_RECOVERY_CODES_ENABLED=false`. API disabled404, UI использует capabilities. Recovery требует TOTP. `FEATURE_EMAIL_VERIFICATION_ENABLED=true` обязательно; false отвергается конфигурацией. `REQUIRE_VERIFIED_EMAIL=false` относится только к входу старых/admin-created пользователей и не отменяет email-confirmation самостоятельной регистрации. Enabled-профиль выбирается явно; configured обязательный фактор не обходится при выключении feature.

Система не привязывает сессию жёстко к IP/UA и не реализует выдуманную экспоненциальную задержку: source identity используется для quotas/audit. TLS termination — один контролируемый gateway; контейнерный backend/DB не публикуются. Local HTTP только в документированном dev/test профиле. В production localhost и HTTP returnTo не доверяются автоматически.

Нельзя логировать password/OTP/secrets/keys/tokens/raw session IDs/codes или unnecessary PII. Diagnostic events содержат только allowlisted operation/reason/request_id. Audit хранит ограниченные идентификаторы событий с корреляцией; подробные arbitrary payloads запрещены. JSON stdout не является настроенным каналом alerts: владельцу ещё нужны staging alerts/retention/on-call drills.

[Sentry privacy](observability.md): bodies/headers/cookies/query/user/IP/geo/exception values/SQL удаляются allowlist projection; Replay только разрешённая staging-оболочка, production hard-off. Live privacy/source-map/ingestion настройки не подтверждаются unit-тестами.

[Privacy/erasure](privacy.md): deletion pending выдаёт limited cookie и отзывает grants; после отмены нужен новый login; backup restore требует актуальный erasure journal. Собственные данные RP не удаляются автоматически через SSO. OIF/public HTTPS/live mail/container/staging proof имеют отдельные записи приёмки, не выводятся из кода или mock tests.

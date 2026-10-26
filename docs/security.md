# Модель угроз и политики безопасности ALXPRGS SSO

Актуализация документации: 26.10.2026, продукт 0.3.0; проверки security-исправлений и их объединения перечислены в приёмке. [Реестр и границы](index.md), [статус](status.md). Прежние измерения/PASS относятся к указанным датам и ревизиям.

Профиль F-01…F-27 дополнен решениями SEC-01…04 (ADR-0023). Документ описывает реализацию, а не сертификацию. Доказательства и ограничения: [приёмка](acceptance.md), [аудит](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/PRODUCTION_READINESS_AUDIT.md).

| Угроза | Реализованная защита | Проверки |
| --- | --- | --- |
| Перебор и CPU exhaustion | PostgreSQL quotas по источнику и account+source/challenge; HMAC идентификаторы; DB failure fail-closed; Argon2 executor2/admission16, максимум2/source, overload429 Retry-After1 | `test_distributed_auth_quota_pg.py`, `test_password_work_budget.py`, `test_login_source_budget_pg.py` |
| Кража/фиксация сессии | Новый случайный секрет на login, в БД hash; host-only HttpOnly/SameSite; production `__Host-`/Secure; абсолютный/idle TTL | `test_auth_sessions_pg.py`, `test_security_revision_pg.py` |
| CSRF/XSS | Cookie mutations требуют Origin/CSRF; enforced CSP у Nginx; bearer/refresh не хранятся в browser storage | `test_security_and_negative_scenarios.py`, `frontend/e2e/csp.spec.ts` |
| Code/refresh replay | PKCE S256 с точной ASCII syntax, redirect exact; User-first locks, одноразовый code, rotation/replay семейства | `test_concurrency_pg.py`, `test_oidc_contract_remediation_pg.py` |
| Подмена JWT | Отдельные server/SDK profiles, RS256-only, issuer/audience/claims types/use/time/nonce; bounded kid до JWKS lookup | `test_signed_token_profiles.py`, `test_python_sdk.py` |
| RBAC/IDOR/stale grants | Серверные права, last-admin invariant, account security revision и атомарный отзыв | `test_admin_status_audit_pg.py`, `test_security_revision_pg.py` |
| MFA bypass/замена фактора | Fresh password + configured MFA, одноразовый session/action/body-bound proof5min; pending TOTP не заменяет active; UV/origin/RP/signature/challenge обязательны | `test_reauthentication_pg.py`, `test_passkey_pg.py`, `frontend/e2e/passkey.spec.ts` |
| Admin MFA bypass / stale role session | `Session.mfa_verified` пишется только сервером; admin API требует live session + RBAC + assurance; password-only/onboarding сессия ограничена; role change отзывает sessions; старые sessions после миграции не получают assurance | `test_admin_mfa_pg.py`, `test_registration_pg.py`, `test_admin_api.py` |
| Downgrade через OIDC grant | Authorization code/refresh хранят assurance snapshot; `amr`/`acr` подписаны; admin-роль не выдаётся grant без требуемого assurance; UserInfo фильтрует admin по токену | `test_mfa_assurance_pg.py`, `test_oidc_pg.py`, `test_signed_token_profiles.py` |
| Recovery code abuse | Выпуск только при подтверждённом TOTP/Passkey после fresh reauth; SHA-256, одноразовое атомарное погашение, повторный выпуск инвалидирует набор; код не даёт phishing-resistant assurance | `test_mfa_assurance_pg.py`, `test_features_pg.py`, `test_concurrency_pg.py` |
| Cross-application step-up / transaction substitution | Opt-in confidential clients only; client/user/session/security-revision/action/payload/nonce binding; server-policy assurance; one-use PostgreSQL redemption; separate JWT `token_use`; exact redirect+PKCE; no proof reuse | `test_external_step_up_pg.py`, `test_step_up_policy.py`, `test_step_up_sdk.py`, `StepUpPage.component.test.tsx` |
| Identity/email spoofing | Самостоятельная регистрация только после email; exact-address/revision tokens; admin change очищает verified, отзывает grants; централизованный входной policy | `test_registration_pg.py`, `test_verified_email_policy_pg.py`, `test_email_verification_pg.py` |
| Подделка proxy/утечка логов | Exact trusted peers, right-to-left chain, stripped incoming forwarding headers; finite operation/reason + bounded UUID correlation, nested redaction | `test_distributed_rate_limiting_pg.py`, `test_diagnostic_codes.py` |

Новые пароли: 15–128 Unicode символов, без обязательного состава или периодической смены. Whole-password common blocklist и повторяющиеся строки отклоняются; источник/лицензия офлайн-списка хранятся в `backend/app/data`. Argon2id: memory65536KiB/time3/parallelism4/salt16/hash32. Dummy для неизвестного пользователя — действительный hash с теми же параметрами; ошибки входа одинаковы. Ограниченный timing experiment проверяет только грубое различие, не доказывает невозможность любого enumeration.

Recovery codes:32 случайных символа A–Z/0–9 (около165бит), отображение четырьмя группами, хранение SHA-256 и атомарное одноразовое погашение. Они заменяют второй фактор после пароля, не самостоятельный login. Выпуск разрешён при подтверждённом TOTP **или** Passkey, требует fresh reauthentication и не выдаёт коды до завершения enrollment; наличие только кодов не делает аккаунт MFA-required. Recovery code не удовлетворяет strict/Passkey-only assurance и не участвует в external step-up. TOTP secrets и pending enrollment — Fernet с отдельным ключом. Ротация этого ключа требует предварительной транзакционной миграции всех ciphertext, см. [operations](operations.md).

Production validation до traffic требует постоянный RSA≥2048, явный kid, сильный SESSION_SECRET_KEY и TOTP_ENCRYPTION_KEY, согласованные точные HTTPS origins/issuer, безопасные TTL, DEBUG=false, runtime роль БД без superuser/ownership/DDL и актуальный schema head. Tool-generated RSA3072; ephemeral RSA допустим только в development/testing. Previous RSA публикуется только до явного UTC deadline. SMTP STARTTLS использует verified context, hostname check и не допускает plaintext fallback/credentials до TLS.

Security revision изменяется при password/reset/block/role/email/factor и критических recovery events. Она отзывает browser sessions, codes, refresh, MFA-step, pending enrollment/actions/email, external step-up requests/proofs; некоторые self-service изменения сохраняют только текущую сессию с новой revision, но очищают её MFA assurance. Старые grants не оживают после unblock. Admin-created/reset password — временный15min/одноразовый: только limited password-change session10min, без OAuth grants; после смены нужен новый login. Эти события не обещают мгновенную инвалидность уже выданного JWT у автономного RP, который проверяет его offline до TTL. External proof погашается только при live session/current revision; offline JWT после redemption остаётся доказательством только на короткий TTL и должен проверяться RP вместе с собственным action state.

Default flags: `FEATURE_TOTP_ENABLED=true`, `FEATURE_PASSKEY_ENABLED=true`, `FEATURE_RECOVERY_CODES_ENABLED=true`, `REQUIRE_ADMIN_MFA=true`. Отсутствие переменных сохраняет эти значения; explicit-disabled профиль требует явных `false`. API disabled404, UI использует capabilities. Recovery требует TOTP или Passkey. `FEATURE_EMAIL_VERIFICATION_ENABLED=true` обязательно; false отвергается конфигурацией. `REQUIRE_VERIFIED_EMAIL=false` относится только к входу старых/admin-created пользователей и не отменяет email-confirmation самостоятельной регистрации. Аккаунт с настроенным фактором не обходится при выключении feature; парольный вход для него блокируется fail-closed. `REQUIRE_ADMIN_MFA=false` — только явное аварийное решение владельца; настройка обоих MFA-флагов в `false` при включённой admin-политике отвергается Settings. `FEATURE_EXTERNAL_STEP_UP_ENABLED=false` по умолчанию; даже при включённом глобальном флаге каждый client обязан отдельно включить step-up и задать allowlist actions/assurance. Public client не может создавать/погашать proof: нужна существующая confidential client authentication. Recovery code не участвует в step-up. Password+TOTP/Passkey, Passkey UV-only для MFA и strict password+Passkey описаны в [ADR-0031](adr/0031-external-transaction-step-up.md); default-on MFA, admin assurance и recovery — [ADR-0032](adr/0032-default-on-mfa-and-admin-policy.md).

Система не привязывает сессию жёстко к IP/UA и не реализует выдуманную экспоненциальную задержку: source identity используется для quotas/audit. TLS termination — один контролируемый gateway; контейнерный backend/DB не публикуются. Local HTTP только в документированном dev/test профиле. В production localhost и HTTP returnTo не доверяются автоматически.

Нельзя логировать password/OTP/secrets/keys/tokens/raw session IDs/codes или unnecessary PII. Diagnostic events содержат только allowlisted operation/reason/request_id. Audit хранит ограниченные идентификаторы событий с корреляцией; подробные arbitrary payloads запрещены. JSON stdout не является настроенным каналом alerts: владельцу ещё нужны staging alerts/retention/on-call drills.

[Sentry privacy](observability.md): bodies/headers/cookies/query/user/IP/geo/exception values/SQL удаляются allowlist projection; Replay только разрешённая staging-оболочка, production hard-off. Live privacy/source-map/ingestion настройки не подтверждаются unit-тестами.

[Privacy/erasure](privacy.md): deletion pending выдаёт limited cookie и отзывает grants; после отмены нужен новый login; backup restore требует актуальный erasure journal. Собственные данные RP не удаляются автоматически через SSO. OIF/public HTTPS/live mail/container/staging proof имеют отдельные записи приёмки, не выводятся из кода или mock tests.

## Границы доверия и остаточные риски

Рассмотрены анонимный сетевой атакующий, обычный пользователь, обладатель украденного bearer/session, контролируемый сайт и RP, злонамеренные входные данные, конкурентные запросы и ошибочная конфигурация оператором. Администратор может регистрировать клиентов, но не считается доверенным источником любых данных для browser rendering. Контроль build runner, signing key или БД способен разрушить основные trust assumptions; ASVS не устраняет такую компрометацию автоматически.

Приоритетные сценарии: перенос Gmail action между регистрациями, replay code/refresh/proofs, подмена access токена ID token, stale roles, IDOR, bypass UV, forged forwarded IP, mail brute force, смешение OP/RP logout, утечки telemetry/query/backups. Для legacy Gmail API JWT подтверждает источник, отдельный action secret — доступ к письму, а browser proof связывает регистрацию с инициатором; новые письма используют ViewAction в исходный браузер; code/link/action погашаются атомарно. Passkey ID нормализуется и ищется по индексу. Просмотр сессий требует отдельный пятиминутный read grant, DELETE — одноразовое action-bound подтверждение. Python artifacts устанавливаются с обязательными hashes; audit/outbox согласованы транзакцией. Реализация и альтернативы — [ADR-0023](adr/0023-security-remediation.md), фактические проверки — [приёмка](acceptance.md).

До production остаются controlled Gmail sender/action и synthetic live mail acceptance, публичные TLS/edge/DNS/IAM и DB transport, custody/rotation секретов и ключей, внешние storage ACL/backup drills, live Sentry privacy/retention/maps/alerts, multi-replica load и OIF, приватная оценка исторических credentials с отзывом при реальном использовании. Локальный Compose/backup PASS не подтверждает внешнюю инфраструктуру. Перед release нужно повторить обязательные scans на точных артефактах; старый Trivy PASS не является текущим сканом.

Администраторский RP требует review exact HTTPS redirect URI; независимый RP может принимать ранее выданный access JWT до exp (до 300 секунд). Компрометация runner, signing key или БД нарушает базовые допущения. Backup dump и source maps чувствительны даже без plaintext паролей.

## Охват security review

Ниже сохранена карта областей ASVS 5.0.0 исходного review, с указанием уже реализованного remediation. Это границы рассмотрения, не новая сертификация или PASS текущего SHA.

| ASVS 5.0.0 area | Применимость и проверка | Ограничения / основные gaps |
| --- | --- | --- |
| V1 Encoding and Sanitization | SQL/argv/CSV/React/URL sinks | Не исчерпывающий browser fuzz всех UI inputs |
| V2 Validation and Business Logic | Models, quotas, pending/one-use/roles, privacy races | Live mail acceptance; scale/load не измерены |
| V3 Web Frontend Security | CORS, CSRF token, browser MIME, escaping/storage/CSP source | 3.4.2/3.5.1/3.5.2 рассмотрены; actual edge headers не проверены |
| V4 API and Web Service | JSON endpoints, auth deps, error models, feature gates | Production request smuggling/edge parser chain не проверена |
| V5 File Handling | Operator backup/source maps/artifacts | Public uploads отсутствуют; operator ACL/encryption нужны |
| V6 Authentication | Password/email/TOTP/Passkey/recovery/reauth | Live mail acceptance; delivery и notifications live не проверены |
| V7 Session Management | Host-only cookie, TTL, revocation, OP/RP separation | Fresh-factor checks описаны ADR-0023; 7.6.1 lifecycle документирован |
| V8 Authorization | Server RBAC/ownership/admin invariants/action proofs | Browser/RP stale token window300s; не мгновенная offline revocation |
| V9 Self-contained Tokens | RS256 claims/profiles/key/cache/replay | Actual production key rotation и custody не проверены |
| V10 OAuth and OIDC | S256/URI/state/nonce, codes, refresh families | 10.1.2/10.4.5 рассмотрены; live OIF/DPoP/mTLS не проверены/не реализованы |
| V11 Cryptography | Argon2id/RSA/Fernet/HMAC/CSPRNG | Production entropy/HSM/backup ключей требуют оператора |
| V12 Secure Communication | HTTPS/STARTTLS validation/TLS config | Реальный DNS/сертификат/DB transport не обследованы |
| V13 Configuration | Secrets flags, quotas, resource budgets, Docker | Нагрузочная приёмка; ownership IAM/firewall/container CVEs не доказаны |
| V14 Data Protection | Privacy lifecycle, redaction, sensitive view blocks | SaaS retention/storage ACL и native backups внешняя приёмка |
| V15 Secure Coding and Architecture | Layering, error handling, dependencies | Supply-chain operational acceptance; review не гарантирует отсутствие неизвестных sinks |
| V16 Security Logging and Error Handling | Safe fields, fixed labels, audit/telemetry | Semantic denied actions/alerts/notifications operational tests нужны |
| V17 WebRTC | Не применимо: реализации нет | Не переносится на будущие функции |

Полная требование-за-требованием L2/L3 acceptance не проводилась. Там, где нет достаточного доказательства, статус не объявлен PASS. Top10 применён как классификация риска, а не checklist сертификата.

Полный исходный анализ, отклонённые гипотезы и исходные находки: [Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/SECURITY_AUDIT.md). Полное старое threat/evidence содержание доступно по этому точному SHA; исторический verdict не переносится на исправленный код.

SSO-SEC-0002: logout/self-service revoke дополнительно отзывают все OIDC refresh/code grants пользователя под account-first lock, без изменения revision и без удаления сохраняемых browser sessions. Поэтому свежий SSO-вход из сохранённой сессии возможен. При подозрении на её кражу используйте revoke-others или смену пароля. Offline JWT до300с не отзывается мгновенно. Решение: [ADR0024](adr/0024-self-service-grant-revocation.md).
### SSO-SEC-0001: квоты OAuth
Token и revoke имеют раздельные квоты 30/60 секунд на проверенный source IP (trusted-proxy policy), до дорогой проверки client_secret. Публичный client_id не расходует глобальную квоту других источников. Общие NAT-источники разделяют лимит; распределённая нагрузка требует edge admission. PostgreSQL outage остаётся fail-closed.

SSO-SEC-0003: start для всех identities выполняет одинаковые Argon2/pending/mail операции без предварительной User lookup. Это исключает status/repeat-ID/send-limit/provider-error membership oracles. Проверка коллизии User выполняется только после mailbox proof в confirm; existing User/credentials не изменяются. Предусмотренные source quotas, MAX_SENDS3/час, DB uniqueness и legal consent сохранены. Повторная заявка может отправить письмо владельцу уже занятого адреса в пределах той же квоты; она не сбрасывает пароль и не выдаёт сессию. Точное constant-time БД/сети не обещается.

### SSO-SEC-0004: объём anonymous denied audit
Анонимные401/403/429 агрегируются до DB/task по server route/reason в bounded counters (256+3overflow), flush60с/worker одной транзакцией и при graceful shutdown. action_denied содержит count/aggregated/window_seconds; request_id/IP/субъект агрегату не приписываются. Ошибка БД сохраняет bounded counts. Authenticated и предметные события остаются индивидуальными. Retention90дней сохранён. Crash может потерять несохранённое anonymous окно; worker count влияет на общий бюджет. [ADR0025](adr/0025-anonymous-audit-aggregation.md).

SSO-SEC-0005: почтовое подтверждение регистрации привязано к независимому HttpOnly browser secret (только SHA-256 в pending); replacement вращает оба proofs. Все code/link/action/resend пути требуют исходный browser, legacy pending fail-closed. Gmail shortcut переходит в browser через ViewAction; Google bearer+mail secret без browser proof недостаточны. [ADR0026](adr/0026-registration-browser-binding.md) заменяет server-to-server enrollment часть ADR0023.

### SSO-SEC-0006: login/Argon2 admission
Login сохраняет PostgreSQL source30/60с и5/60с на identifier+source/account+source; username/email одного аккаунта суммируются. Untrusted forwarding headers не меняют source. Argon2 параметры и2workers прежние: admission≤16queued+running/≤2source,429+RetryAfter1 на saturation; persistent429 RetryAfter60. Cancellation сохраняет slot до завершения worker. DB outage остаётся503/fail-closed. Общий NAT делит source quota; распределённые источники требуют edge/bot admission, гарантия доступности под arbitrary flood не заявлена. [ADR0027](adr/0027-login-source-admission.md).

# Повторный аудит production readiness после F-01…F-27

**Вердикт: CONDITIONALLY READY.** Все локально исправимые нарушения из исходного аудита устранены в коде, миграциях, тестах, CI и документации. До production остаются обязательные внешние доказательства, перечисленные ниже. Это не разрешение на запуск, публикацию или заявление о сертификации; общая приёмка GOAL-09 ещё не завершена.

Первоначальный локальный implementation SHA: `ae700d7a9803b9757980ef1862af31f6f360a97d`, ветка `new/production-readiness-remediation`, продукт `0.2.0`. Исполнитель Codex; начало исправлений `2026-10-04T02:25:20.3844113+03:00`; запись повторного аудита **2026-10-04T14:29:39.176059+03:00**. Первоначальный последующий commit отчёта меняет только документацию и metadata её приватного detector review; ниже результаты относятся к указанному code SHA. Исходный source SHA `7e857ab80398f8084169ee29b141c6edc6794fe8` и первоначальные ошибки сохранены в [baseline отчёте](PRODUCTION_READINESS_AUDIT_BASELINE.md), [архиве probes](audit/readiness_probes_baseline.py) и [исторических evidence](audit/evidence.json). История не переписана.

## 0. Последующая проверка CI — 2026-10-04T21:22:18.101374+03:00

После публикации разрешённого владельцем [PR5](https://github.com/alxprgstech/sso/pull/5)
устранены реальные сбои обязательных Actions и уточнены trust boundaries (ADR0017–0019).
На source SHA `f9e06d71c7806d71d9226cfb591585cbf5f3ef83` [CI37225223182](https://github.com/alxprgstech/sso/actions/runs/37225223182) подтвердил
все **9 обязательных Actions jobs**, включая PostgreSQL default/enabled, Playwright,
Windows, изолированную установку SDK и реальные Linux Compose/Trivy обоих images.
Два SES skips разрешены CI-03 без AWS; доставка и release не заявляются проверенными.
CodeScene остаётся failed только по двум [сохранённым контрактам](testing/codescene-contracts.md):
immutable archived probe и пятиаргументная сигнатура Alembic. Остальные рабочие
замечания исправлены; для этих двух требуется решение владельца о policy review.

E01/F-18 теперь подтверждён настоящим CI; E02 blocked по этим двум policy замечаниям; исключения не применены.
Ниже C01–C08 и их числа относятся **только** к историческому локальному implementation
`ae700d7a9803b9757980ef1862af31f6f360a97d`. Их evidence не переносится на новые commits.
Новые результаты и неуспешный дополнительный local replay записаны отдельно в
[исправлениях CI](testing/pr5-ci-remediation.md) и [журнале](worklog.md).

## 1. Результат и границы

С учётом последующего подтверждения E01: **23 CLOSED, 4 PARTIALLY VERIFIED, 0 BLOCKED EXTERNAL** по исходным 27 находкам. На момент первоначальной локальной проверки было 22/4/1. `CLOSED` означает устранение исходного дефекта и успешную применимую локальную регрессию. `PARTIALLY VERIFIED` означает исправленный код с реальным локальным доказательством, но незавершённой внешней проверкой транспорта/хранения ключей/топологии. Прежний `BLOCKED EXTERNAL` у F-18 снят реальными Linux images/runtime/Trivy в CI; остальные внешние критерии сохраняются. Эти статусы не скрывают незакрытые production gates.

Локально подтверждены реальные PostgreSQL constraints/locks/races, RSA/JWKS/Argon2/Fernet, SMTP TLS с доверенным и недоверенным сертификатами, Chromium SSO двух RP/admin/Passkey/TOTP/Recovery и enforced CSP через настоящий Nginx. Три MFA-флага остались default-off. Новая самостоятельная регистрация всегда проходит подтверждение email. Enabled-профиль проверен отдельно, включая обязательное подтверждение до Passkey. TLS, UV, CSRF, claims, лимиты и одноразовость ради тестов не отключались.

Исходные unit doubles не выданы за PG/crypto/E2E. Матрица [28 исходных probes](audit/readiness-probe-map.md) связывает каждый первоначальный критерий с постоянной регрессией; новый replay — 104 PASS. Отрицательные проверки сохранены, включая реальную подпись вредоносных claims. Отсутствующий production RSA теперь запрещён, стабильность проверяется с доставленным постоянным ключом. Доказательства и контрольные суммы локальных файлов — [remediation-evidence.json](audit/remediation-evidence.json); краткая карта — [REMEDIATION_SUMMARY.md](REMEDIATION_SUMMARY.md).

## 2. Выполненные команды и результаты

Python 3.12.14, PostgreSQL 16.15 (portable, loopback/SCRAM, выделенная marked test DB), Node 24.20.0/npm 11.19.0, Nginx 1.30.5 Windows, настоящий Chromium Playwright. Runtime images используют закреплённый Python 3.13; их Linux-приёмка ещё не выполнена. Ruff 0.16.8, mypy 2.3.1, detect-secrets 1.5.0, pip-audit 2.10.1. `.venv-sentry` и ignored wrappers — особенности этого стенда. Они загружают приватные DSN без вывода значений; для воспроизведения на другой машине настроить выделенную guarded PostgreSQL по [плану тестов](testing/plan.md). Нельзя подставлять рабочую БД или SQLite.

Команды ниже выполнены из корня репозитория. Сокращённый `python` — `.venv-sentry/Scripts/python.exe`, PATH сборки содержит эту среду. Локальные logs/captures/packages находятся в игнорируемом `artifacts/remediation`, не включены в Git и не публикуются: даже synthetic tracebacks могут содержать тестовые JWT. Наборы пересекаются, их числа **не суммируются** в независимое покрытие.

| ID | Фактически выполненная команда | Результат |
| --- | --- | --- |
| C01 | `python artifacts/remediation/run_with_pg.py -m pytest tests/ packages/python-sdk/tests/test_sdk_isolated.py -q -p no:cacheprovider --basetemp=artifacts/remediation/full-final02 --junitxml=artifacts/remediation/full-final02.xml --tb=short` | 535 passed +16 subtests, 5 external-email deselected, 1 Starlette warning; 240.37 s. XML считает 551 вместе с subtests |
| C02 | `REMEDIATION_TEST_PROFILE=enabled` до запуска; `python artifacts/remediation/run_with_pg.py -m pytest tests/test_mfa_features.py tests/integration/test_email_verification_pg.py tests/integration/test_passkey_pg.py tests/integration/test_distributed_rate_limiting_pg.py -q` с XML `enabled-final03.xml` | 20 passed, 30.78 s; три MFA-флага и REQUIRE_VERIFIED_EMAIL=true до импорта приложения |
| C03 | `python artifacts/remediation/run_with_pg.py -m pytest -p tests.conftest docs/audit/test_readiness_probes.py -q -p no:cacheprovider --basetemp=artifacts/remediation/probes-final02 --junitxml=artifacts/remediation/probes-final02.xml --tb=short` | 104 passed, точный code SHA; criteria replay пересекается с C01 |
| C04 | `python artifacts/remediation/run_nginx_browser.py` | 34 default-off /10 enabled browser PASS; настоящий Nginx, PG, SMTP capture и виртуальный WebAuthn с обязательным UV. Loopback HTTP — согласованный тестовый профиль, не проверка публичного TLS |
| C05 | В `frontend`: `npm run lint`, `npm run typecheck`, `npm run typecheck:tests`, `npm run test:unit`, `npm run test:components`, `npm run build`; отдельно `npm run test:telemetry:browser` | lint/types/build PASS, 11 unit/28 component/9 telemetry browser PASS. Реальные SDK/rrweb recordings, intercepted transport, без внешней ingestion |
| C06 | После сборки wheel/sdist и установки с lock в новую `artifacts/remediation/sdk-clean-final`: её `python -m pytest packages/python-sdk/tests/test_sdk_isolated.py tests/test_python_sdk.py tests/test_sdk_freshness_and_jwks.py -q` | 17 passed; импорт подтверждён из site-packages. `pip check` PASS. Demo store/theme 4 PASS; оба реальных demo `/login` дают 302 через installed SDK с state/nonce/S256 |
| C07 | Ruff check/format, mypy по действительным target paths; `python scripts/bump_version.py check`; `python scripts/scan_secrets_and_deps.py`; `python scripts/check_secret_scan.py --self-test`; `npm audit`; `pip-audit --strict -r requirements-lock.txt`; штатный `git diff --check` | Ruff193 formatted/mypy58 PASS; version/invariants/whitespace PASS; dependency audits 0 known vulnerabilities; secret scan136 candidates/0 new, synthetic secret rejected |
| C08 | `ALX_BUILD_SHA=ae700d7a9803b9757980ef1862af31f6f360a97d`; `python scripts/release_bundle.py build --outdir artifacts/remediation/release-final --private-maps artifacts/remediation/release-private-final --require-clean`; `python scripts/release_bundle.py verify --outdir artifacts/remediation/release-final --expected-sha ae700d7a9803b9757980ef1862af31f6f360a97d` | build/verify exit0, восемь payload + manifest/SHA256SUMS, source_tree_dirty=false, version0.2.0, точный SHA; frontend gates повторены сборкой, source maps приватны |

Точные повторённые QA команды: `ruff check backend/ tests/ packages/python-sdk/ scripts/ examples/`, `ruff format --check backend/ tests/ packages/python-sdk/ scripts/ examples/`, `mypy --explicit-package-bases packages/python-sdk/alxprgs_sso backend/app --ignore-missing-imports` — все PASS,193 formatted/58 source files. Итоговый documentation scan после приватной оценки одного публичного CLI-listing fingerprint:137 candidates/0new;28 source signals +1doc signal рассмотрены, исторический baseline сохранён. Дополнительный signal не является credential и не изменяет detectors. Scoped Markdown101 local links и27 finding statuses/immutable baseline проверены; первоначальная неверная README anchor исправлена на существующий раздел ownership.

Дополнительные focused прогоны, также включённые в C01: security-event lock races 8 PASS (оба порядка grant/event), identity/reauth 6 PASS, legacy DB ownership handoff 2 PASS, OIDC/logout/revoke/Basic wire 12 PASS. Схема fresh/previous upgrade → `0010_registration_session`, autogenerate drift пустой; backup/restore и TOTP re-encryption проверены на отдельных синтетических БД.

Не скрыты промежуточные ошибки: enabled Passkey fixtures первоначально не подтвердили email и получили 401; исправлена подготовка через настоящий SMTP/API процесс. Первоначальная race barrier отпускала lock при setup commit; исправлена синхронизация теста по `FOR UPDATE` и наблюдаемому PG lock wait. Sandbox telemetry run завис при очистке; stopped только подтверждённый owned process, повторный разрешённый запуск 9 PASS без увеличения retry/timeout. Sandbox чтение build wheel дало PermissionError; отдельный authorized read verify PASS, ACL защиты не менялись. Все записи сохранены в [worklog](worklog.md), они не считаются успехами. Оставшийся Starlette library warning и frontend chunk warning >500KB не скрыты; это не неисправность проверенной security policy.

## 3. Закрытие каждой исходной находки

В каждом пункте перечислены основные изменённые файлы; полный review — локальный code commit. Ссылки C01…C08 выше задают фактически выполненную команду и результат. Отдельные тесты включены в эти наборы, не являются придуманными дополнительными запусками.

### F-01 — HIGH — PARTIALLY VERIFIED

**Было:** unsafe production secrets/URLs/TTL и ephemeral RSA. **Изменено:** `backend/app/config.py`, `backend/app/core/key_material.py`, `backend/app/core/security.py`, `.env.example`, `docker-compose.yml`, ADR0014. Startup отвергает DEBUG, известные/пустые secrets, неподходящий RSA/kid/overlap, HTTP/несогласованные origins и чрезмерные TTL; production требует доставленный постоянный RSA, workers/restart используют один key. **Регрессия:** `tests/test_production_keys.py` — unsafe configs, реальные независимые процессы/restart, signature overlap/retirement, отсутствие secret output. **Проверено:** C01/C03 PASS. **Осталось:** E03/E05 — public HTTPS и фактическое custody/mounts/rotation production keys; кодовый дефект закрыт, эти развёртывания не запускались.

### F-02 — HIGH — CLOSED

**Было:** login/MFA/client authentication без distributed quota, неограниченный Argon2 work. **Изменено:** `backend/app/core/rate_limit.py`, `backend/app/core/security.py`, `backend/app/services/auth_service.py`, `backend/app/services/oidc_service.py`, `backend/app/services/mfa_service.py`. PG account/source/challenge quotas сохраняются независимо от rejected login transaction; DB outage fail-closed; bounded prefilter и Argon2 pool/inflight сохраняют лимит при cancellation. **Регрессия:** `tests/test_password_work_budget.py`, `tests/integration/test_distributed_auth_quota_pg.py`, `tests/integration/test_distributed_rate_limiting_pg.py`: real multi-process bursts, missing/existing user, MFA, failure/window, event-loop/cancellation. **Проверено:** C01/C02/C03 PASS. **Осталось:** production capacity/SLO входит E05, не отменяет доказанную защиту.

### F-03 — HIGH — CLOSED

**Было:** cookie+CSRF хватало для MFA/admin изменений, TOTP setup затирал активный фактор. **Изменено:** `backend/app/services/reauthentication_service.py`, `backend/app/api/reauthentication.py`, `backend/app/api/admin.py`, `backend/app/api/mfa.py`, `backend/app/services/mfa_service.py`, frontend reauthentication UI. Одноразовый proof привязан к user/session/security revision/action/body, password и обязательному фактору; pending enrolment заменяет активный TOTP только после подтверждения. **Регрессия:** `tests/integration/test_reauthentication_pg.py`, `tests/integration/test_email_identity_uniqueness_pg.py`, `frontend/e2e/protocol_lifecycle.spec.ts`, Passkey/TOTP browser cases: stolen cookie/CSRF, wrong body/session/user/action/expiry/replay отказ, старый фактор сохранён, настоящий reauth разрешает действие. **Проверено:** C01/C02/C04 PASS. **Осталось:** нет локальной зависимости.

### F-04 — HIGH — CLOSED

**Было:** password/reset/block события оставляли codes/refresh/MFA-step и могли воскресить grants после unblock. **Изменено:** `backend/app/services/security_state.py`, auth/admin/OIDC services, `backend/app/models/authentication.py`, session/user/OIDC models, миграции. Security revision snapshot + User-first row locks; событие атомарно отзывает старые grants/steps/proofs. MFA-step хранится hashed и погашается один раз; selfservice password change сохраняет только текущую сессию на новой revision. **Регрессия:** `tests/integration/test_security_revision_pg.py`, `tests/integration/test_security_event_races_pg.py`: 8 реальных lock races в обоих порядках, password/MFA replay и unblock, stale code/refresh отказ. **Проверено:** C01/C03/C04 PASS. **Осталось:** offline JWT у RP действует до ограниченного ≤300s TTL; мгновенный глобальный offline отзыв не заявлен.

### F-05 — HIGH — CLOSED

**Было:** REQUIRE_VERIFIED_EMAIL применялся не на всех grant/session путях. **Изменено:** auth/OIDC/security-state services и API dependencies: общая verified-email policy на password/MFA завершении, code/refresh/access/userinfo/session; самостоятельная регистрация всегда подтверждается, FEATURE_EMAIL_VERIFICATION_ENABLED=false невалиден. **Регрессия:** `tests/integration/test_verified_email_policy_pg.py`, `tests/integration/test_email_verification_pg.py`, enabled Passkey fixtures проходят настоящее подтверждение; negative old grants. **Проверено:** C01/C02/C03 PASS. **Осталось:** внешняя доставка E04, локальная политика подтверждена без флагового обхода.

### F-06 — HIGH — CLOSED

**Было:** смена email наследовала чужое подтверждение и старые challenges. **Изменено:** auth/admin services, `backend/app/services/registration_service.py`, user/pending-action models. Pending address/revision связаны с точным адресом; admin reset/смена identity отзывают старое подтверждение/grants; uniqueness защищена PG, conflict безопасен без SQL/PII. **Регрессия:** `tests/integration/test_email_identity_uniqueness_pg.py`: реальная selfservice/admin почта, два concurrent confirmations одного адреса, wrong-user proof отказ и own-user успех. **Проверено:** C01/C03, focused6 PASS. **Осталось:** E04 для реального провайдера.

### F-07 — HIGH — CLOSED

**Было:** prompt/max_age/silent-auth игнорировались. **Изменено:** `backend/app/services/oidc_service.py`, `backend/app/api/oidc.py`, auth service, frontend authorize/login, SDK client. auth_time берётся из настоящего login; signed short-lived interaction связывает новый login с точным request для prompt=login/max_age=0; prompt=none возвращает protocol error с state на validated callback без UI. **Регрессия:** `frontend/e2e/protocol_lifecycle.spec.ts`, `tests/integration/test_oidc_contract_remediation_pg.py`, `tests/test_sdk_freshness_and_jwks.py`: fresh/silent/recent/expired/max_age0; real login без подмены clocks/claims. **Проверено:** C01/C04/C06 PASS. **Осталось:** OIF E06 — самостоятельная внешняя interoperability проверка, локальные требования закрыты.

### F-08 — HIGH — PARTIALLY VERIFIED

**Было:** SMTP TLS не удостоверял server identity. **Изменено:** `backend/app/services/verification_email.py`, `backend/app/config.py`, `.env.example`, ops/ADR0014: verified SSLContext с hostname/CA, STARTTLS до credentials, отказ plaintext downgrade и credentials без TLS. **Регрессия:** `tests/test_smtp_tls.py` — реальные loopback TLS server trusted/untrusted CA, mismatch hostname, unavailable STARTTLS, отсутствие AUTH до защищённого канала. **Проверено:** C01/C03 PASS. **Осталось:** E04 — настоящий разрешённый SMTP/SES/provider endpoint/доставка, production CA/hostname; local TLS не выдан за SES.

### F-09 — MEDIUM — CLOSED

**Было:** неверные OAuth errors/challenges/no-store. **Изменено:** OIDC API/service/schemas: validated redirect/state, bounded duplicate/unsupported parameter validation, protocol error types, WWW-Authenticate для Basic/Bearer, Cache-Control/Pragma; scheme Basic case-insensitive. **Регрессия:** `tests/integration/test_oidc_contract_remediation_pg.py`, `tests/test_signed_token_profiles.py`, protocol browser — реальная confidential code/PKCE/JWT транзакция и malformed HTTP. **Проверено:** C01/C03/C04, focused12 PASS. **Осталось:** E06.

### F-10 — MEDIUM — CLOSED

**Было:** PKCE syntax принималась только по совпадению digest. **Изменено:** OIDC validation: только S256, verifier43–128 ASCII unreserved, challenge43; empty/Unicode/plain и duplicate inputs отклоняются. **Регрессия:** `tests/test_signed_token_profiles.py`, protocol PG/browser — граничные длины positive и неверный синтаксис даже при совпадающем digest negative, обязательный PKCE public/confidential. **Проверено:** C01/C03/C04 PASS. **Осталось:** E06.

### F-11 — MEDIUM — CLOSED

**Было:** неполные обязательные JWT/ID claims. **Изменено:** `backend/app/core/token_profiles.py`, `packages/python-sdk/alxprgs_sso/token_profiles.py`, SDK client: отдельные access/ID profiles, RS256, issuer/audience/sub/exp/iat/type/scope/nonce/azp и NumericDate validation, no ID-as-access. **Регрессия:** `tests/test_audit_crypto_regressions.py`, `tests/test_signed_token_profiles.py`, installed SDK tests — настоящие RSA signatures с неверными/пропущенными/неверно типизированными claims, positive keys/nonce/multi-aud. **Проверено:** C01/C03/C06 PASS. **Осталось:** E06; локальные crypto negatives не выданы за suite certification.

### F-12 — MEDIUM — CLOSED

**Было:** неполный RP-Initiated Logout. **Изменено:** OIDC API/service: GET query и POST form, validated id_token_hint signature/issuer/aud/sub/client/session и post_logout_redirect/state; expired hint разрешён только для связанной текущей/recent session. Hintless logout требует confirmation/CSRF, не произвольный redirect. **Регрессия:** `tests/integration/test_oidc_contract_remediation_pg.py` — 6 неверных hint/redirect cases сохраняют сессию, GET/POST/expired positive удаляют точную сессию; browser logout двух RP. **Проверено:** C01/C03/C04, focused12 PASS. **Осталось:** E06; optional front/back-channel/session logout не заявлены и не добавлены.

### F-13 — MEDIUM — CLOSED

**Было:** kid неверного типа давал 500 до signature validation. **Изменено:** token/key profiles и SDK JWKS: bounded ASCII kid, header≤16KiB, controlled invalid-token отказ; malformed kid не инициирует fetch. JWKS≤64KiB/16 уникальных подходящих RSA keys. **Регрессия:** `tests/test_production_keys.py`, `tests/test_signed_token_profiles.py`, `tests/test_sdk_freshness_and_jwks.py`: hostile list/object/oversize kid, malformed JWKS, реальные valid RSA. **Проверено:** C01/C03/C06 PASS. **Осталось:** нет локальной зависимости.

### F-14 — MEDIUM — CLOSED

**Было:** SDK терял scope, client policy отсутствовала. **Изменено:** OIDC model/schemas/admin/service/migrations, SDK models/FastAPI/client: per-client allowed_scopes, отказ расширения запроса, claims по granted scopes, scopes и roles независимы, require_scope. **Регрессия:** signed-token/installed SDK/OIDC PG tests: permitted/rejected scopes, role не даёт scope, клиентское изменение через reauth. **Проверено:** C01/C03/C06 PASS. **Осталось:** новые defaults/migration совместимость описаны в [migration.md](migration.md), владелец задаёт scope policy своих RP.

### F-15 — MEDIUM — CLOSED

**Было:** production доверял dev origins/HTTP return targets. **Изменено:** config/main/auth/frontend return URL helpers: ровно production FRONTEND_URL, HTTPS и точный origin, localhost только явный development profile. **Регрессия:** `tests/test_production_origin_policy.py` запускает настоящий middleware в свежем production-config subprocess, разрешённый HTTPS200, foreign/HTTP/localhost отказ; frontend return negative tests. **Проверено:** C01/C03/C05 PASS. **Осталось:** public deployment E03, localhost test profile не является production exception.

### F-16 — MEDIUM — CLOSED

**Было:** admin recovery выдавал постоянный временный пароль без forced change. **Изменено:** auth/admin/OIDC/deps, session-purpose migration, frontend forced change: 15min одноразовый temporary password, ограниченная 10min purpose-session, запрет обычных grants до изменения; security events инвалидируют recovery, после смены нужен fresh login. **Регрессия:** `tests/integration/test_temporary_password_pg.py` — actual recovery/change/login, expiry/replay, ограниченные API/OIDC, прежние credentials отказ. **Проверено:** C01/C03 PASS. **Осталось:** нет локальной зависимости.

### F-17 — MEDIUM — CLOSED

**Было:** слабая password/recovery policy и разные пути отсутствующего user. **Изменено:** core security, config, `backend/app/data/common-passwords*`, SDK/UI docs: 15–128 Unicode, pinned offline MIT blocklist, Argon2id64MiB/t3/p4, реальный dummy hash при missing user, bounded pool, generic login refusal. Recovery32 A–Z/0–9 (≈165bit), hashed normalized, атомарная одноразовая замена второго фактора после пароля. **Регрессия:** work-budget/password/recovery PG/browser, positive Unicode, blocklist/min/max, reuse/no-password отказ. **Проверено:** C01/C02/C04; local timing median existing261.639ms/absent205.965ms, ratio1.2703. **Осталось:** это ограниченный локальный замер, не универсальная гарантия indistinguishability или NIST/AAL certification.

### F-18 — MEDIUM — CLOSED

**Было:** root/dev dependencies/широкая DB identity. **Изменено:** backend/frontend Dockerfiles (включая release), Nginx main/config, Compose, fresh init SQL, `backend/app/core/database_policy.py`, `scripts/transfer_database_ownership.py`, `scripts/check_container_runtime.py`, `.github/workflows/ci.yml`. Immutable image digests; non-root runtime и production-only packages, read-only rootfs/tmpfs/cap_drop/no-new-privileges и CPU/memory/PID bounds; runtime DML отдельно от migration owner, DB startup preflight fail-closed. Offline legacy handoff только известных объектов после проверки DB/owner/markers/остановки app, не REASSIGN OWNED всех объектов. **Регрессия:** `tests/integration/test_migration_upgrade_roles_pg.py`, `tests/test_ci_security_policy.py`: реальные fresh/legacy PG roles, runtime DDL denied/privileged identity denied; mandatory owned image/runtime/Trivy CI. **Проверено:** C01, focused handoff2 PASS; scripts compile/static gates PASS. **Последующее подтверждение:** E01 — реальные Linux build/non-root/read-only/capabilities/resources/network/outage/CSP и Trivy обоих images PASS на `f9e06d71c7806d71d9226cfb591585cbf5f3ef83`, [CI](https://github.com/alxprgstech/sso/actions/runs/37225223182). Локальный Docker отсутствует; доказательство получено обязательным CI job, не статической проверкой. Production topology/retention остаются E03/E05.

### F-19 — MEDIUM — PARTIALLY VERIFIED

**Было:** несогласованный forwarded trust терял scheme/IP. **Изменено:** `deploy/nginx.conf`, frontend Nginx, Compose, deps/rate_limit: одна выбранная TLS boundary, exact Host, strip spoofed forwarding at gateway, exact trusted peer/hops (без wildcard), Uvicorn no-proxy-headers; один безопасный IP parser для quotas/audit. **Регрессия:** real multi-process PG distributed-rate tests для trusted/untrusted chains/spoofing; настоящий local Nginx C04; bounded chain rejection. **Проверено:** C01/C02/C04 PASS. **Осталось:** E03 — реальные public HTTPS hops/network isolation/secure host-only cookies/различимые source IP через весь путь; выбранная модель не объявлена существующим развёртыванием.

### F-20 — MEDIUM — PARTIALLY VERIFIED

**Было:** неправильные names, stdout secrets/overwrite, незавершённая TOTP rotation. **Изменено:** `scripts/rotate_keys.py`, `scripts/migrate_totp_key.py`, operations/env/ADR0014: SESSION_SECRET_KEY/TOTP_ENCRYPTION_KEY, explicit private exclusive destination/permissions, no stdout keys/overwrite, RSA overlap и retirement, session invalidation, offline transactional TOTP re-encryption с backup/rollback. **Регрессия:** production-key tests, `tests/integration/test_totp_key_rotation_pg.py`, backup/restore/TOTP suite: ciphertext реально расшифровывается новым ключом, timestamps сохранены, failure rollback, old file не изменён. **Проверено:** C01/C03 PASS, synthetic Windows ACL/PG drill. **Осталось:** E05 — реальные key custody/escrow, production permissions/mounts и согласованный recovery drill; действующие ключи не менялись.

### F-21 — MEDIUM — CLOSED

**Было:** Alembic target_metadata пустая. **Изменено:** `backend/app/migration_metadata.py`, `backend/alembic/env.py`, migrations0005…0010 и models: controlled imports всех таблиц, constraints/indexes согласованы. **Регрессия:** `tests/integration/test_migration_drift_pg.py`, migration-upgrade-role tests — real fresh и previous revision upgrade → head, пустой autogenerate diff; тестовый guard marker отдельно от app metadata. **Проверено:** C01/C03 PASS. **Осталось:** production upgrade/backup E05, auto-DDL рабочей БД не выполнялся.

### F-22 — MEDIUM — CLOSED

**Было:** safe logs теряли operation/reason/request correlation и security audit coverage. **Изменено:** `backend/app/core/diagnostics.py`, logging/main/audit и security-event call sites: finite codes, bounded validated UUID request ID, audit linkage, recursive allowlist/node/depth limits; arbitrary exceptions/SQL/headers/query/body/messages не логируются. **Регрессия:** `tests/test_diagnostic_codes.py` и privacy suites — real PG correlation/events, fuzz secrets/PII/exception/query, различимые failure codes, actual telemetry recordings negatives. **Проверено:** C01/C05 PASS. **Осталось:** E05 — доставка внешнего alert/on-call и staging Sentry privacy/usage приёмка, не объявлена выполненной одной safe log записью.

### F-23 — MEDIUM — CLOSED

**Было:** CSP только Report-Only. **Изменено:** `deploy/nginx.conf`, frontend CSP/security header snippets, related UI/styles: enforced restrictive CSP, без unsafe-inline/eval; exact optional telemetry ingest, object/frame/base/form ограничения; reporting остаётся диагностическим дополнением. **Регрессия:** `frontend/e2e/csp.spec.ts`, appearance/privacy/telemetry: настоящий Nginx header, inline/foreign script/style/connect блокируются, legitimate UI/QR/theme работают. **Проверено:** C04/C05 PASS. **Осталось:** E01/E03 подтверждают те же packaged headers/publicTLS; локальный browser enforcement уже доказан, Report-Only за него не выдан.

### F-24 — LOW — CLOSED

**Было:** Windows Cyrillic encoding failures, skip при build failure и fake async concurrency evidence. **Изменено:** Windows launcher/reset/process harness/tests, `tests/test_reset_local_ps1.py`, `tests/test_windows_native_encoding.py`, `tests/test_server_lifecycle.py`, реальные PG race tests и обязательный Windows CI. Native CP866 разбирается корректно, exact PID/ownership checks; required build failure теперь FAIL, unawaited doubles исправлены в явно unit tests. **Регрессия:** Windows PowerShell5.1/pwsh7 cancel/failure/foreign-volume/env preservation, actual Cyrillic/native process lifecycle, настоящий PG lock wait. **Проверено:** C01 PASS, skip/xfail обходов нет. **Осталось:** E02 повторяет mandatory Windows/Linux jobs на exact SHA.

### F-25 — LOW — CLOSED

**Было:** OAuth revoke принимал unrelated SSO cookie secret. **Изменено:** OIDC revoke только для OAuth refresh текущего клиента, unknown token200 без fallback удаления OP session; logout отдельный CSRF workflow. **Регрессия:** `tests/integration/test_oidc_contract_remediation_pg.py`: unknown/cookie/other-client secret сохраняют SSO/grant, own refresh revoked; hash/client binding проверены реальной PG. **Проверено:** C01/C03, focused12 PASS. **Осталось:** нет локальной зависимости.

### F-26 — LOW — CLOSED

**Было:** deprecated Authlib JOSE API для Gmail. **Изменено:** `backend/app/services/registration_service.py` — уже закреплённый поддерживаемый PyJWT2.15, Google HTTPS JWKS bounded64KiB/16 RSA, exact Google issuer/aud/azp/kid/time/signature; lock сохранён, собственная криптография не реализуется. **Регрессия:** `tests/test_gmail_signed_bearer.py` — 9 actual RSA-signature tests, неверные claims/expiry/keys и cache bounds отказ. **Проверено:** C01 PASS, deprecated Authlib JOSE warning отсутствует. **Осталось:** E04 — approved Gmail sender/live bearer/action; unit signatures не названы live Google proof.

### F-27 — LOW — CLOSED

**Было:** неверные JWKS/admin routes/flags/versions/SDK examples и старые evidence вместо текущих. **Изменено:** README/API/security/operations/migration/research/data-model/ESPD guides/SDK/example docs/ADR0014…0016, этот отчёт/summary/probe map. Snapshot63 effective routes, `/.well-known/jwks.json`, реальные admin methods, default-off и mandatory registration email; точный installed SDK state/nonce callback без bearer output; Fernet AES128/HMAC, actual schema и version0.2 (document version1.0 отдельно). **Регрессия:** `tests/test_documented_api_contract.py`, clean installed SDK/examples и scoped links/consistency review; архивный audit не исправлялся задним числом. **Проверено:** C01/C06/C07/C08 PASS; итоговые documentation checks записаны в worklog. **Осталось:** GOAL-09 и исторические external reports не преобразованы в PASS; будущий release требует отдельного поручения.

## 4. Стандарты и фактический профиль

| Область | Реализация и доказательство | Граница утверждения |
| --- | --- | --- |
| OIDC Core/Discovery, OAuth code + PKCE S256 | prompt/max_age/auth_time, exact registered redirects, state/nonce, issuer/aud/azp/claims, single-use code/rotating refresh, signed real crypto/browser C01/C03/C04/C06 | Code profile; OIF E06 ещё не запускался; нет certification/FAPI/DCR/implicit/hybrid claim |
| OAuth errors/revocation, RP-Initiated Logout | Wire HTTP/challenges/no-store, client-bound revoke, GET/form POST logout, expired bound hint, CSRF confirmation; focused12 PG PASS | Нет необязательных session/front/back-channel logout; logout certification не заявлена |
| Password/MFA/WebAuthn | Argon2id, minimum/blocklist/quotas, one-use factors, UV/origin/RP/challenge/signature negatives; default-off/enabled отдельные C01/C02/C04 | [NIST SP800-63B-4](https://pages.nist.gov/800-63-4/sp800-63b.html) — обоснование policy, не AAL certificate; отключённый MFA не объявлен защитой default password login |
| ASVS/OWASP security controls | Reauth/security revision, RBAC/IDOR/CSRF, DB atomicity, safe logs/CSP/key/TLS tests | Engineering mapping, не сертифицированное полное соответствие ASVS/юридическим требованиям |
| Ключи/сохранение данных | RSA persistent/overlap, secure key files, библиотечный [Fernet](https://cryptography.io/en/latest/fernet/#implementation), real PG transactional rotation/restore | Custody/backup retention/RPO/RTO внешнего стенда E05 ещё не приняты |

## 5. Функциональная матрица и эксплуатация

| Сценарий | Реальный результат | Ограничение |
| --- | --- | --- |
| Login/logout/два RP/admin/reauth | PG + Nginx/Chromium PASS | HTTPS staging E03 |
| Signup/identity/email/recovery | Local SMTP/API+PG PASS, exact verified policy | Live SES/Gmail E04 |
| TOTP/Passkey/Recovery, default-off APIs | Enabled/default-off PG/browser PASS, virtual authenticator UV обязателен, recovery после password | MFA-флаги default false, production activation — решение владельца |
| Codes/refresh/replay/security-event races | Real PG atomicity и оба row-lock порядка PASS | Offline RP JWT до300s, не мгновенный global revoke |
| Fresh/legacy migrations, least privilege/backup/restore/erasure | Real PG PASS, current head0010, drift пустой, foreign DB/marker refusal | Linux container runtime E01; рабочая retention/restore приёмка E05 |
| Logs/privacy/CSP | Allowlist/fuzz/actual recordings и real enforced browser CSP PASS | Live alerts/Sentry/staging audit E05 |
| SDK/packages/demo/examples | Clean wheel17 и оба demo initiation PASS; bundle exact SHA clean | Не опубликовано, tagged release/remote jobs E02 |

## 6. CI, зависимости и целостность evidence

Actions закреплены полными commit SHA, ограничены permissions, PR не получает production secrets/write credentials. Required checks не skip/xfail/continue-on-error. Container job проверяет actual non-root/read-only/rootfs/caps/resources/private network/DB outage recovery/CSP и Trivy HIGH/CRITICAL (без ignore-unfixed обхода), отдельные ordinary/enabled/Windows gates. SES ordinary CI без credentials может условно не запускаться **только** по разрешённому GOAL CI-03; explicit run_email_tests=true и release по-прежнему обязательны и fail без prerequisites. Remote run на этом SHA ещё отсутствует.

pip-audit/npm audit — 0 известных уязвимостей на момент проверки, не гарантия отсутствия будущих CVE. Source scan использует git tracked/new source scope (включает tracked ignored paths), не сканирует приватные captures/venv как продукт. Whole-file exemptions убраны, synthetic-secret self-test отвергается. 28 новых exact fingerprints приватно разобраны в [secret review](testing/secret-review-remediation.md); старые записи baseline сохранены. Первоначальная оценка владельцем 58 исторических сигналов не считается выполненной: E07.

Bundle собран из clean tree exact code SHA, source_tree_dirty=false. Восьми payload и manifest сопоставлены размеры/SHA256, private maps не попадают в deployment dist. Это **offline dry-run**, не GitHub release: tag=null. Published version/tag не перезаписывался, CODE/CI не развёртывает приложение. CD template вне workflows остаётся полностью закомментированным. Существующие исторические artifacts/CI результатов другого SHA не использованы как успех этого SHA.

## 7. Остаточные внешние проверки: точные условия

Все семь ID — конечные критерии для владельца/отдельной разрешённой сессии. Они не заменяют выполненные локальные исправления. Новые расходы, реальные письма, DNS, публикация и production не входят в это поручение.

| ID / статус | Недостающий input и наблюдаемая причина | Следующее действие / критерий |
| --- | --- | --- |
| E01 VERIFIED IN CI: F-18/Linux images | Actual Compose/runtime/Trivy PASS на `f9e06d71c7806d71d9226cfb591585cbf5f3ef83` ([CI](https://github.com/alxprgstech/sso/actions/runs/37225223182)); локальный Docker отсутствует | На изолированном Docker/Linux checkout code SHA выполнить mandatory `telemetry-container-check` из `.github/workflows/ci.yml`, в том числе `python scripts/check_container_runtime.py` и закреплённый Trivy0.75.0 HIGH/CRITICAL. Сохранить digests/build identity/non-root/rootfs/caps/resources/private-network/outage/CSP results и отсутствие dev packages; проверить release Dockerfile. Использовать только owned campaign/volumes, не reset существующей установки |
| E02 IN_PROGRESS: GitHub CI/release | Публичный push разрешён, PR5 открыт; все9 Actions PASS на `f9e06d71c7806d71d9226cfb591585cbf5f3ef83`, CodeScene failed | Исправить рабочие замечания и сохранить actual exact-head Actions/CodeScene результаты. Для release дополнительно существующий tag и общий exact-tag dry-run с обязательным external email; локальный C08 не заменяет Actions execution |
| E03 BLOCKED EXTERNAL: F-01/F-19/public TLS | Reachable staging issuer/DNS/certificate/trusted hops не предоставлены; домен — допущение | Развернуть отдельный synthetic HTTPS staging по ops/ADR0016; задать точные public URLs и trusted peers, закрыть direct backend/DB. `curl --fail https://<issuer>/.well-known/openid-configuration`, JWKS и `openssl s_client -connect <host>:443 -servername <host> -verify_return_error`; через actual chain проверить issuer/redirect, Secure/HttpOnly/host-only/SameSite cookies/CSRF, exact CORS/CSP/Host, spoofing/разные IP quotas. Сертификат не отключать, cookie/token bodies не публиковать |
| E04 BLOCKED EXTERNAL: F-08/provider/Gmail | Нет поручения на реальные письма и утверждённых provider/testmail/sender prerequisites | После разрешения на synthetic mailboxes, SES access/approved Gmail sender и private testmail/AWS variables: `python -m tests.helpers.testmail_cli preflight`, `python -m pytest tests/integration/test_testmail_email_pg.py -m email_external --run-email-tests -x --tb=short`, `python scripts/run_e2e_suite.py --suite email` с guarded DB. Проверить TLS hostname/CA/credentials transport, доставку/отказ/replay и настоящую Gmail action signature; сохранить только безопасные категории/результаты. См. [email testing](testing/email.md) |
| E05 BLOCKED EXTERNAL: F-01/F-20/custody/ops | Реальных secret mounts/escrow/backup retention/alert destination/on-call/staging Sentry/ресурсного стенда нет | По [operations](operations.md), [security](security.md), [Sentry](observability.md) выполнить утверждённый synthetic staging RSA overlap/retirement+workers restart, session invalidation, offline TOTP migration+rollback и guarded backup/restore+fresh erasure journal. Зафиксировать private key ACL/mount ownership, backup recovery/retention/RPO/RTO/SLO и доставку redacted alert/on-call drill/privacy/usage; не выводить keys/tokens. Local PG/ACL/CSP/recording tests уже PASS, production drill не выполнен |
| E06 BLOCKED EXTERNAL: OIF | Нет отдельного reachable HTTPS issuer, suite alias/account и manually registered clients | Применимые plans: Basic OP, Config OP и RP-Initiated Logout OP с response_type=code. Зарегистрировать exact `https://www.certification.openid.net/test/a/<ALIAS>/callback` и logout `https://www.certification.openid.net/test/a/<ALIAS>/post_logout_redirect`, basic/post clients/scopes. Suite requests должны соблюдать обязательный S256/email/MFA policy; ничего не ослаблять. Сохранить code SHA, private plan config и run URLs/results/failures/warnings. [OP testing](https://openid.net/certification/connect_op_testing/), [logout testing](https://openid.net/certification/connect_op_logout_testing/). Ни один plan не выполнен; certification отсутствует |
| E07 BLOCKED EXTERNAL: исторический baseline owner review | Новые28 fixtures рассмотрены, но первоначальные58 исторических signals не приняты владельцем | Приватно проверить сохранённые history-summary/fingerprints и контекст без вывода values; отличить synthetic fixtures/public identifiers от настоящих credentials. Если найден реальный secret — rotate/incident/history policy по отдельному поручению. Сохранить решение по fingerprints; отсутствие нового detector signal не является owner acceptance |

Для формальной OIF Logout Certification потребовался бы ещё применимый session/front/back-channel profile. Это не требование текущего согласованного Code+RP-Initiated продукта и не причина добавлять необязательные endpoints. Сертификация отдельно не заявляется.

## 8. Точка продолжения и go-live checklist

- [x] Исходный audit/probes сохранены, каждый F-01…F-27 имеет fix/tests/result/status, исходные negatives не ослаблены.
- [x] Все доступные local implementation/PG/crypto/browser/SDK/privacy/scans и clean exact-SHA bundle завершены; план/журнал/актуальный статус обновлены.
- [x] E01: actual Linux images/runtime/CVE на указанном CI SHA.
- [ ] E02: quality gate нового reviewed head и отдельно порученный release.
- [ ] E03/E04: утверждённый HTTPS issuer/proxy/cookies/CORS и разрешённая live provider/Gmail/email приёмка.
- [ ] E05/E07: key/backup/erasure/alerts/privacy custody и приватное историческое owner review.
- [ ] E06: независимые applicable OIF results без заявления сертификата заранее.
- [ ] Отдельное решение владельца о production и выполнение всех критериев раздела8 GOAL. Пока verdict CONDITIONALLY READY; GOAL-09 не закрыт.

Локальное исправление F-01…F-27 и повторный аудит закончены. Продолжение — оставшийся quality gate E02, затем выбранный synthetic HTTPS staging для E03…E06 и private E07. Existing data/production keys не изменялись; Разрешённые push/PR5 выполнены; tag/release/deploy/DNS/live email отсутствуют.

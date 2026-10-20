# Приёмка ALXPRGS SSO

Продукт 0.2.0. Актуальная методика: [03-test-procedure](03-test-procedure.md), [подготовка](testing/README.md), [чек-лист](testing/manual-checklist.md). Результаты ниже исторические: относятся к указанной ревизии и стенду, не подтверждают текущий production. Очистка DOC-CLEANUP-02 не повторяла runtime-проверки.

## Матрица текущей приёмки

Критерии заданы [ТЗ](01-technical-specification.md) и [методикой](03-test-procedure.md). Галочки старых этапов не переносятся на новый SHA.

| Область | Обязательное evidence |
| --- | --- |
| Сборка и качество | Ruff/types/pytest, frontend lint/types/component/build, чисто установленный SDK wheel/sdist и примеры |
| БД и эксплуатация | Реальная PostgreSQL, миграции до head, сохранение данных/roles/drift, backup/restore на отдельной БД, health/readiness и Compose |
| OIDC и сессии | Два RP, PKCE/state/nonce/claims/redirect, code/refresh replay и races, logout, read grant и одноразовые mutation proofs |
| Email и MFA | Обязательная email-confirmation до самостоятельного создания пользователя; три MFA default-off API, enabled TOTP/UV Passkey/recovery negatives |
| Авторизация/privacy | RBAC/IDOR/last-admin/CSRF/Origin/security revision, consent/deletion/retention/restore journal, telemetry redaction |
| CI/release/security | Exact SHA/tag, обязательные gates/scans, hashes/SBOM/provenance, manifest/checksums; CD остаётся выключенным |
| Внешняя production-приёмка | Live providers, sender registration, public TLS/DNS/IAM/secret custody/storage/alerts/load/OIF и owner credential review |

[Прежние акты и команды](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/acceptance.md) сохранены в Git; неуспешные попытки и хронология — [worklog](worklog.md). Локальные результаты последнего remediation приведены ниже.

## SEC-REMED-20261007 — локальная повторная приёмка 18.10.2026

База `170175be06318645c0fd2ef222e2688edf31b37c`, ветка `new/security-remediation`, рабочее дерево поверх базы. Builds/provenance явно помечены `source_tree_dirty=true`; это локальная проверка кандидата, не выпуск и не результат remote CI будущего commit. Решения: [ADR-0023](adr/0023-security-remediation.md).

Среда: Windows, Python3.12.14, pytest9.1.1, Node24.20.0/npm11.19.0, новая tmpfs PostgreSQL16.15 на `127.0.0.1:5433` с safety marker. Backend image Python3.13.16, non-root/read-only Compose; browser backend18000/frontend5173/SMTP11025. Evidence — ignored `artifacts/security-remediation-final/`; raw captures/keys/tokens не публикуются.

| Проверка / фактическая команда | Результат |
| --- | --- |
| `pip install --require-hashes -r requirements-lock-hashed.txt`, clean venv; backend editable `--no-deps --no-build-isolation`, SDK wheel; `pip check` | PASS, graph без конфликтов; hash companions full/runtime/build согласованы |
| `ruff check` / `ruff format --check` backend/tests/SDK/scripts/examples и audit fixture; `mypy --explicit-package-bases ... --ignore-missing-imports` | PASS /230files /73typed files |
| Fresh Alembic `upgrade head`, `init_fresh_ci_test_marker --local-fresh` | PASS,0013_security_outbox; guards не ослаблялись |
| `pytest tests -vv`, default-off в clean CI-prepared env | 687PASS,18subtestsPASS,5external deselected,812.74s; `pytest-final-ci.xml` |
| CI enabled suite: MFA features/email verification/passkey/distributed rate limits | 20PASS,82.87s; реальные PostgreSQL/crypto, SMTP loopback |
| Post-change Origin/redirect/JWKS/credential-ID regressions | 54PASS: реальная OIDC PostgreSQL integration и36unit boundary, включая7новых route/method/header cases |
| Windows key ACL/backup validator regression | 53PASS; injected explicit Everyone ACE, проверены directory/files; backup отвергает широкие права; real RSA/session/TOTP generation+privateACL3PASS |
| SDK `build --no-isolation`, clean installed wheel package/tests + Python SDK/JWKS tests | wheel/sdist PASS;29tests PASS до установки backend в clean-env |
| npm lint/typecheck/typecheck:tests/test:unit/test:components/build | PASS;13unit/40components; повтор builder тоже PASS |
| Secret scanner `--self-test`, baseline неизменён |127candidates/0new (финальный повтор); контрольный synthetic secret отвергнут |
| `pip_audit --strict --no-deps --disable-pip -r requirements-lock.txt`; npm audit |0known/0vulnerabilities, exit0; не zero-day guarantee |
| Docker backend/frontend builds; checksum-verified official Trivy0.75.0 High/Critical/exit-code1 | PASS; final images0High/Critical, frontend libexpat2.9.0-r0/tiff4.7.2-r0 |
| Final isolated Compose runtime + Nginx CSP | PASS: non-root/read-only/capabilities/resources/runtime role,3real browser CSP tests, DB outage/recovery; owned cleanup |
| Final local `release_bundle.py build` | PASS: packages/migrations/frontend, manifest/SHA-256/SBOM/unsigned provenance/private maps separation; публикации нет |
| Browser default-off/enabled, post-change OIDC PG |48PASS /9PASS; OIDC PG+boundary54PASS; согласие с документами ожидается до навигации, UV/OTP/replay assertions сохранены |

Диагностические неуспехи сохранены в worklog: старый installed SDK, missing installed backend в независимом worker (первый IPv4 full685PASS/1FAIL), localhost connection5.031s противIPv4 0.015s, Windows explicit ACL/PSModulePath, CA/cache permissions сканера, пересечение Compose CSP с собственным release npm ci. Они не заменены skip/xfail/retries/timeout или ослаблением защиты; после исправлений среды/кода выполнены указанные повторы. Один ранний final Compose `up` exit1 не сохранил stderr и не засчитан; отдельная финальная кампания прошла полностью после завершения builder.

Внешние SES/Gmail/Sentry и sender registration, public TLS/DNS/IAM/managed secrets, production storage/ACL/нагрузка/OIF и review исторических credentials остаются отдельной приёмкой. CD/release publication/deploy/реальные рассылки не выполнялись. DOC-VERSION-LOCK-01 вне scope.

## Стенд и итоговые проверки remediation

База исправлений `170175be06318645c0fd2ef222e2688edf31b37c`, implementation commit `f4b5fe52aa74c4fd010468eb8a3b9c2dec6eabb2`; merge PR #13 — `7d1585e7bdd40104be7a8b933b998cbc843d46a5`. Проверялось рабочее дерево перед implementation commit; нового прогона merge SHA этой записью не заявляется.

Среда: Windows, Python 3.12.14; изолированная PostgreSQL 16 с новым tmpfs и safety marker; Linux images backend Python 3.13.16. Сырые evidence находятся в ignored `artifacts/security-remediation-final/` и не публикуются.

Подтверждены: Ruff/format и mypy (73 файла); hash companions full/runtime/build; чистая установка закреплённых зависимостей; SDK wheel/sdist и installed-wheel tests (29 PASS); secrets self-test (127 кандидатов, 0 новых (финальный повтор)); pip-audit и npm audit (0 известных уязвимостей); frontend lint/types/test-types, 13 unit и 40 component, build; оба Linux image build; изолированный Compose runtime/non-root/read-only/capabilities/resources/runtime DB role/CSP (3 browser tests), DB outage/recovery и owned cleanup.

Полный pytest на PostgreSQL: 687 PASS, 18 subtests PASS, 5 внешних email cases deselected (812.74s). После подготовки среды как в CI independent distributed-quota worker и реальный backup/restore/TOTP прошли. Enabled CI suite: 20 PASS (82.87s). Дополнительно OIDC PostgreSQL + Origin boundary: 54 PASS (unit boundary 36 PASS), включая 7 новых route/method/header cases, добавленных после старта полного прогона. Финальный release dry-run и Trivy обоих исправленных images PASS. Финальный Compose с последней Origin-правкой, CSP3 и DB outage/recovery PASS; owned cleanup выполнен. Browser retest: default-off48PASS, enabled9PASS (реальные virtual WebAuthn UV, TOTP/recovery replay, два RP). Повтор финальных Compose images: PASS, CSP3PASS, outage/recovery PASS, owned cleanup выполнен. Локальный remediation retest завершён; production-приёмка отдельно.

## Источники и внешняя приёмка

[Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/SECURITY_AUDIT.md) — исходный аудит до исправлений; [Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/audit/security-remediation-20261018.md) — полный retest и диагностика. Действующие решения: [ADR-0023](adr/0023-security-remediation.md), остаточные риски — [security](security.md).

Реальные SES/Gmail/Sentry, sender registration, public TLS/DNS/IAM/managed secrets, storage ACL, multi-replica load/OIF и приватный review исторических credentials не закрыты локальными тестами. Публикация релиза и deployment не выполнялись. DOC-VERSION-LOCK-01 остаётся planned.


## DOC-CLEANUP-02 — 2026-10-20T02:49:55+03:00

Документационная очистка по поручению владельца: старые аудиты удалены после переноса действующих сведений; закрытая диагностика сокращена, журнал/открытые требования/тестовые зависимости сохранены. Проверены UTF-8 всех 64 оставшихся tracked Markdown, 292 локальные ссылки действующего комплекта (0 отсутствующих, исторический worklog исключён из проверки ссылок), 9 Git-целей по точному SHA через git cat-file. Secret scan с контрольным секретом: PASS, 126 candidates/0new, baseline без изменений. Формат diff проверяется после финальной записи. Исходники, миграции, тесты, lock и CI policy не менялись; runtime/remote CI не повторялись.

### SSO-SEC-0005 / #19 — 2026-10-20T16:30:27.5799474+03:00
Main7555f47 pending overwrite подтверждён кодом. PG16/Python3.12.14 миграция0013→0014PASS; итог46PASS: tests/integration/test_registration_flow_binding_pg.py(5), test_registration_browser_cookie.py(2), test_registration.py, integration/test_registration_pg.py, test_gmail_action_binding_pg.py, test_registration_consent_guard_pg.py, test_privacy_pg.py, tests/test_verification_email.py, test_documented_api_contract.py. Original/reverse order ×code/link, copied mailbox proof alone rejected, stale browser/resend/foreignOrigin/legacy rejected, recovery restart creates victim credentials/ordinary role, replay rejected; Gmail real RSA fixture+MockTransport (не liveGoogle), action secret и browser mandatory, concurrent single-use сохранены. Cookie HttpOnly/host-only/Secure/__Host HTTPS подтверждены unit. Первые cookie fixtures FAILED(path/Host), исправлены, final46PASS. Frontend lint/typecheck/typecheck:tests/components40/buildPASS; Ruff/format/mypy65, secret self-test126/0new/diffPASS. Первые2synthetic password literals scan отклонил; заменены генерацией, baseline не изменён. Live Gmail rendering/sender registration, publicHTTPS/browserE2E/production/load не проверены. Gmail shortcut теперь ViewAction, ADR0026; legacy pending требует restart.

SSO-SEC-0005 CI follow-up 2026-10-20T16:40:52.7021636+03:00: guard SCHEMA_REVISION синхронизирован0014 (обязательные privilege/schema проверки сохранены). Migration-role+DBguard/metadata22PASS/1envTempACLerror; metadata8PASS с собственнойtemp. Backend/frontend images buildsPASS; ownedCompose/CSP3/runtime-role/DBoutage-recoveryPASS. Первоначальный CI run39431062296 failed, не засчитанPASS. libx11CVE-2026-88806 pin1.8.14-r0 official apk installPASS, общий runtime patch; release tiffpin синхронизирован source. Повтор remoteCI pending.

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

### SSO-SEC-0002 / #16 — 2026-10-20T16:07:24.3035665+03:00
На main7555f47 refresh-gap подтверждён кодом; accessJWT до exp — согласованное поведение. Изолированная PG16/Python3.12.14: tests/integration/test_self_revoke_grants_pg.py6PASS (logout API/OIDC, one/others, ownership, offlineJWT, оба реальных lock orders refresh/revoke); test_security_revision_pg.py + test_oidc_pg.py10PASS. Ruff/format/mypy64 и secret/diff проверяются перед commit. Production/браузер/нагрузка не запускались. Политика отзывает все grants, сохраняемые browser sessions могут начать новый SSO-flow.

CI image follow-up 2026-10-20T16:41:50.7021040+03:00: inherited libx11CVE-2026-88806 pin1.8.14-r0; source/release manifests согласованы (tiff4.7.2-r0 тоже). Officialnginx apk install/source buildPASS; прежний image scanFAILED, повтор CI pending. Функциональные результаты этой ветки выше; zero-CVE до scan не объявляется.
### SSO-SEC-0001 / #15 — 2026-10-20T16:03:30.6105628+03:00
main7555f47: общий oauth-client bucket подтверждён кодом. Изолированная PostgreSQL16, fresh schema0013 + guard; Python3.12.14. Новый tests/integration/test_oauth_source_quota_pg.py:1PASS; существующие test_oidc_pg.py + test_distributed_rate_limiting_pg.py:10PASS. Ruff и mypy64PASS. Первый новый тест FAILED из-за async lazy-load fixture, исправлен явной загрузкой; повтор1PASS. Первоначальная .venv не содержала sentry_sdk — тесты не собраны, использована .venv-sentry. Без production/внешней почты/нагрузки; NAT и distributed flood не устранены.

CI image follow-up 2026-10-20T16:41:47.0933221+03:00: inherited libx11CVE-2026-88806 pin1.8.14-r0; source/release manifests согласованы (tiff4.7.2-r0 тоже). Officialnginx apk install/source buildPASS; прежний image scanFAILED, повтор CI pending. Функциональные результаты этой ветки выше; zero-CVE до scan не объявляется.

### SSO-SEC-0003 / #17 — 2026-10-20T16:10:59.2619568+03:00
main7555f47:409/202 и пропуск password hash подтверждены кодом. Изолированная PG16/Python3.12.14: tests/test_registration.py + tests/integration/test_registration_pg.py + test_registration_consent_guard_pg.py20PASS; усиленный collision regression1PASS (четыре реальные Argon2id операции, одинаковая202-схема, username/email/case, отсутствие mail/duplicates/pending, confirm-denied, neutral resend). Unit mocks не выдаются за интеграцию. Ruff/format/mypy64PASS; secret/diff перед commit. Исходный REG-06/ПР-15 контракт409 заменён по SSO-SEC-0003 с сохранением отрицательных assertions. Точное выравнивание SMTP/DB timing, production/browser/load не проверялись и не обещаются.

CI image follow-up 2026-10-20T16:41:53.9386077+03:00: inherited libx11CVE-2026-88806 pin1.8.14-r0; source/release manifests согласованы (tiff4.7.2-r0 тоже). Officialnginx apk install/source buildPASS; прежний image scanFAILED, повтор CI pending. Функциональные результаты этой ветки выше; zero-CVE до scan не объявляется.

### SSO-SEC-0003 окончательный uniform-path retest — 2026-10-20T16:56:04.6698984+03:00
Этот результат заменяет ранний response-only UUID/no-mail вариант выше: повторныеID/sendcap/providerfailure могли различать его пути. Финальный start не проверяет User: все identities проходят одинаковые Argon2/pending/mail операции, collision только после mailboxproof вconfirm.26PASS: test_registration_uniform_path_pg.py(2), test_registration.py, integration/test_registration_pg.py, test_registration_consent_guard_pg.py, test_resend_email_pg.py. Проверены stable repeatIDs, обе последовательности202×3→429 (MAX_SENDS3 не менялся), одинаковые503transport failures, реальные Argon2, duplicate refusal после validproof и неизменность existingUser/password. Первый test assumption5 ошибочен: исправлен до actual3, кодлимит неизменён. Mypy64/Ruff/format/secret0new/diffPASS. Source/releaseTrivy0PASS ранее; finalCI этого follow-up выполняется после push. Точное wallclock constanttime не обещано, preproof Userbranch удалён.

## Итог шести security issues — 2026-10-20T17:02:01.9691227+03:00
Все6подтверждены и исправлены отдельными PR вmain; каждый issue имеет доказательные комментарии. Финальные функциональные SHA проверены обязательным GitHub CI (SUCCESS); SESexternal job штатно skipped, не считается live-доставкой.

| Issue / ID | PR | Локальный targeted результат | Проверенный функциональный SHA / CI |
| --- | --- | --- | --- |
| #15 / SSO-SEC-0001 | [21](https://github.com/alxprgstech/sso/pull/21) | PG1+10, source/operation quota | 370e466 / [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39432649902) |
| #16 / SSO-SEC-0002 | [22](https://github.com/alxprgstech/sso/pull/22) | PG6+10, both refresh/revoke lock orders | 852ce9b / [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39432656119) |
| #17 / SSO-SEC-0003 | [23](https://github.com/alxprgstech/sso/pull/23) | final26, uniform pending/mail path | d951639 / [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39434748425) |
| #18 / SSO-SEC-0004 | [24](https://github.com/alxprgstech/sso/pull/24) | final20, counted bounded batches | 28af0c7 / [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39432674860) |
| #19 / SSO-SEC-0005 | [25](https://github.com/alxprgstech/sso/pull/25) | final46, frontend40, migration/Compose/CSP3 | e1e1092 / [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39432532318) |
| #20 / SSO-SEC-0006 | [26](https://github.com/alxprgstech/sso/pull/26) | final23 + scheduling6, both vectors | e451632 / [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39433445951) |

Обязательные backend/default+enabled, E2E, security/dependency/secret, SDKcleaninstall, frontend/windows/version/CD и image/runtime jobs прошли на указанных SHA. Source/release localTrivy0HIGH/CRITICAL; initialimage/schema/testfixture failures исправлены и не засчитаныPASS. Этот итоговый commit меняет только документацию; его обычный CI проверяется отдельно, функциональные результаты выше относятся к точным указанным SHA.

Не выполнялись production, реальные рассылки/live Gmail rendering/sender registration, arbitrary/distributed load. JWT у автономногоRP до300с; NAT и per-worker audit budgets/crash-loss последнего anonymous окна описаны в соответствующих ADR.0014 требует restart legacy pending, Gmail shortcut — browser ViewAction. Функциональных PR-зависимостей нет; при последовательном merge сохранить все append-only записи и совместить uniform start с browser binding. PR не merged, issues вручную не закрыты.

### SSO-SEC-0004 / #18 — 2026-10-20T16:17:10.7190217+03:00
main7555f47 per-request action_denied INSERT подтверждён кодом. PG16/Python3.12.14: окончательный набор tests/test_denied_audit_buffer.py + tests/integration/test_anonymous_audit_budget_pg.py + tests/integration/test_reauthentication_pg.py + tests/test_security_context_redaction.py20PASS.20anonymous401→0rows before flush/1row count20 после; actor-specific audit, cardinality900events→≤259keys,401/403/429, saturation, rollback/concurrentflush failure recovery. Ruff/format/mypy65PASS, secret self-test0new. Два sandbox unit запуска прерваны из-за Windows asyncio socketpair, вне sandbox3PASS, затем final20PASS. Retention90дней сохранён. Нет sustainedload/disk exhaustion/production проверки; crash-loss последнего anonymous окна и per-worker budget описаны ADR0025.

CI image follow-up 2026-10-20T16:41:57.4338874+03:00: inherited libx11CVE-2026-88806 pin1.8.14-r0; source/release manifests согласованы (tiff4.7.2-r0 тоже). Officialnginx apk install/source buildPASS; прежний image scanFAILED, повтор CI pending. Функциональные результаты этой ветки выше; zero-CVE до scan не объявляется.

### SSO-SEC-0005 / #19 — 2026-10-20T16:30:27.5799474+03:00
Main7555f47 pending overwrite подтверждён кодом. PG16/Python3.12.14 миграция0013→0014PASS; итог46PASS: tests/integration/test_registration_flow_binding_pg.py(5), test_registration_browser_cookie.py(2), test_registration.py, integration/test_registration_pg.py, test_gmail_action_binding_pg.py, test_registration_consent_guard_pg.py, test_privacy_pg.py, tests/test_verification_email.py, test_documented_api_contract.py. Original/reverse order ×code/link, copied mailbox proof alone rejected, stale browser/resend/foreignOrigin/legacy rejected, recovery restart creates victim credentials/ordinary role, replay rejected; Gmail real RSA fixture+MockTransport (не liveGoogle), action secret и browser mandatory, concurrent single-use сохранены. Cookie HttpOnly/host-only/Secure/__Host HTTPS подтверждены unit. Первые cookie fixtures FAILED(path/Host), исправлены, final46PASS. Frontend lint/typecheck/typecheck:tests/components40/buildPASS; Ruff/format/mypy65, secret self-test126/0new/diffPASS. Первые2synthetic password literals scan отклонил; заменены генерацией, baseline не изменён. Live Gmail rendering/sender registration, publicHTTPS/browserE2E/production/load не проверены. Gmail shortcut теперь ViewAction, ADR0026; legacy pending требует restart.

SSO-SEC-0005 CI follow-up 2026-10-20T16:40:52.7021636+03:00: guard SCHEMA_REVISION синхронизирован0014 (обязательные privilege/schema проверки сохранены). Migration-role+DBguard/metadata22PASS/1envTempACLerror; metadata8PASS с собственнойtemp. Backend/frontend images buildsPASS; ownedCompose/CSP3/runtime-role/DBoutage-recoveryPASS. Первоначальный CI run39431062296 failed, не засчитанPASS. libx11CVE-2026-88806 pin1.8.14-r0 official apk installPASS, общий runtime patch; release tiffpin синхронизирован source. Повтор remoteCI pending.

### SSO-SEC-0006 / #20 — 2026-10-20T16:35:55.3927006+03:00
PG16/Python3.12.14 final23PASS: tests/integration/test_login_source_budget_pg.py, tests/test_password_work_budget.py, tests/integration/test_security_revision_pg.py, test_distributed_rate_limiting_pg.py, tests/test_security_and_negative_scenarios.py. Original lockout/aliases/spoofedXFF refusal + correct owner other source200;8realArgon2burst→2×401/6×429 + legit200/no503; concurrentArgon2≤2. Cancellation keeps global/source reservations until actualworker exit; dummyhashparams/eventloop tests retained. Ruff/format/mypy64PASS; secret scan beforecommit. NAT/distributed flood/production/multi-replicaCPU load не проверены. Другие PR CI имеют image/schema blockers, журнал содержит точные сведения.

CI image follow-up 2026-10-20T16:42:02.1140334+03:00: inherited libx11CVE-2026-88806 pin1.8.14-r0; source/release manifests согласованы (tiff4.7.2-r0 тоже). Officialnginx apk install/source buildPASS; прежний image scanFAILED, повтор CI pending. Функциональные результаты этой ветки выше; zero-CVE до scan не объявляется.

SEC-ISSUES-20261020 final publication checkpoint 2026-10-20T16:46:52.2264279+03:00:6PR21–26,6issue comments, source/releaseTrivy0HIGH/CRITICALPASS. PR25 exacte1e1092 GitHubCI39432532318SUCCESS (backend/default+enabled, E2E, image/Compose,SDK/security/frontend/windows/version/CD); SESexternal skipped штатно, доставки не подтверждает. PR26 source scheduling6PASS после дополнительной синхронизации реальных429; исходные23PASS остаются, рабочая защита не менялась. Остальные finalCI результаты фиксируются в GitHub PR/issue comments на точных SHA; локальный PASS не заменяет их.

## SEC-MERGE-20261020 — совместная проверка
2026-10-20T20:42:24.7276264+03:00; Windows/Python3.12.14, dedicated fresh PostgreSQL16 container, schema0014 + safety marker. PR22 combined17PASS32.58s; PR23combined17PASS51.13s; PR24audit20PASS14.35s; PR25registration/browserproof32PASS31.34s, включая новый combined resend test. PR26combined35PASS/1FAIL39.99s (worker importapp отсутствовал в PYTHONPATH); повтор independent-worker с backend+root и testDSN1PASS9.80s. Итого36совместных tests прошли. Ruff/format240/mypy75PASS, secrets126candidates0newPASS. Новая интеграция не заменяет live SES/Gmail или load benchmark. CI на обновлённых ветках проверяется перед merge; точные remote результаты в GitHub и worklog.

PR26CI39468423241:701PASS/1FAIL,14subtests; cancellationtest имел преждевременный empty assertion после asyncio cancellation. Исправлена синхронизация реального worker join в unit test, runtime неизменён. Targetedpasswordbudget/PGburst6PASS5.82s; обязательныйCI новогоSHA ожидается.

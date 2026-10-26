# Приёмка ALXPRGS SSO

## DEPLOY-EC2-01 — локальная проверка 25.10.2026

Ветка `new/ec2-deployment`, рабочее дерево; это не опубликованный release и не remote CI.
Установку на EC2 владелец выполняет по [инструкции](ec2-deployment.md) с сопровождением Codex.
Общая AWS-приёмка **не закрыта**.

| Проверка | Фактический результат |
| --- | --- |
| `pytest tests/test_ec2_deployment.py tests/test_ci_security_policy.py tests/test_privacy.py --basetemp artifacts/ec2-pytest-final -q` | 43 passed, 1.42s; unit/contract, команды деплоя в unit явно моделируются |
| `pytest tests/test_ci_email_credentials.py --basetemp artifacts/ec2-ci-email-04 -q` | 9 passed, 4.41s; разрешённый запуск с работающим Git Bash |
| Ruff check и format пяти новых Python-файлов, lint изменённого scanner | PASS |
| `docker build -f deploy/ec2/check.Dockerfile -t sso-ec2-check:local .` и `docker run --rm --network none sso-ec2-check:local` | PASS на Ubuntu26.04: настоящий nginx/TLS с доверенным синтетическим сертификатом, ACME path, maintenance503, overwrite spoofed headers, safe logs, Bash syntax, OpenSSL3072/configure/idempotency/permissions/default-off, независимые процессы flock |
| `build_ec2_bundle.py` из отдельного чистого локального snapshot `06bef2245976d87caa32127b30cfa616e72e2dd1` | Backend/frontend builds, exact source identities, PostgreSQL pinned source → image ID, checksums и transport PASS; это локальный snapshot текущего кандидата, не SHA удалённой ветки |
| `python -m scripts.check_ec2_runtime --bundle artifacts/ec2-candidate-02.tar.gz --sha 06bef2245976d87caa32127b30cfa616e72e2dd1` | PASS: импорт архива, production Compose с отдельными fixture project/subnet/port, настоящая PostgreSQL и head migration, production readiness/role guard, штатный backup/checksum wrapper, restore в отдельную БД со свежим journal, сохранение synthetic marker после повторной миграции/старта |
| Cleanup PostgreSQL fixture `sso-ec2-check-df69838021` | Labels проверены перед Compose down; последующая проверка контейнеров и volume этого имени — пусто. Другие проекты не затронуты |
| `check_secret_scan.py --self-test` | Synthetic control rejected;126 candidates/0new; baseline неизменён |
| UTF-8 Markdown и локальные ссылки | 71 Markdown/323 targets/0missing с URL decoding; повтор после финальных записей отдельно |

Ошибки проверок сохранены в worklog: исходная `.venv` не содержала sentry_sdk;
sandbox TEMP не создавал tmpdirs; Git Bash в sandbox получил MSYS0xC0000022. Исправлено
окружение/выбран отдельный basetemp, assertions и защита не ослаблялись. Первый test-only
multiprocessing worker был несовместим с Python3.14 forkserver; заменён отдельным subprocess,
реальный flock сохранён. Первый link checker не декодировал `%20`; документ не был сломан.

Реальные EC2/systemd bootstrap, публичные DNS/TLS, выпуск/renewal Let’s Encrypt, доставка Resend,
первый admin/open registration, push из GitHub и совместная пользовательская приёмка пока
**не выполнены**. Не выполнялись публикация, настройка AWS/DNS/SSH/Secrets, remote CI, нагрузка
или новый полный dependency/image audit. Для локального nginx проверен синтетический backend;
это не браузерная production-проверка SSO. Код сервера/SDK/frontend и их существующие security
tests не изменялись; общий приёмочный набор приложения не подменяется этими результатами.

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
| CI/release/security | Exact SHA/tag, обязательные gates/scans, hashes/SBOM/provenance, manifest/checksums; EC2 CD разрешён 25.10.2026; live-приёмка отдельно |
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

## SEC-MERGE-20261020 — завершение (2026-10-20T20:54:27.8702087+03:00)

Все шесть PR merged в main, issues #15–20 закрылись автоматически. PR21 уже был merged при начале этой задачи; PR22–26 слиты последовательно после SUCCESS обязательного CI обновлённых heads. Временная цепочка веток разрешена в порядке merge; итоговые PR не оставляют зависимостей вне main.

| Issue | PR | Проверенный head SHA | Merge SHA | CI |
| --- | --- | --- | --- | --- |
| #15 | [#21](https://github.com/alxprgstech/sso/pull/21) | `370e4662249b303c3772f873ef0009812a07bd24` | `8af4008befe36bb56d2a8012ea1149d61d42ee29` | [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39432649902) |
| #16 | [#22](https://github.com/alxprgstech/sso/pull/22) | `782a646a4db512641e9c15174e351966ec8559cf` | `594031605e0591be52ba35dabeef2eb52cfaf1a5` | [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39467439456) |
| #17 | [#23](https://github.com/alxprgstech/sso/pull/23) | `0e3f1b5918b3619ed81a9b48e58c430800a28fa6` | `ced7def59bb00791df99961c24ab7de744867919` | [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39467664603) |
| #18 | [#24](https://github.com/alxprgstech/sso/pull/24) | `40c23f3d8b333568306b7e99af66c5f550e77903` | `bd54a4d31874f714c507cb48fdb7a34ba7ea34b3` | [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39467795407) |
| #19 | [#25](https://github.com/alxprgstech/sso/pull/25) | `84dbe7bec736893be23de29cfd4c24a0e91ef529` | `88a15562c7aca7ede83547c93fcfdb7e10b19355` | [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39468045365) |
| #20 | [#26](https://github.com/alxprgstech/sso/pull/26) | `1ca240b2245dccb77500df01ed940207e310f708` | `941d3f1ccc2b2fee6de5b58e8fb697755ba436ae` | [SUCCESS](https://github.com/alxprgstech/sso/actions/runs/39469344990) |


Ручной code conflict: resend сохраняет нейтральный202 неизвестной/устаревшей заявки и browser proof существующей заявки до MAX_SENDS. Добавлен совместный regression. Все разделы документов обеих сторон восстановлены; история worklog сохранена. После CI failure исправлена синхронизация cancellation unit-test (join реального pool2), runtime admission не менялся. Финальный обязательный CI указан выше; локальные наборы17/17/20/32 и36 combined, дополнительный cancellation/burst6PASS описаны выше (это пересекающиеся наборы, не сумма уникальных tests).

Live SES job был условно пропущен по существующей политике без AWS credentials; это не проверка доставки. Production/deploy, live Gmail и распределённая нагрузка не выполнялись. Завершающий documentation-only checkpoint проверяется локально на UTF-8/ссылки/diff; SUCCESS PR CI не выдаётся за CI его будущего commit SHA.

DEPLOY-EC2-01 версии стенда: testPython3.12.14, pytest9.1.1, Ruff0.16.8, Docker29.8.0; isolated Ubuntu26.04 packages Python3.14/nginx1.28.3. Результаты finalrootoperator и bundle snapshot читаются совместно, без заявления remoteCI/productionPASS.

DEPLOY-EC2-01 final-audit correction: после2855f77 найден и исправлен backup filename collision cleanup. Четыре содержательных unit regression (без настоящего pg_dump) + прежние43:47PASS2.05s. Проверены сохранность existing dump/journal и очистка только собственного partialfile. Dump/journal и operator state теперь fsync. Для нового backup-кода требуется отдельный повтор actualPG transport; прежний snapshotрезультат выше его не подменяет.

Окончательный код DEPLOY-EC2-01: c358413253189c5880ceea4f5c5ca2f195f9a182. Из чистого checkout этого SHA штатный builder создал artifacts/ec2-final.tar.gz; тот же bundle прошёл scripts.check_ec2_runtime на настоящей PostgreSQL с новым collision-safe/fsync backup, контрольной суммой и restore в отдельную БД. Fixtureproject sso-ec2-check-c0035ecb6f удалён labelcheckedComposeDown. Повтор Ubuntu nginx/TLS/configure/fsync/flockPASS. Эти результаты заменяют необходимость повторной проверки нового backupfix, отмеченную выше; AWS/live delivery/ACME/remoteCI по-прежнему не проверены. Suite47PASS2.05s, CIemailpolicy9PASS4.41s; Ruff/format/secretselftestPASS.

DEPLOY-EC2-01 manual-CD 2026-10-25T18:03:29.4349911+03:00: pytest tests/test_ec2_deployment.py tests/test_ci_security_policy.py --basetemp artifacts/manual-cd-tests -q →47PASS2.41s; Ruff/format/diffcheckPASS. Eventmatrix допускает ручной main при failedCI, сохраняет автоматические negativecases и обязательный transport test. Это локальная проверка workflow-контракта, не выполненный GitHubdispatch/EC2деплой; существующие CIошибки остаются failed.

DEPLOY-EC2-01 runner-workspace 2026-10-25T18:14:46.1568259+03:00: пользовательский [job121205110397](https://github.com/alxprgstech/sso/actions/runs/40205394490/job/121205110397) упал до Docker/SSH на отсутствующем artifacts parent. Исправлен helper подготовки. pytest tests/test_ec2_runtime_workspace.py tests/test_ec2_deployment.py tests/test_backup_collision.py tests/test_ci_security_policy.py --basetemp artifacts/ec2-workspace-regression -q →53PASS5.95s с реальными WindowsACL. Отдельный Linux process с networknone подтвердил mode0700, сохранение существующих файлов/reuse refusal и symlink refusal. Ruff/format/diffcheckPASS. Полный remoteCD с исправлением ещё не выполнен; защита transport не отключалась.

## EXT-STEPUP-01 — локальная приёмка (2026-10-26)

Ветка `new/external-step-up-authentication`, база `93c0fad7f92fd2ba8a4b860986fe52e8c3985234`. Продукт/SDK 0.3.0. Это локальные и CI-подобные проверки, не production-приёмка; feature/per-client flags не включались на production, данные/БД/сети production не менялись.

Фактические команды и результаты (Windows, Python3.13.0, PostgreSQL16.10-alpine в отдельном контейнере, `TEST_DATABASE_URL` на 127.0.0.1:5433):
- `pytest tests/test_step_up_policy.py` → 10 passed.
- `pytest tests/integration/test_external_step_up_pg.py` → 9 passed (password, Passkey strict, password+TOTP, TOTP replay, cross-client/PKCE/redirect, subject/session/expiry/revision/revocation, feature flag, admin policy, redirect removal, concurrent redemption).
- `pytest tests/integration/test_reauthentication_pg.py tests/integration/test_oidc_pg.py tests/integration/test_migration_drift_pg.py` → 13 passed.
- `pytest tests/integration/test_passkey_pg.py tests/integration/test_features_pg.py tests/integration/test_oidc_contract_remediation_pg.py` → 21 passed.
- `pytest tests/integration/test_external_step_up_pg.py tests/integration/test_admin_status_audit_pg.py tests/integration/test_reauthentication_pg.py` → 15 passed (до добавления redirect-removal; затем новый набор 19 passed).
- Полный `pytest tests/` с корректными `DATABASE_URL`/`TEST_DATABASE_URL` и `--basetemp artifacts/pytest-stepup` → 777 passed, 5 environment-only failed (psql/pg_dump/hatchling metadata/OpenSSL SMTP cert), 5 deselected; функциональных падений feature нет. Без DATABASE_URL часть subprocess-тестов ошибалась на host `db`, а без basetemp — на Windows ACL Temp; это ограничения локального окружения, не PASS.
- `pytest packages/python-sdk/tests/test_step_up_sdk.py` → 3 passed; собран wheel/sdist 0.3.0; в `.venv-stepup-sdk-test` установлен wheel, `pytest test_step_up_sdk.py test_sdk_isolated.py` → 6 passed, `alxprgs_sso.__version__ == 0.3.0`, backend `app` не импортирован. SHA-256 wheel `1EFADBF5...CFAB`, sdist `EB9B36AE...DA2`.
- `npm run typecheck`, `npm run typecheck:tests`, `npm run lint` (затронутые файлы), `npm run build` → PASS; `npm run test:unit` → 13 passed; `npm run test:components` → 42 passed; `npx playwright test e2e/step_up.spec.ts` → 1 passed (UI contract with mocked API; protocol covered PG).
- `ruff check backend/ tests/ packages/python-sdk/ scripts/ examples/` и `ruff format --check` → PASS; CI mypy command (`mypy --explicit-package-bases packages/python-sdk/alxprgs_sso backend/app --ignore-missing-imports`) → Success, 81 source files.
- `scripts/bump_version.py check` → 0.3.0; `docs/api-routes.json`/markdown contract → 1 passed.

Self-audit findings: (1) Passkey UI nested busy guard prevented submission — fixed; (2) redirect URI was not rechecked against current client registration at redemption after admin policy change — fixed and regression added; (3) TOTP integration test initially reused enrollment step — test corrected to next valid step without weakening replay protection; (4) reference RP execute GET/POST mismatch — example fixed. Security review remains self-review only; no independent reviewer/OIF/external load/SES production was available. No attack was run against production or third-party systems.

Final artifact checkpoint 2026-10-26T14:20:00+03:00: rebuilt from committed tree in `dist/sdk-stepup-final`: wheel `alxprgs_sso-0.3.0-py3-none-any.whl` SHA-256 `1482FC6AFE7CFF36E80BFB0B1EC23037679EB520035CE3B1C47E9EFAD7B7AE44`; sdist `alxprgs_sso-0.3.0.tar.gz` SHA-256 `388F654D7EB5D6E57F80D58B7501367DD06A54F4D5B173C07DA809B83020ABFA`. Reinstalled wheel in `.venv-stepup-sdk-test`; 6 SDK tests passed, version0.3.0, no backend app import. Artifacts are ignored local build output, not published.

SDK/backend integration checkpoint 2026-10-26T14:22:35+03:00: добавлен и выполнен `test_installed_sdk_creates_and_redeems_real_step_up` — публичный `SSOClient` через ASGI transport к реальному FastAPI/PostgreSQL создаёт challenge, браузер подтверждает password, SDK погашает code и проверяет `StepUpProof` по реальному JWKS; повторное погашение даёт `StepUpReplayError`. Итог нового набора: policy10 + PG11 = 21 PASS.

## MFA-DEFAULT-ADMIN-01 — локальная приёмка 26.10.2026

Ветка `new/default-on-mfa-admin-policy` от baseline `b5bb8b4` (EXT-STEPUP-01 merge). Production, DNS, CD, существующий `runtime.env` и секреты не изменялись.

| Проверка | Результат |
| --- | --- |
| `pytest tests/ ... --basetemp artifacts/pytest-mfa-final` (PostgreSQL16, TEST_DATABASE_URL/DATABASE_URL/SYNC=127.0.0.1:5433) | `790 passed, 5 failed, 5 deselected, 18 subtests`; 5 failed — environment-only baseline: отсутствуют `psql` (migration roles), `hatchling` metadata (build lock x2), `pg_dump`/`psql` (backup/restore), локальный OpenSSL CA trust (SMTP STARTTLS). Feature/protocol assertions не падали. |
| Новые PostgreSQL тесты | `test_admin_mfa_pg.py` 6 PASS; `test_mfa_assurance_pg.py` 2 PASS; `test_admin_recovery_pg.py` 1 PASS; `test_features_pg.py` 6 PASS. |
| Migration | `alembic upgrade head` 0015→0016 PASS; drift/metadata tests PASS; downgrade удаляет sessions/codes и отзывает refresh. |
| Frontend | `npm run typecheck` PASS; `typecheck:tests` PASS; `npm run lint` PASS; `npm run test:unit` 14 PASS; `npm run test:components` 45 PASS (новый AdminMfaPage 3); `npm run build` PASS. |
| E2E | `scripts/run_e2e_suite.py --suite passkey` (default-on/admin MFA): 9 PASS, включая реальный TOTP enrollment/login, Passkey, privacy и admin TOTP login. `--suite sso` (explicitly-disabled): 48 PASS, `.last-run.json` status passed; локально использованы SMTP capture и явные synthetic E2E credentials. |
| SDK | source tests 19 PASS; wheel/sdist built; установка wheel в `.venv-stepup-sdk-test` (no backend import), installed SDK tests 18 PASS; новый assurance-compat test PASS. Public API не менялся; wheel не опубликован. |
| Static/security | Ruff PASS для backend/deploy/scripts/tests; migration metadata PASS; API snapshot обновлён; секреты не выводились. |

Self-audit (не независимый аудит): проверены admin API без MFA/со старой сессией, role grant во время password-only сессии, фактор-фейк в теле, pending TOTP/Passkey, удаление последнего фактора, повтор recovery code, cross-user proof, OIDC amr/acr/refresh/UserInfo, session binding, default-on без env, explicit-disabled, конфликт `REQUIRE_ADMIN_MFA`/факторов, non-destructive EC2 update. Найденные в ходе работы проблемы исправлены (rate-limit fixture, migration downgrade fail-closed, admin recovery). Остаточные риски: legacy access JWT до exp, live production rollout/backup, внешний OIDC/SDK review, multi-replica/OIF, отсутствие независимого аудита.

Артефакты: wheel/sdist в `artifacts/sdk-mfa` (ignored build output, не опубликованы). Точные команды/логи — worklog и CI после push (push не выполнялся).

## CD-STAGES-01 — локальная проверка разделённого CD

2026-10-26T19:09:37+03:00, Codex. `.venv/Scripts/python.exe -m pytest tests/test_ec2_deployment.py -q --basetemp artifacts/pytest-cd-stages-02`: **41 passed**. Ruff check/format и `git diff --check`: PASS. Regression проверяет зависимости build → verify → deploy, единый immutable artifact, сохранение SHA/run number, gate автоматического/ручного запуска, отсутствие повторной сборки в verify/deploy, classic Docker store в build/verify. Это unit/policy-проверка; live GitHub повтор failed jobs, transport в новом workflow и production не выполнялись. Приёмка на GitHub остаётся открыта до интеграции.

## CD-PUBLIC-CHECK-01 — финальная внешняя readiness проверка

2026-10-26T19:14:23+03:00, Codex: `.venv/Scripts/python.exe -m pytest tests/test_ec2_deployment.py tests/test_public_readiness.py tests/test_backup_collision.py tests/test_ec2_runtime_workspace.py -q --basetemp artifacts/pytest-cd-public-final`: **60 passed**. Ruff check/format и diff check PASS. Unit negative cases: DNS, TLS certificate, timeout, HTTP503/302, wrong destination, HTML, wrong JSON/DB readiness; positive exact readiness. Workflow: public-check зависит от deploy/installed=true, без повторной установки. Live script с рабочей станции вне sandbox: **HTTP200/database connected**, TLS verification включена; sandbox DNS недоступен. Фактическое выполнение новых jobs на GitHub и selective rerun не проверено до интеграции.

## AUDIT-FULL-20261026 — локальная проверка комплексного аудита

2026-10-27T00:15:00+03:00, DeepSeek Harness. Ветка `audit/full-stack-security-ui-ci-20261026` от `a35550f223cbd38b303311ddb48842a54681c3b7`. Продукт 0.3.0; production/EC2/DNS/secrets/`runtime.env` не изменялись; merge/release/deploy не выполнялись. Отчёты: [summary](audit/2026-10-26-full-audit-summary.md), [findings](audit/2026-10-26-security-findings.md), [API](audit/2026-10-26-api-coverage.md), [frontend](audit/2026-10-26-frontend-qa.md), [CI](audit/2026-10-26-ci-remediation.md), [final](audit/2026-10-26-final-verification.md).

Обнаружено и исправлено 10 подтверждённых дефектов (AUD-2026-01…10): двойной пароль при смене режима регистрации, потеря 5-минутного session-read grant при reload, неотличимый replay TOTP (generic error + расход failed attempts), потеря `Retry-After` headers, reauth-челлендж до RBAC для admin API, падение второго конкурентного подтверждения, уязвимые Python/npm зависимости, 6 HIGH в frontend image, портативность SMTP TLS fixture. TOTP one-use политика не ослаблена.

| Проверка | Фактический результат |
| --- | --- |
| Backend pytest default-on (`pytest -v tests/`, PostgreSQL16.10, Windows/Python3.13.0) | 820 passed, 3 environment-only failed (psql/pg_dump ×2, SMTP CA до fixture-фикса; после фикса 5/5), 5 deselected; см. final-verification |
| Новые PostgreSQL регрессии | `test_totp_reauth_replay_pg.py` 4, `test_registration_mode_reauth_pg.py` 1, `test_admin_authorization_order_pg.py` 3, `test_totp_policy.py` (unit) PASS |
| Ruff check/format, mypy | PASS для изменённых файлов; полный CI-набор — ниже |
| Frontend | `npm ci`, audit 0, lint, typecheck, typecheck:tests, unit 14, components 51, build PASS; npm audit `--audit-level=high` 0 |
| Playwright default-off | sso 6 + multi_client/protocol/telemetry/privacy/appearance/step_up 44 = **50 passed** |
| Playwright enabled | passkey, totp, privacy, telemetry = **9 passed** |
| API inventory | 73 фактических = 73 документированных; snapshot contract PASS; anonymous/regular/admin матрица (73/37/37) без неожиданных 200 |
| Python deps | setuptools 84.1.0/filelock 4.2.1; `pip-audit --strict` 0; hashed/runtime/build locks согласованы |
| Container | frontend nginx 1.30.6-alpine + apk upgrade; Trivy 0.75.0 → 0 HIGH/CRITICAL; non-root/read-only/nginx -t PASS |
| SMTP TLS regression | 5 PASS после добавления KeyUsage/SKI/AKI в синтетические сертификаты |
| Secret scan | `scripts/check_secret_scan.py --self-test` — см. final-verification |

Ограничения: локальный Windows-стенд не содержит `psql`/`pg_dump` — соответствующие migration/backup тесты остаются environment-only и проверяются Linux CI; CodeScene live-gates, Firefox/WebKit, внешние SES/Resend/Sentry, публичный TLS/DNS и production load не проверялись. GitHub Actions для финального HEAD — после push; локальные PASS не заменяют remote CI.

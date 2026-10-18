# Повторная проверка исправлений безопасности

Задача: SEC-REMED-20261007, продолжение 18.10.2026. Ветка `new/security-remediation`, база `170175be06318645c0fd2ef222e2688edf31b37c`; проверяется рабочее дерево поверх базы. Исторический [аудит](../../SECURITY_AUDIT.md) сохранён отдельно и не является verdict исправленной версии. Решения: [ADR-0023](../adr/0023-security-remediation.md).

## Матрица исправлений

| Область | Реализация | Проверка |
| --- | --- | --- |
| SEC-01 / R1 | Независимый 256-bit Gmail action secret, SHA-256 в pending; ротация при resend; общий PG lock для code/link/action; bounded single-flight Google JWKS с проверкой TLS | Cross-mailbox, missing/legacy secret, replay, expiry/resend и конкурентное погашение; реальные подписи fixture и PostgreSQL, Google transport замокан |
| SEC-04 / R2 | Пятиминутный grant только для чтения сессий; одноразовые отдельные proofs для DELETE, привязка к session/revision/action/body | PostgreSQL scope/expiry/replay; frontend grant reuse/refresh; browser сценарий просмотра и отзыва |
| SEC-02 / R2 | Canonical base64url credential IDs и точечный indexed lookup вместо full scan; миграция отказывает при коллизии без потери credentials | Invalid IDs до обращения к БД, exact lookup, PostgreSQL collision/preservation, virtual WebAuthn с обязательным UV |
| SEC-03 / R3 | Hash companions full/runtime/build; require-hashes в CI/Docker; полный offline secret scan с контрольным секретом; SBOM и unsigned local provenance | Чистая установка hashes, отказ pip от изменённого wheel; bundle verification и негативные metadata tests |
| R3 transport | SDK HTTPS/TLS strict default, explicit loopback local; cookie Origin/Referer и безопасные exact redirect URIs | Installed-wheel transport policy, отрицательные URL/Origin/redirect tests и два настоящих RP |
| R4 | Mutation/audit/outbox в одной транзакции; прежний verified recipient, SKIP LOCKED workers, 24h/5 attempts, повтор TTL перед доставкой; owner-only backup destination | Rollback, retry, expiry, concurrency, настоящий backup/restore и отказ при неправильном TOTP key, private ACL |

## Проверки продолжения

Среда: Windows, Python 3.12.14; изолированная PostgreSQL 16 с новым tmpfs и safety marker; Linux images backend Python 3.13.16. Сырые evidence находятся в ignored `artifacts/security-remediation-final/` и не публикуются.

Подтверждены: Ruff/format и mypy (73 файла); hash companions full/runtime/build; чистая установка закреплённых зависимостей; SDK wheel/sdist и installed-wheel tests (29 PASS); secrets self-test (127 кандидатов, 0 новых (финальный повтор)); pip-audit и npm audit (0 известных уязвимостей); frontend lint/types/test-types, 13 unit и 40 component, build; оба Linux image build; изолированный Compose runtime/non-root/read-only/capabilities/resources/runtime DB role/CSP (3 browser tests), DB outage/recovery и owned cleanup.

Полный pytest на PostgreSQL: 687 PASS, 18 subtests PASS, 5 внешних email cases deselected (812.74s). После подготовки среды как в CI independent distributed-quota worker и реальный backup/restore/TOTP прошли. Enabled CI suite: 20 PASS (82.87s). Дополнительно OIDC PostgreSQL + Origin boundary: 54 PASS (unit boundary 36 PASS), включая 7 новых route/method/header cases, добавленных после старта полного прогона. Финальный release dry-run и Trivy обоих исправленных images PASS. Финальный Compose с последней Origin-правкой, CSP3 и DB outage/recovery PASS; owned cleanup выполнен. Browser retest: default-off48PASS, enabled9PASS (реальные virtual WebAuthn UV, TOTP/recovery replay, два RP). Повтор финальных Compose images: PASS, CSP3PASS, outage/recovery PASS, owned cleanup выполнен. Локальный remediation retest завершён; production-приёмка отдельно.

## Исправления по результатам повторной проверки

- Установленный SDK старой локальной среды заменён актуальным wheel; чистая установка проверена отдельно. `node_modules` восстановлен через `npm ci`; release builder и browser выполняются последовательно.
- `localhost` для новой IPv4-only тестовой PostgreSQL вызывал задержку 5.031s на подключение; `127.0.0.1` — 0.015s. Полный тестовый DSN использует точный IPv4 loopback, guards не изменены. Прерванные диагностические прогоны не являются успешными тестами.
- Актуальная Trivy DB выявила в frontend image CVE-2026-77214 (`libexpat`) и CVE-2026-4775 (`tiff`). Только runtime pins обновлены до `2.9.0-r0` и `4.7.2-r0` из официального Alpine v3.24 repository (`apk policy`); [каталог libexpat](https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/libexpat), [каталог tiff](https://pkgs.alpinelinux.org/package/v3.24/main/x86_64/tiff). ABI остаются `libexpat.so.1`/`libtiff.so.6`; лицензии MIT/libtiff. Повтор Trivy High/Critical — 0, Compose/CSP — PASS.
- Генератор Windows keys сохранял сторонние explicit ACE после удаления inheritance. Теперь все сторонние ACE удаляются до записи ключей; чтение DACL генератора и backup validator использует .NET API без зависимости от inherited `PSModulePath`. Regression добавляет explicit Everyone ACE, проверяет owner-only directory/files и отказ backup от широкого ACL: 53 PASS. Системная конфигурация ключей не менялась. Новые package transport tests и Windows ACL tests включены в обязательные CI jobs.
- Дополнительная Origin-политика первоначально блокировала обычную OIDC front-channel навигацию с Referer доверяющего клиента. Только GET `/oauth/authorize` и GET `/oauth/logout` допускают Referer-only переход: первый сохраняет client/redirect/PKCE checks, второй — signed hint binding либо confirmation+CSRF. Явный чужой Origin, все API и mutations сохраняют отказ. Покрыты route/method/header positive/negative regressions; API allowlist не расширена.
- Первый полный browser default-off дал 47 PASS/1 FAIL: смена пароля уже завершалась на сервере, но неявное обновление списка сессий требовало нового read grant и удерживало password dialog. После успешной смены теперь очищается локальный список; загрузка и отдельное подтверждение остаются при явном открытии «Сессий». Component regression с pending `getSessions` подтверждает закрытие формы без неявного чтения. Frontend static/unit13/components40/build повторно PASS; E2E assertion, таймауты и серверная защита сохранены.
- Следующий быстрый default-off browser дал 47 PASS/1 FAIL на штатном login quota: два RP разделяли `compose_admin` с admin UI cases. Выделен `e2e_sso_user` с ролью `user` в синтетическом seed и CI; браузер проверяет обычную роль в ответе RP. Квоты не сбрасываются и не ослабляются; реальная регистрация с email по-прежнему проверяется отдельным UI case.

- В enabled browser helper согласия с документами прерывал отправку последующим page.goto. Теперь переход разрешён после исчезновения обязательной формы и появления ссылки кабинета; проверки согласия сохранены. Повтор enabled9PASS. Финальные frontend lint/test-types и secret self-test PASS.

## Границы результата

Внешние SES/Gmail/Sentry, sender registration, public TLS/DNS/IAM, production secret storage, OIF certification, multi-replica load и review исторических credentials не проверяются этим локальным продолжением. Отдельная задача DOC-VERSION-LOCK-01 остаётся в плане. CD, реальные рассылки, публикация релиза и deployment не выполняются. Default-off TOTP/Passkey/Recovery, обязательное подтверждение email, PKCE/UV/CSRF/RBAC/одноразовость и guards тестовой БД сохраняются.

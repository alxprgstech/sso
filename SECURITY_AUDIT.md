# Security Audit

## Executive Summary

**Вердикт: NOT READY FOR PRODUCTION.** Обнаружен дефект авторизации подтверждения регистрации через Gmail action: доказательство источника Google используется вместо доказательства доступа к конкретному письму. Один локально подписанный JWT, прошедший настоящую проверку RSA с тестовым доверенным ключом, подтвердил две разные регистрации в настоящей PostgreSQL. Получение подходящего настоящего Google JWT и эксплуатация работающего публичного сервиса **не демонстрировались**. Это существенное ограничение доказательства, а не основание считать привязку безопасной.

Основные механизмы защиты реализованы содержательно: Authorization Code + PKCE S256, точные redirect URI, разделение ID/access tokens, атомарное погашение codes, refresh rotation с отзывом семьи при replay, Argon2id, серверный RBAC, action-bound повторная аутентификация, PostgreSQL rate limits, обязательное подтверждение почты при самостоятельной регистрации, default-off MFA и обязательный WebAuthn UV. Общего обхода RBAC, подписи JWT, SQL injection или удалённого исполнения команд не установлено.

Аудит выполнен 07.10.2026, исполнитель Codex, задача `SEC-AUDIT-20261007`, ветка `new/security-audit`. Исходная ревизия **170175be06318645c0fd2ef222e2688edf31b37c**, версия **0.2.0**. Production-код не исправлялся. Добавлен только audit test и актуализирован учёт работы. Исторические отчёты и успешные CI других ревизий не засчитывались как результаты этого аудита.

## Scope and Methodology

Рассмотрены backend/API/services/models/migrations, frontend и маршруты, независимый Python SDK, оба примера клиентов, настройки, Docker/Compose/Nginx, scripts, GitHub Actions CI/release, закомментированный CD, lock-файлы, тесты, документация, текущий Git и достижимая история. Включены public/authenticated/admin переходы, cookie и bearer границы, MFA/email/recovery, privacy lifecycle, concurrency, logging и внешние провайдеры.

Методы: ручной анализ потока данных от входа до изменения состояния; проверка защиты в dependencies и service layer; негативные unit/PG tests; локальные браузерные сценарии; собственное воспроизведение; offline secret scan; dependency audit; контекстная классификация Bandit; второй adversarial проход. Сканирование не заменяет ручной анализ и не доказывает отсутствие неизвестных уязвимостей.

Основной ориентир — [OWASP ASVS 5.0.0](https://github.com/OWASP/ASVS/tree/v5.0.0/5.0), номера требований проверены по официальному JSON версии 5.0.0. Использованы [OWASP Top 10:2025](https://top10.owasp.org/2025/), [OAuth Security BCP — RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html), [JWT BCP — RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html), [OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html), [WebAuthn](https://www.w3.org/TR/webauthn-3/) и официальная документация Google. Это оценка применимых требований, **не сертификат полного соответствия ASVS L2/L3**.

Стенд: Windows, Python 3.12.14, pytest 9.1.1, pip-audit 2.10.1, Bandit 1.8.6, detect-secrets 1.5.0; зависимости приложения из lock-файлов, FastAPI 0.141.1/Starlette 1.7.0. Отдельный Docker PostgreSQL 16 на loopback 5433, tmpfs, миграции до `0010` и штатный safety marker. Существующие контейнеры пользователя не использовались и не изменялись. Браузер — Chromium/Playwright из установленного проекта, локальные порты 8000/5173. Локальные сырые logs/XML, пакеты и captures находятся в игнорируемом `artifacts/security-audit/`; они могут содержать синтетические токены и не предназначены для публикации.

Внешние письма, production/DNS, настоящие пользовательские данные, Google action JWT, Sentry ingestion, AWS IAM/SES и публичный TLS не тестировались. Отсутствие этих проверок указано ниже; mock не назван проверкой live-провайдера. Массовый DoS и атаки на внешние сервисы не проводились.

## Architecture and Attack Surface

| Компонент / граница | Данные и входы | Проверенные механизмы / остаточная граница |
| --- | --- | --- |
| Browser → React → FastAPI | JSON, query, cookies, CSRF header, WebAuthn credentials | CORS allowlist, host-only cookies, server capabilities, explicit input models; browser не управляет feature flags |
| OP → RP1/RP2 → SDK | OAuth query, codes, state, nonce, access/ID/refresh tokens, JWKS | Точная URI, S256, token profiles; RP доверяет только своему issuer/audience; cookie RP отделена от OP |
| Public authentication | Регистрация, парольный/Passkey вход, verification code/link/Gmail action | Persistent quotas, атомарные secrets; **разрыв Gmail action authorization — SEC-01** |
| User/admin → sensitive mutations | Пароль, MFA, email, client secrets, roles, privacy deletion | RBAC, reauthentication proof bound к actor/session/revision/action/body, last-admin invariant |
| FastAPI → PostgreSQL | Accounts, credentials, sessions, codes, refresh families, audit, quotas | Параметризованный SQL, constraints, transactions, row/advisory locks; shared state между replicas |
| Backend → providers | SMTP/SES/Resend, Google certs, Sentry | Фиксированные/операторские адреса; bearer не отправляется на request-derived URL; live policy/доставка не проверены |
| Operator/CI → deployment | Secrets, keys, backups, builds, artifact manifest | Privileged trusted path; отдельные риски инфраструктуры, IAM, ACL и supply chain |

Чувствительные активы: парольные hashes; TOTP secrets; verification/recovery/refresh secrets; signing/session keys; MFA и security revision; роли; client secrets; mailbox ownership; privacy consents; backups и audit. В коде не обнаружены пользовательские file uploads, LDAP/XML parser, template evaluation, arbitrary callback webhooks, WebSocket/WebRTC или message queue consumers. Их отсутствие относится к обозримой ревизии, а не будущим функциям.

## Threat Model

Рассмотрены анонимный сетевой атакующий, обычный пользователь, обладатель украденного bearer/session, контролируемый сайт и RP, злонамеренные входные данные, конкурентные запросы и ошибочная конфигурация оператором. Администратор может регистрировать клиентов, но не считается доверенным источником любых данных для browser rendering. Контроль build runner, signing key или БД способен разрушить основные trust assumptions; ASVS не устраняет такую компрометацию автоматически.

Наиболее опасный подтверждённый переход — перенос service-origin Gmail JWT между pending registrations. Другие приоритетные сценарии: code/refresh replay, ID token как access token, stale roles после отзыва, IDOR в admin/session/MFA, использование proof для другой операции, bypass UV, подделка forwarded IP, mail brute force, смешение RP и OP logout, утечки через telemetry/query/backups. Проверки по этим направлениям отражены ниже.

## Findings Summary

| ID | Severity | Confidence | Finding | Component | Status |
| --- | --- | --- | --- | --- | --- |
| SEC-01 | High | High для дефекта; Medium для live exploitability | Gmail JWT не привязан к конкретной регистрации/почтовому секрету | registration | Подтверждено локально; исправление не выполнялось; production blocker |
| SEC-02 | Low | High | Unknown Passkey ID вызывает чтение всей таблицы credentials | enabled Passkey | Слабость доказана кодом; исчерпание ресурсов не демонстрировалось |
| SEC-03 | Low | High | Python зависимости закреплены версиями без обязательных artifact hashes | build/supply chain | Hardening; компрометация поставки не обнаружена |
| SEC-04 | Low | High | Просмотр/отзыв сессий не требует свежего фактора | session management | ASVS hardening; stolen-session сценарий выведен из кода |

Категории: подтверждённый дефект — SEC-01; высокоуверенная слабость — SEC-02; defense-in-depth — SEC-04 и рекомендации разделов; supply chain — SEC-03. Подтверждённых утечек действующих секретов или известных уязвимостей зависимостей сканеры не сообщили. Test coverage gaps и environment-dependent risks перечислены отдельно и не представлены дополнительными уязвимостями. Critical/Medium находки не добавлялись для полноты таблицы.

## Detailed Findings

### SEC-01 — Gmail origin authentication подменяет authorization конкретного действия

- **Severity / Confidence:** High / High для отсутствующей привязки, Medium для практической эксплуатации с настоящим Google токеном.
- **Компонент и места:** `backend/app/api/auth.py:145`, `:200–208`; `backend/app/services/registration_service.py:48–100`, `:295–307`; `docs/audit/test_security_audit_20261007.py`, тест `test_gmail_bearer_reused_for_unrelated_mailboxes`.
- **Trust boundary / root cause:** API возвращает инициатору pending `challenge_id`. `verify_gmail_bearer` проверяет Google signature/issuer/audience/azp/time, но это доказательство источника и адресата сервиса. `confirm(..., action_id=challenge_id)` выбирает pending по открытому идентификатору, без code/link secret или отдельного limited-use action secret. У JWT не проверяется связь с pending/mailbox. Удаление pending после успеха защищает повтор одного действия, но не перенос JWT на другой pending.
- **Предпосылки:** открытая регистрация, наличие ещё действующего настоящего Gmail bearer для этого сервиса и знание pending ID. ID доступен инициатору регистрации; JWT нельзя самостоятельно подписать ключом атакующего. Получение такого JWT обычным пользователем не доказано. Leakage из обслуживающей инфраструктуры либо иной доступ к настоящему action bearer создаёт реалистичную предпосылку replay. Сам факт получения письма в Gmail не доказан как способ извлечения заголовка.
- **Сценарий / impact:** атакующий создаёт pending с чужим email и своим паролем; имея service-origin bearer, вызывает confirm-gmail с известным ID. Возникает `email_verified=True` без доказательства доступа к письму для данного адреса. Возможны ложное mailbox ownership, pre-hijacking доверия к email и обход обязательного подтверждения новой регистрации. Захват уже существующего аккаунта этим PoC не доказан.
- **Evidence:** local RSA2048 Google-style token, настоящий `jwt.decode`, только загрузка доверенных Google certs заменена локальным MockTransport. Две разные synthetic pending registrations, один и тот же токен, оба POST — 200; PostgreSQL содержит двух verified users. Доставка заменена sink; Google/SaaS не участвовали. Итог audit probes: 4 passed. Это демонстрация authorization defect, а не доказательство подделки Google signature.
- **Воспроизведение:** отдельная PostgreSQL с marker и testing profile; `python -m pytest -p tests.conftest docs/audit/test_security_audit_20261007.py -q --basetemp=artifacts/security-audit/probe-temp`. Использовать только синтетический стенд, не пересылать реальные headers. Тест намеренно доказывает текущий дефект, его зелёный результат не является успешной security acceptance.
- **Классификация:** CWE-862 (Missing Authorization), CWE-294 (Authentication Bypass by Capture-replay). ASVS `v5.0.0-6.3.4` — согласованная защита всех auth путей; `6.6.2` — аналогия требования привязки out-of-band proof к исходному запросу, без утверждения, что email verification тождественна OOB login. Top 10 A01 Broken Access Control / A07 Authentication Failures.
- **Remediation:** независимый криптографически случайный limited-use action secret в action URL, его hash связан с pending, purpose, сроком и одноразовым атомарным погашением. Google bearer остаётся дополнительным proof источника. Не считать UUID, выданный registration API, mailbox secret. До исправления удалить доступность этого shortcut, сохранив обязательные code/link verification; не отключать проверку email целиком.
- **Regression:** valid bearer + неправильный/missing action secret → отказ; secret A + pending B → отказ; тот же bearer может обслужить разные действия только с их собственными действующими секретами; конкурентный replay одного secret — ровно один успех; expiry/неверные подпись/aud/azp/issuer → отказ. Отдельная controlled live Gmail проверка после настройки регистрации sender подтверждает интеграцию, но не заменяет negative binding tests.

Документация [Google Secure actions](https://developers.google.com/workspace/gmail/markup/actions/securing-actions) различает bearer proof источника Google и рекомендуемый limited-use token в URL; [Verify bearer tokens](https://developers.google.com/workspace/gmail/markup/actions/verifying-bearer-tokens) описывает проверку service audience. Вывод об отсутствующей mailbox binding получен из кода приложения, а не приписан Google.

### SEC-02 — полный перебор credentials на неизвестном Passkey ID

- **Severity / Confidence:** Low / High; высоконагрузочный DoS не установлен.
- **Место:** `backend/app/api/mfa.py:296–307`, вызов `:329`, `_find_discoverable_credential`.
- **Boundary / cause:** public enabled authentication получает request-controlled credential ID; после indexed lookup miss выполняет `select(WebAuthnCredential)` без WHERE и материализует все строки для сравнения binary encoding. Стоимость одного промаха растёт с общим количеством credentials, включая зашифрованные/публичные поля строк. Эти строки не возвращаются клиенту — утечка credentials не доказана.
- **Предпосылки / сценарий:** Passkey явно включён, накоплен существенный объём credentials, запрос дошёл до lookup. Многократные случайные IDs увеличивают DB I/O, память и CPU. Persistent quota ограничивает частоту для одного IP, контейнер имеет budget; много источников и рост таблицы остаются риском. Default-off API закрывает этот путь.
- **Evidence:** SQL и loop reviewed; защищающие feature gate, quotas и обязательная последующая crypto/UV проверка сохранены. Нагрузочная эксплуатация не выполнялась. Проверка безопасна на unit fake session: unknown ID фиксирует второй запрос без WHERE; затем измерить synthetic large table на отдельном load стенде.
- **CWE / standards:** CWE-400, ASVS `v5.0.0-13.1.3` (resource budgeting), Top 10 A06 Insecure Design.
- **Remediation / regression:** канонизировать base64url ID при записи и запросе, indexed exact lookup без scan; bounded проверка формата/длины до БД. Legacy migration нормализует уникальные IDs, сохраняя отрицательные проверки WebAuthn. Unknown malformed/valid ID не должен выполнять full-table SQL; query plan и synthetic scaling test проверяют фиксированную стоимость.

### SEC-03 — версии Python packages не удостоверяют конкретные artifacts

- **Severity / Confidence:** Low / High, категория supply-chain hardening.
- **Места:** `backend/Dockerfile:7`, `:26`; `requirements-lock.txt`, `requirements-runtime-lock.txt`, `requirements-build-lock.txt`; install steps `.github/workflows/ci.yml`.
- **Boundary / cause:** build доверяет registry/CA и зафиксированным номерам versions. Pip installation не требует hash каждого загружаемого wheel/sdist. Digest базового Docker image и SHA GitHub Actions не покрывают содержимое Python packages.
- **Предпосылки / impact:** компрометация upstream/package index/допущенной поставки либо ошибочная подмена artifact. Самостоятельно контролировать package имя или index через публичный HTTP request приложения нельзя. Изменённый пакет может исполнить код build/runtime; реального malicious package не обнаружено.
- **Evidence / repro:** lock files содержат exact versions, pip-audit предупреждает отсутствие hashes; install commands не используют `--require-hashes`. Проверка статическая, атака не демонстрировалась.
- **CWE / standards:** CWE-494 как модель загрузки без проверки integrity, ASVS V13 Configuration / V15 Secure Coding, Top 10 A03 Software Supply Chain Failures. Номер отдельного ASVS требования не приписывается без прямого соответствия.
- **Remediation / regression:** хранить hashes допустимых artifacts для целевых Python/platform profiles, enforce `--require-hashes`; проверять dependency inventory/SBOM и provenance при release. Negative install с подменённым artifact hash должен падать. npm lock integrity уже присутствует; package version lock не удалять.

### SEC-04 — управление активными сессиями без свежего фактора

- **Severity / Confidence:** Low / High; hardening, не обход аутентификации.
- **Места:** `backend/app/api/auth.py:372`, `:397`, `:409`; `backend/app/services/reauthentication_service.py:104–121`.
- **Boundary / cause:** список и отзыв своих сессий требуют authenticated user, ownership и для mutations CSRF; router reauthentication guard применяется только к `sensitive_action`, куда session paths не входят. Свежая проверка хотя бы одного фактора для этих операций отсутствует.
- **Предпосылки / сценарий / impact:** обладатель украденной действующей сессии получает CSRF token как пользователь и отзывает другие его сессии, мешая владельцу продолжать работу/реагировать на инцидент. Доступ к чужим user sessions по произвольному UUID ограничен ownership; такой IDOR не обнаружен. Stolen cookie уже предоставляет иной user access, поэтому severity Low.
- **Evidence / repro:** сопоставление маршрутов и allowlist reauthentication. Безопасный regression на двух synthetic sessions должен проверять отказ просмотра/отзыва без fresh factor; чужая сессия всегда недоступна. Browser exploit не демонстрировался.
- **CWE / standards:** CWE-306 применительно к дополнительному factor gate; ASVS `v5.0.0-7.5.2`, Top 10 A07 Authentication Failures. Это gap относительно ASVS, не утверждение нарушения текущего согласованного ТЗ.
- **Remediation:** свежий фактор для просмотра/отзыва sessions, включая Passkey/password согласно доступным факторам; не блокировать обычный logout. Add ownership, expiry, replay и disabled-factor tests.

## Dependency and Supply-Chain Review

`pip-audit --strict -r requirements-lock.txt --disable-pip --no-deps -f json`: **79 packages, 0 известных advisories** на момент запроса. `npm audit --json --prefix frontend`: **0** info/low/moderate/high/critical, 404 total dependencies по registry report. Это проверка lock-набора, не доказательство отсутствия zero-days, runtime deviations или image OS CVEs. Runtime/build Python subsets закреплены отдельно; wheel SDK в чистом окружении установлен с этими версиями. Широкие minimum ranges SDK допустимы для consumer library, но consumer должен самостоятельно проверять своё resolved окружение.

Bandit: 15 391 строк, 172 signals (158 Low, 14 Medium, 0 High). Наиболее частые B603/B607 — операторские subprocess argv без shell; B101 — build/test invariants; B106 — строка token_type `Bearer`, не пароль. B608: owned constant table list и нормализованные journal UUID/time, не SQL из сетевого ввода. B310: фиксированный loopback/provider URL, не request-derived SSRF. Ни один сигнал не автоматически признан exploit. Полный raw JSON сохранён локально.

Actions SHA и Docker digests закреплены; npm integrity в lock сохранена. SEC-03 остаётся рекомендацией. Новые runtime зависимости не добавлялись; tooling установлен только в отдельное локальное окружение. Лицензия backend Proprietary, открытая лицензия продукту не назначалась. Fresh Linux images прошли Trivy 0.75.0: backend и frontend — 0 High/Critical, exit0, vulnerability DB UpdatedAt 2026-10-06T19:11:49Z. Low/Medium CVEs этой командой не оценивались. Полный юридический compatibility review всех transitive licenses и binary provenance не завершён; перед release повторить обязательный gate для exact release artifacts и owner review.

## Authentication / Authorization Review

Registration code/link: нет user до verification, секреты hash/HMAC, TTL и bounded попытки, per-email/peer quotas, FOR UPDATE/unique constraints. Повторный pending заменяет старые secrets. Username/email collision нейтральный по полю, но 409/202 может раскрыть существование конкретного идентификатора; оценить продуктовую необходимость публичной доступности, не считать нейтральный текст полной защитой enumeration. Gmail shortcut рассмотрен отдельно как SEC-01.

Password: Argon2id (64 MiB, time 3, parallelism 4), bounded executor/capacity с сохранением нагрузки при cancel, dummy hash для отсутствующего пользователя, server lockout/quota; ограничения длины и blocklist. Самостоятельного forgot-password endpoint не обнаружено: administrator reset выдаёт короткоживущий temporary password с change-only session, это privileged отдельный сценарий.

OIDC: проверка client, secret и URI до выдачи redirect errors; public clients с обязательным S256; одноразовые 60-second codes; nonce/auth_time; prompt/max_age interaction binding. Code и refresh exchange повторно проверяют активность/revision/почту/privacy под User row lock. Replay refresh отзывает family, rotation и absolute family lifetime ограничены. UserInfo требует access-token profile; ID token не принимается вместо access. Отсутствие DPoP/mTLS и asymmetric client authentication — возможный L3 hardening, не дефект согласованного code+PKCE профиля.

SDK: explicit RS256, issuer/audience/time/token_use, nonce/state в callback, JWKS limits/key size/kid uniqueness, bounded stale cache и refresh throttling. `verify_ssl=False` — явный caller option при безопасном default True; production consumers должны запретить такой override. Offline JWT validation не мгновенно видит security revision/role revocation: срок access token 300 секунд образует остаточное окно. Это архитектурное ограничение, не доказанный signature bypass. Обновление ролей должно сопровождаться понятной operational политикой этого окна.

MFA: TOTP encrypted separate key, enrollment pending bound session/TTL, replay last_step; recovery high-entropy hashed atomic one-use после пароля, standalone recovery login отсутствует. Passkey challenge/origin/RP/signature/UV и counter проверяются; UV **не ослаблялся**. Default flags false проверяются API, enabled отдельным профилем. Отключение требуемого фактора не переключает незаметно пользователя на password-only.

RBAC/IDOR: admin router и services, server roles, registration не назначает admin, ownership sessions/MFA, last-admin advisory lock, user/security revision locks. Reauthentication proof зависит от actor/session/revision/action/canonical body и атомарно потребляется с mutation. Email/password/MFA/admin mutations защищены. Session management gap — SEC-04. Privacy deletion имеет собственную fresh-factor процедуру, cancellation не восстанавливает старые grants.

## Secrets and Cryptography Review

Current source offline scan: финально **254 signals / 0 вне baseline**, profile с отключёнными network verification filters. Первоначально256/2new — два synthetic audit password literals; audit test теперь генерирует пароли CSPRNG, повтор4PASS. Baseline не изменялся. Membership в baseline не удостоверяет действительность/безопасность значения. Private-key signal относится к invalid-key negative fixture в tests/test_production_keys.py; high-entropy signals в основном test/protocol strings, revision metadata и key validation patterns. History scan: **1 745 UTF-8 text blobs**, **3 597 signals**, **1 750 вне текущего baseline**: 1 744 historical npm integrity signals; 4 historical startup DB URL templates; 1 historical acceptance hash metadata; 1 archived UI document TOTP-related signal. Исторический summary уже отмечает DB templates/hash metadata как кандидаты, но не является новым owner attestation. Эти шесть non-lock signals не проверялись через provider, **не объявлены действующими leaked credentials**. Окончательное решение о старом TOTP-related artifact требует приватного owner review, если он когда-либо использовался вне synthetic среды. Секретные значения и tokens в отчёт не включены.

Heuristic scan только достижимых refs и текстовых blobs не покрывает unreachable objects, binary archives, CI artifacts, reflogs, локальные ignored `.env` или секреты в SaaS. Отсутствие подтверждённых утечек не равно доказательству их отсутствия. При признании реального секрета отозвать/ротировать, затем отдельно решить history cleanup; не считать изменение baseline отзывом.

RSA signing key ≥2048, production persistent key/key id checks; RS256 only; high-entropy bearer secrets SHA-256, шестизначные email codes HMAC-derived, TOTP Fernet separate key. Не обнаружены hardcoded production signing keys или собственные криптоалгоритмы. Production config отвергает dev secrets/missing signing key/insecure public origins. Фактические entropy, key ACL, ротация, backup custody и SaaS secrets проверяются оператором; managed secret vault/HSM — hardening. Backup SQL чувствителен, штатный CLI не обеспечивает encryption at rest: storage ACL/encryption/retention обязательны по эксплуатации.

## CI/CD and Deployment Review

CI PR/main и release — GitHub Actions; actions full SHA, default permissions read; не используется pull_request_target для выполнения PR code с write/secrets. Проверены expression/input границы, command argv, target checkout и publish job. Release принимает валидный существующий SemVer tag, закрепляет SHA, повторяет reusable CI именно этой ревизии; upload/manifest/hash verification до draft, отказ перезаписи опубликованной версии. Write permission изолирована от исполнения checkout code в publish job. Manual release требует email tests; отсутствие AWS credentials допускает условный skip только обычного SES CI job, не live acceptance.

CD остаётся вне active workflows, все строки `deploy/github-actions/cd.yml.example` закомментированы; активных deploy jobs не обнаружено. В этом аудите release/commit/push/deployment не запускались. Private Sentry source maps отделены от frontend artifact; public map publishing не включён; live project permissions/upload не проверены.

Оба Linux image builds выполнены локально с отдельными audit tags. Trivy запущен checksum-verified binary; итог CVE проверки указан в заключительном checkpoint. Remote CI этого SHA, artifact provenance и реальный publish не запускались. Наличие обязательных jobs в YAML не означает их PASS. Один локальный build frontend/SDK не заменяет release acceptance.

## Configuration and Infrastructure Review

Production settings требуют HTTPS exact public origin, persistent signing material, non-default session/TOTP secrets, secure cookie policy, verified STARTTLS для SMTP; обязательный email flag нельзя выключить. Default local HTTP profile ограничен loopback и не называется production TLS. Forwarded chain учитывается только от configured trusted peer; backend no-proxy-headers, proxy очищает заголовки; wildcard trust запрещён.

Compose/Docker: non-root backend/frontend, readonly/cap_drop/no-new-privileges, quotas, internal DB, отдельные runtime/migrator roles и startup ownership checks. SQL injection sink review: SQLAlchemy parameters, constant operator SQL; пользовательские identifiers не подставляются в SQL. Backup restore — намеренно privileged выполнение trusted dump, не публичный file upload.

Nginx/TLS example содержит CSP, HSTS, TLS1.2/1.3, ограничение request body/timeouts и logs без query. Browser preview не проверяет Nginx headers. Дополнительно реальный новый Nginx image проверен на loopback3333: index200, map404, enforcing CSP с frame-ancestors none, DENY/nosniff/no-referrer/Permissions-Policy; UID101/read-only. Это проверка local HTTP, не public TLS или proxy к backend. Нужна отдельная приёмка развёрнутого reverse proxy: chain/trust/Host/CORS/CSP/TLS/cookie; из исходников нельзя удостоверить DNS, доступность PostgreSQL, tenant isolation, IAM, secret storage или firewall. Docker Desktop использован только для отдельной тестовой БД; существующая локальная deployment среда не аудитировалась как production.

## Logging, Monitoring and Abuse Resistance

Safe formatting и allowlist event fields ограничивают PII, tokens/passwords/query/errors; backend telemetry reconstructs payload, frontend consent, blocked sensitive UI, same-origin worker и sanitized replay envelope. LocalStorage используется для appearance/privacy, bearer/refresh там не найден. Provider endpoints фиксированы/операторские; Google cert URL не зависит от JWT jku или HTTP параметров — SSRF через него не найден.

Replay определяется telemetry environment `staging`; staging намеренно запускается с `ENVIRONMENT=production` для production security policies (`docs/observability.md:20`). Это не подтверждённый bypass: selector `SENTRY_ENVIRONMENT` является операторской trust boundary. Неверное выставление staging в настоящем production остаётся configuration risk; согласие и sanitization не отменяют требования правильного профиля.

Persistent quotas защищают register/email/security/OIDC между replicas; ошибки DB не превращаются в allow. Argon2 worker budget, timeouts, Docker resource limits ограничивают нагрузку. SEC-02 требует устранения full scan. Google cert fetch происходит на каждом syntactically valid bearer; quota/cache/streamed size bound до JSON parsing — полезный hardening против provider amplification. Load attack и доступность Google не проверялись.

Audit фиксирует auth/admin события, но generic `client_rejected` не заменяет семантическое расследование каждого failed authorization. Рекомендуется тестировать actor/route/action/reason без payload secrets, transactional mutation+audit где возможно, alerts на replay/failed MFA/escalation; не подавлять инфраструктурные сбои. Уведомления пользователю о смене password/factors — дополнение по ASVS 6.3.7, live delivery не оценивалась. Фактические retention и alert response в SaaS/ops не доказаны.

## Security Test Coverage

Фактические команды и завершённые результаты этой сессии:

| Проверка | Результат | Что доказывает / ограничение |
| --- | --- | --- |
| Alembic upgrade head + fresh marker | PASS | Настоящая выделенная PostgreSQL; production migration не запускалась |
| `pytest tests -q --basetemp=... --junitxml=...` | 637 passed, 2 failed, 5 deselected, 18 subtests | Общий прогон **не зелёный**; external email исключён штатно |
| Targeted signed Gmail/token/core negatives, non-PG | 42 passed, 7 deselected | Unit/mocks отделены от PostgreSQL/live crypto trust |
| Audit probes с `-p tests.conftest` | 4 passed | Binding defect и MIME rejection; fixture trust, настоящая PG |
| Ruff project + audit test | PASS | Static lint |
| Mypy backend/SDK | PASS, 68 files | Types, не security proof |
| Frontend lint/typecheck/typecheck:tests | PASS | Static frontend checks |
| Frontend unit/components/build | 13 / 39 passed; build PASS | Component behavior/build, не production proxy |
| SDK wheel/sdist + new venv installed wheel tests | 17 passed | Реальный site-packages import, JWT/JWKS/SDK negatives; без live IdP |
| pip-audit / npm audit | 0 известных advisories | На момент запроса, не image scan |
| Offline secrets current/history | Завершены | Метаданные и приватная triage, без проверки действительности credentials |

Заключительный browser run с installed SDK wheel и локальным SMTP sink: default-off **47 passed**, enabled **9 passed**, включая real WebAuthn UV/TOTP/recovery replay, exit0. `artifacts/security-audit/e2e-clean-wheel.log`. Предыдущий enabled run 8 passed/1 failed (TOTP setup UI) не скрыт; причина первого сбоя не доказана отдельно, более поздний полный run прошёл без изменения защиты/таймаутов/assertions. Финальные audit probes после генерируемых synthetic паролей: **4 passed, 1.90s**, `probe-final03.xml`. Testmail isolated env test: **1 passed**; полный общий прогон после этого отдельно не повторялся. Свежие backend/frontend Docker builds PASS; Trivy High/Critical обоих images exit0/0 findings; local non-root readonly Nginx headers/maps PASS. Все тесты используют синтетические identities. Fresh venv SDK не импортирует внутренности сервера для library behavior; test harness использует backend conftest только для тестовой коллекции. Live two-client callback проверяется отдельно браузером.

Общий PG прогон: `test_registration_duplicate_collisions_pg` — четвертая register попытка ожидает 409, получает 429; synthetic forwarded IP не становится доверенным только из-за заголовка. Ошибка совместимости тестового сценария с квотой/peer trust требует отдельного исправления test setup, **не отключения rate limits или глобального доверия proxy**. `test_configuration_env_precedence_and_validation_redaction` — окружение содержит пустой `TESTMAIL_API_KEY`, который имеет приоритет над synthetic `.env`. Это воспроизводимая конфигурация test harness, не установленный production bypass. Для строгого повторения убрать только внешний TESTMAIL override в новом процессе. Ни assertions, ни guard не ослаблялись.

Первый общий прогон: 542 passed / 3 failed / 94 errors — Windows Temp access и недоступные native `psql`/`pg_dump`; после собственного basetemp/PATH исправлены инфраструктурные ошибки, но не все тесты. Первый browser run: 44 passed / 3 failed — отсутствовали explicit isolated RP credentials/local SMTP capture, registration UI и следующий шаг не завершились. Эти прогоны не скрыты и не засчитаны как полная приёмка.

Не закрыто: полная Compose/runtime matrix, actual reverse-proxy CSP/TLS, настоящие email/Gmail/Sentry/SES checks, multi-instance load/restart и production backup ACL/recovery на утверждённой инфраструктуре. Existing tests относятся к реальной PG concurrency/replay и не заменены SQLite. Одна успешная suite не доказывает все ASVS requirements.

## False Positives and Dismissed Candidates

| Кандидат | Проверка и причина отказа от находки |
| --- | --- |
| Login CSRF из отсутствия pre-auth CSRF header | JSON без MIME/text/plain → 422 без cookie; application/json принимается, но браузер требует preflight, чужой origin вне CORS allowlist. Не доказан browser cookie injection. Добавить Origin gate можно как hardening |
| JWT alg/kid/jku confusion, ID token как access | Allowlist RS256, fixed JWKS source, bounded kid и key profile, separate token_use/aud/issuer; отрицательные tests |
| Отключённый UV / альтернативный RP fallback | UV обязательный; challenge/RP/origin/signature проверяются; server challenge fallback не повторяет проверку с другим RP |
| Auth/MFA скрыты только frontend | Backend gates проверяются прямым API; disabled required factor не даёт password-only upgrade |
| SQL injection по Bandit B608 | Table list owned constants; journal UUID/time normalization; пользовательские values параметризованы |
| Command injection по B603/B607 | argv без shell, операторские пути; restore trusted dump — intentional privileged operation |
| Backend 0.0.0.0 / dev HTTP | Container internal bind и documented loopback test profile, production config отдельно ограничен |
| Bearer string как hardcoded password | Token type literal, не секрет |
| Replay включается при ENVIRONMENT=production | Документированный staging на production security profile; нужен правильный telemetry environment, remote override не найден |
| Logout недостаточно отзывает все RP tokens | Документированные независимые OP/RP lifetimes, ID hint/user/session binding и confirmation+CSRF. Глобальный logout не обещан |
| Refresh race и admin stale grant | User lock/revision + FOR UPDATE и atomic family revocation; action proof bound body/session; tests не ослаблялись |
| CSV formula/XSS | CSV dangerous prefixes escaped, React default escaping; JSON detail context, не raw HTML sink |
| npm integrity как leaked secret | Package checksum public metadata, не credential; history signals отделены |

Второй adversarial проход выполнен отдельно после первоначальной карты: повторно проверены Gmail claims versus action secret, fallback WebAuthn/unknown ID, router dependency versus session paths, simple-request login MIME/CORS, stale roles/refresh user locks, logout ownership, telemetry environment/privacy envelope, SDK stale JWKS и CI trusted SHA/secrets. SEC-01 сохранился после проверки окружающих controls; SEC-02 и SEC-04 обнаружены через повторную проверку lookup/allowlist. Подозрение Replay отклонено после сверки с документированным staging, а не только после поиска флага.

## ASVS Coverage

| ASVS 5.0.0 area | Применимость и проверка | Ограничения / основные gaps |
| --- | --- | --- |
| V1 Encoding and Sanitization | SQL/argv/CSV/React/URL sinks | Не исчерпывающий browser fuzz всех UI inputs |
| V2 Validation and Business Logic | Models, quotas, pending/one-use/roles, privacy races | SEC-01; scale/load не измерены |
| V3 Web Frontend Security | CORS, CSRF token, browser MIME, escaping/storage/CSP source | 3.4.2/3.5.1/3.5.2 рассмотрены; actual edge headers не проверены |
| V4 API and Web Service | JSON endpoints, auth deps, error models, feature gates | Production request smuggling/edge parser chain не проверена |
| V5 File Handling | Operator backup/source maps/artifacts | Public uploads отсутствуют; operator ACL/encryption нужны |
| V6 Authentication | Password/email/TOTP/Passkey/recovery/reauth | SEC-01; delivery и notifications live не проверены |
| V7 Session Management | Host-only cookie, TTL, revocation, OP/RP separation | SEC-04 (7.5.2); 7.6.1 lifecycle документирован |
| V8 Authorization | Server RBAC/ownership/admin invariants/action proofs | Browser/RP stale token window300s; не мгновенная offline revocation |
| V9 Self-contained Tokens | RS256 claims/profiles/key/cache/replay | Actual production key rotation и custody не проверены |
| V10 OAuth and OIDC | S256/URI/state/nonce, codes, refresh families | 10.1.2/10.4.5 рассмотрены; live OIF/DPoP/mTLS не проверены/не реализованы |
| V11 Cryptography | Argon2id/RSA/Fernet/HMAC/CSPRNG | Production entropy/HSM/backup ключей требуют оператора |
| V12 Secure Communication | HTTPS/STARTTLS validation/TLS config | Реальный DNS/сертификат/DB transport не обследованы |
| V13 Configuration | Secrets flags, quotas, resource budgets, Docker | SEC-02; ownership IAM/firewall/container CVEs не доказаны |
| V14 Data Protection | Privacy lifecycle, redaction, sensitive view blocks | SaaS retention/storage ACL и native backups внешняя приёмка |
| V15 Secure Coding and Architecture | Layering, error handling, dependencies | SEC-03; review не гарантирует отсутствие неизвестных sinks |
| V16 Security Logging and Error Handling | Safe fields, fixed labels, audit/telemetry | Semantic denied actions/alerts/notifications operational tests нужны |
| V17 WebRTC | Не применимо: реализации нет | Не переносится на будущие функции |

Полная требование-за-требованием L2/L3 acceptance не проводилась. Там, где нет достаточного доказательства, статус не объявлен PASS. Top10 применён как классификация риска, а не checklist сертификата.

## Prioritized Remediation Plan

**P0 — immediate / production-blocking:** устранить SEC-01 в корне: отдельный одноразовый action secret и atomic binding либо удалить shortcut при сохранении code/link. Негативные cross-registration/replay/concurrency tests и controlled live Google acceptance после локального исправления. Обязательное email verification не выключать.

**P1 — high priority:** восстановить достоверную зелёную acceptance этой ревизии с изолированным env/SMTP/RP setup; пройти обязательную Linux image/Trivy/release/edge matrix; подтвердить production keys/TLS/DB roles/backups и operator secrets/history decision. Исправления production поведения и тестовой инфраструктуры оформлять отдельной задачей. При обнаружении действующего исторического секрета немедленно отозвать, severity пересмотреть.

**P2 — medium priority:** indexed canonical Passkey lookup (SEC-02), свежий фактор для session management (SEC-04), denied-action semantic audit/alerts и sensitive-change notification tests; bounded Google cert fetching/cache/quota. Проверять fail-closed и реальные replay, не заменять нагрузку retry/timeout.

**P3 — hardening / defense in depth:** mandatory Python artifact hashes/SBOM/provenance (SEC-03), managed secret storage и rotation drills, production SDK TLS policy, Origin checks поверх CSRF, URL registration policy для админских RP, privacy retention evidence. DPoP/mTLS и asymmetric client auth оценить при необходимости ASVS L3; не вводить их без согласования профиля interoperability.

## Residual Risk and Unverified Assumptions

| Не проверено | Имеющееся evidence / confidence | Что нужно для завершения |
| --- | --- | --- |
| Настоящий Gmail action bearer и регистрация sender | Local cryptographic fixture подтверждает дефект кода; доступность live атаки условная | Controlled sender/action registration, synthetic Gmail inbox, authorized local callback capture; не реальные пользовательские письма |
| SES/Resend/SMTP public delivery | Код/config/unit; 5 external tests исключены | Явное поручение на synthetic live delivery, credentials вне Git и утверждённые recipients |
| Public TLS/edge/network/IAM | Config/source only | Утверждённый stage endpoint, infrastructure/role data и разрешённая область теста |
| Linux images/OS CVEs/runtime | Fresh images build PASS; Trivy High/Critical0, полного runtime matrix нет | Полная runtime acceptance отдельного Compose project; перед release повторить Trivy exact artifacts; Low/Medium здесь не оценены |
| Sentry SaaS/retention/maps/alerts | SDK/component/browser локально, ingestion interception | Утверждённый staging project и live privacy acceptance |
| History credential validity | Offline reachable text metadata; 6 non-lock candidates требуют контекста | Приватное owner подтверждение synthetic context, отзыв при реальном использовании; values не публиковать |
| Multi-replica DoS/backup recovery/ACL | PG tests/config; ограниченный single-host synthetic стенд | Отдельный load/recovery стенд и storage/IAM evidence |

Админские URI принимаются из configured list с точным matching, но scheme policy требует operator review; malicious registered RP является privileged misconfiguration, публичный arbitrary redirect не доказан. Backup dump и sourcemaps могут содержать чувствительные данные даже при отсутствии исходных passwords. Большая совокупность успешных тестов не устраняет эти trust assumptions.

## Final Verdict

**NOT READY FOR PRODUCTION.** SEC-01 нарушает доказательство доступа к адресу для самостоятельной регистрации: локально продемонстрирована переносимость Google-style service bearer между registrations. Это достаточный blocker для обязательного email ownership независимо от отсутствия live exploitation. Дополнительно общий test run пока не полностью зелёный и внешняя инфраструктура не принята. Остальные находки преимущественно Low/hardening; они не представлены как доказанный массовый compromise. Исправления не выполнены в рамках аудита; после remediation необходим targeted negative retest и актуальная приёмка конкретного SHA.

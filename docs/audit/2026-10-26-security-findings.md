# Findings аудита 26.10.2026

Все записи подтверждены воспроизведением на локальном стенде (PostgreSQL 16 + реальный Chromium, где применимо). Секреты, OTP, cookie и персональные данные не приводятся. Severity — оценка impact × likelihood для текущей архитектуры, не CVSS-сертификация.

## AUD-2026-01 — Пароль администратора требовался дважды при смене режима регистрации

- **Severity:** Medium (UX + лишняя передача credential; не bypass).
- **Компоненты:** `backend/app/schemas/admin.py`, `backend/app/services/system_service.py`, `frontend/src/api/client.ts`, `frontend/src/features/admin/useAdminController.ts`, `frontend/src/pages/AdminPage.tsx`.
- **Preconditions:** администратор с assurance меняет `registration_mode`.
- **Reproduction (до исправления):** открыть `/admin/system`, ввести пароль в форму, нажать «Применить» → 401 `reauthentication_required` → диалог снова просит пароль и второй фактор. Итог: два ввода пароля и один MFA на одну операцию.
- **Root cause:** endpoint одновременно проверял legacy-поле `current_admin_password` и router-level action-bound `X-Reauthentication` proof, который уже требует свежий пароль и настроенный фактор и привязан к точному телу запроса.
- **Fix:** поле `current_admin_password` стало необязательным (проверяется, если передано, для старых клиентов); новый клиент отправляет только `{mode}`; подтверждение выполняет один одноразовый proof. Digest-binding сохранён, поэтому подменить `mode` после подтверждения нельзя.
- **Regression tests:** `tests/integration/test_registration_mode_reauth_pg.py` (proof без пароля в теле → 200; legacy-пароль → 200; неверный legacy-пароль → 401; proof для другого body → 401; без proof → 401), `frontend/src/App.component.test.tsx` (один вызов API с `mode`), Playwright `sso.spec.ts` 02/04 (в форме 0 password-полей, в диалоге 1).
- **Verification:** PostgreSQL-тесты 4 PASS; компонентный тест PASS; браузер: `formPasswordFields=0`, `dialogPasswordFields=1`, успешное переключение режима.
- **Residual risk:** старый клиент, продолжающий слать пароль в теле, по-прежнему передаёт его дважды; контракт задокументирован и подлежит удалению при следующем major.

## AUD-2026-02 — Пятиминутный grant просмотра сессий терялся при reload и в новой вкладке

- **Severity:** Medium (UX/политика: подтверждений больше, чем обещает документированный пятиминутный срок).
- **Компоненты:** `frontend/src/api/client.ts`, `ReauthenticationDialog.tsx`, backend `GET /api/v1/auth/sessions`.
- **Preconditions:** пользователь подтвердил просмотр сессий; затем перезагрузил страницу (или открыл новую вкладку) в пределах 5 минут.
- **Reproduction (до исправления):** подтвердить доступ к `/account/sessions`, нажать F5 → снова диалог password+MFA, хотя серверный grant ещё валиден и `/api/v1/auth/sessions` с сохранённым заголовком возвращает 200.
- **Root cause:** grant хранился только в памяти singleton `ApiClient`; полная перезагрузка/новая вкладка его теряла. Серверная часть работала корректно (5 минут, session/revision binding, повторное использование для GET, запрет для mutation).
- **Fix:** tab-scoped `sessionStorage` (`alxprgs.sso.sessions-read-grant.v1`) с серверным `expires_at`; очистка при смене сессии/logout, протухании и 401; grant никогда не отправляется мутациям; одинаковые concurrent GET объединяются в один запрос подтверждения. Mutation-proof остаётся полностью одноразовым и не кэшируется.
- **Security trade-off:** XSS в том же origin может прочитать grant в пределах 5 минут; это даёт только список собственных сессий (IP/UA/время), не mutation. Альтернатива «повторно спрашивать при reload» отклонена как противоречащая документированному сроку. Зафиксировано в ADR-0033.
- **Regression tests:** `frontend/src/api/session-grants.component.test.tsx` (reuse/expiry/logout/coalescing/no-mutation), `ReauthenticationDialog.component.test.tsx` (queue), Playwright `sso.spec.ts` 06.
- **Verification:** браузер: первый визит dialog=true; reload dialog=false, GET ушёл с сохранённым grant; после logout ключ удалён. Playwright 06 PASS.
- **Residual risk:** новая вкладка всё ещё требует одного подтверждения (sessionStorage не разделяется между вкладками осознанно, чтобы не использовать localStorage для bearer-подобного секрета).

## AUD-2026-03 — Повторно использованный TOTP-шаг выглядел как неверный код

- **Severity:** Medium (UX + риск исчерпания failed-attempt budget и повторного ввода пароля).
- **Компоненты:** `backend/app/services/totp_service.py`, `backend/app/services/reauthentication_service.py`, `backend/app/api/auth.py`, `frontend/src/components/ReauthenticationDialog.tsx`, `frontend/src/api/client.ts`.
- **Preconditions:** TOTP-код уже принят (login/elevation/reauth), пользователь в пределах того же 30-секундного шага запускает ещё одну чувствительную операцию.
- **Reproduction (до исправления):** войти с TOTP, открыть `/account/sessions`, ввести тот же код в диалоге → generic `401 reauthentication_required` «Подтвердите пароль и действующий второй фактор». Повторные попытки увеличивали `failed_attempts`; после 5 операция требовала заново пароль, хотя код был реальным и просто уже погашенным.
- **Root cause:** `verify_totp` возвращал `False` и для неверного кода, и для replay; вызывающий код не мог отличить одно от другого.
- **Fix:** replay детектируется до мутации шага и поднимает `TOTPReplayException` → `401 totp_code_reused` с `Retry-After`/`retry_after` (только для аутентифицированных elevation/reauthentication путей). Replay **не** увеличивает `failed_attempts`; сама политика «строго больше предыдущего шага» не изменена. UI показывает пояснение об одноразовости и countdown до следующего кода; Passkey остаётся предпочтительным методом.
- **Regression tests:** `tests/integration/test_totp_reauth_replay_pg.py` (5 PG-тестов: spent step + retry hint + authorization survives; wrong code generic + failure count; concurrent same-step → ровно один 200; login→reauth replay; следующий шаг проходит), `tests/test_totp_policy.py` (строгая монотонность и bounded retry), dialog component test (countdown + пояснение).
- **Verification:** браузер: после login тем же кодом → alert «Этот код уже был использован…», countdown «через 24 с», password-поле не появилось (proof жив). Replay-защита не ослаблена: второй код того же шага не принимается ни на одном пути.
- **Residual risk:** в пределах одного шага пользователь обязан дождаться следующего кода либо использовать Passkey; это осознанная цена RFC 6238 one-time semantics.

## AUD-2026-04 — Кастомный обработчик `AuthenticationException` терял заголовки

- **Severity:** Low (протокольная корректность).
- **Компонент:** `backend/app/main.py`.
- **Reproduction:** `TOTPReplayException` содержит `Retry-After`, но ответ 401 не содержал заголовок, потому что handler создавал `JSONResponse` без `headers`.
- **Fix:** `headers=exc.headers`; regression проверяет `Retry-After` в integration-тесте.
- **Residual risk:** нет; другие handlers не используют заголовки.

## AUD-2026-05 — Admin API выдавал reauth-челлендж до проверки RBAC

- **Severity:** Low (authorization ordering/UX; bypass не найден).
- **Компоненты:** `backend/app/api/admin.py`.
- **Preconditions:** аутентифицированный пользователь без роли admin вызывает чувствительный admin endpoint.
- **Reproduction (до исправления):** `POST /api/v1/admin/clients` без proof → `401 reauthentication_required` (запрос пароля+MFA), тогда как читающие admin endpoints давали `403`. Пользователь получал приглашение подтвердить операцию, которую никогда не сможет выполнить.
- **Fix:** `require_admin_user` добавлен в router-level dependencies перед `require_recent_reauthentication`; regular user получает `403 forbidden` без создания `SecurityAuthorization`, admin без assurance — `403 admin_mfa_required`, anonymous — `401`.
- **Regression tests:** `tests/integration/test_admin_authorization_order_pg.py` (3 кейса, включая отсутствие созданных proof-строк).
- **Verification:** аутентифицированная матрица: все 14 admin-маршрутов для regular user → 403.
- **Residual risk:** порядок зависимостей FastAPI — неявный контракт; тест фиксирует поведение.

## AUD-2026-06 — Второй конкурентный чувствительный запрос завершался ошибкой

- **Severity:** Low (UX/надёжность; security не ослаблена).
- **Компонент:** `frontend/src/components/ReauthenticationDialog.tsx`.
- **Reproduction:** два разных чувствительных запроса одновременно (например, две мутации) → второй `reject("Дождитесь завершения текущего подтверждения")`, операция не выполнялась и требовала ручного повтора.
- **Fix:** очередь подтверждений; после завершения текущего диалога сразу открывается следующий; отмена отклоняет всю очередь; одинаковые concurrent GET объединяются на уровне клиента (mutation-proof никогда не разделяется).
- **Regression tests:** `ReauthenticationDialog.component.test.tsx` (queue) + `session-grants.component.test.tsx` (coalescing read, два mutation prompt).
- **Residual risk:** очередь может показать несколько последовательных диалогов при массовых операциях — это соответствует политике одного proof на mutation.

## AUD-2026-07 — Уязвимые Python-зависимости

- **Severity:** Medium (supply chain; dev/build-зависимости).
- **Evidence:** CI job `Security & Dependencies Scan` (run 40357493471): `setuptools 84.0.0` GHSA-xmj3-9gf7-h52w; `filelock 4.0.12` CVE-2026-112940, -112913, -112907.
- **Fix:** `setuptools==84.1.0`, `filelock==4.2.1` в `requirements-lock.txt`; `scripts/hashed_locks.py --generate`; runtime/build locks не изменились; `pip-audit --strict` → «No known vulnerabilities found»; `pip check` и lock-check PASS.
- **Residual risk:** новые CVE после даты скана; gate повторяется в CI.

## AUD-2026-08 — Уязвимые npm-зависимости

- **Severity:** High (CI gate; dev/build-граф, не входит в browser bundle).
- **Evidence:** CI job `Frontend Build & Typecheck`: `undici` high (GHSA-4qv8-2p9j-2685, GHSA-f72v-6w45-q472, GHSA-xjj6-f33q-929c) через `@sentry/cli` и `jsdom`; `next` critical (GHSA-2464-fhr4-w9xw, GHSA-p3m5-59mp-jv5r, GHSA-673q-mjm6-r5xr) как peer `geist`; `@vitest/mocker` moderate.
- **Fix:** `vitest 5.0.5`, `jsdom 30.1.3`, `@sentry/cli 3.8.2`, затем non-force `npm audit fix` (`next 16.4.3`, `undici 6.29.1/8.12.3`). `npm audit --audit-level=high` → `found 0 vulnerabilities`; `npm ci`, lint, typecheck, typecheck:tests, unit 14, components 51, build PASS. `next` остаётся транзитивным peer'ом `geist` и в bundle не попадает.
- **Residual risk:** peer-граф `geist` может снова привести уязвимый `next` при обновлении lock; gate поймает.

## AUD-2026-09 — HIGH-уязвимости в frontend container image

- **Severity:** High (production image; edge nginx).
- **Evidence:** CI `Immutable Containers...`: Trivy 6 HIGH — nginx 1.30.5-r1 (CVE-2026-15176/-93479/-97205), curl 8.22.0-r0 (CVE-2026-92392), brotli-libs 1.2.0-r1 (CVE-2026-111497).
- **Fix:** base image `nginx:1.30.6-alpine@sha256:47928b…` + `apk upgrade --no-cache` (curl 8.23.0-r0, brotli-libs 1.2.1-r0, nginx 1.30.6-r1); `apk add` pins сохранены для libexpat/pcre2/tiff/libx11.
- **Verification:** локальная сборка `sso-frontend-audit`; Trivy 0.75.0 → 0 HIGH/CRITICAL; `nginx -t` под `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges`, non-root uid 101; build-info и отсутствие sourcemaps сохранены.
- **Residual risk:** новые CVE после сборки; CI пересобирает и сканирует.

## AUD-2026-10 — Локальный SMTP TLS-тест не работал на OpenSSL 3.x

- **Severity:** Low (test portability; не дефект продукта).
- **Reproduction:** `pytest tests/test_smtp_tls.py` на Windows/Python 3.13 → `SSLCertVerificationError: Missing Authority Key Identifier`, затем `CA cert does not include key usage extension`.
- **Fix:** синтетический CA получил `BasicConstraints`, `KeyUsage(keyCertSign, crlSign)`, `SubjectKeyIdentifier`; серверный сертификат — `ExtendedKeyUsage(serverAuth)` и `AuthorityKeyIdentifier`. Позитивные/негативные TLS-проверки не менялись.
- **Verification:** 5 PASS, включая trusted/untrusted/hostname/no_starttls.

## Гипотезы, которые не подтвердились

| Гипотеза | Проверка | Вывод |
| --- | --- | --- |
| Read grant можно использовать для mutation | `test_reauthentication_pg.py::test_session_read_grant_and_mutation_proof_are_separate` | Action binding отклоняет; grant только для точного GET |
| Смена роли/пароля не инвалидирует старые сессии/revision | `test_security_revision_pg.py`, `test_admin_mfa_pg.py` | Инвалидация работает; старые grants не получают admin |
| TOTP можно принять дважды конкуренцией | новый `test_concurrent_same_step_confirmations_have_one_winner` | Ровно один 200; row lock |
| Admin API доступен без assurance | `test_admin_mfa_pg.py`, `test_mfa_assurance_pg.py` | 403 до RBAC/assurance |
| Внешний клиент может использовать чужой step-up proof | `test_external_step_up_pg.py` (cross-client/replay/session/revision/redirect) | Отклоняется |
| ID token принимается вместо access token | OIDC contract tests / UserInfo | Отклоняется (`invalid_token`) |
| Ошибка БД открывает доступ (fail-open) | `test_fail_closed_on_database_failure`, deny-audit tests | Fail-closed |

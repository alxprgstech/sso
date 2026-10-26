# Полный аудит ALXPRGS SSO — 26.10.2026 (сводка)

- **Основание:** поручение владельца от 26.10.2026 (полный security/functional/UX/CI аудит).
- **Исходная ревизия:** `a35550f223cbd38b303311ddb48842a54681c3b7` (`origin/main`, PR #34).
- **Ветка:** `audit/full-stack-security-ui-ci-20261026`.
- **Продукт:** 0.3.0. Стенд: Windows 11, Python 3.13.0, Node 24.20.0/npm 11.19.0, Docker 29.8.0, PostgreSQL 16.10-alpine (отдельный контейнер, `127.0.0.1:5433`), Chromium (Playwright), локальный SMTP capture.
- **Режим:** локальные синтетические данные; production, EC2, DNS, secrets, `runtime.env`, реальные рассылки и внешнее сканирование `auth.alxprgs.tech` не затрагивались. Merge/release/deploy не выполнялись.

## 1. Что проверено

| Область | Объём |
| --- | --- |
| Backend pytest (реальная PostgreSQL) | Полный набор `tests/`, default-on профиль; отдельно enabled/disabled и новые регрессии |
| API inventory | 73 пары method/path из фактического OpenAPI; snapshot-тест + анонимная и аутентифицированная матрица |
| Browser E2E | default-off: sso, multi_client_sso, protocol_lifecycle, telemetry, privacy, appearance, step_up; enabled: passkey, totp, privacy, telemetry |
| Frontend | lint, typecheck, typecheck:tests, unit (node:test), components (vitest/jsdom), production build, npm audit |
| SDK | исходные тесты, wheel/sdist, установка в чистую среду, installed tests |
| CI | воспроизведение трёх упавших jobs: Python deps, npm deps, container/Trivy |
| Инфраструктура | сборка backend/frontend images, Trivy 0.75.0, non-root/read-only runtime, nginx config test |
| Документация | сверка API/ADR/README, новые отчёты `docs/audit/` |

## 2. Подтверждённые дефекты и исправления

Полные карточки — [security-findings](2026-10-26-security-findings.md), разбор reauth/TOTP — [reauth-totp-analysis](2026-10-26-reauth-totp-analysis.md).

| ID | Severity | Суть | Исправление |
| --- | --- | --- | --- |
| AUD-2026-01 | Medium (UX/security-adjacent) | Смена режима регистрации требовала пароль дважды (тело + reauth-диалог) и MFA | Одно action-bound подтверждение; legacy-поле необязательно и не отправляется новым клиентом |
| AUD-2026-02 | Medium (UX/correctness) | Пятиминутный grant просмотра сессий терялся при reload/новой вкладке → лишние password+MFA | Tab-scoped `sessionStorage` с серверным сроком; очистка при смене сессии/ошибке; mutations не используют |
| AUD-2026-03 | Medium (UX/anti-replay) | Повторно использованный TOTP-шаг выглядел как неверный код; повторные попытки расходовали failed_attempts и требовали пароль заново | Отдельный `401 totp_code_reused` + `Retry-After`; replay не считается неверной попыткой; в UI countdown и пояснение |
| AUD-2026-04 | Low (protocol) | Кастомный handler `AuthenticationException` терял headers (в т.ч. `Retry-After`) | Headers пробрасываются в `JSONResponse` |
| AUD-2026-05 | Low (authorization ordering) | Non-admin получал reauth-челлендж (401) на admin API до RBAC | RBAC на router-level до reauth: regular → 403; admin без assurance → 403 `admin_mfa_required` |
| AUD-2026-06 | Low (concurrency/UX) | Второй конкурентный чувствительный запрос падал с «дождитесь подтверждения» | Очередь в диалоге; одинаковые concurrent GET объединяются |
| AUD-2026-07 | Medium (supply chain) | `setuptools 84.0.0` GHSA-xmj3-9gf7-h52w; `filelock 4.0.12` CVE-2026-112940/-112913/-112907 | `setuptools 84.1.0`, `filelock 4.2.1`; hash-locks перегенерированы; pip-audit чист |
| AUD-2026-08 | High (supply chain) | npm audit: `undici` high (через `@sentry/cli`), `next` critical (peer `geist`), `vitest/mocker` moderate | `vitest 5.0.5`, `jsdom 30.1.3`, `@sentry/cli 3.8.2`, совместимый `audit fix` (`next 16.4.3`, `undici 6.29.1/8.12.3`); 0 vulnerabilities |
| AUD-2026-09 | High (container) | frontend image: 6 HIGH (nginx 1.30.5, curl 8.22.0-r0, brotli-libs 1.2.0-r1) | `nginx:1.30.6-alpine` + `apk upgrade`; Trivy 0 HIGH/CRITICAL; non-root/read-only сохранены |
| AUD-2026-10 | Low (test portability) | Синтетический SMTP CA отвергался OpenSSL 3.x (нет KeyUsage/SKI/AKI) | Сертификаты приведены к корректному профилю; проверки TLS не ослаблены |

## 3. Что проверено и признано корректным

- **TOTP одноразовость** — строго возрастающий `last_verified_step` под row lock; один код не проходит дважды ни последовательно, ни конкурентно, ни между login/elevation/reauth. Политика сохранена; изменения касаются только диагностики и UX, не приёма кода.
- **Action-bound reauth proof** — привязка к user/session/revision/action/body, одноразовое погашение в транзакции mutation; GET /sessions использует отдельный переиспользуемый read grant.
- **OIDC/OAuth** — PKCE S256, exact redirect, state/nonce, issuer/audience/signature/time, refresh rotation + family replay, UserInfo только Bearer access token, logout/revoke.
- **Admin assurance** — `Session.mfa_verified` пишется только сервером; admin API требует assurance; OIDC не выдаёт admin-роль grant без assurance; recovery code не даёт strict assurance.
- **CSRF/Origin/CORS/cookies** — HMAC CSRF, exact Origin, host-only HttpOnly cookie, `__Host-` в production.
- **Rate limits** — PostgreSQL, fail-closed, независимые buckets для login/OAuth/MFA.
- **External step-up** — client/subject/action/payload/redirect/session/revision binding, one-use redemption, feature disabled по умолчанию (404).
- **Секреты/redaction** — тесты redaction, secret scanner, отсутствие токенов в логах.

## 4. Не подтверждено / не проверено

- Публичный TLS/DNS/edge, реальные SES/Resend/Gmail/Sentry, production backup/restore, OIF/multi-replica load, HSM/key custody — внешняя приёмка, не выполнялась.
- Полный ASVS L2/L3 requirement-by-requirement — нет.
- Firefox/WebKit E2E не запускались (Chromium только); отмечено как ограничение.
- CodeScene live-доступ не проверялся; рефакторинг выполнен только по очевидным локальным дублям/сложности, без изменения security semantics.
- Внешнее активное сканирование `auth.alxprgs.tech` запрещено и не выполнялось.

## 5. Итог

Ветка содержит исправления подтверждённых дефектов с регрессионными тестами (backend PostgreSQL, frontend unit/component, browser E2E), обновлённые зависимости/образы и отчёты. Финальные результаты прогонов и CI — [final-verification](2026-10-26-final-verification.md). Вердикт: **READY FOR REVIEW** при условии зелёного CI на финальном HEAD; внешняя production-приёмка остаётся открытой.

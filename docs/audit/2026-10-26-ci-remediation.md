# CI / Dependencies / Containers remediation — 26.10.2026

Исходный неуспешный run: GitHub Actions **40357493471** (`main` = `a35550f`), три упавших job:

1. `Security & Dependencies Scan`;
2. `Frontend Build & Typecheck`;
3. `Immutable Containers, Runtime Policy and Image Audit`.

## 1. Python dependencies

| Пакет | Было | Уязвимость | Стало |
| --- | --- | --- | --- |
| setuptools | 84.0.0 | GHSA-xmj3-9gf7-h52w | 84.1.0 |
| filelock | 4.0.12 | CVE-2026-112940, CVE-2026-112913, CVE-2026-112907 | 4.2.1 |

- Версии выбраны как минимальные исправленные по данным `pip-audit`/CI, не «последние вообще».
- `requirements-lock.txt` → `python scripts/hashed_locks.py --generate` (PyPI artifact metadata, sha256).
- `requirements-runtime-lock.txt` и `requirements-build-lock.txt` не изменились; `runtime_lock.py --check` и `build_lock.py --check` PASS.
- Проверки: `pip-audit --strict -r requirements-lock.txt` → «No known vulnerabilities found»; `pip check` и hash-companion check PASS.
- Транзитивные зависимости `setuptools`/`filelock` не изменились (пакеты без runtime-зависимостей в этом графе).

## 2. Frontend dependencies

Исходно (`npm ci`, CI): 4 vulnerabilities (2 moderate, 1 high, 1 critical).

| Пакет | Источник | Действие |
| --- | --- | --- |
| `@vitest/mocker` / `vitest` 5.0.2 | dev | → `vitest 5.0.5` |
| `jsdom` 30.1.1 (undici 8.11.2) | dev | → `jsdom 30.1.3` (undici 8.12.3) |
| `@sentry/cli` 3.8.0 (undici 6.29.0) | dev | → `@sentry/cli 3.8.2` (undici 6.29.1) |
| `next` 16.3.8 (peer `geist`) | dev/build | `npm audit fix` → 16.4.3 |

- `npm audit fix` без `--force`; lockfile обновлён штатно.
- `next` остаётся транзитивным peer'ом `geist` (пакет нужен только для локальных woff2; в bundle не входит), версия зафиксирована lock-файлом.
- Проверки после изменений: `npm audit --audit-level=high` → `found 0 vulnerabilities`; `npm ci`; `npm run lint`; `npm run typecheck`; `npm run typecheck:tests`; `npm run test:unit` (14); `npm run test:components` (51); `npm run build`; `node e2e` Playwright (50 + 9).
- Sentry build/sourcemaps: `ALX_RELEASE_BUILD=1 npm run build` + `python scripts/check_sentry_build.py` выполняются в CI; локально проверен обычный build, release-вариант не изменялся.

## 3. Container images

Исходный Trivy (frontend): 6 HIGH — nginx 1.30.5-r1 (CVE-2026-15176, CVE-2026-93479, CVE-2026-97205), curl 8.22.0-r0 (CVE-2026-92392), brotli-libs 1.2.0-r1 (CVE-2026-111497).

Изменение `frontend/Dockerfile`:

```dockerfile
FROM nginx:1.30.6-alpine@sha256:47928bf67eb62a1863cb08d9ecb52d3e704304ba614eaee17884204677702951
RUN apk upgrade --no-cache && apk add --no-cache libexpat=2.9.0-r0 pcre2=10.49-r0 tiff=4.7.2-r0 libx11=1.8.14-r0
```

- `apk upgrade` подтянул curl 8.23.0-r0, brotli-libs 1.2.1-r0, nginx 1.30.6-r1; digest базового образа закреплён.
- Backend image (`python:3.13.16-alpine3.24` + `apk upgrade`) не менялся; его скан в CI был чистым.
- Проверки: сборка `sso-frontend-audit`; Trivy 0.75.0 `--scanners vuln --severity HIGH,CRITICAL` → **0**; `nginx -t` под `--read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges`; uid 101 non-root; build-info присутствует; `*.map` отсутствуют.
- Runtime policy (`scripts/check_container_runtime.py`) выполняется в CI; локально Compose-контур не перезапускался после изменения образа, но image-level проверки пройдены.

## 4. CodeScene (PR #35) — 27.10.2026

Проверка `CodeScene Code Health Review (main)` выполняется как GitHub check и анализирует точный HEAD PR.

**Исходный результат** на `0bbe31b`: gate `Prevent hotspot decline` **FAILED**; `frontend/src/api/client.ts` Code Health 9.39 → 8.82, две находки:

1. `ApiClient.storedSessionReadGrant` — Complex Conditional: проверка валидности из трёх условий (`typeof authorization`, `typeof expiresAt`, `expiresAt <= now`) в одном `||`-выражении.
2. `ApiError.constructor` — Excess Number of Function Arguments: 5 > 4 после добавления `retryAfter`.

**Рефакторинг** `5cf9c68`:

- разбор grant вынесен в маленькие функции `isRecord`, `isFutureTimestamp`, `validateStoredGrant`, `parseStoredGrant`, `readStoredGrant`; каждая проверка — отдельное простое условие, `storedSessionReadGrant` содержит два простых ветвления;
- `ApiError` принимает типизированный `ApiErrorInit` (один аргумент); `message/status/code/route/retryAfter`, `instanceof ApiError`/`Error` сохранены, обновлены все call sites и Sentry classifier test;
- поведение не изменено: server-owned `expires_at`, очистка при corrupted/invalid/expired/недоступном storage, grant только для `GET /api/v1/auth/sessions`, mutations его не используют.

**Результат** на `5cf9c68`: check **success**, «Quality Gate Passed», **3/3 gates passed**, аннотаций нет; старые inline review comments CodeScene удалил после успешного анализа (API: 0 comments/0 threads). Численное значение Code Health в публичном check не раскрывается, а CodeScene UI недоступен из этой сети (CloudFront HTTP 403); gate подтверждает отсутствие decline относительно baseline 9.39. Эвристика `Absence of Expected Change Pattern` остаётся advisory и не устранялась правкой `DashboardPage.tsx`.

Локальные проверки рефакторинга: `session-grants.component.test.tsx` **18 passed**, components **64 passed**, unit 14, lint/typecheck/typecheck:tests/build PASS, Playwright default-off **49** + enabled **9** passed.

## 5. Что осталось за рамками

- Фактический GitHub Actions run для нового HEAD — после push; локальные результаты не заменяют remote CI.
- Windows safety jobs и CD policy jobs не воспроизводились локально (unit-наборы для них входят в общий pytest).
- SES external job по-прежнему требует credentials и не считается проверкой доставки.
- CodeScene UI недоступен из сети аудита; использован GitHub check/review API (точный head SHA и результат зафиксированы).

## Первый PR run 40404078649 (HEAD 0342046)

- **Green:** Security & Dependencies, SDK, Containers/Trivy, CD policy/EC2, Windows safety, Version.
- **Backend:** `test_login_totp_code_cannot_be_reused_for_reauthentication` упал с `assert 200 == 401`. Причина — дефект самого теста: код TOTP генерировался повторно по текущему времени, и через границу 30-секундного шага во второй запрос уходил уже следующий код (легитимно принимался). Исправлено: код фиксируется один раз для login и replay; в spent-step тесте используется код точного шага (`_code_at_step`); «неверный» код исключает расширенное окружение шагов. Проверка через границу окна: 4 passed. Продукт replay не пропускал.
- **Frontend job cancelled по 10-минутному timeout:** шаг `playwright install --with-deps` скачивал apt-пакеты с медленного зеркала 9+ минут (лог: Get:2…Get:16, 21:25→21:34), гейт не падал. Timeout job увеличен до 25 минут; сам гейт не изменён и обязателен. Playwright E2E job прошёл за 13.5 мин при лимите 15 → лимит увеличен до 20.
- **Playwright E2E:** success (default-off + enabled).

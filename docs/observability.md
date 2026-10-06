# Наблюдаемость Sentry

Сверка документации: 06.10.2026, продукт 0.2.0. [Реестр и границы](index.md), [статус](status.md). Прежние измерения/PASS относятся к указанным датам и ревизиям.

Реализация SENTRY-01..07, ADR-0010. По решению владельца используются два проекта одной организации EU/DE: `alxprgs-sso-backend` (FastAPI) и `alxprgs-sso-frontend` (React). Browser отправляет данные напрямую. SDK закреплены: Python 2.71.0, JavaScript/bundler plugins 11.2.0, CLI 3.8.0. Отдельный Python SDK и demo clients не зависят от Sentry.

## Конфигурация и включение

По умолчанию отправка выключена. `.env` игнорируется; credentials и реальные DSN не копировать в документы, artifacts или сообщения диагностики. DSN публичен для browser ingestion, но не даёт прав чтения/управления проектом. Upload token — секрет, только protected GitHub Secret.

| Runtime setting | Default | Назначение |
| --- | --- | --- |
| `SENTRY_ENABLED`, `SENTRY_FRONTEND_ENABLED` | `false` | Независимое включение ошибок компонентов |
| `SENTRY_DSN`, `SENTRY_FRONTEND_DSN` | пусто | Отдельные HTTPS ingestion DSN |
| `SENTRY_ENVIRONMENT` | выводится из `ENVIRONMENT` | `local`, `test`, `staging`, `production` |
| `SENTRY_TRACES_SAMPLE_RATE`, `SENTRY_FRONTEND_TRACES_SAMPLE_RATE` | `0` | Root sampling; конечные числа `[0,1]` |
| `SENTRY_REPLAY_ENABLED` | `false` | Дополнительный staging gate |
| `SENTRY_REPLAYS_SESSION_SAMPLE_RATE`, `SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE` | `0` | Replay sampling `[0,1]` |

Environment defaults: development→local, testing→test, production→production. Staging использует `ENVIRONMENT=production`, `SENTRY_ENVIRONMENT=staging`, настоящие HTTPS origins и production security policies. Значение `SENTRY_RELEASE` берётся из build metadata; runtime override не применяется. Пустой DSN отключает соответствующий ingestion даже при включённом flag. В обычном testing backend не создаёт transport; специальные тесты передают transport явно. Runners принудительно выключают обычную test telemetry.

`GET /api/v1/auth/telemetry-config` публичен, `Cache-Control: no-store`, без обращения к БД. Возвращает frontend flags/DSN/environment/rates и точные propagation targets. Не возвращает backend DSN, credentials, user data. Bootstrap запрашивает его без cookies и ждёт не более 300 ms; неверный ответ/отказ не мешает React render. Privacy нельзя ослабить через ответ endpoint.

WEB-PERF-01: лёгкий frontend facade не импортирует Sentry SDK в начальной загрузке. Runtime загружается асинхронно при включённой конфигурации и согласии, с повторной проверкой согласия/generation после загрузки; `initializeTelemetry` возвращает `Promise<boolean>`. Отзыв синхронно запрещает работу существующего клиента до его асинхронного закрытия. Runtime transport/sanitization/Replay policy сохраняются. Source-owned React ErrorBoundary отображает локальный fallback и передаёт фиксированную обобщённую ошибку без exception text/component values; ошибки до инициализации SDK не буферизуются. Тестовый harness ожидает инициализацию; browser suite перехватывает synthetic SDK payloads локально и запрещает остальные внешние соединения. [ADR-0022](adr/0022-frontend-critical-loading.md).

Порядок rollout: errors с нулевыми traces/Replay → staging privacy/source-map smoke → tracing `0.01` для обоих компонентов → отдельная Replay-приёмка → staging Replay `0 / 0.10`. Flags остаются false до соответствующей live-приёмки. Production Replay выключен кодом независимо от flags/rates.

## Capture и privacy

Framework integration отправляет unexpected exceptions и HTTP 5xx ровно один раз. 4xx authentication/authorization/OAuth/feature/validation/404/409/429 не создают Issues. Перехваченный capabilities DB failure и проглоченная mail failure отправляются отдельно с фиксированным operation tag. Для ошибки, которая затем становится 5xx, повторный capture не добавляется. Logging integration не подключён; audit events остаются в PostgreSQL.

События, transactions и envelope metadata проходят allowlist. Сохраняются exception type, безопасное расположение stack frames, зарегистрированный route template, method/status, timings/trace IDs, fixed component/operation/provider metadata и artifact release/environment. Exception values заменяются фиксированной категорией. Request/response bodies, cookies, headers, query/fragment, user/IP/geo, extras, SQL text/parameters, driver messages, mail MIME/recipients/subject/MessageId, свободные logs/messages, locals и attachments не отправляются. SDK data collection выключена явно; SQL engine использует `hide_parameters=True`.

Stdout formatter выдаёт ограниченный JSON; Uvicorn access logs нормализуют route и не выводят query, клиентский IP и произвольный request ID. Nginx access logs содержат method/status/duration. Сырые логи не экспортируются. `/health/*`, config endpoint, OPTIONS и неизвестные scanner routes не создают transactions; health errors не создают events. Discovery/JWKS roots ограничены `0.001`. Эти exclusions и rate=0 имеют приоритет над parent sampling; затем принятый parent продолжается. Browser headers разрешены только для текущего origin `/api/` и `/oauth/`; внешний redirect/demo origin исключён. Backend outgoing propagation выключена. Входной baggage очищается до framework SDK; `strict_trace_continuation=True` не является аутентификацией headers.

Mail span `email.send` сохраняет только provider, operation, template, result. Существующий `asyncio.to_thread` переносит context; новые workers/очереди приложения не добавлены. SDK использует собственный ограниченный background transport; handlers не flush telemetry, shutdown ждёт до двух секунд. Init/ingestion failure не меняет auth policy.

## Ограниченный staging Replay

Replay загружается отдельным локальным chunk. Все auth/dashboard/admin views, включая Navbar и secret dialogs, блокируются общим `[data-sentry-block]` контейнером. Текст/inputs маскируются, media блокируются; unmask/unblock, network detail URLs и headers пусты, bodies выключены. Console/network/custom recording events удалены. Максимальная длительность — пять минут.

У SDK 11.2 rrweb Meta не проходит `beforeAddRecordingEvent`; поэтому recorder не запускается на initial URL с query/fragment. Это касается verification token и return_to ещё до React effect. Worker размещён на том же origin, без CDN/blob. Перед закреплённым compression worker выполняется локальная allowlist-проекция rrweb: фиксированные URL routes, masked text, ограниченные numeric geometry/IDs, фиксированные tags и block dimensions; произвольные DOM attributes/CSS удалены. Replay показывает только безопасную оболочку и позиции, оформление может быть неполным.

Перед ingestion transport распаковывает recording и требует marker очистки каждого event. Ошибка parsing/decompression, отсутствие Worker или неподдерживаемый protocol приводит к отказу отправки всего Replay envelope. Ошибки UI продолжают отправляться. Этот дополнительный протокол привязан к 11.2.0: upgrade требует нового аудита настоящих сжатых recordings. Production не подключает recorder/worker или эти async chunks. SDK privacy harness проверяет реальные serialized envelopes; это не заменяет полноценный SSO E2E на PostgreSQL с default-off/enabled MFA.

## Build, private maps и trusted release

Identity: `alxprgs-sso@<VERSION>+<full 40-character SHA>`. `python scripts/build_identity.py` проверяет текущую revision; `--expected-sha` требует точного совпадения. Для локального source smoke можно сохранить generated resource:

```powershell
python scripts/build_identity.py --out backend/app/_build_info.json
```

Resource игнорируется и не является вручную редактируемым источником версии. Hatch hook включает identity в wheel/sdist; FastAPI version берётся из неё. Docker получает проверенный `ALX_BUILD_SHA`; start scripts вычисляют его через Git. Локальная dirty сборка маркируется `source_tree_dirty=true` и не допускается к live release upload. Production использует clean tagged artifacts.

```powershell
python scripts/release_bundle.py build --outdir artifacts/release-check --private-maps artifacts/sentry-private-check
python scripts/release_bundle.py verify --outdir artifacts/release-check --expected-sha <FULL_SHA>
python scripts/sentry_release.py --release-dir artifacts/release-check --private-maps artifacts/sentry-private-check --expected-sha <FULL_SHA>
```

Каталоги вывода должны отсутствовать или быть пустыми; прежние outputs не удаляются. Последняя команда без `--upload` не делает сетевых mutations и не требует credentials. Для настоящего выпуска добавляются существующий tag и `--require-clean`; version preparation/release authority описаны в [releases.md](releases.md).

Release Vite использует hidden maps, Debug IDs injection и `disable-upload`; plugin telemetry/debug/release create/finalize выключены. Для Vite 8 entry-map serialization после injection восстанавливается только metadata Debug ID из точного JS. JS/map pairs, hashes, artifact identity и deployment archive проверяются; frontend не пересобирается после upload. Worker не содержит приложение/TSX и не требует private application map. Source maps копируются в отдельный private bundle до удаления из dist; архив/image не содержит `.map`, Nginx возвращает 404. Test harness не входит в deployment artifact.

`prepare-sentry-release` использует trusted workflow revision, проверяет download artifacts, устанавливает фиксированный CLI без credentials. Release создаётся с `dateReleased=null`, `ref=SHA`, commit URL и только commit IDs; GitHub App/repository association не требуется. После server-side CLI validation проверяются проекты/version/ref/url/lastCommit; лишь затем задаётся release date. Повтор сохраняет уже установленную дату. Token доступен только единственному upload step: там не выполняются install/build/scripts tagged checkout. Variables: `SENTRY_ORG`, `SENTRY_PROJECT_BACKEND`, `SENTRY_PROJECT_FRONTEND`, `SENTRY_URL=https://de.sentry.io/`, `SENTRY_RELEASE_UPLOAD_ENABLED=false` по умолчанию. `SENTRY_AUTH_TOKEN` хранится в protected GitHub Secret. Предпочтителен organization CI token с минимальным `org:ci`; фактические scopes/операции проверяются в выбранной организации. Commit association передаёт только проверенный SHA/repository URL/ID, без author email/full message.

`dry_run=true` и выключенный upload выполняют только offline validation. При включённом upload отсутствие credentials/ошибка blocks draft. Private intermediate retention — один день; он не включён в GitHub Release. Build не создаёт deploy record. CD остаётся полностью закомментированным; будущий deploy record разрешён только после успешного health check.

## Proxy, CSP и server settings

Генератор CSP принимает только validated public frontend DSN и разрешает точный ingest origin:

```powershell
python scripts/render_sentry_csp.py --dsn <FRONTEND_PUBLIC_DSN> --out artifacts/sentry-csp.conf
```

По умолчанию генератор выдаёт enforced CSP; основной proxy также применяет enforced policy. `--report-only` — явный временный диагностический выбор staging. `--enforce` сохранён для совместимости. До смены точного ingest origin выполните браузерную проверку, включая blocked-ingestion сценарий. Scripts/styles/workers self, images self/data, object none, base self, frame ancestors none. Snippet подключается через `frontend/security-headers.conf` и `/etc/nginx/snippets/sso-csp.conf` внутри image либо include внешнего proxy. Для runtime origin монтировать generated snippet read-only и проверить `nginx -t`; в готовом release image frontend JS не менять. TLS/trusted proxy security не ослаблять. Default snippet не разрешает Sentry до настройки точного origin.

В обоих Sentry проектах до rollout включить server-side scrubbing, sensitive fields, запрет хранения IP и удалить geographic context. Прямая browser отправка всё равно раскрывает IP соединения ingestion-сервису. Эти настройки SaaS требуют отдельной фактической проверки; client-side projection уже удаляет данные до выхода из приложения. Проверить Student activation, billing period, units и On-demand disabled непосредственно в организации.

## Проверки и live-приёмка

Offline команды из корня (Windows: `PYTHONPATH=.;backend`, Linux: `PYTHONPATH=.:backend`):

```text
pytest tests/test_sentry.py tests/test_release_bundle.py
pytest tests/integration/test_sentry_pg.py
npm --prefix frontend run test:telemetry:browser
```

PG тест требует `TEST_DATABASE_URL` и существующий safety marker из [подготовка тестирования](testing/README.md). Он реально выполняет SQLAlchemy query и проверяет timings/очистку spans. Подмена SQLite/mock не засчитывается. Browser harness перехватывает real SDK envelopes; decompression mandatory, production hard-off и missing-worker fallback проверяются отрицательно. Обычные SSO browser suites/default-off/enabled и SES/testmail checks остаются обязательными.

Staging acceptance: проверенный artifact и maps upload до запуска → временный synthetic harness вне production artifact → один controlled backend и frontend failure → проверить Issue release/environment/исходную TSX location → вручную просмотреть error/trace и decompressed Replay → реальные PG/mail/distributed tracing → сравнение disabled/enabled на одном стенде. Предлагаемые overhead gates: backend p95 рост ≤max(5 ms,5%); основной frontend gzip рост ≤100 KiB; в production startup отсутствуют recorder/worker downloads. Размер bundle сам по себе не подтверждает p95 или production smoke.

На 02.10.2026 организация EU и public DSN подтверждены владельцем. GitHub execution, upload/source association, staging hostname/privacy settings/alerts, staging PG/mail/distributed tracing и backend p95 остаются отдельными live-критериями. Локальные guarded PostgreSQL и оба обычных SSO/MFA browser профиля проверены; main gzip delta проверен на одном стенде. Фактические локальные результаты и продолжение — [acceptance.md](acceptance.md), [status.md](status.md).

## Alerts, quota и отключение

Перед rollout создать owner/team rules в обоих проектах: production new issue/regression; unexpected spike ≥20 events/5 minutes, повтор не чаще часа. Wrong password/OTP/403/429 не входят. Performance alert добавлять после baseline. Настройки rules ещё требуют выполнения в SaaS.

Ориентир Student offer: 50K errors, 100K transactions, 500 replays, 1 GB attachments; фактический billing проверить в организации. Attachments не отправляются. Общие рабочие бюджеты обоих проектов: 35K errors, 70K transactions, 350 replays. Usage прогнозировать как текущий расход ×дней периода/прошедших дней; rollout проверять регулярно, затем еженедельно и после releases. При прогнозе выше бюджета делить trace/Replay rates на два; при 85% quota выключать новые traces/Replay. Unexpected errors первоначально сохранять, шум фильтровать только после диагностики. Parent sampling и поддельные headers не дают жёсткой гарантии quota.

Для 30 дней: transactions≈30×(backend requests/day×sB+browser roots/day×sF). При 1000/day в каждом компоненте и rates 0.01 получается 600 transactions/month; это расчётный пример, не измерение трафика. Replay≈30×staging sessions/day×unexpected error fraction×0.10. При 1000 sessions/day и 1% ошибок — 30/month, production — 0.

Rollback: flags компонента false → SDK не инициализируется; tracing rates 0; Replay flag false и rates 0. Backend пересоздать с новым runtime env; frontend config вступает в силу при reload. Уже открытые вкладки требуют reload. Полный rollback использует предыдущий проверенный artifact с его собственной identity. Безопасные logging/SQL/readiness исправления сохраняются.

Официальные материалы: [Python privacy](https://docs.sentry.io/platforms/python/data-management/data-collected/), [React options](https://docs.sentry.io/platforms/javascript/guides/react/configuration/options/), [Replay privacy](https://docs.sentry.io/platforms/javascript/guides/react/session-replay/privacy/), [source maps](https://docs.sentry.io/platforms/javascript/guides/react/sourcemaps/uploading/vite/), [server-side scrubbing](https://docs.sentry.io/security-legal-pii/scrubbing/server-side-scrubbing/), [Student offer](https://education.github.com/pack). SDK/bundler licenses MIT; CLI FSL-1.1-MIT, build tool `sentry` FSL-1.1-Apache-2.0. Это tooling licenses; закрытая лицензия приложения не меняется.

## Privacy consent и housekeeping

Браузерный Sentry дополнительно требует diagnostics consent; Replay — отдельный consent, diagnostics и server staging. Отзыв выключает client/transport, stop Replay с flush:false; изменения storage синхронизируют вкладки. Отказ и недоступный storage не блокируют SSO. Выбор 180 дней без user identity, malformed/expired fail-closed. Серверные errors остаются отдельным очищенным каналом.

Worker проверяет due erasure при startup и раз в минуту; ошибка пишет фиксированную категорию privacy_maintenance_failed без payload/exception text/PII и повторяется на следующем tick. Для эксплуатационного alert проверяйте `SELECT count(*), min(deletion_scheduled_for) FROM users WHERE deletion_scheduled_for <= clock_timestamp()`; растущая задержка требует проверки DB/worker, а не переноса срока. Audit retention 90d, journal 30d, краткие rate-limit windows независимы. Log/backup quotas и фактические сроки Sentry SaaS до production подтверждает оператор.

## Статус тарифных ориентиров

Student quota и бюджеты выше — исторические/расчётные ориентиры, не подтверждённые условия текущего аккаунта. До включения оператор сверяет фактический план и usage в SaaS. Default .env.example/Compose задаёт SENTRY_ENVIRONMENT=local; для production/staging это значение нужно выбрать явно, автоматический вывод Settings работает только при отсутствии override.

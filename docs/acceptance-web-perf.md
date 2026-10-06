# WEB-PERF-01 — загрузка frontend

Локальная проверка 06.10.2026, Codex. Основание: пользовательский Lighthouse report с Performance 84, FCP 3.1 s, LCP 3.6 s и замечаниями cache/render-blocking/unused JS. Эти цифры предоставлены владельцем, самостоятельно этот Lighthouse run не воспроизводился.

Внесены cache policy Nginx, объединение tokens CSS, preload Geist, параллельный auth bootstrap, DeferredDialog для Feedback/reauth и условная загрузка Sentry runtime. Подробности/альтернативы — [ADR-0022](adr/0022-frontend-critical-loading.md). Новые зависимости не добавлены, browser target не изменён. Синхронный theme script оставлен для правильной темы до первого кадра и сохранения CSP.

## Измерения

Стенд: локальный Docker frontend Nginx, существующий backend; публичная `/login`, без авторизации. Chromium 153.0.8010.12 через Playwright/CDP, viewport 390×844, CPU slowdown 4, latency 150 ms, download 200000 bytes/s, upload 93750 bytes/s. Каждый из трёх запусков использует новый browser context, cache disabled. После видимого заголовка и networkidle читаются PerformanceObserver LCP/CLS и PerformanceResourceTiming encodedBodySize; тексты страниц/пользовательские данные не сохраняются. Последние замеры выполнены без одновременных тестовых прогонов.

| Показатель | До | После |
| --- | ---: | ---: |
| Медиана FCP | 2204 ms | 1796 ms |
| Медиана LCP | 2204 ms | 1796 ms |
| Медиана CLS | 0.07821 | 0.07744 |
| Загруженный JS, encodedBodySize | 273164 bytes | 144854 bytes |
| JS/CSS/WOFF2, encodedBodySize | 353702 bytes | 225316 bytes |

Результаты: [before](acceptance-web-perf-before.json), [after](acceptance-web-perf-after.json). FCP/LCP уменьшились на 18.5%, JS на 47.0%, все перечисленные ресурсы на 36.3%. Промежуточный cache/dialog-only вариант не показал ускорения FCP и не принят как итоговый результат; фактические сведения сохранены в worklog. Три локальных замера имеют ограниченную статистическую силу. Эти измерения не используют Lighthouse simulated throttling, не измеряют TBT/Speed Index и не дают нового Lighthouse score. Пользовательский отчёт мог быть получен на другом маршруте/авторизованном профиле.

## Проверки и воспроизведение

Из `frontend/`:

```text
npm run build
npm run lint
npm run typecheck:tests
npm run test:unit
npm run test:components
npm run test:telemetry:browser
```

Для HTTP/UI browser checks установить `PLAYWRIGHT_BASE_URL=http://localhost:3000` и выполнить `npx playwright test e2e/csp.spec.ts e2e/appearance.spec.ts` против локальной Docker source-сборки. Source identity задаётся проверенным `ALX_BUILD_SHA`; пересборка выполнялась `docker compose --env-file .env -f docker-compose.yml up -d --build --no-deps frontend`. Только frontend пересоздан, БД/backend не изменены. `docker exec alxprgs-sso-frontend nginx -t` проверяет настоящую конфигурацию.

Build/Docker build, lint/test-types и unit 13 PASS. Components 39 PASS, включая реальный SDK transport, sanitized source ErrorBoundary и отзыв согласия во время import. Telemetry browser 9 PASS/20 s с настоящим SDK/Replay и локальными перехваченными payloads; общий context guard запрещает внешний egress. Первоначальный auto-review отказ из-за возможного Sentry egress устранён доказанными route intercepts и явным guard, не внешней отправкой. Browser UI/cache/CSP/UTF8 финальный результат фиксируется ниже после завершения прогона. Полный PostgreSQL/OIDC E2E, production Nginx и Lighthouse не запускались в этой задаче.

В ходе проверки исправлен синтаксис quoted regex Nginx (неудачный запуск и остановленный browser run не считаются PASS). Тесты не пропускаются, assertions не ослаблены, timeouts не увеличены; async capture/modal ожидания отражают реальные lazy операции.

Финальный browser прогон 2026-10-06T03:44:55.6268903+03:00: 40 PASS/1.3 min (37 appearance UI fixtures +3realNginx HTTP/CSP/UTF8/cache tests). No consent: runtime/Replay/Dialog chunks не запрашиваются, CSS tokens не загружаются отдельно; существующие hashed assets имеют TTL1year и CSP/nosniff, mutable TTL1h, HTMLno-cache; missing assets/maps404 без cache. Secret scan135/0new PASS.

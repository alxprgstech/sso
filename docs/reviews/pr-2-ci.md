# Анализ GitHub Actions для PR #2

Задача REVIEW-CI-02-01; исполнитель: текущая рабочая сессия. Начало 2026-10-03T20:15:49.4264720+03:00; завершение 2026-10-03T20:25:34.844787+03:00. Ветка new, HEAD 3dbd10b6765260ead3ffe9f1eb6b4357430b6348.

Источник: [CI run 37137927331](https://github.com/alxprgstech/sso/actions/runs/37137927331), event pull_request, attempt 1, completed/failure. API и логи подтверждены для текущего PR HEAD. Это дополнение к [анализу CodeScene](pr-2-codescene.md), а не другая интерпретация его метрик.

## Backend: format check

[Backend job](https://github.com/alxprgstech/sso/actions/runs/37137927331/job/111246191953) остановился на шаге Run Ruff Lint and Format check.

- `ruff check backend/ tests/ packages/python-sdk/ scripts/ examples/` прошёл.
- `ruff format --check backend/ tests/ packages/python-sdk/ scripts/ examples/` вернул exit 1: 11 файлов нужно форматировать, 131 уже отформатирован.
- Обе команды повторены локально с Ruff 0.16.8: lint passed, format failed с тем же списком.
- Mypy, миграции и backend pytest в этом job skipped. Их нельзя считать failed тестами или успешной приёмкой.

Список файлов:

- `scripts/run_overnight_stability.py`
- `tests/conftest.py`
- `tests/db_guard.py`
- `tests/integration/test_concurrency_pg.py`
- `tests/integration/test_email_verification_pg.py`
- `tests/integration/test_registration_pg.py`
- `tests/integration/test_testmail_email_pg.py`
- `tests/test_mfa_features.py`
- `tests/test_ops_backup_restore_totp.py`
- `tests/test_registration.py`
- `tests/test_sso_cross_clients.py`

Это переносы аргументов, словарей и assertions, а также пустые строки. Исправление — применить штатный Ruff formatter к перечисленным файлам и повторить обе полные команды. Изменять правила Ruff или исключать файлы не требуется.

Уточнение прежнего локального отчёта: последний UI этап проверял format только для четырёх Python файлов. Это не подтверждало успешный format check всей области CI. Более широкое прежнее указание «Ruff passed» следует читать как lint; полный formatter на текущем HEAD не проходит. Эта запись явно корректирует область подтверждённых проверок без переписывания истории.

## Playwright: resize и резерв cookies

[Playwright job](https://github.com/alxprgstech/sso/actions/runs/37137927331/job/111246191977): 27 сценариев, 26 passed, один failed.

Упал `dashboard, QR and modal surfaces: light` в [appearance.spec.ts](../../frontend/e2e/appearance.spec.ts), строки 196–215. После `setViewportSize(390×844)` helper `bannerAtBottom` (строки 46–55) сравнивает ранее прочитанную высоту баннера с padding контейнера. На строке 52 ожидается разница меньше 2 px, получено 105.18787499999999 px.

Подтверждена рассинхронизация layout: [CookieBanner](../../frontend/src/components/PrivacyControls.tsx), строки 24–33, сохраняет измерение в `--cookie-banner-height` через resize/ResizeObserver; [CSS](../../frontend/src/index.css), строка 282, использует его для padding app-shell. После смены ширины высота баннера может уже измениться, а callback ещё не обновил переменную. Немедленная проверка попадает в этот промежуток. Разные DOM-вызовы helper дополнительно не образуют единый снимок layout.

Диагностика на неизменённом frontend build и отдельном localhost preview, Chromium, с явно подставленными UI API-контрактами:

- Исходный тест: `playwright test e2e/appearance.spec.ts --grep 'dashboard, QR and modal surfaces: light' --repeat-each=8 --output=test-results-ci-diagnosis --reporter=line` — 8 passed. Это диагностическая серия, не исправление и не переоценка failed CI. Первая попытка с anchored grep не выбрала тестов; pattern исправлен.
- Отдельный read-only probe: 30 чередований desktop/mobile, 22 немедленных несовпадения. В одном из них banner 261.171875 px, padding 155.984 px; разница **105.18787499999999 px**, совпадающая с CI.
- После двух requestAnimationFrame в каждом из 30 измерений разница меньше 2 px; постоянных несовпадений 0. Probe не меняет ResizeObserver, приложение или безопасность. Проблема воспроизведена на уровне DOM-геометрии; визуальное перекрытие в отрисованном кадре этим отдельно не доказано.

Предлагаемое исправление: предпочтительно резервировать нижнюю панель самой CSS-раскладкой внутри viewport, устранив зависимость пространства от отложенного JS измерения. Если измерение сохраняется, необходимо явно проверять согласованное состояние после resize. В тесте собирать размеры баннера/reserve/scroll area одним evaluate и ждать проверяемого условия (`expect.poll`), сохраняя строгий допуск 2 px и отсутствие перекрытия. Слепая задержка, увеличение допуска или retries не исправляют причину.

Официальные ссылки: [ResizeObserver processing model](https://drafts.csswg.org/resize-observer/) и [Playwright assertions / expect.poll](https://playwright.dev/docs/test-assertions#expectpoll).

Enabled профиль в CI не стартовал из-за default-off failed step. Три настоящих default-off privacy сценария, ordinary SSO, реальная самостоятельная регистрация и двухклиентский SSO в этом run прошли; это не заменяет skipped enabled проверки.

## Другие jobs этого run

Шесть внутренних jobs successful: Verify Version Consistency, Verify Inactive CD Template, Sentry Container Packaging, SDK Package Build & Clean Install, Security & Dependencies Scan, Frontend Build & Typecheck. Последние включают свои проверки зависимостей/секретов/типов/сборки и SDK browser harness, как указано в workflow. Это наблюдаемый remote результат для данного SHA, не общая production приёмка.

Real SES email integration and browser E2E skipped по условию PR; это отдельное предусмотренное ограничение, не следствие Ruff. Внешние юридические/SES/Sentry условия и общая приёмка остаются отдельными.

## Дальнейшая работа и границы

Сначала устранить форматирование и рассинхронизацию resize; затем необходимая backend/PostgreSQL и default-off/enabled браузерная регрессия, новый CI. CodeScene рефакторинг и повторный анализ сохраняются как отдельная группа требований.

Код и workflow не менялись, исправления/commit/push/rerun CI не выполнялись. Локальные результаты находятся в рабочих документах; сырые CI logs/probe в ignored artifacts/ci-pr2, не для коммита. Собственный preview остановлен после диагностики; пользовательский localhost:3000 не изменялся.

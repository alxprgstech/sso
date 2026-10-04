# Исправления проверок PR 5

Задача PR5-CI-01, статус in_progress. Исходный неуспешный запуск:
[37200621991](https://github.com/alxprgstech/sso/actions/runs/37200621991),
head `3a2aac35c5bc3ea6813c4a2fa94ade27ece068f6`.

| Проверка | Наблюдаемая причина | Исправление |
| --- | --- | --- |
| Frontend | Release build context исключал nginx-main.conf | Полный allowlist необходимых конфигураций и regression test COPY |
| Backend | SMTP-тест зависел от testing-only sink, процессные лимиты накапливались между тестами, редкий session key не проходил production policy, lifecycle не имел frontend dependencies | Токен из реально полученного SMTP-письма, изоляция на границе теста, rejection sampling прежних 512 случайных бит, обязательная сборка frontend в backend job |
| Windows | Три PostgreSQL-теста выбраны в job без PostgreSQL | Маркерное разделение платформенных unit-проверок; реальная PG-защита остаётся в обязательном полном backend job |
| Enabled E2E | TOTP confirm получил 429 после предыдущих независимых Passkey-сценариев | Явный beforeEach seed с очисткой rate windows только на базе с проверенным маркером; лимиты внутри сценария сохранены |
| Containers | Trivy нашёл HIGH/CRITICAL в старой Debian 12 базе и инструментах установки; Debian13 оставил45HIGH | Официальный Python 3.13.16 / Alpine3.24 по проверенному digest; удаление ненужных curl/PG client/pip/setuptools/wheel из runtime, проверка musl-совместимости обязательным Compose job |
| CodeScene | Сложные и длинные методы, чрезмерные параметры, смешение обязанностей | Рефакторинг остаётся in_progress; подавление замечаний и изменение gates не выполняются |

Обоснование: [ADR 0017](../adr/0017-ci-runtime-and-test-isolation.md).
Очистка counters по умолчанию выключена в seed; включается только явно перед
независимым браузерным тестом. Regression test подтверждает отказ очистки без
маркера и сохранение данных после такого отказа. Отдельные тесты исчерпывают
полный процессный лимит и требуют HTTP 429.

## Локальная проверка 2026-10-04T18:14:24.000+03:00

- 84 unit tests, 4 PostgreSQL cases deselected в отдельном unit-прогоне,
  2 PowerShell subtests: PASS. Новый basetemp находится в ignored artifacts.
- 71 focused tests с настоящим PostgreSQL: PASS, 347.71 s. Включены генератор,
  CSRF rotation, SMTP/email identity, feature profiles, marker protection и
  rate limiting между отдельными процессами. Этот результат не заменяет полный CI.
- Frontend lint, test typecheck и production build: PASS. Vite сообщает обычное
  предупреждение о размере основного chunk; ошибки сборки нет.
- Ruff check и format check по всему проекту: PASS до выделения collection helpers;
  повторная проверка conftest запускается после изменения.
- Enabled Chromium/Nginx suite и новый GitHub run: pending; Trivy на обновлённом
  образе и CodeScene пока не подтверждены.

Первый focused run не PASS: 15 passed / 56 setup errors из-за неверного порта
локального стенда и недоступного прежнего pytest temp. Свой PostgreSQL безопасно
перезапущен на 127.0.0.1:5433 после проверки отсутствия других клиентов; новый
basetemp устранил проблему каталога. Защита БД не изменялась.

SES skips в обычном PR разрешены CI-03; доставки они не доказывают.
Слияние, production, выпуск версии и настоящая рассылка не выполняются.

## Повторная диагностика 2026-10-04T18:37:09.000+03:00

Head `820240eb49a83db02fd2c47f266ceb34f006ba06`,
[run37212573835](https://github.com/alxprgstech/sso/actions/runs/37212573835):
frontend, Windows, browser E2E, SDK, source security, version и CD — PASS.
Backend default-off — PASS; enabled step выявил ещё3 testing-only SMTP sink
в Passkey helper (17passed/3failed). Исправлено получение токена из доставленного
письма; точный enabled набор при development ENVIRONMENT и трёх включённых MFA
прошёл20tests62.78s на настоящем PostgreSQL. Политика verified email сохранена.
Trivy на Debian13:45HIGH/0CRITICAL, неPASS; Alpine candidate ещё не проверен.
CodeScene: collection hook теперь10.00, остальные23новых файла и6hotspots
остаются failed до дальнейшего рефакторинга.

Локальный enabled Nginx campaign завершился до браузерных тестов: backend startup
превысил установленный15s readiness deadline. НеPASS, timeout не увеличивался;
owned Nginx/SMTP остановлены. Реальный GitHub browser job на этом head — PASS.
JWT profile decomposition дополнительно проверен96tests с реальными подписями,
35.84s; новые crypto/UI изменения пока отделены от runtime follow-up commit.

## Readiness при остановленной БД — 2026-10-04

Head `1003d14d3e0c87278e770637eae7e66da319e8fa`,
[run37213910502](https://github.com/alxprgstech/sso/actions/runs/37213910502):
все Actions jobs кроме container job — PASS; SES skips по CI-03.
Alpine build, read-only/UID/role checks и browser CSP прошли; следующая проверка
остановки БД завершилась TimeoutError клиентского запроса с неизменным3s deadline.
Readiness теперь ограничивает сам DB await (DNS/connect/pre-ping/query) до2s
через asyncio.timeout и возвращает прежний503. Клиентский deadline/503 assertion
не ослаблены. Unit cancellation/response checks:3passed,1PGcase deselected,0.13s.
Повторный реальный Compose proof и Trivy ещё pending.

CodeScene refactoring текущего working tree: JWT real-signature96PASS;
reauthentication/credential revision/temporary-password/production configuration
62PASS на PostgreSQL33.99s; mypy58files/Ruff PASS. Это промежуточные результаты,
не закрытие всех CodeScene замечаний и не проверка очередного remote head.


## Подтверждённые Actions и quality refactoring — 2026-10-04T21:01:12.890399+03:00

Все обязательные Actions PASS на `c1a6f23f3cb43b77a8dfb6f026bd86adbaa67c77` ([run37215595679](https://github.com/alxprgstech/sso/actions/runs/37215595679)), `1917f9b4045b97f31e1b651866712e4b96f1677a` ([run37217316095](https://github.com/alxprgstech/sso/actions/runs/37217316095)) и `c8fcdcb2bc7c707f0a01be8226cad12a0ef5228d` (exact-head check API). Это включает реальные Linux Compose, DB outage/recovery с прежними deadlines, runtime roles/read-only/non-root, оба Trivy audits, PostgreSQL default/enabled, Playwright и Windows. Только два разрешённых SES skips без credentials; доставка не заявляется проверенной.

ADR0018 фиксирует разделение trust boundaries, реальных lifecycle phases и связанных доказательств. ADR0019 устраняет Any при внутренних импортах: `mypy.ini` задаёт только пути репозитория, без type ignores или глобальных настроек. Новые проверки обнаруживают несовместимую UUID→int assignment именно в импортированном User; проверяют rollback повреждённой регистрации и прежний пятиаргументный Alembic callback. Shared timestamp base не меняет metadata/registry/схему. WebAuthn context не принимает параметры доверия от HTTP-клиента; exact origins/RP ID/UV/purpose и atomic consumption сохранены.

Третья группа локально:112passed89.31s;9passed379.50s import/callback;enabled20passed387.31s. Канонический mypy61files, Ruff check/format, runtime lock и secret self-test PASS. CodeScene последнего отправленного head ещё failed; новый head pending. Исторический audit probe и обязательная сигнатура Alembic не изменяются ради метрики. Полная production/live-приёмка не завершена.

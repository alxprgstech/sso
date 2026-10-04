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
| Containers | Trivy нашёл HIGH/CRITICAL в старой Debian 12 базе и инструментах установки | Официальный Python 3.13.16 / Debian 13 по проверенному digest; удаление ненужных curl/PG client/pip/setuptools/wheel из runtime |
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

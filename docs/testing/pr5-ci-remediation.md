# Исправления проверок PR 5

Задача PR5-CI-01, статус blocked только по двум CodeScene contracts; рабочие причины исправлены. Исходный неуспешный запуск:
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


## Последние рабочие CodeScene замечания — 2026-10-04T21:24:36.410422+03:00

На44c3ff96600bf9aa107ef1bf138814414ad8c664 ([CI37222860411](https://github.com/alxprgstech/sso/actions/runs/37222860411)) все9 обязательных Actions success,2SES skips. CodeScene оставил6files: session lifecycle, discoverable Passkey lookup, overall complexity двух token_profiles, archived probe и Alembic callback.

SessionRequest/SessionAuthorization разделяют входные metadata и доказательство revision/MFA, actual locked-account/lifetime/authorization phases сохраняют consume/audit/commit order. Discoverable lookup разделяет credential ID и active user. token_claims и token_audience отделяют structural types/time и audience/azp от token-use policy; AST review17bodies unchanged у сервера и независимого SDK. Local110passed226.79s с actualPG/RSA; mypy65/Ruff200/runtime lock/secret scan PASS. Remote результат этой группы pending. Дополнительный audit replay103passed/1worker-timeout247.93s сохранён как failed; неизменный30s deadline не увеличен.


## После e97f7e9 — 2026-10-04T21:38:27.846070+03:00

[CI37224469586](https://github.com/alxprgstech/sso/actions/runs/37224469586) exactSHAe97f7e92b98a6ff45e2bfcd3897d15aa4180320a:9Actions success,2SES skips. CodeScene5remainingfiles: consume_temporary_password complexconditional,2token_claims overallcomplexity и2[contracts](codescene-contracts.md). Temporal policy отделена в token_dates;17function bodiesunchanged у обоих independent implementations. Used и missing/expired temporary password guards разделены с прежним отказом. ActualPG/crypto60passed6.82s; mypy67/Ruff202/runtime lock/secret scanPASS. Newcandidate CI ещёpending, CodeScene не объявленPASS.


## Итог source checks — 2026-10-04T21:47:51.194815+03:00

На `f9e06d71c7806d71d9226cfb591585cbf5f3ef83` все9mandatory Actions [PASS](https://github.com/alxprgstech/sso/actions/runs/37225223182),2SES skipsCI03. CodeScene failed только по двум [сохранённым контрактам](codescene-contracts.md); все остальные замечания устранены. Это точный blocker, неуспехгейта не скрыт. Publicpush/PR5разрешён владельцем; merge/deployment/releaseне выполнялись. Следующийdocs-onlyhead проверяется отдельно перед финальнымотчётом.


## Разрешённые исключения — 2026-10-04T22:06:36.934108+03:00

Владелец согласовал ровно два [сохранённых контракта](codescene-contracts.md). Exact-path JSON исключает2complexityrules только у immutablearchive; functiondirective исключает только5argumentssmell include_object. Archive hash и callback AST неизменны,8callback/import regressionsPASS2.32s, Ruff/scansPASS. Новыйremotehead pending; successfulgate ещё не заявлен.


### 2026-10-04T23:31:35.029980+03:00 — Codex, PR5-CI-01: выполнен критерий исправления CI/CodeScene
Начало 2026-10-04T15:04:59.289865+03:00, завершение 2026-10-04T23:31:35.029980+03:00. На `94298ed4cfd05362b08b9b5d778013346554c06c` все **9 обязательных [Actions jobs](https://github.com/alxprgstech/sso/actions/runs/37232030605) успешны**; [CodeScene7806490](https://codescene.io/projects/85555/delta/results/7806490) — success, все 3 quality gates прошли. Два SES jobs skipped по CI-03 без AWS credentials; реальная доставка не проверена.
Владелец разрешил ровно два исключения: точный архивный путь с двумя правилами Complex Method / Excess Number of Function Arguments и локальная директива include_object для обязательных пяти аргументов. Remote analysis подтвердил одну новую директиву; профиль The Bare Minimum и три gates сохранены. Исправление ошибочного первоначального OverallCodeComplexity имени документировано отдельно, не скрыто. Archive SHA-256 byte-exact, callback AST/signature прежние; 8 callback/import tests за 2.32 s PASS, Ruff/scans — 137 кандидатов и 0 новых — PASS; 33 документа, 112 локальных ссылок и 27 статусов (23 CLOSED / 4 PARTIAL) PASS. Прежние failed replay/CI и исторические результаты ae700d7 сохраняются.
PR5 открыт, mergeable=true, другие ветки включены в main. Статус done в рамках исправления remote checks; CI-часть E02 выполнена, tag/release/live HTTPS/email/OIF/operations/private owner review и GOAL-09 не завершены. Production/merge/deploy/release/live emails не выполнялись; собственная PostgreSQL ранее остановлена. Финальный docs-only commit проверяется отдельно; точный финальный head/result будет приведён в чате и описании PR.

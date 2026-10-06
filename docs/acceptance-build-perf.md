# BUILD-PERF-01 — ускорение локальной сборки

## Методика

Исходный пользовательский лог: общий build303,1s, полный builder pip273,7s,
frontend build15,3s; это наблюдение, а не контрольный замер на текущем стенде.
Контрольная ревизия — Git HEAD до изменений; оптимизированная — рабочее дерево
ветки `new/local-build-cache`. Новые зависимости и версии не вводятся.

Стенд: Windows/Docker Desktop, Docker29.8.0, Buildx0.37.1,
отдельный `docker-container` builder `sso-build-perf-20261006`, BuildKit0.33.1.
Логи `--progress plain` и Stopwatch wall time сохраняются локально в
`artifacts/build-perf/` (ignored). Пользовательский builder cache не очищается.
Контексты не содержат `.env` и ключей благодаря существующему `.dockerignore`.

Холодные baseline/optimized сборки могут выполняться параллельно и включают
разные затраты на первоначальную загрузку базовых образов/BuildKit. Их wall time
нельзя использовать как строгий процент выигрыша. Для сравнения причины
пересборки используются последовательные warm/new-SHA сценарии на том же builder.

Команда backend (PowerShell; `$revision` — полный SHA из `git rev-parse HEAD`):

```powershell
docker buildx build --builder sso-build-perf-20261006 --progress plain --load --build-arg "ALX_BUILD_SHA=$revision" -f backend/Dockerfile -t sso-perf-after .
```

Frontend проверяется аналогично с `frontend/Dockerfile`. Повтор без изменений
должен показывать `CACHED`; новый валидный SHA пересобирает identity/application,
сохраняя dependency layers. Изменения source/lock проверяются в отдельной копии
контекста: добавление безопасного комментария в исходник или пустой строки в lock
позволяет проверить invalidation без изменения версий пакетов.

## Текущее состояние

- Build lock:9pins вместо79 full pins, closure `build` + backend build-system;
  runtime/test extras исключены.
- CI проверяет build lock после установки full lock; CI cache storage не менялся.
- `pip check` выполняется после builder dependencies и после установки backend wheel.
- Ruff/import formatting PASS; unit/build-lock + existing security-policy21PASS.
- Docker: оба backend образа и frontend собраны (exit0); wheel/runtime `pip check` PASS.
- Imports/version/SHA/non-dev packages/Nginx/no-public-sourcemaps PASS;
  итоговый backend user10001:10001, pip cache в образ не попал.
- Новый SHA `f95ca174ef586a0481e68877f84d4d889ddf5501` фактически проверен
  внутри обоих SHA-образов; исходный SHA `148d4a885873c66cec304c9a30854e418eb054d7`.
- Отдельный Compose project `sso-perf-20261006`, порт3300/сеть172.30.51.0/24:
  migrations exit0/readiness200/non-root/read-only/capabilities/resources/CSP PASS.
  Тестовый project остановлен; только собственный новый volume удалён с label guard.
  Существующий SSO на3000 сохранён и healthy.
- Docker cache matrix:18 assertions по фактическим plain logs PASS.
  После нового SHA pip/npm установки остаются `CACHED`, identity/application
  пересобираются; source changes сохраняют dependency cache; lock changes
  запускают установки заново. Runtime и повторное builder lock invalidation
  подтвердили `Using cached`; отдельный frontend `npm ci --offline` PASS.

## Результаты замеров

Один последовательный прогон на том же builder, wall time с `--load`, exit0
для всех11 сценариев:

| Сценарий | Backend до | Backend после | Frontend после |
| --- | ---: | ---: | ---: |
| Повтор без изменений |13,66s|14,71s|5,95s|
| Новый SHA |253,16s|25,07s|17,44s|
| Изменение source |—|26,06s|49,89s|
| Изменение build/npm lock |—|36,56s|98,83s|
| Изменение runtime lock |—|52,04s|—|

Backend новый SHA: примерно10,1 раза быстрее (сокращение90,1%) в этом прогоне.
Повтор без изменений существенно не ускорился: ранее он уже использовал layer
cache; экспорт и загрузка образа составляют заметную часть wall time.
Это одиночный замер, не гарантированное время на другой сети/машине.

Cold baseline655,18s, первоначальный optimized294,95s, frontend362,80s.
Окончательный Dockerfile с раздельными cache IDs106,35s при уже выполненной части
общей работы. Эти cold/control цифры **не используются для процента ускорения**:
boot BuildKit/base downloads/concurrent work были различны. Первое builder-lock
invalidation заполнило новый `sso-pip-build` cache; второе подтвердило его reuse.

Исходники source-сценариев и пустые строки/комментарий в lock изменялись только
в отдельном ignored context. Никакие версии зависимостей или production defaults
ради проверок не менялись. Full/runtime locks и команды запуска сохранены.

Ruff check/format PASS; secret scan135candidates/0new; CI workflow cache storage
не менялся. Remote CI, полный браузерный E2E и production не проверялись.

Host тесты запускаются в отдельной tools environment с `--noconftest`: эти unit
тесты не используют PostgreSQL/API fixtures. Это не считается integration/E2E.
Первоначальные host pytest запуски не прошли из-за отсутствующих httpx/sentry-sdk
и недоступной sandbox temp directory; повтор использует workspace basetemp.

Изолированный builder и тестовые image tags удалены после проверок; plain logs/JSON сохранены локально. UTF-8/локальные ссылки затронутых документов и git diff --check PASS. Пользовательские контейнеры healthy, тестовый volume отсутствует.

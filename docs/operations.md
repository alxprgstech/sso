# Руководство по эксплуатации ALXPRGS SSO

- **Версия документа**: 1.0.0
- **Дата**: 24.09.2026
- **Статус**: Действующий эксплуатационный регламент

---

## 1. Общее описание эксплуатационного контура

Эксплуатационный контур содержит три постоянных сервиса и одноразовый `migrate` job. БД находится только во внутренней `db_network`; gateway/backend соединяются через `proxy_network`:

1. **`db`** (`postgres:16-alpine`):
   - Реляционная СУБД PostgreSQL 16;
   - Хранение постоянных данных в Docker volume `sso_db_data`;
   - Проверка работоспособности: `pg_isready -U sso_user -d sso_db`.
2. **`backend`** (`alxprgs-sso-backend`):
   - FastAPI приложение на Python 3.13;
   - Миграции выполняет отдельный `migrate` job с ролью `sso_migrator` до запуска backend; runtime использует только `sso_runtime`;
   - Uvicorn ASGI сервер на порту 8000;
   - Эндпоинты проверки жизнеспособности: `/health/live` (Liveness) и `/health/ready` (Readiness с проверкой подключения к БД).
3. **`frontend`** (`alxprgs-sso-frontend`):
   - Nginx 1.30.5 + статический production-бандл React 18 SPA;
   - Проксирование запросов к API, OIDC, Discovery и Healthcheck на сервис `backend:8000`;
   - Local HTTP8080 внутри контейнера, только127.0.0.1:3000 на хосте. Production требует явно настроенный единственный TLS gateway из `deploy/nginx.conf`; шаблон не является готовым публичным развёртыванием.

---

## 2. Развёртывание и запуск

### 2.1. Подготовка конфигурации окружения

Скопируйте пример файла переменных окружения:
```bash
cp .env.example .env
```

Задайте безопасные значения секретов для production:
```bash
# Генерация ключей:
python scripts/rotate_keys.py --kind rsa --output-dir <новый-защищённый-каталог> --key-id <уникальный-kid>
```

Отредактируйте `.env`:
- `SESSION_SECRET_KEY`: случайная строка не менее 64 символов; генерация `--kind session` в отдельный новый каталог;
- `TOTP_ENCRYPTION_KEY`: отдельный случайный Fernet base64 ключ; генерация `--kind totp` в отдельный новый каталог;
- `JWT_PRIVATE_KEY_PEM`: путь внутри runtime к постоянному RSA secret mount либо PEM из secret store; `JWT_KEY_ID` явный уникальный ASCII kid;
- `BASE_URL`: внешний базовый URL (например, `https://auth.alxprgs.tech`);
- `OIDC_ISSUER`: идентификатор поставщика удостоверений (`https://auth.alxprgs.tech`); production требует тот же точный HTTPS origin в `BASE_URL`, `FRONTEND_URL`, `WEBAUTHN_ORIGIN` и matching host в `WEBAUTHN_RP_ID`;
- Убедитесь, что все флаги отложенных возможностей установлены в `false`:
  - `FEATURE_TOTP_ENABLED=false`
  - `FEATURE_PASSKEY_ENABLED=false`
  - `FEATURE_RECOVERY_CODES_ENABLED=false`
  - `FEATURE_EMAIL_VERIFICATION_ENABLED=true` (обязательное подтверждение самостоятельной регистрации)
  - `REQUIRE_VERIFIED_EMAIL=false`

### 2.2. Запуск через Docker Compose

Подтверждение почты обязательно для самостоятельной регистрации; `FEATURE_EMAIL_VERIFICATION_ENABLED=false` больше не допускается. `EMAIL_PROVIDER=smtp` сохраняет прежние `SMTP_*`; `EMAIL_PROVIDER=ses` использует `SES_REGION` (default `us-east-1`), `SES_FROM_EMAIL` (default `sso@alxprgs.tech`) и `SES_FROM_NAME` (default `ALXPRGS`). Compose передаёт эти параметры контейнеру backend. Для локального Compose владелец может указать стандартные `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` и, для временных credentials, `AWS_SESSION_TOKEN` в игнорируемом Git файле `.env`; Compose передаёт их только backend, а boto3 читает обычной AWS credential chain. После изменения `.env` пересоздайте контейнер: `docker compose up -d --force-recreate backend`. Не добавляйте значения ключей в `.env.example`, код, документацию или сообщения; вывод `docker compose config` и `docker inspect` также может содержать их. Если локальные ключи не заданы, пустые переменные пропускаются botocore, и остаются другие стандартные провайдеры credentials. На AWS назначьте процессу IAM role с `ses:SendEmail` на ARN identity `alxprgs.tech` в `us-east-1`, по возможности ограниченной `ses:FromAddress`. Production runtime обязан иметь доступ к SES API по HTTPS с обычной проверкой сертификата. [AWS credential chain](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html), [Compose environment](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/).

Перед включением SES оператор проверяет статус identity и custom MAIL FROM `bounce.alxprgs.tech` в нужном регионе, статус sandbox/production access, права роли и отсутствие блокировки отправки. Если credentials отсутствуют, identity не разрешает `From`, получатель отклонён либо API недоступен, приложение фиксирует безопасную категорию `email_delivery_failed` без содержимого письма; публичный ответ остаётся нейтральным. `ses_email_accepted` с Message ID означает принятие запроса SES, а не доставку. Поздние bounce/complaint события этим приложением пока не обрабатываются. Автоматические проверки работают с fake-клиентом и локальным SMTP, без реальной отправки через AWS.

После миграции 0003 клиенты `/api/v1/auth/register` должны обрабатывать HTTP 202 и `challenge_id`; HTTP 201 и немедленного `user_id` больше нет. В открытом режиме без работающей почты заявка остаётся в БД, пользователь не создаётся, а API возвращает 503. Повторная отправка по `challenge_id` выдаёт новый код/ссылку (не более трёх писем за час), срок каждого — 10 минут. Для диагностики смотрите категории `email_delivery_failed` в аудите и технический `ses_email_accepted message_id` в логе backend; не выводите сам код, токен, тело или AWS credentials.

Город и страна остаются «Неизвестно», пока доверенный ingress не удаляет исходные клиентские `X-ALX-Geo-*` и сам не передаёт проверенные значения. Поставляемые Nginx-конфигурации удаляют эти заголовки. AMP и Schema.org в письме не гарантируют интерфейсную карточку Gmail: отправитель должен отдельно зарегистрироваться в Google для AMP и email markup, а для Gmail action запросить bearer token и проверить его на сервере. Обычные HTML, текст, код и ссылка работают без одобрения Google.

```bash
# Сборка и запуск контейнеров в фоновом режиме
docker compose up -d --build

# Проверка статуса сервисов и healthcheck
docker compose ps

# Просмотр журналов
docker compose logs -f backend
```

### 2.3. Инициализация первого администратора

После первого запуска и успешного применения миграций создайте учетную запись администратора через CLI:

```bash
# В интерактивном терминале внутри работающего контейнера:
docker compose exec -it backend python -m app.cli.bootstrap_admin --username admin --email admin@alxprgs.tech

# Либо в локальном интерактивном окружении (при доступной БД):
alx-admin --username admin --email admin@alxprgs.tech
```

Пароль задаётся через скрытый терминальный запрос. Не передавайте его аргументом процесса: командная строка может попасть в историю и списки процессов.

---

## 3. Управление миграциями базы данных

Миграции схемы БД выполняются с использованием Alembic:

```bash
# Применение всех миграций
docker compose exec backend alembic upgrade head

# Проверка текущей ревизии базы данных
docker compose exec backend alembic current

# Создание новой миграции при изменении моделей
docker compose exec backend alembic revision --autogenerate -m "describe_changes"

# Откат на одну ревизию назад (в случае необходимости)
docker compose exec backend alembic downgrade -1
```

---

## 4. Резервное копирование и восстановление

### 4.1. Создание резервной копии базы данных

Скрипт `scripts/backup_db.py` выполняет `pg_dump`, проверяет непустой файл и выводит SHA-256. Без явного `--docker` используется только локальный `pg_dump` из `PATH`; при его отсутствии команда завершается ошибкой. Перед любым запуском проверяйте сервер и БД, особенно если используете `--docker`: имя контейнера должно принадлежать именно выбранному PostgreSQL.

```bash
# Только после независимой проверки соответствия контейнера нужному серверу:
python scripts/backup_db.py --docker --container <проверенный-контейнер> --output-dir backups/

# Либо прямое подключение к локальному PostgreSQL:
python scripts/backup_db.py --host localhost --port 5432 --user sso_user --db sso_db
```

Указанные команды — инструкции, а не свидетельство проверки нынешнего дерева. Файл и его контрольную сумму храните вместе с отдельно защищённым TOTP encryption key; сам дамп и ключ не коммитьте.

### 4.2. Восстановление базы данных

Скрипт `scripts/restore_db.py` требует `--confirm`. `psql` запускается с `ON_ERROR_STOP=1`: SQL-ошибка возвращает ненулевой код. Restore заменяет существующие данные целевой БД; сначала создайте отдельную пустую цель и убедитесь, что адрес и владелец совпадают с планом восстановления.

```bash
# Только после проверки контейнера:
python scripts/restore_db.py <проверенный-dump.sql> --confirm --deletion-journal <свежий-журнал.json> --docker --container <проверенный-контейнер> --db <отдельная-тестовая-БД>

# Восстановление через локальный psql:
python scripts/restore_db.py <проверенный-dump.sql> --confirm --deletion-journal <свежий-журнал.json> --host localhost --port 5432 --user sso_user --db <отдельная-тестовая-БД>
```

Для локальной интеграционной кампании выделите отдельный PostgreSQL 16 на `localhost:5433` с пользователем `sso_test_user` и БД `alxprgs_sso_test`. После миграций и **до** тестов на пустой БД с явным `TEST_DATABASE_URL` выполните `python -m scripts.init_fresh_ci_test_marker --local-fresh`. Команда проверяет точный адрес, отсутствие старого маркера, ожидаемую схему, исходную закрытую конфигурацию и отсутствие данных во всех прикладных таблицах. Fixture pytest и E2E seed больше не создают/исправляют маркер самостоятельно. Если проверка отказала, не изменяйте существующую БД ради теста; подготовьте новую пустую БД. CI использует этот же скрипт для выделенного сервиса на `localhost:5432` без локального флага.

---

## 5. Ротация криптографических ключей

Генерация не изменяет runtime или БД. Скрипт требует существующий parent и **новый** destination,
отказывает при повторе, создаёт POSIX 0700/0600 или Windows owner-only ACL до записи файлов.
Не выводит значения ключей; файл RSA в формате PKCS8, default 3072 bits. Parent, backup и secret
store должны быть защищены оператором. Не добавляйте их в Git; не выводите содержимое файлов/Compose env.

```bash
python scripts/rotate_keys.py --kind rsa --output-dir <новый-каталог-rsa> --key-id <новый-уникальный-kid> --bits 3072
python scripts/rotate_keys.py --kind session --output-dir <новый-каталог-session>
python scripts/rotate_keys.py --kind totp --output-dir <новый-каталог-totp>
```

### 5.1. RSA: перекрытие и restart

Сохраните отдельно backup действующего private/public key, kid и конфигурации. Создайте новую пару;
доставьте новый private файл одинаково всем workers; установите `JWT_PRIVATE_KEY_PEM` и `JWT_KEY_ID`.
В `JWT_PREVIOUS_PUBLIC_KEY_PEM` укажите старый public файл, в `JWT_PREVIOUS_KEY_ID` — старый kid,
в `JWT_PREVIOUS_KEY_VALID_UNTIL` — timezone-aware ISO 8601 UTC deadline.
Deadline отсчитывается от **последнего** выпуска старым worker: как минимум максимальный JWT TTL
плюс согласованный clock skew (практический запас не менее 10 минут), с учётом желаемого окна
приёма logout hints. По достижении срока JWKS и validator прекращают принимать старый kid,
включая expired logout hints. Не удаляйте предыдущий public ключ раньше срока; затем удалите параметры.
Скоординируйте rolling restart: никакой процесс не должен продолжать старую подпись после принятого
момента отсчёта. Проверьте JWKS обоих ключей, токен до/после смены, restart и два worker.
Процессная `rotate_active_signing_key` в production запрещена; изменения выполняются через secret store.
Rollback до deadline: вернуть старый private/kid, сохранить новый public как previous с новым deadline
для уже выпущенных токенов; после окончания окна требуется новый согласованный rollout.

### 5.2. SESSION_SECRET_KEY

При остановленных workers доставьте новый ключ одинаково всему кластеру. Он меняет CSRF/email
derivation; действующие CSRF и email-code challenges перестают подходить. Opaque browser sessions
хранятся по SHA-256 независимо от этого ключа: **сама замена ключа не удаляет сессии**.
Для incident rotation дополнительно отзывайте все browser sessions/grants/pending actions штатной
административной процедурой security revision; старый offline access JWT живёт до TTL.
Синтетический drill должен проверить отказ старого CSRF, корректный новый login и факт выбранного
отзыва. Rollback требует оценки, какие старые proofs снова станут пригодными; при инциденте
не возвращать скомпрометированный ключ. Новый session key нельзя путать с Fernet или RSA.

### 5.3. TOTP_ENCRYPTION_KEY: только вместе с ciphertext migration

Остановите **все** API/worker/CLI, пишущие TOTP, и закройте входящий трафик. Сделайте backup БД,
отдельный backup старого ключа/конфигурации; сначала проверьте restore на отдельной синтетической БД.
Создайте новый `--kind totp` destination. В конфигурации migration оставьте старый действующий ключ.

```bash
python scripts/migrate_totp_key.py --old-key-file <защищённый-старый-файл> --new-key-file <защищённый-новый-файл> --offline-maintenance --confirm
```

Команда выбирает только configured `DATABASE_URL_SYNC`, блокирует строки, сначала расшифровывает
весь набор, затем MultiFernet.rotate сохраняет timestamp и перешифровывает в одной транзакции.
При любом повреждении ciphertext транзакция откатывается. Значения/DSN в stdout не выводятся.
После commit **до restart** установите новый `TOTP_ENCRYPTION_KEY` для всех процессов.
Проверьте enrolled TOTP положительным и отрицательным OTP на синтетическом аккаунте, затем readiness.
Не оставляйте workers со старым ключом после commit. Rollback в offline mode: migration с обратной
парой ключей и конфигурацией, соответствующей текущему ciphertext, либо согласованный backup restore
с актуальным deletion journal; возврат одного старого ключа без возврата ciphertext недопустим.
Флаг offline-maintenance является явным подтверждением оператора, а не механизмом остановки других
процессов; advisory lock предотвращает два одновременных migration CLI, но не заменяет maintenance.

### 5.4. Проверка production configuration и SMTP

Настройки отвергают dev/empty secret, отсутствующий/слабый RSA, неявный/unsafe kid, несогласованный
HTTPS origin, DEBUG и TTL сверх границ: code 60s/access 300s/MFA 300s/session idle 12h/absolute 7d,
refresh 7d/family 30d. Небезопасная конфигурация не доходит до serving/readiness.
SMTP в production требует `SMTP_USE_TLS=true`; credentials без TLS запрещены и в dev/test.
Используется системный CA trust, либо явный `SMTP_CA_FILE` с доверенным CA; cert и hostname проверяются.
STARTTLS unavailable/untrusted/mismatch завершается отказом без credentials или plaintext fallback.
SES продолжает использовать штатный HTTPS boto3 transport с проверкой сертификата.
Локальные TLS/crypto проверки не доказывают внешнюю доставку, custody или backup/restore production.

---

## 6. Мониторинг и диагностика

### Раздельные роли БД и обновление существующего volume

Свежий пустой volume выполняет `deploy/postgres/010-init-roles.sh` и `init-roles.sql` один раз.
Повторный Compose запуск существующей БД не создаёт роли и не меняет владельца таблиц.
Не удаляйте volume ради обновления. Сохраните проверенный backup/deletion journal и закрытую
копию прежней конфигурации. Остановите всех backend workers, migrate и соединения monitoring
на выбранной выделенной БД. `POSTGRES_USER` остаётся эксплуатационным owner; приложение его
credentials не получает. Задайте отдельные случайные `SSO_RUNTIME_PASSWORD` и
`SSO_MIGRATOR_PASSWORD` в защищённом окружении оператора; пароли должны различаться.

Владелец БД применяет `psql --no-psqlrc --set ON_ERROR_STOP=1 --file deploy/postgres/init-roles.sql`
с явно выбранными PGHOST/PGPORT/PGUSER/PGDATABASE и защищённым PGPASSFILE. Скрипт читает
пароли ролей из env, не из аргументов. Используйте выделенную БД без чужих таблиц/ролей:
существующие cluster-wide `sso_runtime`/`sso_migrator` сначала должны быть установлены как
принадлежащие этому deployment; init не заменяет их пароли и не разрешает переиспользовать
чужую роль. Ни DSN, ни вывод `docker compose config` с secrets не помещайте в журнал.

После создания ролей установите `DATABASE_URL_SYNC` owner-соединения **только для CLI**:

```text
python scripts/transfer_database_ownership.py --expected-database <точное-имя-БД> --expected-owner <точный-owner> --offline-maintenance --confirm
```

CLI проверяет точную БД/login, отсутствие других соединений, неповышенные dedicated roles
без наследования и прежнего владельца каждого application table. Он передаёт только
известные application tables/привязанные sequences и public schema в одной транзакции;
чужие таблицы не передаёт, `REASSIGN OWNED` для всего cluster не используется. Ошибка
откатывает handoff. Флаг maintenance подтверждает, что оператор остановил workload.
Затем миграции выполнять как `sso_migrator`, backend запускать как `sso_runtime`,
проверить head0010_registration_session, readiness, login и отказ runtime CREATE/ALTER/DROP.
Production startup отвергает повышенную runtime роль, ownership/CREATE schema и schema drift.
Не выдавайте runtime роль migrator membership для обхода отказа.

Rollback приложения с прежними schema expectations требует проверенного восстановления
backup в maintenance, актуального deletion journal и совместимой конфигурации ключей.
Без проверки совместимости не откатывайте миграции и не возвращайте superuser приложению.
Реальные fresh/0004→head и ownership/DML/DDL drills —
`tests/integration/test_migration_upgrade_roles_pg.py`; production custody/restore здесь не доказаны.

### 6.1. Эндпоинты контроля состояния (Health Checks)

- **Liveness probe**: `GET /health/live`
  - Возвращает `200 OK` (`{"status": "alive"}`).
  - Используется оркестратором для проверки работы процесса uvicorn.
- **Readiness probe**: `GET /health/ready`
  Ожидание БД, включая DNS/connect/pre-ping/query, ограничено2s. Если БД
  недоступна или операция не завершилась в срок, сервер возвращает503;
  успешный ответ требует реальной проверки БД, кэшированный ready не используется.
  - Возвращает `200 OK` (`{"status": "ready", "database": "connected"}`).
  - Возвращает `503 Service Unavailable`, если подключение к PostgreSQL недоступно.

### 6.2. Журналирование и аудит

- Логи бэкенда выводятся в stdout в структурированном виде.
- Все события безопасности (вход, выход, неудачные попытки, блокировки, создание клиентов, ротация секретов) персистентно фиксируются в таблице PostgreSQL `audit_events` и доступны администраторам через REST API (`GET /api/v1/admin/audit`) и интерфейс панели управления.

## Реальные email-тесты

SES остаётся существующим отправителем; testmail.app применяется только как получатель тестовых писем. Владелец отдельно обеспечивает SES production access и выделенные IAM credentials; приложение не меняет account/DNS/configuration sets. Main/release CI требует четыре scoped Secrets (session token optional) и TESTMAIL_NAMESPACE Variable. Обычная рабочая Compose БД для внешней группы не используется. [Запуск, безопасность artifacts, IAM и troubleshooting](testing/email.md).

## Эксплуатация Sentry

Flags/rates default-off; EU projects и DSN получены, включение требует live privacy/source-map приёмки. Backend env управляет database-free browser config. Для остановки component flag=false, tracing rates=0, Replay flag=false/rates=0; backend пересоздать, browser tabs перезагрузить. JSON stdout и PostgreSQL audit остаются локальными каналами. Nginx query/IP/Referer не пишет в access log; .map возвращает 404. Enforced CSP включён по умолчанию. Generated snippet разрешает только точный frontend ingest origin; Report-Only доступен как явно выбранный диагностический режим staging, не production default. Upload token не передавать application containers. Конкретные команды, alerts/quota/smoke и rollback: [observability.md](observability.md).

## Удаление, сроки хранения и восстановление (0004_privacy)

Миграцию `alembic upgrade head` выполнить до запуска нового backend/frontend. Она добавляет состояния и согласия; также необратимо удаляет старую геолокацию и полные User-Agent. Старые пользователи подтверждают текущие документы после входа. Публичный контракт регистрации теперь требует обе отметки и актуальные версии.

Backend lifespan запускает privacy maintenance сразу и затем раз в минуту. Общий PostgreSQL advisory lock исключает несколько владельцев; после простоя выбираются просроченные заявки с исходным сроком. Проверяйте отсутствие `privacy_maintenance_failed` и возраст просроченных заявок (observability.md). Аудит очищается через 90 дней; UUID/время окончательного удаления — через 30.

Backup скрипт удаляет только собственные файлы старше 30 дней. Дополнительно ежедневно выполняйте `python scripts/prune_backups.py <каталог>` даже при остановленном создании backup; для внешнего хранилища задайте тот же retention отдельно. Сторонние файлы и символические ссылки не удаляются.

Перед восстановлением закройте доступ и остановите backend на восстанавливаемой БД. Из актуального источника, а не из backup, экспортируйте `python scripts/export_deletion_journal.py <свежий-журнал.json>` с явно настроенным `DATABASE_URL_SYNC`. Журнал содержит только UUID и UTC-время, действителен для restore пять минут. `python scripts/restore_db.py <backup.sql> --confirm --deletion-journal <свежий-журнал.json>` применяет dump и удаления в одной транзакции с ON_ERROR_STOP. После проверки миграций и отсутствия удалённых субъектов откройте доступ. Без актуального журнала скрипт отказывает; восстановление не продлевает первоначальные сроки. Приложение не может само гарантировать очистку внешних копий: это обязанность эксплуатации.

До production подтвердите реквизиты оператора, фактические провайдеры/локализацию, внешние сроки хранения и тексты docs/privacy.md. Не публикуйте проектные документы как проверенное юридическое соответствие.


## Файлы оформления

Сборка frontend включает public/theme вместе с index/assets; доставляйте весь dist. Для запуска demo из checkout необходим каталог frontend/public/theme с theme.js, palette.css и demo.css; API разрешает только эти имена. Смена темы не требует миграции и не меняет auth flags. CSP script-src/style-src self достаточен; inline exceptions не нужны. При обновлении работающего frontend пересоберите и перезапустите его обычным способом: текущий контейнер сам исходные изменения не подхватывает.

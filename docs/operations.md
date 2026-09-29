# Руководство по эксплуатации ALXPRGS SSO

- **Версия документа**: 1.0.0
- **Дата**: 24.09.2026
- **Статус**: Действующий эксплуатационный регламент

---

## 1. Общее описание эксплуатационного контура

Эксплуатационный контур ALXPRGS SSO состоит из трех основных контейнеризированных сервисов, объединенных изолированной сетью `sso_network`:

1. **`db`** (`postgres:16-alpine`):
   - Реляционная СУБД PostgreSQL 16;
   - Хранение постоянных данных в Docker volume `sso_db_data`;
   - Проверка работоспособности: `pg_isready -U sso_user -d sso_db`.
2. **`backend`** (`alxprgs-sso-backend`):
   - FastAPI приложение на Python 3.13;
   - Автоматическое применение миграций Alembic (`alembic upgrade head`) при запуске контейнера;
   - Uvicorn ASGI сервер на порту 8000;
   - Эндпоинты проверки жизнеспособности: `/health/live` (Liveness) и `/health/ready` (Readiness с проверкой подключения к БД).
3. **`frontend`** (`alxprgs-sso-frontend`):
   - Nginx 1.27 + статический production-бандл React 18 SPA;
   - Проксирование запросов к API, OIDC, Discovery и Healthcheck на сервис `backend:8000`;
   - Единая точка входа по HTTP (порт 80 внутри контейнера, порт 3000 на хосте в development/staging, порт 80/443 в production).

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
python scripts/rotate_keys.py
```

Отредактируйте `.env`:
- `SECRET_KEY`: криптографически стойкая строка (минимум 32 байта hex);
- `MFA_ENCRYPTION_KEY`: Fernet base64 ключ для шифрования TOTP секретов;
- `BASE_URL`: внешний базовый URL (например, `https://auth.alxprgs.tech`);
- `OIDC_ISSUER`: идентификатор поставщика удостоверений (`https://auth.alxprgs.tech`);
- Убедитесь, что все флаги отложенных возможностей установлены в `false`:
  - `FEATURE_TOTP_ENABLED=false`
  - `FEATURE_PASSKEY_ENABLED=false`
  - `FEATURE_RECOVERY_CODES_ENABLED=false`
  - `FEATURE_EMAIL_VERIFICATION_ENABLED=false`
  - `REQUIRE_VERIFIED_EMAIL=false`

### 2.2. Запуск через Docker Compose

Для подтверждения почты `FEATURE_EMAIL_VERIFICATION_ENABLED` включается отдельно от выбора транспорта. `EMAIL_PROVIDER=smtp` сохраняет прежние `SMTP_*`; `EMAIL_PROVIDER=ses` использует `SES_REGION` (default `us-east-1`), `SES_FROM_EMAIL` (default `sso@alxprgs.tech`) и `SES_FROM_NAME` (default `ALXPRGS`). Compose передаёт эти параметры контейнеру backend. Не помещайте AWS access keys в `.env`, Compose, документацию или исходники. На AWS назначьте процессу IAM role с `ses:SendEmail` на ARN identity `alxprgs.tech` в `us-east-1`, по возможности ограниченной `ses:FromAddress`; локально используйте стандартный AWS profile/credential chain. Локальный Compose-контейнер должен отдельно получить стандартный источник credentials во время запуска: профиль AWS на хосте не появляется внутри контейнера автоматически. Production runtime обязан иметь доступ к SES API по HTTPS с обычной проверкой сертификата.

Перед включением SES оператор проверяет статус identity и custom MAIL FROM `bounce.alxprgs.tech` в нужном регионе, статус sandbox/production access, права роли и отсутствие блокировки отправки. Если credentials отсутствуют, identity не разрешает `From`, получатель отклонён либо API недоступен, приложение фиксирует безопасную категорию `email_delivery_failed` без содержимого письма; публичный ответ остаётся нейтральным. `ses_email_accepted` с Message ID означает принятие запроса SES, а не доставку. Поздние bounce/complaint события этим приложением пока не обрабатываются. Автоматические проверки работают с fake-клиентом и локальным SMTP, без реальной отправки через AWS.

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
python scripts/restore_db.py <проверенный-dump.sql> --confirm --docker --container <проверенный-контейнер> --db <отдельная-тестовая-БД>

# Восстановление через локальный psql:
python scripts/restore_db.py <проверенный-dump.sql> --confirm --host localhost --port 5432 --user sso_user --db <отдельная-тестовая-БД>
```

Для локальной интеграционной кампании выделите отдельный PostgreSQL 16 на `localhost:5433` с пользователем `sso_test_user` и БД `alxprgs_sso_test`. После миграций и **до** тестов на пустой БД с явным `TEST_DATABASE_URL` выполните `python -m scripts.init_fresh_ci_test_marker --local-fresh`. Команда проверяет точный адрес, отсутствие старого маркера, ожидаемую схему, исходную закрытую конфигурацию и отсутствие данных во всех прикладных таблицах. Fixture pytest и E2E seed больше не создают/исправляют маркер самостоятельно. Если проверка отказала, не изменяйте существующую БД ради теста; подготовьте новую пустую БД. CI использует этот же скрипт для выделенного сервиса на `localhost:5432` без локального флага.

---

## 5. Ротация криптографических ключей

Для генерации новых ключевых материалов используйте `scripts/rotate_keys.py`:

```bash
python scripts/rotate_keys.py --output-dir keys/ --bits 2048
```

Скрипт формирует:
1. Новую пару ключей RSA для подписи токенов OpenID Connect (`oidc_private.pem` и `oidc_public.pem`).
2. Новый симметричный ключ Fernet для переменной `MFA_ENCRYPTION_KEY`.
3. Новый псевдослучайный ключ для переменной `SECRET_KEY`.

> **ВАЖНО**: При ротации ключей подписи OIDC старый открытый ключ должен сохраняться в JWKS до истечения срока действия ранее выпущенных токенов (не менее 10 минут).

---

## 6. Мониторинг и диагностика

### 6.1. Эндпоинты контроля состояния (Health Checks)

- **Liveness probe**: `GET /health/live`
  - Возвращает `200 OK` (`{"status": "alive"}`).
  - Используется оркестратором для проверки работы процесса uvicorn.
- **Readiness probe**: `GET /health/ready`
  - Возвращает `200 OK` (`{"status": "ready", "database": "connected"}`).
  - Возвращает `503 Service Unavailable`, если подключение к PostgreSQL недоступно.

### 6.2. Журналирование и аудит

- Логи бэкенда выводятся в stdout в структурированном виде.
- Все события безопасности (вход, выход, неудачные попытки, блокировки, создание клиентов, ротация секретов) персистентно фиксируются в таблице PostgreSQL `audit_logs` и доступны администраторам через REST API (`GET /api/v1/admin/audit-log`) и интерфейс панели управления.

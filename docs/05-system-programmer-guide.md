# Руководство системного программиста ALXPRGS SSO

- **Обозначение документа**: ЕСПД.ГОСТ 19.503-79.РСП-05
- **Проект**: ALXPRGS SSO
- **Версия документа**: 1.0.0
- **Дата**: 24.09.2026
- **Статус**: Действующий

---

## 1. Назначение и область применения

Настоящее руководство предназначено для системных администраторов, DevOps-инженеров и системных программистов, осуществляющих развертывание, конфигурирование, резервное копирование и сопровождение серверного контура ALXPRGS SSO.

---

## 2. Системные требования и зависимости

- Процессор: x86_64 или ARM64, от 2 ядер;
- Оперативная память: от 2 ГБ;
- Дисковое пространство: от 10 ГБ;
- Docker Engine >= 24.0, Docker Compose >= 2.20;
- Публикуется только loopback3000 в dev. Backend8000/DB5432 доступны в приватных сетях, не внешним клиентам. Production TLS gateway/сертификат/публичный443 настраивает владелец отдельно.

---

## 3. Архитектура развертывания

Сервисный контур описывается в `docker-compose.yml`:
- `db`: образ `postgres:16-alpine`, персистентное хранилище `sso_db_data`;
- `backend`: digest-pinned `python:3.13-slim-bookworm`, UID10001, production-only зависимости, read-only/tmpfs/cap-drop/resource bounds; Uvicorn без автоматического доверия forwarding headers;
- `migrate`: отдельный одноразовый job с ролью `sso_migrator`, `alembic upgrade head`; backend ждёт его успешного завершения и использует ограниченный `sso_runtime`;
- `frontend`: образ на базе `nginx:1.30.5-alpine (закреплён digest)` с раздачей React SPA и проксированием API/OIDC на бэкенд.

---

## 4. Конфигурация переменных окружения

| Переменная | Описание | Значение по умолчанию | Обязательность в prod |
| --- | --- | --- | --- |
| `DATABASE_URL` | Строка подключения к PostgreSQL | `postgresql+psycopg://...` | Да |
| `SESSION_SECRET_KEY` | Ключ CSRF/email derivation | Dev placeholder | Случайный, минимум 64 символа |
| `TOTP_ENCRYPTION_KEY` | Fernet-ключ для шифрования TOTP секретов | Dev placeholder | Отдельный случайный ключ даже при TOTP=false |
| `JWT_PRIVATE_KEY_PEM`, `JWT_KEY_ID` | Постоянный RSA key/file и явный kid | Временный ключ только dev/test | Да |
| `JWT_PREVIOUS_PUBLIC_KEY_PEM`, `JWT_PREVIOUS_KEY_ID`, `JWT_PREVIOUS_KEY_VALID_UNTIL` | Public key перекрытия, kid и timezone-aware deadline | Пусто | Все вместе при rotation |
| `BASE_URL` | Базовый внешний URL сервера | `http://localhost:8000` | Да (`https://auth.alxprgs.tech`) |
| `OIDC_ISSUER` | Идентификатор эмитента OIDC | `https://auth.alxprgs.tech` | Да |
| `FEATURE_TOTP_ENABLED` | Флаг поддержки TOTP | `false` | Обязательно `false` |
| `FEATURE_PASSKEY_ENABLED` | Флаг поддержки Passkey | `false` | Обязательно `false` |
| `FEATURE_RECOVERY_CODES_ENABLED` | Флаг резервных кодов | `false` | Обязательно `false` |
| `FEATURE_EMAIL_VERIFICATION_ENABLED` | Обязательная проверка email до самостоятельной регистрации | `true` | `false` отвергается |
| `REQUIRE_VERIFIED_EMAIL` | Политика входа существующих/admin users | `false` | Явный выбор владельца |

---

## 5. Эксплуатационные регламенты

### 5.1. Резервное копирование
Выполняется ежедневно с помощью скрипта:
```bash
python scripts/backup_db.py --docker --output-dir backups/
```
Скрипт проверяет код завершения `pg_dump`, валидирует размер файла и записывает контрольную сумму SHA-256.

### 5.2. Восстановление данных
Восстановление производится с явным подтверждением:
```bash
python scripts/restore_db.py backups/<backup_file>.sql --confirm --deletion-journal <свежий-журнал.json> --docker
```

### 5.3. Генерация и ротация ключей
Для выпуска новой RSA пары OIDC и ключей шифрования:
```bash
python scripts/rotate_keys.py --kind rsa --output-dir <новый-защищённый-каталог> --key-id <новый-kid> --bits 3072
```
Session и TOTP генерируются отдельно с `--kind session`/`--kind totp`. RSA меняется с перекрытием
и restart всех workers. `TOTP_ENCRYPTION_KEY` меняется только после транзакционной migration
существующих ciphertext в offline maintenance. Значения не выводятся в консоль. Порядок backup,
rollback, startup validation и verified SMTP описан в [operations.md](operations.md).

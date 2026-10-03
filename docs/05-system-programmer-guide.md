# Руководство системного программиста ALXPRGS SSO

- **Обозначение документа**: ЕСПД.ГОСТ 19.503-79.РСП-05
- **Проект**: ALXPRGS SSO
- **Версия**: 1.0.0
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
- Доступные порты: 80, 443 (или 3000 в dev-контуре), 8000 (backend), 5432 (PostgreSQL).

---

## 3. Архитектура развертывания

Сервисный контур описывается в `docker-compose.yml`:
- `db`: образ `postgres:16-alpine`, персистентное хранилище `sso_db_data`;
- `backend`: образ на базе `python:3.13-slim-bookworm`, запуск через Uvicorn, предварительное применение миграций Alembic (`alembic upgrade head`);
- `frontend`: образ на базе `nginx:1.27-alpine` с раздачей React SPA и проксированием API/OIDC на бэкенд.

---

## 4. Конфигурация переменных окружения

| Переменная | Описание | Значение по умолчанию | Обязательность в prod |
| --- | --- | --- | --- |
| `DATABASE_URL` | Строка подключения к PostgreSQL | `postgresql+psycopg://...` | Да |
| `SECRET_KEY` | Секретный ключ для сессий и CSRF | Сгенерированная строка | Да (>= 32 байт) |
| `MFA_ENCRYPTION_KEY` | Fernet-ключ для шифрования TOTP секретов | Base64 ключ Fernet | Да |
| `BASE_URL` | Базовый внешний URL сервера | `http://localhost:8000` | Да (`https://auth.alxprgs.tech`) |
| `OIDC_ISSUER` | Идентификатор эмитента OIDC | `https://auth.alxprgs.tech` | Да |
| `FEATURE_TOTP_ENABLED` | Флаг поддержки TOTP | `false` | Обязательно `false` |
| `FEATURE_PASSKEY_ENABLED` | Флаг поддержки Passkey | `false` | Обязательно `false` |
| `FEATURE_RECOVERY_CODES_ENABLED` | Флаг резервных кодов | `false` | Обязательно `false` |
| `FEATURE_EMAIL_VERIFICATION_ENABLED` | Флаг подтверждения email | `false` | Обязательно `false` |
| `REQUIRE_VERIFIED_EMAIL` | Требование подтверждения email | `false` | Обязательно `false` |

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
python scripts/rotate_keys.py --output-dir keys/ --bits 2048
```
Обновите переменные `JWT_PRIVATE_KEY_PEM` и `MFA_ENCRYPTION_KEY` в соответствии с инструкциями в `docs/operations.md`.

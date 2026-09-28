#!/usr/bin/env bash
# ==============================================================================
# ALXPRGS SSO - Скрипт первого запуска и инициализации для Linux/macOS (Bash)
# Реализует требования SETUP-01..SETUP-09 и TEST-SETUP-04 из GOAL-02
# ==============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}=================================================================${NC}"
echo -e "${CYAN}       ALXPRGS SSO - Мастер первого запуска и инициализации      ${NC}"
echo -e "${CYAN}=================================================================${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Проверка наличия Docker в PATH (SETUP-01, TEST-SETUP-04)
echo -n "[1/6] Проверка наличия Docker..."
if ! command -v docker >/dev/null 2>&1; then
    echo -e " ${RED}[НЕ НАЙДЕН]${NC}"
    echo ""
    echo -e "${RED}[ERROR] Docker не найден в PATH хостовой системы (SETUP-01, TEST-SETUP-04).${NC}" >&2
    echo -e "${YELLOW}Для запуска ALXPRGS SSO необходим установленный Docker Engine или Docker Desktop.${NC}" >&2
    echo -e "${YELLOW}Инструкция по установке: https://docs.docker.com/get-docker/${NC}" >&2
    exit 1
fi
echo -e " ${GREEN}[OK]${NC}"

# 2. Проверка доступности демона Docker (TEST-SETUP-04)
echo -n "[2/6] Проверка доступности Docker daemon..."
if ! docker info >/dev/null 2>&1; then
    echo -e " ${RED}[НЕДОСТУПЕН]${NC}"
    echo ""
    echo -e "${RED}[ERROR] Служба Docker (daemon) не запущена или недоступна (TEST-SETUP-04).${NC}" >&2
    echo -e "${YELLOW}Пожалуйста, запустите службу Docker (systemctl start docker или Docker Desktop) и повторите команду.${NC}" >&2
    exit 1
fi
echo -e " ${GREEN}[OK]${NC}"

# Определение команды compose
if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo -e "${RED}[ERROR] Docker Compose не найден (требуется 'docker compose' или 'docker-compose').${NC}" >&2
    exit 1
fi

# 3. Проверка доступности порта 3000 на loopback 127.0.0.1 (SETUP-08, TEST-SETUP-04)
echo -n "[3/6] Проверка порта 127.0.0.1:3000..."
PORT_BUSY=0
if command -v nc >/dev/null 2>&1; then
    if nc -z 127.0.0.1 3000 2>/dev/null; then
        PORT_BUSY=1
    fi
elif (echo >/dev/tcp/127.0.0.1/3000) 2>/dev/null; then
    PORT_BUSY=1
fi

if [ "$PORT_BUSY" -eq 1 ]; then
    # Проверяем, не запущен ли уже наш собственный контейнер frontend
    EXISTING_CONTAINER=$("${COMPOSE_CMD[@]}" ps -q frontend 2>/dev/null || true)
    if [ -z "$EXISTING_CONTAINER" ]; then
        echo -e " ${RED}[ЗАНЯТ]${NC}"
        echo ""
        echo -e "${RED}[ERROR] Порт 127.0.0.1:3000 уже занят сторонним процессом (TEST-SETUP-04).${NC}" >&2
        echo -e "${YELLOW}Освободите порт 3000 или остановите конфликтующую службу перед повторным запуском.${NC}" >&2
        exit 1
    fi
fi
echo -e " ${GREEN}[OK]${NC}"

# 4. Проверка и безопасная генерация .env файла (SETUP-04)
echo -n "[4/6] Подготовка локальной конфигурации (.env)..."
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

if [ ! -f "$ENV_FILE" ]; then
    echo -e " ${YELLOW}[СОЗДАНИЕ]${NC}"
    echo "  Генерация криптографически стойких секретов..."

    if command -v openssl >/dev/null 2>&1; then
        SESSION_SECRET=$(openssl rand -hex 64)
        TOTP_KEY=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')
        DB_PASSWORD=$(openssl rand -hex 24)
    else
        SESSION_SECRET=$(head -c 64 /dev/urandom | xxd -p | tr -d '\n' || od -An -tx1 -N64 /dev/urandom | tr -d ' \n')
        TOTP_KEY=$(head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n')
        DB_PASSWORD=$(head -c 24 /dev/urandom | xxd -p | tr -d '\n' || od -An -tx1 -N24 /dev/urandom | tr -d ' \n')
    fi

    if [ ! -f "$ENV_EXAMPLE" ]; then
        echo -e "${RED}[ERROR] Не найден обязательный шаблон .env.example.${NC}" >&2
        exit 1
    fi

    for key in DEBUG BASE_URL FRONTEND_URL DATABASE_URL DATABASE_URL_SYNC POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB SESSION_SECRET_KEY TOTP_ENCRYPTION_KEY FEATURE_TOTP_ENABLED FEATURE_PASSKEY_ENABLED FEATURE_RECOVERY_CODES_ENABLED FEATURE_EMAIL_VERIFICATION_ENABLED REQUIRE_VERIFIED_EMAIL; do
        count=$(grep -c "^${key}=" "$ENV_EXAMPLE" || true)
        if [ "$count" -ne 1 ]; then
            echo -e "${RED}[ERROR] Некорректный шаблон .env.example: ожидается ровно одна строка ${key}.${NC}" >&2
            exit 1
        fi
    done

    umask 077
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    DB_URL="postgresql+psycopg://sso_user:${DB_PASSWORD}@db:5432/sso_db"
    sed -i.bak \
        -e 's|^DEBUG=.*|DEBUG=false|' \
        -e 's|^BASE_URL=.*|BASE_URL=http://localhost:3000|' \
        -e 's|^FRONTEND_URL=.*|FRONTEND_URL=http://localhost:3000|' \
        -e "s|^DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" \
        -e "s|^DATABASE_URL_SYNC=.*|DATABASE_URL_SYNC=${DB_URL}|" \
        -e 's|^POSTGRES_USER=.*|POSTGRES_USER=sso_user|' \
        -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${DB_PASSWORD}|" \
        -e 's|^POSTGRES_DB=.*|POSTGRES_DB=sso_db|' \
        -e "s|^SESSION_SECRET_KEY=.*|SESSION_SECRET_KEY=${SESSION_SECRET}|" \
        -e "s|^TOTP_ENCRYPTION_KEY=.*|TOTP_ENCRYPTION_KEY=${TOTP_KEY}|" \
        -e 's|^FEATURE_TOTP_ENABLED=.*|FEATURE_TOTP_ENABLED=false|' \
        -e 's|^FEATURE_PASSKEY_ENABLED=.*|FEATURE_PASSKEY_ENABLED=false|' \
        -e 's|^FEATURE_RECOVERY_CODES_ENABLED=.*|FEATURE_RECOVERY_CODES_ENABLED=false|' \
        -e 's|^FEATURE_EMAIL_VERIFICATION_ENABLED=.*|FEATURE_EMAIL_VERIFICATION_ENABLED=false|' \
        -e 's|^REQUIRE_VERIFIED_EMAIL=.*|REQUIRE_VERIFIED_EMAIL=false|' \
        "$ENV_FILE"
    rm -f "${ENV_FILE}.bak"

    chmod 600 "$ENV_FILE"
    echo -e "  ${GREEN}Файл .env успешно создан с уникальными криптографическими ключами.${NC}"
else
    echo -e " ${GREEN}[СОХРАНЁН]${NC}"
    echo "  Существующий файл .env сохранён без перезаписи (SETUP-04)."
fi

# 5. Запуск Docker Compose сервисов (SETUP-02)
echo "[5/6] Запуск контейнеров ALXPRGS SSO..."
"${COMPOSE_CMD[@]}" up -d --build

# Ожидание готовности healthcheck
echo -n "  Ожидание готовности сервисов (проверка /health/live)..."
MAX_ATTEMPTS=30
ATTEMPT=0
IS_HEALTHY=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    sleep 2
    ATTEMPT=$((ATTEMPT + 1))
    if curl -s -f -m 3 "http://127.0.0.1:3000/health/live" >/dev/null 2>&1; then
        IS_HEALTHY=1
        break
    fi
    echo -n "."
done

if [ "$IS_HEALTHY" -ne 1 ]; then
    echo -e " ${RED}[ТАЙМАУТ]${NC}"
    echo ""
    echo -e "${RED}[ERROR] Сервисы не перешли в состояние готовности за 60 секунд (TEST-SETUP-04).${NC}" >&2
    echo -e "${YELLOW}Проверьте журнал бэкенда: ${COMPOSE_CMD[*]} logs backend${NC}" >&2
    exit 1
fi
echo -e " ${GREEN}[ГОТОВО]${NC}"

# 6. Запуск мастера первичного администратора (SETUP-03..SETUP-07, SETUP-09)
echo "[6/6] Инициализация первого администратора..."
echo ""

if [ -t 0 ]; then
    "${COMPOSE_CMD[@]}" exec backend python -m app.cli.bootstrap_admin
else
    "${COMPOSE_CMD[@]}" exec -T backend python -m app.cli.bootstrap_admin
fi

BOOTSTRAP_EXIT=$?

echo ""
echo -e "${CYAN}=================================================================${NC}"
if [ "$BOOTSTRAP_EXIT" -eq 0 ]; then
    echo -e "${GREEN}             ALXPRGS SSO готов к использованию!                  ${NC}"
    echo -e "${CYAN}=================================================================${NC}"
    echo ""
    echo -e "  Вход в систему:        ${CYAN}http://localhost:3000${NC}"
    echo -e "  Панель администратора: ${CYAN}http://localhost:3000/admin${NC}"
    echo ""
    echo -e "  (Служба доступна строго на 127.0.0.1:3000, порт БД защищён)"
    echo ""

    if [ -t 0 ]; then
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "http://localhost:3000" >/dev/null 2>&1 || true
        elif command -v open >/dev/null 2>&1; then
            open "http://localhost:3000" >/dev/null 2>&1 || true
        fi
    fi
else
    echo -e "${RED}      Инициализация завершилась с ошибкой (код $BOOTSTRAP_EXIT)   ${NC}"
    echo -e "${CYAN}=================================================================${NC}"
    exit "$BOOTSTRAP_EXIT"
fi

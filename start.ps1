# ==============================================================================
# ALXPRGS SSO - Скрипт первого запуска и инициализации для Windows (PowerShell)
# Реализует требования SETUP-01..SETUP-09 и TEST-SETUP-04 из GOAL-02
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "       ALXPRGS SSO - Мастер первого запуска и инициализации      " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Проверка наличия Docker в PATH (SETUP-01, TEST-SETUP-04)
Write-Host "[1/6] Проверка наличия Docker..." -NoNewline
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host " [НЕ НАЙДЕН]" -ForegroundColor Red
    Write-Host ""
    Write-Host "[ERROR] Docker не найден в PATH хостовой системы (SETUP-01, TEST-SETUP-04)." -ForegroundColor Red
    Write-Host "Для запуска ALXPRGS SSO необходим установленный Docker Desktop." -ForegroundColor Yellow
    Write-Host "Пожалуйста, установите Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/" -ForegroundColor Yellow
    Write-Host "После установки перезапустите терминал и повторите: .\start.ps1" -ForegroundColor Yellow
    exit 1
}
Write-Host " [OK]" -ForegroundColor Green

# Immutable identity for this source build; never take a release name from .env.
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Error "Git is required to identify the Docker build revision. Use verified release artifacts for deployments without a checkout."
    exit 1
}
$buildRevision = ([string] (& git -C $PSScriptRoot rev-parse HEAD)).Trim()
if ($LASTEXITCODE -ne 0 -or $buildRevision -notmatch '^[a-f0-9]{40}$') {
    Write-Error "Cannot determine the full Git revision for this build."
    exit 1
}
$env:ALX_BUILD_SHA = $buildRevision

# 2. Проверка доступности демона Docker (TEST-SETUP-04)
Write-Host "[2/6] Проверка доступности Docker daemon..." -NoNewline
$null = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host " [НЕДОСТУПЕН]" -ForegroundColor Red
    Write-Host ""
    Write-Host "[ERROR] Служба Docker (daemon) не запущена или недоступна (TEST-SETUP-04)." -ForegroundColor Red
    Write-Host "Пожалуйста, запустите Docker Desktop и дождитесь инициализации службы." -ForegroundColor Yellow
    exit 1
}
Write-Host " [OK]" -ForegroundColor Green

# Определение команды compose
$composeExe = "docker"
$composeArgs = @("compose")
$null = docker compose version 2>&1
if ($LASTEXITCODE -ne 0) {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $composeExe = "docker-compose"
        $composeArgs = @()
    } else {
        Write-Host "[ERROR] Docker Compose не найден (требуется плагин 'docker compose' или утилита 'docker-compose')." -ForegroundColor Red
        exit 1
    }
}

# Bind Compose to this checkout and its configuration, including when automatic
# .env discovery is disabled or a different working directory is selected.
$composeArgs += @("--env-file", (Join-Path $PSScriptRoot ".env"), "-f", (Join-Path $PSScriptRoot "docker-compose.yml"))

# 3. Проверка доступности порта 3000 на loopback 127.0.0.1 (SETUP-08, TEST-SETUP-04)
Write-Host "[3/6] Проверка порта 127.0.0.1:3000..." -NoNewline
$portBusy = $false
try {
    $tcp = New-Object System.Net.Sockets.TcpClient
    $async = $tcp.BeginConnect("127.0.0.1", 3000, $null, $null)
    $ok = $async.AsyncWaitHandle.WaitOne(400, $false)
    if ($ok -and $tcp.Connected) {
        $portBusy = $true
        $tcp.EndConnect($async)
    }
    $tcp.Close()
} catch {
    $portBusy = $false
}

if ($portBusy) {
    # Проверяем, не запущен ли уже наш собственный контейнер frontend
    $existingContainers = & $composeExe @composeArgs ps -q frontend 2>&1
    if (-not $existingContainers) {
        Write-Host " [ЗАНЯТ]" -ForegroundColor Red
        Write-Host ""
        Write-Host "[ERROR] Порт 127.0.0.1:3000 уже занят сторонним процессом (TEST-SETUP-04)." -ForegroundColor Red
        Write-Host "Освободите порт 3000 или остановите конфликтующую службу перед повторным запуском." -ForegroundColor Yellow
        exit 1
    }
}
Write-Host " [OK]" -ForegroundColor Green

# 4. Проверка и безопасная генерация .env файла (SETUP-04)
Write-Host "[4/6] Подготовка локальной конфигурации (.env)..." -NoNewline
$envFile = Join-Path $PSScriptRoot ".env"
$envExample = Join-Path $PSScriptRoot ".env.example"

if (-not (Test-Path $envFile)) {
    Write-Host " [СОЗДАНИЕ]" -ForegroundColor Yellow
    Write-Host "  Генерация криптографически стойких секретов..."

    # Генерация криптографических случайных секретов
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()

    # SESSION_SECRET_KEY (64 байта hex = 128 символов)
    $sessBytes = New-Object byte[] 64
    $rng.GetBytes($sessBytes)
    $sessionSecret = [System.BitConverter]::ToString($sessBytes).Replace("-", "").ToLower()

    # TOTP_ENCRYPTION_KEY (32 байта Base64)
    $totpBytes = New-Object byte[] 32
    $rng.GetBytes($totpBytes)
    $totpKey = [System.Convert]::ToBase64String($totpBytes).Replace("+", "-").Replace("/", "_")

    # POSTGRES_PASSWORD (24 байта hex)
    $dbBytes = New-Object byte[] 24
    $rng.GetBytes($dbBytes)
    $dbPassword = [System.BitConverter]::ToString($dbBytes).Replace("-", "").ToLower()

    $runtimeBytes = New-Object byte[] 32
    $migratorBytes = New-Object byte[] 32
    $rng.GetBytes($runtimeBytes)
    $rng.GetBytes($migratorBytes)
    $runtimePassword = [System.BitConverter]::ToString($runtimeBytes).Replace("-", "").ToLower()
    $migratorPassword = [System.BitConverter]::ToString($migratorBytes).Replace("-", "").ToLower()
    $rng.Dispose()

    if (-not (Test-Path -LiteralPath $envExample)) {
        throw "Не найден обязательный шаблон .env.example. Восстановите его из репозитория."
    }
    $utf8 = [System.Text.UTF8Encoding]::new($false, $true)
    $envContent = [System.IO.File]::ReadAllText($envExample, $utf8)
    $dbUrl = "postgresql+psycopg://sso_runtime:${runtimePassword}@db:5432/sso_db"
    $replacements = [ordered]@{
        DEBUG = "false"
        BASE_URL = "http://localhost:3000"
        FRONTEND_URL = "http://localhost:3000"
        DATABASE_URL = $dbUrl
        DATABASE_URL_SYNC = $dbUrl
        POSTGRES_USER = "sso_user"
        POSTGRES_PASSWORD = $dbPassword
        SSO_RUNTIME_PASSWORD = $runtimePassword
        SSO_MIGRATOR_PASSWORD = $migratorPassword
        POSTGRES_DB = "sso_db"
        SESSION_SECRET_KEY = $sessionSecret
        TOTP_ENCRYPTION_KEY = $totpKey
        WEBAUTHN_RP_ID = "localhost"
        WEBAUTHN_ORIGIN = "http://localhost:3000"
        FEATURE_TOTP_ENABLED = "false"
        FEATURE_PASSKEY_ENABLED = "false"
        FEATURE_RECOVERY_CODES_ENABLED = "false"
        REQUIRE_VERIFIED_EMAIL = "false"
    }
    foreach ($key in $replacements.Keys) {
        $pattern = "(?m)^$key=.*$"
        if ([regex]::Matches($envContent, $pattern).Count -ne 1) {
            throw "Некорректный шаблон .env.example: ожидается ровно одна строка $key."
        }
        $envContent = [regex]::Replace($envContent, $pattern, "$key=$($replacements[$key])")
    }
    [System.IO.File]::WriteAllText($envFile, $envContent, $utf8)
    Write-Host "  Файл .env успешно создан с уникальными криптографическими ключами." -ForegroundColor Green
} else {
    Write-Host " [СОХРАНЁН]" -ForegroundColor Green
    Write-Host "  Существующий файл .env сохранён без перезаписи (SETUP-04)."
}

# 5. Запуск Docker Compose сервисов (SETUP-02)
$existingConfig = [System.IO.File]::ReadAllText($envFile)
$missingRoles = @()
foreach ($name in @("SSO_RUNTIME_PASSWORD", "SSO_MIGRATOR_PASSWORD")) {
    $processValue = [Environment]::GetEnvironmentVariable($name, "Process")
    if ([string]::IsNullOrWhiteSpace($processValue) -and
        $existingConfig -notmatch ('(?m)^\s*{0}\s*=\s*[^\s#]' -f $name)) {
        $missingRoles += $name
    }
}
if ($missingRoles.Count -gt 0) {
    Write-Host "[ERROR] Старая или неполная конфигурация .env: отсутствуют $($missingRoles -join ', ')." -ForegroundColor Red
    Write-Host "Для сохранения БД: docs/operations.md, раздел 'Раздельные роли БД и обновление существующего volume'."
    Write-Host "Для новой установки с удалением всех локальных данных: .\reset-local.ps1, затем .\start.ps1."
    exit 1
}
Write-Host "[5/6] Запуск контейнеров ALXPRGS SSO..."
& $composeExe @composeArgs up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Ошибка запуска контейнеров Docker Compose (TEST-SETUP-04)." -ForegroundColor Red
    Write-Host "Проверьте логи командой: $((@($composeExe) + $composeArgs) -join ' ') logs" -ForegroundColor Yellow
    exit 1
}

# Ожидание готовности healthcheck
Write-Host "  Ожидание готовности сервисов (проверка /health/live)..." -NoNewline
$maxAttempts = 30
$attempt = 0
$isHealthy = $false

while ($attempt -lt $maxAttempts) {
    Start-Sleep -Seconds 2
    $attempt++
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:3000/health/live" -UseBasicParsing -TimeoutSec 3 -ErrorAction SilentlyContinue
        if ($response -and $response.StatusCode -eq 200) {
            $isHealthy = $true
            break
        }
    } catch {
        # Ожидание следующей попытки
    }
    Write-Host "." -NoNewline
}

if (-not $isHealthy) {
    Write-Host " [ТАЙМАУТ]" -ForegroundColor Red
    Write-Host ""
    Write-Host "[ERROR] Сервисы не перешли в состояние готовности за 60 секунд (TEST-SETUP-04)." -ForegroundColor Red
    Write-Host "Проверьте журнал бэкенда: $((@($composeExe) + $composeArgs) -join ' ') logs backend" -ForegroundColor Yellow
    exit 1
}
Write-Host " [ГОТОВО]" -ForegroundColor Green

# 6. Запуск мастера первичного администратора (SETUP-03..SETUP-07, SETUP-09)
Write-Host "[6/6] Инициализация первого администратора..."
Write-Host ""

$isTty = [Environment]::UserInteractive -and -not [Console]::IsInputRedirected -and -not $NonInteractive

if ($isTty) {
    # Интерактивный вызов внутри контейнера бэкенда
    & $composeExe @composeArgs exec backend python -m app.cli.bootstrap_admin
} else {
    # Неинтерактивный вызов
    & $composeExe @composeArgs exec -T backend python -m app.cli.bootstrap_admin
}

$bootstrapExit = $LASTEXITCODE

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
if ($bootstrapExit -eq 0) {
    Write-Host "             ALXPRGS SSO готов к использованию!                  " -ForegroundColor Green
    Write-Host "=================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Вход в систему:        http://localhost:3000" -ForegroundColor White
    Write-Host "  Панель администратора: http://localhost:3000/admin" -ForegroundColor White
    Write-Host ""
    Write-Host "  (Служба доступна строго на 127.0.0.1:3000, порт БД защищён)" -ForegroundColor Gray
    Write-Host ""

    if (-not $NoBrowser -and $isTty) {
        try {
            Start-Process "http://localhost:3000"
        } catch {
            # Headless / браузер не поддерживается
        }
    }
} else {
    Write-Host "      Инициализация завершилась с ошибкой (код $bootstrapExit)   " -ForegroundColor Red
    Write-Host "=================================================================" -ForegroundColor Cyan
    exit $bootstrapExit
}

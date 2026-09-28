# Полный сброс локального Compose-контура ALXPRGS SSO.
# Запускайте только из интерактивного PowerShell после проверки имени Docker context.
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$composeFile = Join-Path $PSScriptRoot "docker-compose.yml"
$envFile = Join-Path $PSScriptRoot ".env"

if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
    Write-Error "Не найден docker-compose.yml рядом со скриптом."
    exit 1
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker не найден в PATH."
    exit 1
}

# Фиксированный проект исключает влияние COMPOSE_PROJECT_NAME из окружения.
# Новые тома требуют отдельного просмотра и явного изменения этого скрипта.
$composeArgs = @("compose", "-f", $composeFile, "-p", "sso")
$volumes = @(& docker @composeArgs config --volumes)
if ($LASTEXITCODE -ne 0 -or $volumes.Count -ne 1 -or $volumes[0].Trim() -ne "sso_db_data") {
    Write-Error "Не удалось проверить единственный том sso_db_data. Сброс остановлен."
    exit 1
}

Write-Host "Будут удалены контейнеры и сеть Compose-проекта sso, том sso_sso_db_data со всей базой и локальный .env."
$dockerContext = & docker context show
if ($LASTEXITCODE -ne 0 -or -not $dockerContext) {
    Write-Error "Не удалось определить Docker context. Сброс остановлен."
    exit 1
}
Write-Host "Текущий Docker context: $dockerContext"
Write-Host "Образы Docker и файлы резервных копий вне проекта не удаляются."
$confirmation = Read-Host "Для безвозвратного удаления введите УДАЛИТЬ SSO"
if ($confirmation -cne "УДАЛИТЬ SSO") {
    Write-Host "Сброс отменён; данные не изменены."
    exit 1
}

& docker @composeArgs down --volumes
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker Compose не завершил сброс. .env сохранён; проверьте состояние контейнеров и тома."
    exit 1
}

if (Test-Path -LiteralPath $envFile -PathType Leaf) {
    Remove-Item -LiteralPath $envFile -Force
}
Write-Host "Локальные данные SSO удалены. Для новой установки выполните .\start.ps1."

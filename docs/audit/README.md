# Воспроизведение AUDIT-PROD-01

Основной результат — [русский отчёт](../PRODUCTION_READINESS_AUDIT.md). Проверен source SHA `7e857ab80398f8084169ee29b141c6edc6794fe8`, версия 0.2.0. Диагностические файлы не меняют приложение и не входят в обычный pytest testpaths. На этом SHA ожидается **27 failed / 9 passed**: assertions описывают желаемую защиту и сохраняют воспроизведение найденных нарушений. После исправлений failures должны стать PASS без ослабления assertions.

## Локальные probes

PowerShell из корня репозитория, с установленным `requirements-lock.txt` и исходным SDK:

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'backend;packages/python-sdk;.'
New-Item -ItemType Directory -Force artifacts/audit | Out-Null
.venv-sentry/Scripts/python.exe -m pytest docs/audit/test_readiness_probes.py -q --junitxml=artifacts/audit/probes-final.xml
```

`.venv-sentry` — реально работавшая среда этого аудита, а не обязательное имя для других машин; можно использовать эквивалентный Python с закреплёнными зависимостями. Tests используют synthetic users, реальные RSA/Argon2/Fernet/PKCE библиотеки и ASGI HTTP. `unit_db`, DB responses и legal receipt state — явные doubles. Они **не подтверждают PostgreSQL locks, constraints или concurrency**. Нет внешней отправки email, production данных или изменения production ключей.

## Git-история без вывода значений

```powershell
.venv-sentry/Scripts/python.exe docs/audit/inspect_history.py
```

Требуется detect-secrets 1.5.0 из lock. Скрипт читает доступные refs/blobs, использует detector settings текущего baseline, отключает только сетевую provider verification для offline read-only сканирования; detectors не отключаются. Временные копии blobs удаляются. Output `artifacts/audit/history-scan.json` содержит paths/lines/types/fingerprints, **не значения**. Candidates вне baseline требуют приватного контекстного review. Итог текущего review — [history-summary.json](history-summary.json); отсутствие signals не является гарантией отсутствия секретов. Скрипт не изменяет baseline и не удаляет историю.

## Результаты и границы

- [evidence.json](evidence.json): команды/итоги и SHA-256 доступных локальных logs. Logs находятся в игнорируемом `artifacts`, не публикуются автоматически; synthetic pytest tracebacks могут содержать test JWT.
- [python-dependencies.json](python-dependencies.json), [frontend-dependencies.json](frontend-dependencies.json): versions и license metadata существующих locked packages; не юридическое заключение.
- Для настоящих integration/browser/backup проверок нужна отдельная защищённая test PostgreSQL по [operations](../operations.md) и [test plan](../testing/plan.md). Guard не отключать, рабочую БД не использовать, SQLite не подставлять.
- UI appearance tests используют mocked API; telemetry browser tests используют настоящий SDK с intercepted ingestion; это не SSO E2E и не live Sentry delivery.
- Локальный `release_bundle.py build` проверил восемь payload files и checksums. `source_tree_dirty=true` из-за audit docs: этот dry-run не разрешает публикацию. Фактический tag/release/production deployment отдельно поручает владелец.

Production source остался неизменным. Все fixes из отчёта находятся в статусе planned/open.

Digest metadata хранится в `sha256_bytes`, full commit — в `source_commit_bytes`: JSON arrays unsigned bytes, канонический hex получается `bytes(array).hex()`. Это публичные контрольные суммы, а не секреты. Такой формат устраняет ложные entropy signals без изменения baseline/detectors и сохраняет полную проверку целостности logs.

# Воспроизведение исходного и повторного аудита

Историческое локальное evidence в [отчёте](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/PRODUCTION_READINESS_AUDIT.md) относится к code SHA `ae700d7a9803b9757980ef1862af31f6f360a97d`, версия0.2.0, ветка `new/production-readiness-remediation`: Первоначальный snapshot CONDITIONALLY READY,22 CLOSED/4 PARTIALLY VERIFIED/1 BLOCKED EXTERNAL. Последующее реальное CI подтверждение E01/F18 даёт23CLOSED/4PARTIALLY VERIFIED; текущие PR/quality gates описаны в начале отчёта. [Summary](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/REMEDIATION_SUMMARY.md), [новые безопасные evidence](remediation-evidence.json).

## Сохранённый baseline

[Первоначальный отчёт](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/PRODUCTION_READINESS_AUDIT_BASELINE.md), source SHA `7e857ab80398f8084169ee29b141c6edc6794fe8`, NOT READY/27 findings; [архив исходных probes](readiness_probes_baseline.py) неизменён. На исходном SHA было27 failed/9passed; эти результаты не переписаны. Baseline doubles были явно unit, не доказательством PG locks/crypto/E2E.

## Текущий replay

[Карта28 исходных критериев](readiness-probe-map.md) указывает постоянные regressions, включая реальные PG и RSA negatives. Актуальный модуль импортирует эти проверки и запускается отдельно от обычного testpaths:

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'backend;packages/python-sdk;.'
# Сначала выделенная synthetic PostgreSQL с marker/guard по testing/plan.md.
# TEST_DATABASE_URL и остальные private variables задаются вне Git/вывода.
python -m pytest -p tests.conftest docs/audit/test_readiness_probes.py -q --junitxml=artifacts/audit/probes-current.xml
```

Исторический локальный run на ae700d7 с private environment wrapper записан как C03 в отчёте:104 passed/1Starlette warning. Он пересекается с535full, не отдельное суммируемое покрытие. Negative assertions/UV/PKCE/verified-email/quota не ослаблялись. Missing production RSA запрещён; persistent/restart тест использует доставленный реальный key. Обычный CI также исполняет постоянные исходные тесты.

## Git-история без вывода значений

`python docs/audit/inspect_history.py` читает refs/blobs и пишет только paths/lines/types/fingerprints, не candidate values. Detect-secrets1.5.0 закреплён; offline network provider verification не является live credential check. [Исторический summary](history-summary.json) сохранён; новая28-candidate context assessment — [secret review](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/testing/secret-review-remediation.md). Первоначальное owner решение по58 историческим signals остаётся E07, не объявлено автоматически выполненным.

## Evidence и границы

- [evidence.json](evidence.json), dependency inventories и qa-summary — исторический исходный аудит, не актуальные PASS нового SHA.
- [remediation-evidence.json](remediation-evidence.json) содержит точный implementation SHA, XML counts/timestamps/контрольные суммы и clean release manifest payload metadata. Digests/commits записаны arrays unsigned bytes; canonical hex = `bytes(array).hex()`. Это публичные IDs, не secrets.
- Raw local logs/captures/private maps/DSN/packages игнорируются и не публикуются; даже synthetic failures могут содержать JWT. Guard/test DB не отключать, рабочую БД/SQLite не использовать.
- Actual local PG/races/backup, Nginx/Chromium SSO/admin/default-off/enabled и TLS loopback PASS. Telemetry uses actual SDK/rrweb/intercepted ingestion, не live Sentry. Production Replay hard-off.
- Exact code SHA local bundle clean/source_tree_dirty=false PASS, tag=null, никаких published artifacts. Actual Linux images/Trivy/remoteCI/publicHTTPS/provider/ops/OIF/owner review требуют E01…E07 и не считаются пройденными.

# Исправления production readiness F-01…F-27

Code SHA `ae700d7a9803b9757980ef1862af31f6f360a97d`, продукт0.2.0; повторный аудит 2026-10-04T14:29:39.176059+03:00, Codex. Первоначальный локальный snapshot:22 CLOSED/4 PARTIALLY VERIFIED/1 BLOCKED EXTERNAL. Дополнение 2026-10-04T21:22:18.101374+03:00: **CONDITIONALLY READY**,23 CLOSED/4 PARTIALLY VERIFIED; E01 подтверждён реальными Linux Compose/Trivy в [CI37222860411](https://github.com/alxprgstech/sso/actions/runs/37222860411) на `44c3ff96600bf9aa107ef1bf138814414ad8c664`. Остальные внешние gates и CodeScene E02 сохраняются. Это не production-приёмка GOAL-09.

Основные изменения: strict production keys/TLS, PG quotas/security revision/reauth, verified identity, OIDC wire/PKCE/claims/fresh-auth/logout/scopes и независимый SDK, forced password change, non-root/least-privilege runtime/DB, enforced CSP/safe diagnostic codes, настоящие races/Windows tests и точная документация. Три MFA-флага default false; обязательное registration email подтверждение сохранено.

| Finding | Severity | Итог | Подробности |
| --- | --- | --- | --- |
| F-01 | HIGH | PARTIALLY VERIFIED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-01--high--partially-verified) |
| F-02 | HIGH | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-02--high--closed) |
| F-03 | HIGH | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-03--high--closed) |
| F-04 | HIGH | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-04--high--closed) |
| F-05 | HIGH | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-05--high--closed) |
| F-06 | HIGH | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-06--high--closed) |
| F-07 | HIGH | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-07--high--closed) |
| F-08 | HIGH | PARTIALLY VERIFIED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-08--high--partially-verified) |
| F-09 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-09--medium--closed) |
| F-10 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-10--medium--closed) |
| F-11 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-11--medium--closed) |
| F-12 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-12--medium--closed) |
| F-13 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-13--medium--closed) |
| F-14 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-14--medium--closed) |
| F-15 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-15--medium--closed) |
| F-16 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-16--medium--closed) |
| F-17 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-17--medium--closed) |
| F-18 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-18--medium--closed) |
| F-19 | MEDIUM | PARTIALLY VERIFIED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-19--medium--partially-verified) |
| F-20 | MEDIUM | PARTIALLY VERIFIED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-20--medium--partially-verified) |
| F-21 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-21--medium--closed) |
| F-22 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-22--medium--closed) |
| F-23 | MEDIUM | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-23--medium--closed) |
| F-24 | LOW | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-24--low--closed) |
| F-25 | LOW | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-25--low--closed) |
| F-26 | LOW | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-26--low--closed) |
| F-27 | LOW | CLOSED | [Fix / regression / result](PRODUCTION_READINESS_AUDIT.md#f-27--low--closed) |

Исторический локальный implementation ae700d7: полный535 +16subtests, enabled20, replay104, настоящий Nginx/Chromium34+10, clean installed SDK17, frontend11unit/28component/9telemetry; пересекающиеся наборы не суммируются. Ruff/mypy/types/build/scans PASS, dependency audits0known vulnerabilities, clean exact-SHA bundle8payload+manifest/checksums PASS. Источник проверок — [evidence](audit/remediation-evidence.json) и [журнал](worklog.md).

Текущий Actions CI подтверждён; CodeScene E02 остаётся failed. Не проверено: public HTTPS/proxy, live SES/Gmail, operational key/backup/alert/privacy custody, applicable OIF и историческое owner secret review. Точные inputs/команды/условия — [раздел7 отчёта](PRODUCTION_READINESS_AUDIT.md#7-остаточные-внешние-проверки-точные-условия). Публичные push/PR разрешены владельцем и выполнены; deployment/release/live mail не проводились.

Первоначальный NOT READY audit и failures — [неизменённый baseline](PRODUCTION_READINESS_AUDIT_BASELINE.md). Local closure относится к новому code SHA, а не переписывает прежний результат.

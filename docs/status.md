# Актуальный статус ALXPRGS SSO

## Точка продолжения

- AGENT-RULES-01 — done: введены выборочное чтение, исключение для консультаций и учёт по существенным этапам; история отделена. Проверки — [журнал](worklog.md). Ветка запушена; [PR #36](https://github.com/alxprgstech/sso/pull/36) в main. Следующий шаг: review и CI текущего HEAD; merge PR не выполнялся.
- Продукт 0.3.0; общая production-приёмка не закрыта. Требования безопасности и default-on MFA сохранены. Исторические локальные/CI результаты — [acceptance](acceptance.md); они не доказывают текущий SHA.
- Последняя запись передачи по CD-STAGES-01/CD-PUBLIC-CHECK-01: PR #34, код `07f871a`, локальные проверки и HTTPS успешны; remote CI, интеграция и selective rerun в этой сессии не проверялись. Дальнейшие действия требуют проверки текущего состояния PR/CI.
- Открытые задачи и блокеры — [план](plan.md): версия lock, внешняя OIF/ops приёмка, FR-08; live SES/Gmail/Sentry, multi-replica и owner review остаются условиями общей приёмки. Архивирование не закрывает эти требования.

## Последние результаты из main

Перенесено из main db74885: PR #35 уже интегрирован; результаты ниже относятся к указанным ревизиям.

## AUDIT-FULL-20261026 — in_progress → review

2026-10-27T00:15:00+03:00: в ветке `audit/full-stack-security-ui-ci-20261026` выполнен комплексный аудит (security/auth/API/frontend/CI). Исправлены: двойной пароль REG-02, потеря 5-минутного session-read grant при reload (tab-scoped sessionStorage), диагностика repeated TOTP (`401 totp_code_reused` + Retry-After без ослабления one-use), потеря exception headers, RBAC до reauth для admin API, очередь reauth-диалога; обновлены setuptools/filelock, vitest/jsdom/@sentry/cli + транзитивные next/undici, frontend image nginx 1.30.6 + apk upgrade. Добавлены PostgreSQL/unit/component/Playwright регрессии и отчёты `docs/audit/2026-10-26-*`, ADR-0034. Локально: backend pytest, frontend 14 unit/51 components, Playwright 50+9, pip-audit/npm audit/Trivy 0. Production/EC2/DNS/secrets не затрагивались. Следующий шаг — push, PR и проверка GitHub CI на финальном HEAD; общая production-приёмка остаётся открытой.

## CODESCENE-REMEDIATION-01 — done

2026-10-27T01:46:00+03:00: CodeScene gate `Prevent hotspot decline` для PR #35 исправлен в `5cf9c68` без изменения security-поведения. `client.ts`: grant parsing вынесен в простые функции, `ApiError` принимает typed options object; добавлены 13 регрессий (18 в session-grants, 64 components). CodeScene на новом HEAD — success, 3/3 gates passed; GitHub Actions run 40412383740 — success (9/9 обязательных jobs). Merge/release/deploy не выполнялись.

## Навигация по истории

[Предыдущий срез](status-history.md) сохраняет подробности MFA/step-up/security/CD и границы прежних проверок. [Архив плана](plan-history.md) сохраняет старые ID и статусы. В [журнале](worklog.md) ищи нужный ID; читать всё при каждом старте не требуется. Не возобновляй старые задачи автоматически.

# Актуальный статус ALXPRGS SSO

Обновлено: 2026-10-18T16:13:56+03:00. Продукт 0.2.0; ветка `new/security-remediation`, база `170175be06318645c0fd2ef222e2688edf31b37c`. SEC-REMED-20261007-R1–R5 — `done`: локальные исправления и приёмка завершены. SEC-REMED-PR-01 — `in_progress`: commit/push/PR по поручению владельца.

## Реализовано

- R1: независимый Gmail action secret, resend rotation, атомарное погашение code/link/action; bounded fail-closed Google JWKS.
- R2: canonical Passkey IDs, миграция с отказом коллизий, indexed lookup; отдельный пятиминутный session read grant и одноразовые mutation proofs.
- R3: strict SDK TLS/local loopback, Origin/Referer policy с OIDC front-channel границей, безопасные redirect URI; hash companions/CI/Docker, SBOM и unsigned provenance.
- R4: transactional audit/outbox, bounded delivery, owner-only backup/key ACL; устранено сохранение сторонних explicit Windows ACE. Обновлены два уязвимых Alpine package pins frontend image.

Решения: [ADR-0023](adr/0023-security-remediation.md). Матрица и пределы evidence: [повторная проверка](audit/security-remediation-20261018.md). Исходный [аудит](../SECURITY_AUDIT.md) — исторический документ до исправлений.

## Подтверждённые проверки продолжения

Ruff/format, mypy73files; full/runtime/build hash companions; clean hashed install и pip check; SDK wheel/sdist и29installed-wheel tests; frontend lint/types/test-types/unit13/components40/build; secrets127/0new и self-test; pip-audit/npm audit0known; Trivy backend/исправленный frontend High/Critical0; Compose и3CSP browser tests до последней Origin-правки; ACL+backup53PASS; Origin policy36PASS; генерация RSA/session/TOTP с owner-onlyACL3PASS.

Финальный full pytest:687PASS/18subtestsPASS,5external email deselected; enabled PG20PASS; post-change OIDC PG+boundary54PASS. Browser default-off48PASS/enabled9PASS. Финальные images Trivy0High/Critical, release dry-run PASS; Compose runtime/CSP3/outage/recovery PASS с owned cleanup. Неуспешные диагностические запуски сохранены в [журнале](worklog.md).

## Ограничения и продолжение

Локальные результаты сохранены в [приёмке](acceptance.md). Завершить commit/push/PR; remote CI будущего commit ещё не подтверждён.

Production-приёмка остаётся открытой: реальные SES/Gmail/Sentry, sender registration, public TLS/DNS/IAM/secret storage, внешние backup/storage ACL, OIF/multi-replica load и review исторических credentials не проверены локальным retest. [DOC-VERSION-LOCK-01](plan.md) остаётся отдельной planned задачей и не входит в remediation.

Default-off TOTP/Passkey/Recovery и обязательное email confirmation сохранены. Release publication, deployment, CD activation и реальные рассылки не выполняются. Чужие контейнеры/данные сохраняются; тестовый backend использует порт18000.

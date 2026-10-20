# Актуальный статус ALXPRGS SSO

Обновлено 20.10.2026. Продукт 0.2.0, база `7d1585e7bdd40104be7a8b933b998cbc843d46a5` содержит merge [PR #13](https://github.com/alxprgstech/sso/pull/13). Текущая рабочая ветка `new/documentation-value-review`. Production-приёмка открыта.

## Реализация и подтверждения

SEC-REMED-20261007-R1–R5 завершены локально 18.10.2026: Gmail action binding/rotation, canonical indexed Passkey lookup, separate session grants/proofs, строгие TLS/Origin/redirect policies, hashed dependencies/SBOM/provenance, transactional audit/outbox и private key/backup ACL. Решения — [ADR-0023](adr/0023-security-remediation.md).

Последний локальный retest: full PostgreSQL 687 PASS/18 subtests, enabled20, post-change OIDC54; browser default48/enabled9; SDK29, frontend unit13/components40; Compose/CSP/outage/recovery, builds/release dry-run/Trivy/secrets успешны. Пять внешних email tests исключены. Точные команды, окружение, scope и ограничение dirty source — [приёмка](acceptance.md); failures — [worklog](worklog.md). Это результаты прежнего кандидата, не новый прогон merge SHA. Remote CI merge SHA в текущей задаче не проверен.

## Документация

DOC-VALUE-01 завершён. DOC-CLEANUP-02 завершён: сокращены старые BUG/checklist/планы/CI chronology, evidence перенесено в приёмку, threat model — в security. Старый security audit, отдельный remediation report и разовый отчёт анализа удалены; tracked версии доступны по точным Git-ссылкам в действующих документах. Worklog, audit replay/probe map и CodeScene policy сохранены.

Проверки очистки: 64 Markdown UTF-8, 292 локальные ссылки без отсутствующих целей, 9 исторических Git targets; secret self-test успешен, 126 candidates/0new. Полный журнал сохранён.

## Продолжение

- DOC-VERSION-LOCK-01 — planned: согласовать version metadata npm lock с bump/check и regression; [дефект](testing/defects.md).
- Production: live SES/Gmail/Sentry и sender registration; public TLS/DNS/IAM/secret storage; внешние backup/storage ACL/alerts, OIF/multi-replica load, owner review исторических credentials — не проверены локальной приёмкой.
- Последующая работа — [план](plan.md). Начатые ранее внешние проверки не отменены очисткой. Release publication/deployment/CD activation/реальные рассылки не выполнялись.

TOTP/Passkey/Recovery выключены по умолчанию; email confirmation самостоятельной регистрации обязательно. Защита и тесты этой очисткой не меняются.

SSO-SEC-0006 in_progress; первые5issues опубликованы независимыми PR21–25, не merged.

SSO-SEC-0006 локально проверен23PASS. Общая кампания продолжается: remoteCI выявил libx11image CVE вPR21–24 и устаревший schema guard вPR25; исправления и повторы обязательны до итогового отчёта.

Общий inherited image-CVE blocker исправлен pinned libx11/tiff; повтор обязательного CI pending.

## Завершение обработки #15–20 (2026-10-20T16:46:52.2264279+03:00)
Созданы PR21–26 вmain, комментарии оставлены в6issues. Все подтверждённые сценарии имеют regression; локальные результаты в acceptance. Общий inheritedlibx11CVE исправлен во всех ветках; source/releaseTrivy0HIGH/CRITICALPASS. PR25 schema guard0014 исправлен, ComposeCSP3/migrationrole и GitHubCI39432532318SUCCESS. Остальные обязательные CI повторяются; актуальные итоги смотреть в checks соответствующих PR и финальных issue-comments. Merge, ручное закрытие, production и реальные рассылки не выполнялись. Внешние SES/Gmail rendering/load ограничения остаются; общая production-приёмка этим не закрыта.

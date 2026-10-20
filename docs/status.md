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

SSO-SEC-0002 in_progress (2026-10-20T16:05:11.3295866+03:00); #15 опубликован PR21 в независимой ветке, не merged.

SSO-SEC-0002 завершён локально 2026-10-20T16:07:24.3035665+03:00: PG6+10PASS; scope — все grants, JWT до exp. #17–20 продолжаются.
## Текущая security-кампания
SEC-ISSUES-20261020 in_progress с 2026-10-20T16:00:07.3287809+03:00: отдельные исправления/PR для #15–20; результаты прежней приёмки не переносятся на новые изменения.

SSO-SEC-0001: локальное исправление и PG1+10/Ruff/mypy завершены 2026-10-20T16:03:30.6105628+03:00; PR подготавливается. Остальные пять issues in_progress.

Общий inherited image-CVE blocker исправлен pinned libx11/tiff; повтор обязательного CI pending.

SEC-MERGE-20261020 in_progress (2026-10-20T20:32:43.1105797+03:00): merge разрешён владельцем; PR21 уже merged,22–26 ожидают последовательного объединения и CI. Старые статусы выше исторические.

SSO-SEC-0003 in_progress; #15PR21/#16PR22 опубликованы отдельно, не merged.

SSO-SEC-0003 локально done 2026-10-20T16:10:59.2619568+03:00:20PASS + realArgon2 collision1PASS. PR подготавливается; #18–20 продолжаются.

Общий inherited image-CVE blocker исправлен pinned libx11/tiff; повтор обязательного CI pending.

Последний #17 follow-up (2026-10-20T16:56:04.6698984+03:00): единый pending/mail путь без Userlookup устраняет дополнительные repeat-ID/quota/providerfailure oracles;26PASS+static/secretPASS, ADR0028. Коллизия раскрывается только после mailbox proof, existing credentials не меняются; MAX_SENDS3 сохранён. PR23 ждёт финальный CI. Другие5PR21/22/24/25/26 уже имеют SUCCESS на финальных functional SHA; ссылки в worklog. Общая production-приёмка и live SES/Gmail/load вне этой кампании.

## Финальный результат (2026-10-20T17:02:01.9691227+03:00)
Все6issues обработаны: #15→PR21, #16→PR22, #17→PR23, #18→PR24, #19→PR25, #20→PR26. Все6finalfunctionalCI SUCCESS; exactSHA/runlinks/localtests — acceptance. Security blockers image/schema устранены без ослабления проверок. Final#17 использует единый pending/mail путь, а не ранний response-only вариант. Каждому issue оставлен результат; PR не merged, issues вручную не закрыты. Следующий шаг — review владельца; возможны конфликты append-only документов при последовательном merge, сохранить оба registration изменения. Production/liveSES/GmailRendering/distributedload остаются вне подтверждённой приёмки. Этот итоговый documentation-only checkpoint проверяется обычным CI.

SSO-SEC-0004 in_progress; #15–17 PR21–23 опубликованы, не merged.

SSO-SEC-0004 локально done 2026-10-20T16:17:10.7190217+03:00:20PASS,65typechecked; #19–20 продолжаются.

Общий inherited image-CVE blocker исправлен pinned libx11/tiff; повтор обязательного CI pending.

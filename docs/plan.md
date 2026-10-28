# План ALXPRGS SSO

Обновлено 28.10.2026 (AGENT-RULES-01). Сокращён по поручению владельца (DOC-CLEANUP-02). Текущие требования: [ТЗ](01-technical-specification.md), AGENTS.md. Хронология сохраняется в [worklog](worklog.md); [исходный план](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/plan.md) хранит подробные критерии, зависимости, начало/завершение и промежуточные результаты всех прежних ID. Старые задачи не отменены очисткой; исторический blocked/planned не превращён автоматически в done.

## Текущие задачи

| ID | Приоритет | Зависимости | Статус | Критерий и следующий шаг |
| --- | --- | --- | --- | --- |
| CD-IDEMPOTENCY-01 | P2 | CD-STAGES-01, CD-PUBLIC-CHECK-01 | done | Пропускать повторный CD уже исправно установленного полного SHA: ранняя HTTPS-проверка identity/readiness до сборки и повторная проверка под серверной блокировкой; различать deployed/already_deployed/superseded; сохранить CI gate, freshness, sequence, transport, backup и rollback; совместимость старого ssoctl и документированный первый переход. Начало 2026-10-29T00:40:24+03:00; завершение 2026-10-29T01:19:54+03:00; исполнитель DeepSeek Harness. Локально: 177 targeted PASS, Ruff, mypy, bash -n, diff; GitHub Actions run `40779407713` на `2a56fd2` — все jobs success (Playwright PASS); CodeScene external gate — pass. [PR #38](https://github.com/alxprgstech/sso/pull/38). Production не изменялся; требуется точечное обновление ssoctl. |
| MFA-RECOVERY-EXPORT-01 | P2 | MFA-DEFAULT-ADMIN-01, frontend | done | Скачивание текущего набора резервных кодов в UTF-8 TXT (email, инструкция, BOM), генерация при TOTP или Passkey; Passkey сначала создаётся, затем имя с автоподстановкой и подтверждением пустого. Authlib 1.8.0→1.9.1 по CVE. Начало 2026-10-28T23:35:15+03:00. Проверки: frontend lint/typecheck/typecheck:tests/unit 20/components 79/build, pip_audit 0, secret scan 0 new. CI run `40767610691` — success, Playwright PASS. [PR #37](https://github.com/alxprgstech/sso/pull/37); merge/release не выполнялись. |
| DOC-VERSION-LOCK-01 | P2 | DOC-REFRESH-01, DOC-DEF-01 | planned | Bump/check учитывают root package-lock version и packages[""].version; regression в отдельной копии без изменения dependency resolution. Начало реализации не назначено. |
| AUDIT-FIX-03 | P1 | Локальное OIDC remediation, внешний стенд | blocked | Выполнить применимую OIF matrix на утверждённом публичном HTTPS issuer с отдельными клиентами; локальный retest не заменяет внешний результат. |
| AUDIT-FIX-05 | P1 | Локальное ops remediation, утверждённая инфраструктура | blocked | Подтвердить public TLS/DNS/IAM/secret storage, внешние backup/storage ACL и alerts. Локальные Linux images/Trivy/Compose проверены 18.10; внешний production-контур остаётся условием разблокировки. |
| FR-08 | P2 | FRONTEND-REDESIGN-01 | planned | Необязательное продолжение frontend; исходные критерии и границы — [план redesign](https://github.com/alxprgstech/sso/blob/3603d5721938f594d7892c8c33ba33912906bcb4/docs/frontend-redesign-plan.md). Не закрыто очисткой. |
| DOC-CLEANUP-02 | P2 | DOC-VALUE-01 | done | Сократить историю, перенести полезные сведения и удалить заменённые отчёты; сохранить открытые требования и тестовые зависимости; links/UTF-8/diff/secret scan. |
| EXT-STEPUP-01 | P0 | OIDC/MFA/SDK, PostgreSQL, frontend | done | Реализован opt-in cross-application hosted step-up с password/TOTP/Passkey/комбинированными политиками, transaction binding, one-use server redemption, SDK/UI/тестами и self-audit. Матрица, миграция0015, SDK0.3.0 и локальные коммиты зафиксированы; production activation не входит. |
| MFA-DEFAULT-ADMIN-01 | P0 | EXT-STEPUP-01, PostgreSQL, frontend, SDK, EC2 | done | Default-on TOTP/Passkey/Recovery, обязательная MFA администратора, session assurance, recovery при TOTP/Passkey, non-destructive EC2 migration, OIDC role assurance, тесты и self-audit. Начало 2026-10-26T14:52:11+03:00; code `9dd90d1`, CI `008f658`, ветка new/default-on-mfa-admin-policy. Production не изменялся; точные результаты — [acceptance](acceptance.md). |

Внешние SES/Gmail/Sentry, sender registration, multi-replica load и приватный owner review исторических credentials остаются условиями общей приёмки; [матрица и ограничения](acceptance.md), [безопасность](security.md). Их исторические ID/статусы/времена доступны по исходному плану и журналу, нового PASS нет. Остальные прежние незакрытые локальные/CI checkpoints требуют сверки с более поздним evidence перед возобновлением, а не автоматического выполнения старого плана.

## История

Завершённые этапы и исторические реестры: [архив плана](plan-history.md). Не читать целиком при старте задачи.

## CD-STAGES-01 — in_progress
Приоритет P1; зависимости: существующий EC2 CD. Разделить build → verify → deploy с неизменяемым приватным artifact одного run/SHA. Критерий: повтор failed deploy не пересобирает и не перепроверяет успешные jobs; gates/freshness/transport/server rollback сохранены; regression policy tests PASS. Начало: 2026-10-26T19:06:39+03:00; исполнитель Codex.

CD-STAGES-01 — done (local), 2026-10-26T19:09:37+03:00. Build/verify/deploy и immutable artifact одного run реализованы; точное имя из outputs build совместимо с закреплённым download-artifact. Проверки: EC2/policy 41 PASS, Ruff check/format PASS, git diff --check PASS. Live GitHub rerun остаётся непроверенным до интеграции; production не затронут.

## CD-PUBLIC-CHECK-01 — in_progress
Приоритет P1; зависимость CD-STAGES-01. Начало 2026-10-26T19:11:57+03:00; Codex. Добавить финальный отдельный job public-check: HTTPS /health/ready на auth.alxprgs.tech после фактической установки; ошибка делает CD красным, повтор не развёртывает заново. Критерии: positive/negative unit и workflow tests, docs, push всех изменений ветки и PR в main.

CD-PUBLIC-CHECK-01 — done (local), 2026-10-26T19:14:23+03:00. Реализован отдельный public-check после installed=true, HTTPS /health/ready с TLS/HTTP/JSON validation без redirects/retries; добавлен в обязательный CI test suite. EC2/public/backup/workspace:60PASS, Ruff/check/format/diffPASS. Live HTTPS с рабочей станции PASS (200/database connected). Следующий шаг: commit/push/PR; live GitHub scheduler и selective rerun остаются непроверенными.

2026-10-26T19:15:37+03:00 — CD-STAGES-01/CD-PUBLIC-CHECK-01: push и [PR #34](https://github.com/alxprgstech/sso/pull/34) выполнены; критерии текущего запроса закрыты. Новые jobs/selective rerun проверяются после интеграции; merge/deploy не поручены.

## AGENT-RULES-01 — done
Приоритет P2; зависимости: действующие правила проекта. Начало 2026-10-28T23:17:59.7544429+03:00. Критерий: выборочное чтение, исключение для консультаций, учёт по существенным этапам, отдельная история, сохранение требований безопасности; проверка локальных ссылок и diff. Завершение 2026-10-28T23:19:59+03:00. Выборочное чтение и учёт по этапам введены; история сохранена отдельно. Проверки: 119 локальных ссылок/UTF-8, дословная сохранность security/MFA и архивов, git diff --check PASS. Следующий шаг: локальный commit; runtime-проверки для редакторской правки не требуются.

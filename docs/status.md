# Актуальный статус ALXPRGS SSO

## Точка продолжения

- AGENT-RULES-01 — done: введены выборочное чтение, исключение для консультаций и учёт по существенным этапам; история отделена. Проверки — [журнал](worklog.md). Следующий шаг: review локального коммита в `new/lean-agent-rules`; push/PR не выполнялись.
- Продукт 0.3.0; общая production-приёмка не закрыта. Требования безопасности и default-on MFA сохранены. Исторические локальные/CI результаты — [acceptance](acceptance.md); они не доказывают текущий SHA.
- Последняя запись передачи по CD-STAGES-01/CD-PUBLIC-CHECK-01: PR #34, код `07f871a`, локальные проверки и HTTPS успешны; remote CI, интеграция и selective rerun в этой сессии не проверялись. Дальнейшие действия требуют проверки текущего состояния PR/CI.
- Открытые задачи и блокеры — [план](plan.md): версия lock, внешняя OIF/ops приёмка, FR-08; live SES/Gmail/Sentry, multi-replica и owner review остаются условиями общей приёмки. Архивирование не закрывает эти требования.

## Навигация по истории

<<<<<<< HEAD
[Предыдущий срез](status-history.md) сохраняет подробности MFA/step-up/security/CD и границы прежних проверок. [Архив плана](plan-history.md) сохраняет старые ID и статусы. В [журнале](worklog.md) ищи нужный ID; читать всё при каждом старте не требуется. Не возобновляй старые задачи автоматически.
=======
Конфликты разрешены с сохранением всех шести security-контрактов. Для совместимости нейтральной регистрации и browser proof добавлен regression resend; в cancellation unit-test ожидание завершения asyncio заменено корректным join реальных потоков перед final cleanup assertion. Production-код лимитов для исправления теста не менялся. Обязательный CI финальных PR heads успешен; CI последующего documentation-only checkpoint — отдельная ревизия.

При обновлении требуется миграция `0014_registration_browser`; старые незавершённые регистрации должны начать flow заново. Существующие accounts/sessions миграция не изменяет. Logout/self-revoke отзывает все refresh/code grants, сохраняемые browser sessions могут начать новый flow; offline access JWT действует до exp, максимум300с.

Локально проверены совместные security-сценарии на отдельной PostgreSQL16, Ruff/format/mypy, секреты и Markdown. Полный backend/PG, enabled/default-off browser, SDK, frontend и контейнерные проверки выполнены обязательным CI PR. Live SES job без AWS credentials пропущен по ранее согласованной политике; доставки он не подтверждает.

Production-приёмка остаётся открыта: live SES/Gmail/Sentry и sender registration, public TLS/DNS/IAM/secret storage, внешние backup/storage ACL/alerts, OIF/multi-replica load и owner review исторических credentials. Deployment, release publication и активация CD не выполнялись. DOC-VERSION-LOCK-01 и остальные открытые требования — [план](plan.md).

TOTP/Passkey/Recovery доступны по умолчанию; MFA администратора обязательна; email confirmation самостоятельной регистрации обязательно. Текущая схема и security-модель — [миграция](migration.md), [безопасность](security.md), [ADR-0032](adr/0032-default-on-mfa-and-admin-policy.md).

## DEPLOY-EC2-01 — in_progress
2026-10-25T16:16:15.9332703+03:00: согласован активный CD из main после CI того же SHA вместо прежнего запрета. Ветка new/ec2-deployment. AWS-команды выполняет владелец; live-приёмка пока не выполнена.

2026-10-25T16:57:52.0663676+03:00: локальная реализация DEPLOY-EC2-01 готова к review: bootstrap/nginx/Let'sEncrypt timers/Resend alerts/backupchecksums/CD exactSHA и инструкция. Проверки43unit+9CIpolicy, реальный UbuntuTLS/flock/OpenSSL и PostgreSQLbundle/backuprestorePASS. Код приложения не менялся. AWS/remoteCI/liveemail/ACME не проверены; следующий шаг — первоначальный bootstrap владельцем по [инструкции](ec2-deployment.md). Общаяприёмка остаётся открыта.

Локальный codecommit: 2855f77b26ef95ea2189a5b70a81ce150b8b50ed, new/ec2-deployment; push отсутствует. Точка продолжения — раздел2 инструкции EC2 и результаты владельческого запуска.

2026-10-25T17:05:53.5624069+03:00: finalaudit выявил backup filename collision cleanup; исправлен с4regression,47targetedPASS. Выполняется повтор transport/actualPG для этой версии; ранее записанный handoff не закрывает новыйfix.

2026-10-25T17:10:53.1873172+03:00: повтор после backupfix завершён: codecommit c358413253189c5880ceea4f5c5ca2f195f9a182 собран и проверен actualPG/backuprestore/checksum;47targetedPASS, UbuntuTLS/config/fsync/flockPASS, secrets126/0new. Локальная реализация готова; ожидается пользовательский запуск по docs/ec2-deployment.md. Общая AWS-приёмка пока in_progress, remote push отсутствует.

2026-10-25T17:13:06.0638441+03:00: DEPLOY-EC2-01 blocked только на внешнем действии владельца: ожидается результат bootstrap EC2. Код и локальные проверки готовы, дерево до этой записи чистое; AWS/live-приёмка не выполнена. Продолжение после сообщения об успехе либо обезличенной ошибке установщика.

2026-10-25T17:27:42.1509866+03:00: владелец запустил bootstrap EC2; пакеты установлены, конфигурация создана, nginx syntax PASS. Новый наблюдаемый blocker — Certbot HTTP-01 connection timeout на публичном TCP80. Сертификат и bootstrap не завершены; требуются сетевые проверки владельцем и повтор bootstrap. Прежнее ожидание первого запуска снято фактическим выводом.

2026-10-25T18:03:29.4349911+03:00: по прямому запросу владельца подготовлен manualCD без общегоCI через workflow_dispatch только main. Автоматический success gate и обязательный transport test сохранены;47unit/contractPASS. Для появления Runworkflow изменение должно быть в main; фактический запуск не выполнялся.

2026-10-25T18:14:46.1568259+03:00: устранён clean-runner failure Output parent must already exist в transport check. Parent artifacts создаётся автоматически;53tests и actualLinux permissionsPASS. Обновить main и запустить новый ручной CD; повтор старогоrun останется на старомSHA. EC2переустановка для этой ошибки не требуется.

2026-10-25T19:41:38+0300: найдена первопричина падения CD run 6 на проверке image ID: раннер ubuntu-24.04 использует containerd image store (ID=digest манифеста, docker save=OCI), сервер — классический store (ID=config-digest); backend получил другой ID, PostgreSQL без тега не загрузился. Исправление: pin классического store на раннерах CD/CI, config-digest из парса images.tar, тег alxprgs-sso-postgres, репетиция серверной проверки после load, argv в ошибках ssoctl, ADR-0030; 42 targeted PASS. Пуш в main по прямому указанию владельца запускает CI→CD; live-деплой подтверждается новым CD run.

2026-10-25T20:52:00+0300: первый успешный production-деплой — 69794fb, sequence 11, публичная HTTPS/discovery проверка PASS (auth.alxprgs.tech). Транспорт образов стабилизирован: классический image store закреплён на раннерах CD/CI и на сервере (bootstrap + инструкция). Автоматический CD из push заблокирован красными security-audit job до отдельного обновления зависимостей (undici npm; setuptools/filelock pip; trivy); ручной workflow_dispatch из main работает. Следующий шаг владельца: sudo ssoctl admin и live-приёмка.

## CD-STAGES-01 — in_progress
2026-10-26T19:06:39+03:00: разделение CD на повторяемые стадии; следующий шаг — workflow, regression tests, документация.

CD-STAGES-01 — done (local), 2026-10-26T19:09:37+03:00: в new/cd-retry-stages подготовлены build → verify → deploy с повторным использованием immutable transport (7 дней). EC2/policy41PASS, Ruff/diffPASS. Push/deploy не выполнялись; live-повтор GitHub Actions ещё не проверен. Продолжение: review и интеграция, новый run использует разделённый workflow.

CD-PUBLIC-CHECK-01 — in_progress, 2026-10-26T19:11:57+03:00: добавление внешнего HTTPS readiness последним job, затем проверка, push и PR.

2026-10-26T19:14:23+03:00 — CD-PUBLIC-CHECK-01 локально done: build → verify → deploy → public-check. Последний job проверяет публичный /health/ready, повторяется без установки. Targeted60PASS/Ruff/diffPASS; реальный HTTPS с рабочей станции PASS. Готовится push/PR; remote CI и selective rerun пока не проверены.

2026-10-26T19:15:37+03:00 — CD-STAGES-01/CD-PUBLIC-CHECK-01: изменения запушены, [PR #34](https://github.com/alxprgstech/sso/pull/34) открыт в main, конфликтов нет по GitHub metadata. Код07f871a;60 targeted PASS и live HTTPS PASS. Merge/deploy не выполнялись; remote CI не оценён.

## AUDIT-FULL-20261026 — in_progress → review

2026-10-27T00:15:00+03:00: в ветке `audit/full-stack-security-ui-ci-20261026` выполнен комплексный аудит (security/auth/API/frontend/CI). Исправлены: двойной пароль REG-02, потеря 5-минутного session-read grant при reload (tab-scoped sessionStorage), диагностика repeated TOTP (`401 totp_code_reused` + Retry-After без ослабления one-use), потеря exception headers, RBAC до reauth для admin API, очередь reauth-диалога; обновлены setuptools/filelock, vitest/jsdom/@sentry/cli + транзитивные next/undici, frontend image nginx 1.30.6 + apk upgrade. Добавлены PostgreSQL/unit/component/Playwright регрессии и отчёты `docs/audit/2026-10-26-*`, ADR-0034. Локально: backend pytest, frontend 14 unit/51 components, Playwright 50+9, pip-audit/npm audit/Trivy 0. Production/EC2/DNS/secrets не затрагивались. Следующий шаг — push, PR и проверка GitHub CI на финальном HEAD; общая production-приёмка остаётся открытой.

## CODESCENE-REMEDIATION-01 — done

2026-10-27T01:46:00+03:00: CodeScene gate `Prevent hotspot decline` для PR #35 исправлен в `5cf9c68` без изменения security-поведения. `client.ts`: grant parsing вынесен в простые функции, `ApiError` принимает typed options object; добавлены 13 регрессий (18 в session-grants, 64 components). CodeScene на новом HEAD — success, 3/3 gates passed; GitHub Actions run 40412383740 — success (9/9 обязательных jobs). Merge/release/deploy не выполнялись.
>>>>>>> origin/main

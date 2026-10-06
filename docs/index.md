# Документация ALXPRGS SSO

Продукт 0.2.0. Актуализация: 06.10.2026. Источник версии — `VERSION`; состояние приёмки — [status.md](status.md). Целевой issuer `https://auth.alxprgs.tech` не подтверждает существование production.

## Как читать комплект

| Задача | Документы |
| --- | --- |
| Запустить локально, создать администратора | [README](../README.md), [эксплуатация](operations.md) |
| Настроить приложение | [Конфигурация](configuration.md), [миграция](migration.md) |
| Пользоваться и администрировать | [Руководство оператора](04-operator-guide.md), [frontend](frontend.md) |
| Подключить сервис | [Руководство программиста](06-programmer-guide.md), [SDK](sdk.md), [API](api.md), [примеры](../examples/README.md) |
| Проверить систему | [Подготовка тестирования](testing/README.md), [методика](03-test-procedure.md), [чек-лист](testing/manual-checklist.md) |
| Разобраться в требованиях | [ТЗ](01-technical-specification.md), [описание программы](02-program-description.md), [архитектура](architecture.md), [модель данных](data-model.md) |
| Проверить ограничения | [Безопасность](security.md), [privacy](privacy.md), [наблюдаемость](observability.md), [дефекты](testing/defects.md) |
| Выпустить версию | [Релизы](releases.md), [системное руководство](05-system-programmer-guide.md) |
| Понять историю | [ADR](adr/0001-stack-selection.md), [приёмка](acceptance.md), [журнал](worklog.md), [план](plan.md) |

## Правила актуальности

ТЗ и AGENTS.md задают требования; исходники описывают фактическую реализацию. При расхождении сохраняется требование и регистрируется дефект. OpenAPI показывает схемы/маршруты, но не доказывает бизнес-политику, криптографию или атомарность PostgreSQL.

Исторический PASS относится только к указанным SHA, профилю и окружению. ADR сохраняют первоначальную мотивацию; поздние решения могут заменять отдельные положения. Удалённые GOAL и разовые отчёты доступны по точным ссылкам Git, их не требуется восстанавливать в рабочем дереве.

## Реестр проверки

Полный пофайловый реестр DOC-REFRESH-01 приведён ниже. Поддерживаемый комплект включает Markdown, снимок API, публичные robots/llms и исторические evidence JSON. Исходники probes, лицензии зависимостей, кэши и сгенерированные артефакты не являются инструкциями продукта; исторические evidence не обновляются под текущий SHA.


Сверка означает проверку документа/источников/ссылок в указанном объёме, а не runtime PASS. Реестр охватывает 63 Markdown и 13 сопутствующих файлов.

| Документ | Результат | Источник и предел проверки |
| --- | --- | --- |
| [AGENTS.md](../AGENTS.md) | проверен | Действующие правила владельца; изменять требования не поручено |
| [ALXPRGS Design Language.md](../ALXPRGS%20Design%20Language.md) | обновлён | Нормативный дизайн, frontend tokens/маршруты и ADR0021/0022; исходный английский текст сохранён |
| [CHANGELOG.md](../CHANGELOG.md) | исторический; проверен | История версий сверена с VERSION; не новый выпуск, прежние записи сохранены |
| [README.md](../README.md) | обновлён | README/manifest/Compose/start scripts, API и навигация |
| [backend/README.md](../backend/README.md) | обновлён | README/manifest/Compose/start scripts, API и навигация |
| [docs/01-technical-specification.md](../docs/01-technical-specification.md) | обновлён | Требования, API/services/config и фактическая топология |
| [docs/02-program-description.md](../docs/02-program-description.md) | обновлён | Требования, API/services/config и фактическая топология |
| [docs/03-test-procedure.md](../docs/03-test-procedure.md) | обновлён | README/manifest/Compose/start scripts, API и навигация |
| [docs/04-operator-guide.md](../docs/04-operator-guide.md) | обновлён | App/routes/controllers/tokens/footer, capabilities и backend policy |
| [docs/05-system-programmer-guide.md](../docs/05-system-programmer-guide.md) | обновлён | Compose/Dockerfile/Alembic/операционные scripts; help, без runtime/restore |
| [docs/06-programmer-guide.md](../docs/06-programmer-guide.md) | обновлён | SDK client/fastapi/signatures и demo_app/demo_sessions; snippets compile, без live callback |
| [docs/acceptance.md](../docs/acceptance.md) | обновлён | Хронология задач и результатов, новый checkpoint, без переноса прежних PASS |
| [docs/adr/0001-stack-selection.md](../docs/adr/0001-stack-selection.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0002-oidc-library.md](../docs/adr/0002-oidc-library.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0003-webauthn-library.md](../docs/adr/0003-webauthn-library.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0004-feature-flags-and-mfa-policy.md](../docs/adr/0004-feature-flags-and-mfa-policy.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0005-registration-mode-and-bootstrap-state.md](../docs/adr/0005-registration-mode-and-bootstrap-state.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0006-demo-client-sessions.md](../docs/adr/0006-demo-client-sessions.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0007-ses-email-provider.md](../docs/adr/0007-ses-email-provider.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0008-registration-after-email-verification.md](../docs/adr/0008-registration-after-email-verification.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0009-testmail-email-testing.md](../docs/adr/0009-testmail-email-testing.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0010-sentry-observability.md](../docs/adr/0010-sentry-observability.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0011-privacy-and-deletion.md](../docs/adr/0011-privacy-and-deletion.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0012-web-theme-and-cookie-layout.md](../docs/adr/0012-web-theme-and-cookie-layout.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0013-pr-quality-refactoring.md](../docs/adr/0013-pr-quality-refactoring.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0014-production-keys-and-transport.md](../docs/adr/0014-production-keys-and-transport.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0015-security-revision-and-reauth.md](../docs/adr/0015-security-revision-and-reauth.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0016-protocol-and-runtime-remediation-profile.md](../docs/adr/0016-protocol-and-runtime-remediation-profile.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0017-ci-runtime-and-test-isolation.md](../docs/adr/0017-ci-runtime-and-test-isolation.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0018-security-flow-decomposition.md](../docs/adr/0018-security-flow-decomposition.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0019-typecheck-import-roots.md](../docs/adr/0019-typecheck-import-roots.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0020-resend-email-provider.md](../docs/adr/0020-resend-email-provider.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0021-frontend-design-platform.md](../docs/adr/0021-frontend-design-platform.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/adr/0022-frontend-critical-loading.md](../docs/adr/0022-frontend-critical-loading.md) | исторический; проверен | Связь с поздними ADR, область решения, ссылки; исторический контекст сохранён |
| [docs/api.md](../docs/api.md) | обновлён | FastAPI OpenAPI, API routers/schemas и test_documented_api_contract |
| [docs/architecture.md](../docs/architecture.md) | обновлён | Требования, API/services/config и фактическая топология |
| [docs/audit/README.md](../docs/audit/README.md) | обновлён | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [docs/audit/readiness-probe-map.md](../docs/audit/readiness-probe-map.md) | обновлён | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [docs/configuration.md](../docs/configuration.md) | обновлён | Settings/validators, Compose environment, start scripts; локальные secrets не выводились |
| [docs/data-model.md](../docs/data-model.md) | обновлён | ORM models и цепочка 0001…0010; без PostgreSQL drift run |
| [docs/frontend.md](../docs/frontend.md) | обновлён | App/routes/controllers/tokens/footer, capabilities и backend policy |
| [docs/index.md](../docs/index.md) | обновлён | Покрытие реестра, структура и локальные ссылки |
| [docs/migration.md](../docs/migration.md) | обновлён | Compose/Dockerfile/Alembic/операционные scripts; help, без runtime/restore |
| [docs/observability.md](../docs/observability.md) | обновлён | Privacy/security state/reauth/config/telemetry, frontend consent; внешняя приёмка отдельно |
| [docs/operations.md](../docs/operations.md) | обновлён | Compose/Dockerfile/Alembic/операционные scripts; help, без runtime/restore |
| [docs/plan.md](../docs/plan.md) | обновлён | Хронология задач и результатов, новый checkpoint, без переноса прежних PASS |
| [docs/privacy.md](../docs/privacy.md) | обновлён | Privacy/security state/reauth/config/telemetry, frontend consent; внешняя приёмка отдельно |
| [docs/releases.md](../docs/releases.md) | обновлён | bump/build_identity/release_bundle, CI/release workflow; CD comment gate |
| [docs/research.md](../docs/research.md) | обновлён | Синтетическая методика, отсутствие introspection endpoint, границы измерений |
| [docs/sdk.md](../docs/sdk.md) | обновлён | SDK client/fastapi/signatures и demo_app/demo_sessions; snippets compile, без live callback |
| [docs/secret-scan.md](../docs/secret-scan.md) | обновлён | check_secret_scan, baseline fingerprints, UTF-8 и контрольный образец |
| [docs/security.md](../docs/security.md) | обновлён | Privacy/security state/reauth/config/telemetry, frontend consent; внешняя приёмка отдельно |
| [docs/standards-profile.md](../docs/standards-profile.md) | обновлён | Состав ЕСПД и ограничения Markdown; сертификация не заявляется |
| [docs/status.md](../docs/status.md) | обновлён | README/manifest/Compose/start scripts, API и навигация |
| [docs/testing/README.md](../docs/testing/README.md) | обновлён | pytest/runner/CI, тестовые профили и guards; прежние результаты отделены |
| [docs/testing/codescene-contracts.md](../docs/testing/codescene-contracts.md) | обновлён | pytest/runner/CI, тестовые профили и guards; прежние результаты отделены |
| [docs/testing/defects.md](../docs/testing/defects.md) | обновлён | pytest/runner/CI, тестовые профили и guards; прежние результаты отделены |
| [docs/testing/email.md](../docs/testing/email.md) | обновлён; SES раздел перенесён из README | pytest/runner/CI, тестовые профили и guards; прежние результаты отделены |
| [docs/testing/manual-checklist.md](../docs/testing/manual-checklist.md) | обновлён; история сохранена | pytest/runner/CI, тестовые профили и guards; прежние результаты отделены |
| [docs/worklog.md](../docs/worklog.md) | обновлён | Хронология задач и результатов, новый checkpoint, без переноса прежних PASS |
| [examples/README.md](../examples/README.md) | обновлён | SDK client/fastapi/signatures и demo_app/demo_sessions; snippets compile, без live callback |
| [frontend/public/brand/README.md](../frontend/public/brand/README.md) | проверен | Локальные artwork и source-manifest; provenance сохраняется |
| [packages/python-sdk/README.md](../packages/python-sdk/README.md) | обновлён | SDK client/fastapi/signatures и demo_app/demo_sessions; snippets compile, без live callback |
| [.env.example](../.env.example) | проверен | Settings/validators, Compose environment, start scripts; локальные secrets не выводились |
| [deploy/github-actions/cd.yml.example](../deploy/github-actions/cd.yml.example) | проверен | bump/build_identity/release_bundle, CI/release workflow; CD comment gate |
| [docs/api-routes.json](../docs/api-routes.json) | проверен | FastAPI OpenAPI, API routers/schemas и test_documented_api_contract |
| [docs/audit/evidence.json](../docs/audit/evidence.json) | исторический; проверен | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [docs/audit/frontend-dependencies.json](../docs/audit/frontend-dependencies.json) | исторический; проверен | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [docs/audit/history-summary.json](../docs/audit/history-summary.json) | исторический; проверен | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [docs/audit/python-dependencies.json](../docs/audit/python-dependencies.json) | исторический; проверен | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [docs/audit/qa-summary.json](../docs/audit/qa-summary.json) | исторический; проверен | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [docs/audit/remediation-evidence.json](../docs/audit/remediation-evidence.json) | исторический; проверен | Исходные SHA/evidence и постоянные tests; без повторения PG-проб |
| [frontend/public/brand/source-manifest.json](../frontend/public/brand/source-manifest.json) | проверен | Локальные artwork и source-manifest; provenance сохраняется |
| [frontend/public/licenses/Geist-OFL.txt](../frontend/public/licenses/Geist-OFL.txt) | проверен | Лицензионный текст сохранён; Geist self-hosted, не лицензия продукта |
| [frontend/public/llms.txt](../frontend/public/llms.txt) | проверен | Публичные routes App и Nginx static; robots не заменяет RBAC, без HTTP прогона |
| [frontend/public/robots.txt](../frontend/public/robots.txt) | проверен | Публичные routes App и Nginx static; robots не заменяет RBAC, без HTTP прогона |

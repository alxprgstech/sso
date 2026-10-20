# Актуальный статус ALXPRGS SSO

Обновлено 2026-10-20T20:54:27.8702087+03:00; продукт0.2.0. В main интегрированы все шесть исправлений SSO-SEC-0001–0006: [PR21](https://github.com/alxprgstech/sso/pull/21), [PR22](https://github.com/alxprgstech/sso/pull/22), [PR23](https://github.com/alxprgstech/sso/pull/23), [PR24](https://github.com/alxprgstech/sso/pull/24), [PR25](https://github.com/alxprgstech/sso/pull/25), [PR26](https://github.com/alxprgstech/sso/pull/26). SEC-MERGE-20261020 done; issues15–20 закрылись автоматически после merge. Точные проверенные head/merge SHA, CI и локальные результаты — [приёмка](acceptance.md); история, включая исправленные ошибки проверок — [worklog](worklog.md).

Конфликты разрешены с сохранением всех шести security-контрактов. Для совместимости нейтральной регистрации и browser proof добавлен regression resend; в cancellation unit-test ожидание завершения asyncio заменено корректным join реальных потоков перед final cleanup assertion. Production-код лимитов для исправления теста не менялся. Обязательный CI финальных PR heads успешен; CI последующего documentation-only checkpoint — отдельная ревизия.

При обновлении требуется миграция `0014_registration_browser`; старые незавершённые регистрации должны начать flow заново. Существующие accounts/sessions миграция не изменяет. Logout/self-revoke отзывает все refresh/code grants, сохраняемые browser sessions могут начать новый flow; offline access JWT действует до exp, максимум300с.

Локально проверены совместные security-сценарии на отдельной PostgreSQL16, Ruff/format/mypy, секреты и Markdown. Полный backend/PG, enabled/default-off browser, SDK, frontend и контейнерные проверки выполнены обязательным CI PR. Live SES job без AWS credentials пропущен по ранее согласованной политике; доставки он не подтверждает.

Production-приёмка остаётся открыта: live SES/Gmail/Sentry и sender registration, public TLS/DNS/IAM/secret storage, внешние backup/storage ACL/alerts, OIF/multi-replica load и owner review исторических credentials. Deployment, release publication и активация CD не выполнялись. DOC-VERSION-LOCK-01 и остальные открытые требования — [план](plan.md).

TOTP/Passkey/Recovery выключены по умолчанию; email confirmation самостоятельной регистрации обязательно. Текущая схема и security-модель — [миграция](migration.md), [безопасность](security.md).

# ADR-0004: флаги возможностей и политика MFA

Принято 24.09.2026; частично заменено 29.09.2026. Первоначальное решение выключало четыре возможности, включая email verification. Эта часть отменена [ADR-0008](0008-registration-after-email-verification.md); privacy и парольная/reauth policy уточнены [ADR-0011](0011-privacy-and-deletion.md) и [ADR-0015](0015-security-revision-and-reauth.md).

Действующая часть: TOTP, Passkey и Recovery codes реализованы полностью, выключены в default-профиле, защищены серверными gates и не включаются запросом клиента. Recovery требует TOTP; отключение настроенного обязательного фактора не даёт password-only обход. Проверяются default-off API и enabled положительные/отрицательные сценарии. Подтверждение email самостоятельной регистрации обязательно; false отвергается конфигурацией. `REQUIRE_VERIFIED_EMAIL` регулирует вход старых/admin-created пользователей.

Скрывать только UI недостаточно; альтернативой выбраны серверные gates и startup validation. Профиль — [конфигурация](../configuration.md), почта — [ADR-0007](0007-ses-email-provider.md). [Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/adr/0004-feature-flags-and-mfa-policy.md) сохраняет исходную мотивацию и заменённые положения; прежний PASS не заявляется текущим результатом.

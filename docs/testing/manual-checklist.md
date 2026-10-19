# Чек-лист текущей приёмки ALXPRGS SSO

Продукт 0.2.0; подготовлен 06.10.2026. Все пункты ниже ожидают отдельного runtime-прогона; исторические PASS не переносятся на новую ревизию. Запишите SHA, профиль, стенд и результаты в acceptance.md.

## Текущие сценарии

- [ ] Чистый isolated Compose: owner/runtime/migrator, head0013, health/live и health/ready, bootstrap и повтор без изменения данных.
- [ ] Open-регистрация: условия/согласие, HTTP202 pending; неверный код/replay отказ; после настоящего email — User и обычный login. Closed — отказ без письма.
- [ ] Login/logout, cookie/CSRF/exact Origin; настроенный фактор до полной сессии; временный admin пароль → обязательная смена → новый login.
- [ ] Default-off: прямые MFA API404 и скрытый UI; email обязателен. Enabled: TOTP/UV Passkey/Recovery положительные и отрицательные случаи, без bypass.
- [ ] Два RP: state/nonce/PKCE, второй вход с OP session; logout OP не обещает back-channel отзыв всех RP.
- [ ] Admin RBAC/IDOR, последний администратор, session revoke, scopes и одноразовый secret; reauth/action/body-bound proof.
- [ ] Privacy/legal gates; request/cancel/deadline/worker, retention и restore с актуальным deletion journal на отдельной БД.
- [ ] Keyboard/mobile/theme footer/cookies/dialog, CSP за Nginx, reduced motion; fixtures отдельно от настоящего входа.
- [ ] SDK wheel/sdist, чистая установка, JWKS/claims/ошибки и запуск двух примеров.
- [ ] CI/release на нужном SHA, security scans, внешний HTTPS/OIF/mail/Sentry/owner review по применимым критериям.

[Подготовка](README.md), [методика](../03-test-procedure.md), [статус](../status.md).


[Историческая версия](https://github.com/alxprgstech/sso/blob/7d1585e7bdd40104be7a8b933b998cbc843d46a5/docs/testing/manual-checklist.md) содержит прежний заполненный акт, а не текущие отметки.

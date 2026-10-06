# Руководство программиста ALXPRGS SSO

- Обозначение: ЕСПД.ГОСТ 19.504-79.РП-06.
- Продукт 0.2.0; актуализация 06.10.2026.

## 1. Назначение и условия

Интегратор использует независимый установленный SDK либо OIDC discovery. Зарегистрируйте клиента, exact redirect/logout URI и allowed scopes. Целевой issuer — проектный адрес, production требует отдельной приёмки.

## 2. Python SDK и вызовы

Единый подробный источник с кодом — [SDK](sdk.md). Собранный wheel устанавливается в чистую среду без app.*. start_authorization возвращает URL/verifier/state/nonce. Одноразовую flow-запись храните на сервере, проверяйте error/state на callback; handle_web_callback проверяет ID Token и nonce. Refresh заменяется атомарно, токены остаются на RP.

## 3. API и защита ресурсов

[API](api.md) описывает discovery/JWKS/authorize/token/userinfo/revoke/logout и cookie API. ID Token нельзя использовать как Bearer. FastAPI require_scope и require_role независимы. Offline RP может принимать прежний access JWT до exp после отзыва на OP.

## 4. Примеры и frontend

[Два demo](../examples/README.md) реализуют state/nonce/PKCE и отдельные RP-сессии: один worker, процессная память. [Frontend](frontend.md) описывает маршруты, capability gates, CSP и lifetime секретов. Согласия/password-change/deletion gates не обходятся deep link.

## 5. Проверки и ограничения

[Тестирование](testing/README.md) включает сборку, изолированную установку SDK и примеры. Проверки используют синтетический стенд. [Статус](status.md), [приёмка](acceptance.md) различают исходники, прошлые результаты и внешние блокеры.

# Python SDK ALXPRGS SSO

Версия продукта и пакета — 0.2.0; источник истины — корневой `VERSION`. Код закрытый, SDK не опубликован в публичном registry. SDK не импортирует серверные `app.*` модули.

Сборка и установка из проверенного локального артефакта:

```bash
python -m build --no-isolation packages/python-sdk --outdir dist/sdk
python -m pip install dist/sdk/alxprgs_sso-0.2.0-py3-none-any.whl
```

Зависимости и их точные версии находятся в `packages/python-sdk/pyproject.toml` и `requirements-lock.txt`. Для проверки примеров устанавливайте wheel в чистую среду; `PYTHONPATH` не должен подменять установленный SDK исходниками.

`SSOClient` загружает `/.well-known/jwks.json`, кэширует публичные RSA ключи и проверяет RS256, issuer, audience, обязательные claims, их типы и времена. Некорректный или чрезмерный `kid` отвергается до загрузки JWKS. `verify_access_token` принимает только Access Token; `verify_id_token` проверяет отдельный ID-профиль и ожидаемый nonce. ID Token не используется как Bearer для API.

Рекомендуемый веб-поток:

```python
import os
from alxprgs_sso import SSOClient

client = SSOClient(
    server_url="https://auth.alxprgs.tech",
    client_id="client_portal_app",
    client_secret=os.environ["CLIENT_SECRET"],
)

authorization_url, verifier, state, nonce = client.start_authorization(
    redirect_uri="https://portal.alxprgs.tech/callback",
    scope="openid profile email",
    prompt="login",
    max_age=300,
)


# Сохраните verifier/state/nonce и redirect_uri в одноразовой серверной записи
# потока, привязанной к случайному HttpOnly cookie браузера. Перенаправьте на URL.
# На callback погасите эту запись атомарно, затем вызовите:
async def complete_callback(code, received_state, saved_flow):
    return await client.handle_web_callback(
        code=code,
        state=received_state,
        expected_state=saved_flow.state,
        code_verifier=saved_flow.verifier,
        redirect_uri="https://portal.alxprgs.tech/callback",
        expected_nonce=saved_flow.nonce,
        max_age=300,
    )
```

Возвращённый `WebSessionInfo` содержит проверенный `user` и токены. Храните его на сервере; браузеру выдавайте случайный непрозрачный ID в host-only Secure/HttpOnly cookie. Не печатайте токены, не передавайте их в URL страницы приложения и не сохраняйте в localStorage/sessionStorage. Обрабатывайте protocol error callback, не принимая его как успешный вход. Трёхэлементный `generate_authorization_url` сохранён для совместимости, но не рекомендуется: он не возвращает nonce для безопасного callback.

`refresh_token` выполняет ротацию; заменяйте сохранённый refresh немедленно и атомарно. Повтор старого refresh отзывает семейство. `revoke_token` относится к OAuth refresh grants, а не к OP browser cookie. `create_logout_url(id_token_hint, post_logout_redirect_uri, state)` требует ID Token текущей RP-сессии и заранее зарегистрированный точный redirect. RP также удаляет свою локальную сессию; logout OP не является back-channel уведомлением всех RP.

FastAPI API-защита:

```python
from fastapi import Depends, FastAPI
from alxprgs_sso import SSOClient, UserClaims
from alxprgs_sso.fastapi import SSOFastAPISecurity

app = FastAPI()
security = SSOFastAPISecurity(
    SSOClient(
        server_url="https://auth.alxprgs.tech",
        client_id="client_my_service",
    )
)


@app.get("/profile")
def profile(user: UserClaims = Depends(security.require_scope("profile"))):
    return {"subject": user.sub, "username": user.preferred_username}


@app.get("/admin")
def admin(user: UserClaims = Depends(security.require_role("admin"))):
    return {"subject": user.sub}
```

`UserClaims.scope`/`scopes` содержат проверенные scopes; username/email могут отсутствовать без `profile`/`email`. `require_scope` не предоставляет admin обхода. Роли и scopes проверяются независимо; при необходимости endpoint применяет обе зависимости. В текущем `require_role` admin удовлетворяет проверке роли, что не расширяет scopes.

Автономная проверка JWT на RP не проверяет каждое изменение account state в БД OP. Уже выданный Access Token может оставаться приемлемым на автономном RP до короткого TTL; OP UserInfo и новые grants проверяют текущую security revision. Примеры `examples/client1`, `examples/client2` используют реальные state/nonce/PKCE и серверное хранение, но их память процесса — демонстрационный single-worker store, не production persistence.


При max_age SDK требует auth_time integer и проверяет его возраст. Для max_age=0 предусмотрено строго ограниченное окно доставки callback5s с целочисленной точностью NumericDate; auth_time старше5s отвергается. Это локальное решение о доставке, не разрешение OP переиспользовать прежний login: сервер связывает fresh request и новую аутентификацию, nonce остаётся обязательным. Для ненулевого max_age дополнительных5s нет. JWKS загружается потоково до64KiB, набор1–16 уникальных public RSA≥2048 проверяется до кэширования. Некорректный ответ не заменяет последний проверенный набор; после max_stale_seconds сеть должна восстановиться, иначе отказ.
Основание auth_time/max_age — [OpenID Connect Core, раздел3.1.3.7](https://openid.net/specs/openid-connect-core-1_0.html#IDTokenValidation); NumericDate и ограничение окна доставки учитываются явно.

## Сборка и границы проверки

Версия — корневой VERSION, публичная публикация пакета не подтверждается README. Полный поток start_authorization/handle_web_callback, настройка expected_issuer и сборка wheel описаны в [SDK](../../docs/sdk.md). Интеграция требует установленного пакета, без импорта backend. [Чистая среда и проверки](../../docs/testing/README.md). Прежние результаты читаются с датой/SHA.

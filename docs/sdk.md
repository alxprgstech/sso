# Python SDK ALXPRGS SSO

Версия продукта и пакета — 0.3.0; источник истины — корневой `VERSION`. Код закрытый, SDK не опубликован в публичном registry. SDK не импортирует серверные `app.*` модули.

Сборка и установка из проверенного локального артефакта:

```bash
python -m build --no-isolation packages/python-sdk --outdir dist/sdk
python -m pip install --require-hashes -r requirements-lock-hashed.txt
python -m pip install --no-deps --no-build-isolation dist/sdk/alxprgs_sso-0.3.0-py3-none-any.whl
```

Диапазоны зависимостей и зафиксированный набор находятся в `packages/python-sdk/pyproject.toml` и `requirements-lock.txt`. Для проверки примеров устанавливайте wheel в чистую среду; `PYTHONPATH` не должен подменять установленный SDK исходниками.

`SSOClient` загружает `/.well-known/jwks.json`, кэширует публичные RSA ключи и проверяет RS256, issuer, audience, обязательные claims, их типы и времена. Некорректный или чрезмерный `kid` отвергается до загрузки JWKS. `verify_access_token` принимает только Access Token; `verify_id_token` проверяет отдельный ID-профиль и ожидаемый nonce. ID Token не используется как Bearer для API.

С ревизии MFA-DEFAULT-ADMIN-01 OP добавляет в Access/ID Token подписанные `amr` (`pwd`, `otp`, `hwk`, `mfa`) и `acr` (`urn:alxprgs:acr:pwd`/`urn:alxprgs:acr:mfa`). SDK не отвергает эти дополнительные claims и не трактует наличие роли как доказательство MFA. Административная роль `admin` не выдаётся OP для authorization code/refresh без требуемого session assurance, поэтому RP, использующий SDK-роли, не получает admin-право из password-only grant. Публичный API SDK в этой задаче не менялся; для собственной assurance-политики RP может дополнительно проверять подписанные `amr`/`acr` стандартными средствами либо запросить отдельный hosted step-up. SDK не повышает assurance самостоятельно и не обходит `assurance_unavailable`/`StepUpPolicyError`.

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

## Cross-application transaction step-up (0.3.0)

Только confidential client. Сервер должен иметь `FEATURE_EXTERNAL_STEP_UP_ENABLED=true`; для клиента отдельно включаются `step_up_enabled`, assurance levels и actions (см. `PATCH /api/v1/admin/clients/{client_id}/step-up`). SDK не позволяет public-клиенту без секрета создать или погасить proof.

```python
import hashlib
import json

canonical_json = json.dumps(
    {"setting": "allow_external_sharing", "value": False},
    sort_keys=True,
    separators=(",", ":"),
).encode()
payload_hash = hashlib.sha256(canonical_json).hexdigest()
request = await sso.create_step_up_request(
    action="critical_settings_change",
    payload_hash=payload_hash,
    subject=expected_sub,
    assurance="reauth_strict",
    redirect_uri="https://portal.alxprgs.tech/step-up/callback",
    description="Изменить критические настройки доступа",
    ttl_seconds=120,
)
# Сохраните request (включая state/nonce/code_verifier) в одноразовой
# серверной записи, привязанной к текущей RP-сессии, и перенаправьте браузер:
authorization_url = sso.build_step_up_url(request)

# В callback проверьте state и передайте параметры из сохранённой записи:
proof = await sso.consume_step_up_proof(
    code=received_code,
    request=request,
    state=received_state,
    expected_subject=expected_sub,
    expected_action="critical_settings_change",
    expected_payload_hash=payload_hash,
)
# proof.claims проверены по issuer/audience/subject/action/payload/acr/amr/nonce.
# Только после этого выполняйте действие; повторный consume невозможен.
```

`create_step_up_request` генерирует PKCE S256, state и nonce; `StepUpRequest` хранит их и не печатает в repr. `consume_step_up_proof` обязательно выполняет server-side redemption с Basic client authentication; локальная проверка подписи не считается доказательством одноразовости. SDK проверяет `token_use=external_step_up_proof`, `aud=client_id`, issuer, подпись RS256 через JWKS, время, subject, action, payload hash, assurance (`acr`), факторы (`amr`) и nonce. Истёкший, повторно погашенный, чужой или изменённый proof приводит к `StepUpExpiredError`, `StepUpReplayError`, `StepUpBindingError` или `StepUpRejectedError`; `StepUpUnavailableError` означает disabled/policy, `StepUpPolicyError` — недоступный способ. Не сохраняйте proof/токены в localStorage/sessionStorage и не передавайте client secret в браузер.

Серверный протокол: `POST /api/v1/step-up/requests`, `GET /api/v1/step-up/requests/{token}`, `POST .../passkey/options`, `POST .../verify`, `POST .../deny`, `POST /api/v1/step-up/redeem`. Browser endpoints используют cookie+CSRF; creation/redeem — Basic client authentication. Код живёт не более 60 секунд, request — настроенный TTL (30–300), pending requests ограничены. Recovery codes в step-up не участвуют; strict требует Passkey UV + свежий password, mfa допускает Passkey UV либо password+TOTP. Точный бандл/проверка изолированного wheel — [testing](testing/README.md), пример RP — [examples/step-up-rp](../examples/step_up_rp.py).

FastAPI API-защита:

```python
from fastapi import Depends, FastAPI
from alxprgs_sso import SSOClient, UserClaims
from alxprgs_sso.fastapi import SSOFastAPISecurity

app = FastAPI()
security = SSOFastAPISecurity(SSOClient(
    server_url="https://auth.alxprgs.tech", client_id="client_my_service",
))

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

## Условия сборки и локальный issuer

Для --no-isolation заранее установите requirements-lock.txt (включает build/setuptools/wheel); requirements-build-lock.txt предназначен для backend builder и не содержит setuptools/wheel; wheel проверяйте после установки в отдельную среду с зависимостями SDK. README пакета показывает FastAPI helper, этот документ — полный callback. SSOClient.expected_issuer задаётся явно, когда transport server_url отличается от issuer. Срок/лимиты JWKS и fallback не отключайте ради тестов. [Тестирование](testing/README.md), [примеры](../examples/README.md).

## Unreleased: transport policy

SSOClient по умолчанию принимает только HTTPS, certificate verification обязательна. `verify_ssl=False` запрещён в любом профиле. Для локального HTTP явно передайте `transport_profile="local"`; допустимы только localhost и loopback IP, включая IPv6. Это несовместимое изменение, VERSION 0.3.0. Не выводите server URL с userinfo; userinfo/query/fragment в URL сервера отвергаются. Demo uses `SSO_TRANSPORT_PROFILE=local` только для локального стенда.

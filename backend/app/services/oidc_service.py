from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from authlib.oauth2.rfc6749.util import scope_to_list
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.exceptions import AuthenticationException, OAuthErrorException
from app.core.security import (
    async_verify_password,
    create_jwt,
    decode_jwt,
    generate_random_token,
    hash_token,
    valid_pkce_challenge,
    verify_pkce,
)
from app.models.oidc import (
    AuthorizationCode,
    OIDCClient,
    RefreshToken,
)
from app.models.session import Session
from app.models.user import User
from app.schemas.oidc import TokenResponse, UserInfoResponse
from app.services.audit_service import AuditService
from app.services.security_state import require_account_access, revision

settings = get_settings()


class OIDCService:
    @staticmethod
    async def get_and_validate_client(
        db: AsyncSession,
        client_id: str,
        client_secret: str | None = None,
        require_secret: bool = True,
    ) -> OIDCClient:
        if require_secret:
            from app.services.privacy_service import RateLimit, consume_rate_limit

            await consume_rate_limit(db, settings, RateLimit("oauth-client", client_id, 30))
        stmt = select(OIDCClient).where(OIDCClient.client_id == client_id)
        client = (await db.execute(stmt)).scalar_one_or_none()

        if not client or not client.is_active:
            raise OAuthErrorException("invalid_client", "Клиент не найден или деактивирован", 401)

        if client.client_type == "confidential" and require_secret:
            if not client_secret or not client.client_secret_hash:
                raise OAuthErrorException("invalid_client", "Требуется client_secret", 401)
            if not await async_verify_password(client_secret, client.client_secret_hash):
                raise OAuthErrorException("invalid_client", "Неверный client_secret", 401)

        return client

    @staticmethod
    def validate_redirect_uri(client: OIDCClient, redirect_uri: str) -> None:
        """
        Строгая проверка redirect_uri: точное совпадение со списком URI клиента (SSO-02).
        Запрещены wildcards (*), относительные пути и поддомены.
        """
        registered_uris = [r.uri for r in client.redirect_uris]
        if redirect_uri not in registered_uris:
            raise OAuthErrorException(
                "invalid_request",
                f"Указанный redirect_uri '{redirect_uri}' не зарегистрирован для данного клиента",
                400,
            )

    @staticmethod
    async def create_authorization_code(
        db: AsyncSession,
        client: OIDCClient,
        user: User,
        redirect_uri: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        nonce: str | None = None,
        scope: str = "openid profile email",
        auth_time: datetime | None = None,
        session_id: uuid.UUID | None = None,
    ) -> str:
        """
        Выпускает одноразовый authorization code с привязкой к клиенту, URI и PKCE S256 (SSO-03).
        TTL = 60 секунд.
        """
        if code_challenge_method != "S256" or not valid_pkce_challenge(code_challenge):
            raise OAuthErrorException(
                "invalid_request", "Поддерживается только метод PKCE S256", 400
            )

        from app.services.privacy_service import require_access

        if not set(scope.split()) <= set((client.allowed_scopes or "openid profile email").split()):
            raise OAuthErrorException("invalid_scope", "Scope не разрешён для этого клиента", 400)

        current = await db.scalar(
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not current or not current.is_active:
            raise OAuthErrorException("invalid_grant", "Аккаунт недоступен", 400)
        await require_access(db, current)
        require_account_access(current, settings)
        if session_id is not None:
            session = await db.scalar(
                select(Session).where(
                    Session.id == session_id,
                    Session.user_id == current.id,
                    Session.security_revision == revision(current),
                    Session.purpose == "full",
                    Session.expires_at > datetime.now(timezone.utc),
                )
            )
            if session is None:
                raise OAuthErrorException(
                    "login_required", "Сессия больше не допускает авторизацию", 400
                )
            auth_time = session.auth_time

        raw_code = generate_random_token(32)
        code_hash = hash_token(raw_code)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=settings.AUTH_CODE_TTL_SECONDS)

        auth_code_record = AuthorizationCode(
            code_hash=code_hash,
            client_id=client.id,
            user_id=user.id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            nonce=nonce,
            scope=scope,
            is_used=False,
            expires_at=expires_at,
            security_revision=revision(current),
            auth_time=auth_time or now,
        )
        db.add(auth_code_record)
        await db.commit()
        return raw_code

    @staticmethod
    async def exchange_code(
        db: AsyncSession,
        client_id: str,
        client_secret: str | None,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponse:
        """
        Обмен authorization code на Access Token, ID Token и ротируемый Refresh Token.
        Атомарное погашение кода в транзакции PostgreSQL.
        """
        client = await OIDCService.get_and_validate_client(
            db, client_id, client_secret, require_secret=True
        )

        code_hash = hash_token(code)
        now = datetime.now(timezone.utc)
        # Account row precedes token rows, matching erasure/revocation lock order.
        candidate = await db.scalar(
            select(AuthorizationCode.user_id).where(
                AuthorizationCode.code_hash == code_hash, AuthorizationCode.client_id == client.id
            )
        )
        if candidate:
            await db.execute(select(User.id).where(User.id == candidate).with_for_update())

        # Выбираем код авторизации
        stmt = (
            select(AuthorizationCode)
            .where(
                AuthorizationCode.code_hash == code_hash,
                AuthorizationCode.client_id == client.id,
            )
            .with_for_update()
        )
        auth_code_obj = (await db.execute(stmt)).scalar_one_or_none()

        if not auth_code_obj:
            raise OAuthErrorException("invalid_grant", "Недействительный authorization code", 400)

        # Проверка повторного использования (Replay Protection)
        if auth_code_obj.is_used:
            await AuditService.log_event(
                db,
                event_type="auth_code_replay_detected",
                user_id=auth_code_obj.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"client_id": client_id},
            )
            raise OAuthErrorException(
                "invalid_grant",
                "Код авторизации уже был использован ранее (обнаружена попытка повтора)",
                400,
            )

        if auth_code_obj.expires_at <= now:
            raise OAuthErrorException("invalid_grant", "Срок действия кода авторизации истёк", 400)

        if auth_code_obj.redirect_uri != redirect_uri:
            raise OAuthErrorException(
                "invalid_grant", "Параметр redirect_uri не совпадает с исходным запросом", 400
            )

        # Проверка PKCE S256
        if not verify_pkce(
            code_verifier, auth_code_obj.code_challenge, auth_code_obj.code_challenge_method
        ):
            raise OAuthErrorException(
                "invalid_grant", "Неверный параметр code_verifier для PKCE", 400
            )

        # Атомарно помечаем код как использованный
        auth_code_obj.is_used = True
        await db.flush()

        # Получаем пользователя
        user_stmt = select(User).where(User.id == auth_code_obj.user_id)
        user = (await db.execute(user_stmt)).scalar_one_or_none()

        if not user or not user.is_active:
            raise OAuthErrorException(
                "invalid_grant", "Учётная запись пользователя заблокирована", 400
            )

        return await OIDCService._generate_tokens_for_user(
            db=db,
            user=user,
            client=client,
            scope=auth_code_obj.scope,
            nonce=auth_code_obj.nonce,
            ip_address=ip_address,
            user_agent=user_agent,
            expected_revision=auth_code_obj.security_revision or 0,
            auth_time=auth_code_obj.auth_time,
        )

    @staticmethod
    async def rotate_refresh_token(
        db: AsyncSession,
        client_id: str,
        client_secret: str | None,
        raw_refresh_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenResponse:
        """
        Ротация refresh token с выявлением повторного использования (Token Replay Detection)
        и аннулированием всего семейства (Token Family) (SSO-05).
        """
        client = await OIDCService.get_and_validate_client(
            db, client_id, client_secret, require_secret=True
        )

        token_hash = hash_token(raw_refresh_token)
        now = datetime.now(timezone.utc)
        candidate = await db.scalar(
            select(RefreshToken.user_id).where(
                RefreshToken.token_hash == token_hash, RefreshToken.client_id == client.id
            )
        )
        if candidate:
            await db.execute(select(User.id).where(User.id == candidate).with_for_update())

        stmt = (
            select(RefreshToken)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.client_id == client.id,
            )
            .with_for_update()
        )
        rt_obj = (await db.execute(stmt)).scalar_one_or_none()

        if not rt_obj:
            raise OAuthErrorException("invalid_grant", "Недействительный refresh_token", 400)

        # Если токен уже отозван -> ОБНАРУЖЕН REPLAY! Отзываем всю семью токенов!
        if rt_obj.is_revoked:
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.family_id == rt_obj.family_id)
                .values(is_revoked=True)
            )
            await AuditService.log_event(
                db,
                event_type="refresh_token_replay_detected",
                user_id=rt_obj.user_id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"family_id": str(rt_obj.family_id), "client_id": client_id},
            )
            await db.commit()
            raise OAuthErrorException(
                "invalid_grant",
                "Попытка повторного использования refresh токена. Всё семейство токенов отозвано в целях безопасности.",
                400,
            )

        if rt_obj.expires_at <= now:
            raise OAuthErrorException("invalid_grant", "Срок действия refresh токена истёк", 400)

        # Проверка абсолютного срока жизни семейства токенов (SSO-05 / FINAL-11)
        first_token_stmt = (
            select(RefreshToken.created_at)
            .where(RefreshToken.family_id == rt_obj.family_id)
            .order_by(RefreshToken.created_at.asc())
            .limit(1)
        )
        first_created_at = (await db.execute(first_token_stmt)).scalar_one_or_none()
        if first_created_at is not None:
            max_family_expiry = first_created_at + timedelta(
                seconds=settings.REFRESH_FAMILY_MAX_LIFETIME_SECONDS
            )
            if now >= max_family_expiry:
                await db.execute(
                    update(RefreshToken)
                    .where(RefreshToken.family_id == rt_obj.family_id)
                    .values(is_revoked=True)
                )
                await AuditService.log_event(
                    db,
                    event_type="refresh_family_expired",
                    user_id=rt_obj.user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details={"family_id": str(rt_obj.family_id), "client_id": client_id},
                )
                await db.commit()
                raise OAuthErrorException(
                    "invalid_grant",
                    "Срок действия семейства refresh-токенов истёк (превышен максимальный абсолютный лимит)",
                    400,
                )

        # Отзываем использованный refresh токен
        rt_obj.is_revoked = True
        await db.flush()

        # Получаем пользователя
        user_stmt = select(User).where(User.id == rt_obj.user_id)
        user = (await db.execute(user_stmt)).scalar_one_or_none()

        if not user or not user.is_active:
            raise OAuthErrorException(
                "invalid_grant", "Учётная запись пользователя заблокирована", 400
            )

        # Выпускаем новую пару токенов с сохранением family_id
        return await OIDCService._generate_tokens_for_user(
            db=db,
            user=user,
            client=client,
            scope=rt_obj.scope,
            family_id=rt_obj.family_id,
            ip_address=ip_address,
            user_agent=user_agent,
            expected_revision=rt_obj.security_revision or 0,
            auth_time=rt_obj.auth_time,
        )

    @staticmethod
    async def _generate_tokens_for_user(
        db: AsyncSession,
        user: User,
        client: OIDCClient,
        scope: str,
        nonce: str | None = None,
        family_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        expected_revision: int | None = None,
        auth_time: datetime | None = None,
    ) -> TokenResponse:
        granted_scopes = set(scope_to_list(scope))
        if not granted_scopes <= set((client.allowed_scopes or "openid profile email").split()):
            raise OAuthErrorException("invalid_scope", "Scope не разрешён для этого клиента", 400)
        from app.services.privacy_service import has_current_acceptance

        current = await db.scalar(
            select(User)
            .where(User.id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            not current
            or not current.is_active
            or current.deletion_scheduled_for
            or not await has_current_acceptance(db, user.id)
        ):
            raise OAuthErrorException(
                "invalid_grant", "Необходимо завершить взаимодействие с аккаунтом в SSO", 400
            )
        try:
            require_account_access(current, settings)
        except AuthenticationException:
            raise OAuthErrorException(
                "invalid_grant", "Аккаунт не допускает выдачу токенов", 400
            ) from None
        if expected_revision is not None and revision(current) != expected_revision:
            raise OAuthErrorException("invalid_grant", "Безопасность аккаунта изменилась", 400)
        user = current
        roles = [r.name for r in user.roles]
        now = datetime.now(timezone.utc)
        authenticated_at = auth_time or now

        # 1. Access Token (JWT RS256, 5 минут, SSO-04 фильтрация claims)
        access_payload: dict[str, Any] = {
            "sub": str(user.id),
            "aud": client.client_id,
            "scope": scope,
            "token_use": "access_token",
            "jti": str(uuid.uuid4()),
            "security_revision": revision(current),
        }
        if "profile" in granted_scopes:
            access_payload["preferred_username"] = user.username
            access_payload["roles"] = roles
        if "email" in granted_scopes:
            access_payload["email"] = user.email
            access_payload["email_verified"] = user.email_verified

        access_token = create_jwt(
            access_payload, expires_in_seconds=settings.ACCESS_TOKEN_TTL_SECONDS
        )

        # 2. ID Token (JWT RS256, если запрошен scope openid, SSO-04 фильтрация claims)
        id_token = None
        if "openid" in granted_scopes:
            id_payload: dict[str, Any] = {
                "sub": str(user.id),  # Стабильный непрозрачный UUID (SSO-04)
                "aud": client.client_id,
                "token_use": "id_token",
                "auth_time": int(authenticated_at.timestamp()),
            }
            if nonce:
                id_payload["nonce"] = nonce
            if "profile" in granted_scopes:
                id_payload["preferred_username"] = user.username
                id_payload["roles"] = roles
            if "email" in granted_scopes:
                id_payload["email"] = user.email
                id_payload["email_verified"] = user.email_verified

            id_token = create_jwt(id_payload, expires_in_seconds=settings.ACCESS_TOKEN_TTL_SECONDS)

        # 3. Refresh Token (Ротируемый токен, 7 дней с ограничением абсолютного срока жизни)
        raw_refresh = generate_random_token(32)
        rt_hash = hash_token(raw_refresh)
        target_family_id = family_id or uuid.uuid4()
        rt_expires = now + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS)

        # Ограничиваем срок действия нового refresh токена абсолютным сроком жизни семейства
        if family_id is not None:
            first_token_stmt = (
                select(RefreshToken.created_at)
                .where(RefreshToken.family_id == family_id)
                .order_by(RefreshToken.created_at.asc())
                .limit(1)
            )
            first_created_at = (await db.execute(first_token_stmt)).scalar_one_or_none()
            if first_created_at is not None:
                max_family_expiry = first_created_at + timedelta(
                    seconds=settings.REFRESH_FAMILY_MAX_LIFETIME_SECONDS
                )
                if rt_expires > max_family_expiry:
                    rt_expires = max_family_expiry

        new_rt = RefreshToken(
            family_id=target_family_id,
            token_hash=rt_hash,
            client_id=client.id,
            user_id=user.id,
            scope=scope,
            is_revoked=False,
            expires_at=rt_expires,
            security_revision=revision(current),
            auth_time=authenticated_at,
        )
        db.add(new_rt)
        await db.commit()

        await AuditService.log_event(
            db,
            event_type="token_issued",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"client_id": client.client_id, "scope": scope},
        )

        return TokenResponse(
            access_token=access_token,
            token_type="Bearer",
            expires_in=settings.ACCESS_TOKEN_TTL_SECONDS,
            refresh_token=raw_refresh,
            id_token=id_token,
            scope=scope,
        )

    @staticmethod
    async def get_userinfo(db: AsyncSession, access_token: str) -> UserInfoResponse:
        """
        Возвращает профиль пользователя по Bearer Access Token (SSO-01, SSO-03, SSO-04).
        Строго отклоняет ID Token (SSO-03).
        Фильтрует claims email/profile согласно scope из access token (SSO-04).
        """
        try:
            payload = decode_jwt(access_token, expected_use="access_token")
            user_id = uuid.UUID(payload["sub"])
        except Exception:
            raise OAuthErrorException(
                "invalid_token", "Токен недействителен или срок его действия истёк", 401
            )

        # Проверка SSO-03: Не принимать ID token как access token
        if payload.get("token_use") != "access_token":
            raise OAuthErrorException("invalid_token", "Передан ID Token вместо Access Token", 401)

        token_scope = payload.get("scope", "")
        token_scopes = set(scope_to_list(token_scope))

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise OAuthErrorException("invalid_token", "В токене отсутствует claim 'sub'", 401)

        stmt = select(User).where(User.id == user_id)
        user = (await db.execute(stmt)).scalar_one_or_none()

        from app.services.privacy_service import has_current_acceptance

        if (
            not user
            or not user.is_active
            or user.deletion_scheduled_for
            or not await has_current_acceptance(db, user.id)
        ):
            raise OAuthErrorException(
                "invalid_token", "Пользователь заблокирован или не найден", 401
            )

        try:
            require_account_access(user, settings)
        except AuthenticationException:
            raise OAuthErrorException("invalid_token", "Аккаунт не допускает доступ", 401) from None
        if payload.get("security_revision", 0) != revision(user):
            raise OAuthErrorException("invalid_token", "Безопасность аккаунта изменилась", 401)

        return UserInfoResponse(
            sub=str(user.id),
            preferred_username=user.username if "profile" in token_scopes else None,
            email=user.email if "email" in token_scopes else None,
            email_verified=user.email_verified if "email" in token_scopes else None,
            roles=[r.name for r in user.roles] if "profile" in token_scopes else [],
        )

    @staticmethod
    async def revoke_token(
        db: AsyncSession,
        client_id: str,
        client_secret: str | None,
        token: str,
        token_type_hint: str | None = None,
    ) -> None:
        """
        Отзыв токенов по RFC 7009 (Token Revocation).
        """
        client = await OIDCService.get_and_validate_client(
            db, client_id, client_secret, require_secret=True
        )

        token_hash = hash_token(token)
        # Ищем refresh токен
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.client_id == client.id,
        )
        rt = (await db.execute(stmt)).scalar_one_or_none()
        if rt:
            rt.is_revoked = True
            await db.commit()
            return

        # По стандарту RFC 7009 если токен не найден, возвращается 200 OK

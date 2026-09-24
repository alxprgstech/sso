from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.core.exceptions import OAuthErrorException
from app.core.security import (
    create_jwt,
    decode_jwt,
    generate_random_token,
    hash_token,
    verify_password,
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

settings = get_settings()


class OIDCService:
    @staticmethod
    async def get_and_validate_client(
        db: AsyncSession,
        client_id: str,
        client_secret: str | None = None,
        require_secret: bool = True,
    ) -> OIDCClient:
        stmt = select(OIDCClient).where(OIDCClient.client_id == client_id)
        client = (await db.execute(stmt)).scalar_one_or_none()

        if not client or not client.is_active:
            raise OAuthErrorException("invalid_client", "Клиент не найден или деактивирован", 401)

        if client.client_type == "confidential" and require_secret:
            if not client_secret or not client.client_secret_hash:
                raise OAuthErrorException("invalid_client", "Требуется client_secret", 401)
            if not verify_password(client_secret, client.client_secret_hash):
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
    ) -> str:
        """
        Выпускает одноразовый authorization code с привязкой к клиенту, URI и PKCE S256 (SSO-03).
        TTL = 60 секунд.
        """
        if code_challenge_method != "S256":
            raise OAuthErrorException(
                "invalid_request", "Поддерживается только метод PKCE S256", 400
            )

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
            db, client_id, client_secret, require_secret=(client_secret is not None)
        )

        code_hash = hash_token(code)
        now = datetime.now(timezone.utc)

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
        user = (await db.execute(user_stmt)).scalar_one()

        if not user.is_active:
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
            db, client_id, client_secret, require_secret=(client_secret is not None)
        )

        token_hash = hash_token(raw_refresh_token)
        now = datetime.now(timezone.utc)

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

        # Отзываем использованный refresh токен
        rt_obj.is_revoked = True
        await db.flush()

        # Получаем пользователя
        user_stmt = select(User).where(User.id == rt_obj.user_id)
        user = (await db.execute(user_stmt)).scalar_one()

        if not user.is_active:
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
    ) -> TokenResponse:
        roles = [r.name for r in user.roles]
        now = datetime.now(timezone.utc)

        # 1. Access Token (JWT RS256, 5 минут)
        access_payload: dict[str, Any] = {
            "sub": str(user.id),
            "aud": client.client_id,
            "preferred_username": user.username,
            "email": user.email,
            "email_verified": user.email_verified,
            "scope": scope,
            "roles": roles,
            "token_use": "access_token",
            "jti": str(uuid.uuid4()),
        }
        access_token = create_jwt(
            access_payload, expires_in_seconds=settings.ACCESS_TOKEN_TTL_SECONDS
        )

        # 2. ID Token (JWT RS256, если запрошен scope openid)
        id_token = None
        if "openid" in scope.split():
            id_payload: dict[str, Any] = {
                "sub": str(user.id),  # Стабильный непрозрачный UUID (SSO-04)
                "aud": client.client_id,
                "preferred_username": user.username,
                "email": user.email,
                "email_verified": user.email_verified,
                "roles": roles,
                "token_use": "id_token",
            }
            if nonce:
                id_payload["nonce"] = nonce
            id_token = create_jwt(id_payload, expires_in_seconds=settings.ACCESS_TOKEN_TTL_SECONDS)

        # 3. Refresh Token (Ротируемый токен, 7 дней)
        raw_refresh = generate_random_token(32)
        rt_hash = hash_token(raw_refresh)
        target_family_id = family_id or uuid.uuid4()
        rt_expires = now + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS)

        new_rt = RefreshToken(
            family_id=target_family_id,
            token_hash=rt_hash,
            client_id=client.id,
            user_id=user.id,
            scope=scope,
            is_revoked=False,
            expires_at=rt_expires,
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
        """
        try:
            payload = decode_jwt(access_token)
        except Exception:
            raise OAuthErrorException(
                "invalid_token", "Токен недействителен или срок его действия истёк", 401
            )

        # Проверка SSO-03: Не принимать ID token как access token
        if payload.get("token_use") != "access_token":
            raise OAuthErrorException("invalid_token", "Передан ID Token вместо Access Token", 401)

        user_id_str = payload.get("sub")
        if not user_id_str:
            raise OAuthErrorException("invalid_token", "В токене отсутствует claim 'sub'", 401)

        stmt = select(User).where(User.id == uuid.UUID(user_id_str))
        user = (await db.execute(stmt)).scalar_one_or_none()

        if not user or not user.is_active:
            raise OAuthErrorException(
                "invalid_token", "Пользователь заблокирован или не найден", 401
            )

        return UserInfoResponse(
            sub=str(user.id),
            preferred_username=user.username,
            email=user.email,
            email_verified=user.email_verified,
            roles=[r.name for r in user.roles],
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
            db, client_id, client_secret, require_secret=(client_secret is not None)
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

        # Если передан session token
        session_stmt = select(Session).where(Session.session_token_hash == token_hash)
        sess = (await db.execute(session_stmt)).scalar_one_or_none()
        if sess:
            await db.delete(sess)
            await db.commit()
            return
        # По стандарту RFC 7009 если токен не найден, возвращается 200 OK

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import generate_csrf_token
from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationException
from app.core.privacy import short_user_agent
from app.core.security import (
    async_hash_password,
    async_rehash_password,
    async_verify_password,
    create_jwt,
    decode_jwt,
    generate_random_token,
    hash_token,
    needs_rehash,
)
from app.models.authentication import AuthenticationStep
from app.models.registration import PendingRegistration
from app.models.session import Session
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.security_state import (
    invalidate_security_state,
    lock_user,
    require_account_access,
    revision,
)

settings = get_settings()


@dataclass(frozen=True, repr=False)
class LoginAttempt:
    username: str
    password: str
    ip_address: str | None
    user_agent: str | None


class AuthService:
    @staticmethod
    async def create_user_session(
        db: AsyncSession,
        user_id: uuid.UUID,
        ip_address: str | None,
        user_agent: str | None,
        settings: Settings,
        expected_revision: int | None = None,
        mfa_token: str | None = None,
    ) -> tuple[str, Session, str]:
        """
        Создаёт новую серверную сессию в базе данных.
        Возвращает: (raw_session_token, session_model, csrf_token).
        """
        raw_token = generate_random_token(32)
        token_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS)
        user = await db.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not user or not user.is_active:
            raise AuthenticationException("Аккаунт недоступен")
        require_account_access(user, settings, allow_temporary=True)
        credential = user.password_credential
        temporary = bool(credential and credential.requires_change)
        if temporary:
            expires_at = AuthService._consume_temporary_password(user, now, expires_at)
        if expected_revision is not None and revision(user) != expected_revision:
            raise AuthenticationException("Безопасность аккаунта изменилась; повторите вход")
        if mfa_token is not None:
            await AuthService._consume_mfa_step(db, user, mfa_token, now)
        purpose = "deletion_management" if user.deletion_scheduled_for else "full"
        if temporary:
            purpose = "password_change"

        session = Session(
            user_id=user_id,
            session_token_hash=token_hash,
            ip_address=ip_address,
            user_agent=short_user_agent(user_agent) if user_agent else None,
            expires_at=expires_at,
            last_activity_at=now,
            purpose=purpose,
            security_revision=revision(user),
            auth_time=now,
        )
        db.add(session)
        if mfa_token is not None:
            await AuditService.log_event(
                db,
                "mfa_login_success",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                commit=False,
            )
        await db.commit()
        await db.refresh(session)

        csrf_token = generate_csrf_token(session.id, settings)
        return raw_token, session, csrf_token

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        username: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        settings: Settings | None = None,
    ) -> tuple[User, bool, str | None, list[str]]:
        """
        Аутентификация пользователя по паролю (Argon2id).
        Возвращает: (user, mfa_required, mfa_token, available_methods).
        """
        if settings is None:
            settings = get_settings()
        attempt = LoginAttempt(username, password, ip_address, user_agent)

        await AuthService._consume_login_limits(db, attempt, settings)
        # Поиск пользователя по username или email
        stmt = (
            select(User)
            .where((User.username == username) | (User.email == username))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        user = await AuthService._verify_password(db, user, attempt)
        if settings.REQUIRE_VERIFIED_EMAIL and not user.email_verified:
            await AuditService.log_event(
                db,
                "login_blocked_unverified_email",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        require_account_access(user, settings, allow_temporary=True)
        credential = user.password_credential
        if credential is None:
            raise AuthenticationException("Неверный логин или пароль")
        if credential.requires_change and (
            credential.temporary_consumed_at is not None
            or credential.temporary_expires_at is None
            or credential.temporary_expires_at <= datetime.now(timezone.utc)
        ):
            raise AuthenticationException("Неверный логин или пароль")

        available_methods = await AuthService._available_factors(db, user, attempt, settings)
        if available_methods:
            token = await AuthService._create_mfa_step(db, user, available_methods, settings)
            return user, True, token, available_methods
        # Проверка обязательного подтверждения email (REG-09)
        if settings.REQUIRE_VERIFIED_EMAIL and not user.email_verified:
            await AuditService.log_event(
                db,
                event_type="login_blocked_unverified_email",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise AuthenticationException(
                "Вход заблокирован: требуется подтверждение адреса электронной почты",
                error="email_verification_required",
            )

        # Успешный вход без MFA (в default-профиле)
        await AuditService.log_event(
            db,
            event_type="login_success",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return user, False, None, []

    @staticmethod
    async def verify_mfa_step_token(
        token: str, db: AsyncSession, *, method: str | None = None, settings: Settings | None = None
    ) -> User:
        """Проверяет токен шага MFA и возвращает пользователя."""
        from app.services.privacy_service import RateLimit, consume_rate_limit

        active_settings = settings or get_settings()
        await consume_rate_limit(db, active_settings, RateLimit("mfa-token", hash_token(token), 5))
        user_id, payload = AuthService._decode_mfa_step(token, method)

        await consume_rate_limit(db, active_settings, RateLimit("mfa-account", str(user_id), 5))
        user = await lock_user(db, user_id)
        require_account_access(user, settings or get_settings(), allow_temporary=True)
        await AuthService._locked_live_mfa_step(db, user, token, datetime.now(timezone.utc))
        if payload.get("security_revision") != revision(user):
            raise AuthenticationException("Шаг MFA недействителен или уже использован")
        return user

    @staticmethod
    async def change_password(
        db: AsyncSession,
        user: User,
        current_password: str,
        new_password: str,
        current_session_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Смена пароля с проверкой текущего доступа и отзывом всех других сессий (USR-01)."""
        user = await lock_user(db, user.id)
        if not user.password_credential or not await async_verify_password(
            current_password, user.password_credential.password_hash
        ):
            raise AuthenticationException("Текущий пароль указан неверно")

        if current_password == new_password:
            raise AuthenticationException("Новый пароль должен отличаться от текущего")

        user.password_credential.password_hash = await async_hash_password(new_password)
        forced = user.password_credential.requires_change
        user.password_credential.requires_change = False
        user.password_credential.temporary_expires_at = None
        user.password_credential.temporary_consumed_at = None

        await invalidate_security_state(
            db, user, preserve_session_id=None if forced else current_session_id
        )

        await AuditService.log_event(
            db,
            event_type="password_change",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            commit=False,
        )
        await db.commit()

    @staticmethod
    async def revoke_session(
        db: AsyncSession,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> bool:
        """Отзыв конкретной сессии пользователя."""
        stmt = delete(Session).where(Session.id == session_id, Session.user_id == user_id)
        res = await db.execute(stmt)
        await db.commit()
        return (getattr(res, "rowcount", 0) or 0) > 0

    @staticmethod
    async def revoke_all_sessions(
        db: AsyncSession,
        user_id: uuid.UUID,
        except_session_id: uuid.UUID | None = None,
    ) -> int:
        """Отзыв всех сессий пользователя."""
        stmt = delete(Session).where(Session.user_id == user_id)
        if except_session_id:
            stmt = stmt.where(Session.id != except_session_id)
        res = await db.execute(stmt)
        await db.commit()
        return getattr(res, "rowcount", 0) or 0

    @staticmethod
    async def register_user(
        db: AsyncSession,
        username: str,
        email: str,
        password: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        settings: Settings | None = None,
        request_details: dict[str, str] | None = None,
        legal_versions: dict[str, str] | None = None,
    ) -> PendingRegistration:
        """Begin registration; the user is created only after mailbox verification."""
        from app.services.registration_service import RegistrationService

        return await RegistrationService.start(
            db,
            username=username,
            email=email,
            password=password,
            ip_address=ip_address or "127.0.0.1",
            user_agent=user_agent,
            details=request_details or {},
            settings=settings or get_settings(),
            legal_versions=legal_versions or {},
        )

    @staticmethod
    def _consume_temporary_password(user: User, now: datetime, expires_at: datetime) -> datetime:
        credential = user.password_credential
        if credential is None:
            raise AuthenticationException("Неверный логин или пароль")
        if (
            credential.temporary_consumed_at is not None
            or credential.temporary_expires_at is None
            or credential.temporary_expires_at <= now
        ):
            raise AuthenticationException("Временный пароль истёк или уже использован")
        credential.temporary_consumed_at = now
        expires_at = min(expires_at, now + timedelta(minutes=10))
        return expires_at

    @staticmethod
    async def _consume_mfa_step(db: AsyncSession, user: User, token: str, now: datetime) -> None:
        step = await AuthService._locked_live_mfa_step(db, user, token, now)
        step.consumed_at = now

    @staticmethod
    async def _consume_login_limits(
        db: AsyncSession, attempt: LoginAttempt, settings: Settings
    ) -> None:
        from app.services.privacy_service import RateLimit, consume_rate_limit

        await consume_rate_limit(
            db, settings, RateLimit("login-identifier", attempt.username.strip().casefold(), 5)
        )
        if attempt.ip_address:
            await consume_rate_limit(db, settings, RateLimit("login-ip", attempt.ip_address, 30))
        owner = await db.scalar(
            select(User.id).where(
                (User.username == attempt.username) | (User.email == attempt.username)
            )
        )
        if owner:
            await consume_rate_limit(db, settings, RateLimit("login-account", str(owner), 5))

    @staticmethod
    async def _verify_password(db: AsyncSession, user: User | None, attempt: LoginAttempt) -> User:
        if not user or not user.is_active:
            # Защита от timing attacks и перечисления пользователей: выполняем фиктивную проверку
            await async_verify_password(attempt.password, None)
            await AuditService.log_event(
                db,
                event_type="login_failed",
                ip_address=attempt.ip_address,
                user_agent=attempt.user_agent,
                details={"reason": "user_not_found_or_inactive", "identifier": attempt.username},
            )
            raise AuthenticationException("Неверный логин или пароль")

        # Проверка пароля
        if not user.password_credential:
            await async_verify_password(attempt.password, None)
            raise AuthenticationException("Неверный логин или пароль")

        if not await async_verify_password(
            attempt.password, user.password_credential.password_hash
        ):
            await AuditService.log_event(
                db,
                event_type="login_failed",
                user_id=user.id,
                ip_address=attempt.ip_address,
                user_agent=attempt.user_agent,
                details={"reason": "invalid_password"},
            )
            raise AuthenticationException("Неверный логин или пароль")

        # Проверка необходимости рехеширования (Argon2id rehash)
        if needs_rehash(user.password_credential.password_hash):
            user.password_credential.password_hash = await async_rehash_password(attempt.password)
            await db.flush()
        return user

    @staticmethod
    async def _available_factors(
        db: AsyncSession, user: User, attempt: LoginAttempt, settings: Settings
    ) -> list[str]:
        # Проверка MFA политик (SEC-FLAG-03, SEC-FLAG-04)
        has_totp = bool(user.totp_credential and user.totp_credential.is_confirmed)
        has_passkey = bool(user.webauthn_credentials and len(user.webauthn_credentials) > 0)

        # Инвариант SEC-FLAG-04: предотвращение скрытого понижения класса защиты (No Silent Bypass)
        if AuthService._factor_policy_unavailable(has_totp, has_passkey, settings):
            await AuditService.log_event(
                db,
                event_type="login_blocked_mfa_disabled",
                user_id=user.id,
                ip_address=attempt.ip_address,
                user_agent=attempt.user_agent,
                details={"has_totp": has_totp, "has_passkey": has_passkey},
            )
            raise AuthenticationException(
                "Учётная запись требует второго фактора (MFA), который отключен на сервере. "
                "Обратитесь к администратору для сброса факторов."
            )

        from app.services.privacy_service import factor_methods

        available_methods = factor_methods(user, settings)
        return available_methods

    @staticmethod
    async def _create_mfa_step(
        db: AsyncSession, user: User, methods: list[str], settings: Settings
    ) -> str:
        # Генерируем временный подписанный токен шага MFA
        mfa_payload = {
            "sub": str(user.id),
            "purpose": "mfa_step",
            "token_use": "mfa_step",
            "aud": "alxprgs:mfa",
            "jti": str(uuid.uuid4()),
            "security_revision": revision(user),
            "methods": methods,
        }
        mfa_token = create_jwt(mfa_payload, expires_in_seconds=settings.MFA_STEP_TTL_SECONDS)
        db.add(
            AuthenticationStep(
                user_id=user.id,
                security_revision=revision(user),
                token_hash=hash_token(mfa_token),
                expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=settings.MFA_STEP_TTL_SECONDS),
            )
        )
        await db.commit()
        return mfa_token

    @staticmethod
    def _decode_mfa_step(token: str, method: str | None):
        try:
            payload = decode_jwt(token, audience="alxprgs:mfa", expected_use="mfa_step")
            if payload.get("purpose") != "mfa_step":
                raise AuthenticationException("Недействительный токен MFA")
            user_id = uuid.UUID(payload["sub"])
            if method is not None and method not in payload.get("methods", []):
                raise AuthenticationException("Недопустимый метод MFA")
        except Exception:
            raise AuthenticationException("Срок действия шага MFA истёк или токен недействителен")

        return user_id, payload

    @staticmethod
    def _require_unused_mfa_step(step: AuthenticationStep, now: datetime) -> None:
        if step.consumed_at is not None or step.expires_at <= now:
            raise AuthenticationException("Шаг MFA недействителен или уже использован")

    @staticmethod
    async def _locked_live_mfa_step(
        db: AsyncSession, user: User, token: str, now: datetime
    ) -> AuthenticationStep:
        step = await db.scalar(
            select(AuthenticationStep)
            .where(
                AuthenticationStep.token_hash == hash_token(token),
                AuthenticationStep.user_id == user.id,
            )
            .with_for_update()
        )
        if step is None:
            raise AuthenticationException("Шаг MFA недействителен или уже использован")
        AuthService._require_unused_mfa_step(step, now)
        if step.security_revision != revision(user):
            raise AuthenticationException("Шаг MFA недействителен или уже использован")
        return step

    @staticmethod
    def _factor_policy_unavailable(totp: bool, passkey: bool, settings: Settings) -> bool:
        factors = (
            (totp, settings.FEATURE_TOTP_ENABLED),
            (passkey, settings.FEATURE_PASSKEY_ENABLED),
        )
        return any(present and not enabled for present, enabled in factors)

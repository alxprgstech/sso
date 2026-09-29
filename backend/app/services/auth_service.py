from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import generate_csrf_token
from app.config import Settings, get_settings
from app.core.exceptions import AuthenticationException
from app.core.security import (
    create_jwt,
    decode_jwt,
    generate_random_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.models.session import Session
from app.models.user import PasswordCredential, User
from app.services.audit_service import AuditService

settings = get_settings()


class AuthService:
    @staticmethod
    async def create_user_session(
        db: AsyncSession,
        user_id: uuid.UUID,
        ip_address: str | None,
        user_agent: str | None,
        settings: Settings,
    ) -> tuple[str, Session, str]:
        """
        Создаёт новую серверную сессию в базе данных.
        Возвращает: (raw_session_token, session_model, csrf_token).
        """
        raw_token = generate_random_token(32)
        token_hash = hash_token(raw_token)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS)

        session = Session(
            user_id=user_id,
            session_token_hash=token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
            last_activity_at=now,
        )
        db.add(session)
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
        # Поиск пользователя по username или email
        stmt = select(User).where((User.username == username) | (User.email == username))
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not user.is_active:
            # Защита от timing attacks и перечисления пользователей: выполняем фиктивную проверку
            verify_password(password, "$argon2id$v=19$m=65536,t=3,p=4$dummy$dummy")
            await AuditService.log_event(
                db,
                event_type="login_failed",
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "user_not_found_or_inactive", "identifier": username},
            )
            raise AuthenticationException("Неверный логин или пароль")

        # Проверка пароля
        if not user.password_credential:
            raise AuthenticationException("Учётная запись не настроена для входа по паролю")

        if not verify_password(password, user.password_credential.password_hash):
            await AuditService.log_event(
                db,
                event_type="login_failed",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "invalid_password"},
            )
            raise AuthenticationException("Неверный логин или пароль")

        # Проверка необходимости рехеширования (Argon2id rehash)
        if needs_rehash(user.password_credential.password_hash):
            user.password_credential.password_hash = hash_password(password)
            await db.commit()

        # Проверка MFA политик (SEC-FLAG-03, SEC-FLAG-04)
        has_totp = bool(user.totp_credential and user.totp_credential.is_confirmed)
        has_passkey = bool(user.webauthn_credentials and len(user.webauthn_credentials) > 0)

        # Инвариант SEC-FLAG-04: предотвращение скрытого понижения класса защиты (No Silent Bypass)
        if (has_totp and not settings.FEATURE_TOTP_ENABLED) or (
            has_passkey and not settings.FEATURE_PASSKEY_ENABLED
        ):
            await AuditService.log_event(
                db,
                event_type="login_blocked_mfa_disabled",
                user_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"has_totp": has_totp, "has_passkey": has_passkey},
            )
            raise AuthenticationException(
                "Учётная запись требует второго фактора (MFA), который отключен на сервере. "
                "Обратитесь к администратору для сброса факторов."
            )

        # Если MFA включено на сервере и у пользователя настроены факторы:
        available_methods = []
        if settings.FEATURE_TOTP_ENABLED and has_totp:
            available_methods.append("totp")
            if settings.FEATURE_RECOVERY_CODES_ENABLED:
                available_methods.append("recovery_code")
        if settings.FEATURE_PASSKEY_ENABLED and has_passkey:
            available_methods.append("passkey")

        if available_methods:
            # Генерируем временный подписанный токен шага MFA
            mfa_payload = {
                "sub": str(user.id),
                "purpose": "mfa_step",
                "methods": available_methods,
            }
            mfa_token = create_jwt(mfa_payload, expires_in_seconds=settings.MFA_STEP_TTL_SECONDS)
            return user, True, mfa_token, available_methods

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
    async def verify_mfa_step_token(token: str, db: AsyncSession) -> User:
        """Проверяет токен шага MFA и возвращает пользователя."""
        try:
            payload = decode_jwt(token)
            if payload.get("purpose") != "mfa_step":
                raise AuthenticationException("Недействительный токен MFA")
            user_id = uuid.UUID(payload["sub"])
        except Exception:
            raise AuthenticationException("Срок действия шага MFA истёк или токен недействителен")

        stmt = select(User).where(User.id == user_id, User.is_active.is_(True))
        user = (await db.execute(stmt)).scalar_one_or_none()
        if not user:
            raise AuthenticationException("Пользователь не найден или заблокирован")
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
        if not user.password_credential or not verify_password(
            current_password, user.password_credential.password_hash
        ):
            raise AuthenticationException("Текущий пароль указан неверно")

        if current_password == new_password:
            raise AuthenticationException("Новый пароль должен отличаться от текущего")

        user.password_credential.password_hash = hash_password(new_password)

        # Отзыв всех остальных сессий пользователя
        stmt = delete(Session).where(Session.user_id == user.id)
        if current_session_id:
            stmt = stmt.where(Session.id != current_session_id)
        await db.execute(stmt)

        await AuditService.log_event(
            db,
            event_type="password_change",
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
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
    ) -> User:
        """
        Самостоятельная регистрация обычного пользователя (REG-01..REG-09).
        Создает учетную запись с ролью 'user' и без сессии.
        """
        from app.services.system_service import SystemService
        from app.core.rate_limit import check_registration_rate_limit
        from app.core.rbac import ROLE_USER
        from app.core.exceptions import AuthorizationException
        from app.models.user import Role, UserRole
        from fastapi import HTTPException, status
        from sqlalchemy import func
        from sqlalchemy.exc import IntegrityError

        # 1. Проверка доступности регистрации (REG-02, REG-03)
        mode = await SystemService.get_registration_mode(db)
        if mode != "open":
            await AuditService.log_event(
                db,
                event_type="registration_rejected_closed",
                ip_address=ip_address,
                user_agent=user_agent,
                details={"username": username},
            )
            raise AuthorizationException("Регистрация новых пользователей в данный момент закрыта")

        # 2. Ограничение частоты запросов (REG-07)
        await check_registration_rate_limit(db, ip_address or "127.0.0.1")

        # 3. Нормализация данных (REG-05)
        clean_username = username.strip()
        clean_email = email.strip().lower()

        # 4. Проверка существования (защита от коллизий, единый 409 без раскрытия полей REG-06)
        stmt = select(User).where(
            (func.lower(User.username) == clean_username.lower())
            | (func.lower(User.email) == clean_email)
        )
        existing = (await db.execute(stmt)).scalar_one_or_none()
        if existing:
            await AuditService.log_event(
                db,
                event_type="registration_collision",
                ip_address=ip_address,
                user_agent=user_agent,
                details={"reason": "username_or_email_conflict"},
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "user_already_exists",
                    "detail": "Учётная запись с указанными данными уже существует",
                },
            )

        # 5. Атомарное создание пользователя и учетных данных
        role_stmt = select(Role).where(Role.name == ROLE_USER)
        role_user = (await db.execute(role_stmt)).scalar_one_or_none()
        if not role_user:
            role_user = Role(name=ROLE_USER, description="Стандартный пользователь экосистемы")
            db.add(role_user)
            await db.flush()

        new_user = User(
            id=uuid.uuid4(),
            username=clean_username,
            email=clean_email,
            is_active=True,
            is_superuser=False,
            email_verified=False,
        )
        db.add(new_user)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "user_already_exists",
                    "detail": "Учётная запись с указанными данными уже существует",
                },
            )

        # Добавляем парольные учетные данные
        pw_cred = PasswordCredential(
            user_id=new_user.id,
            password_hash=hash_password(password),
        )
        db.add(pw_cred)

        # Привязываем роль 'user'
        user_role = UserRole(user_id=new_user.id, role_id=role_user.id)
        db.add(user_role)

        # Если включена функция подтверждения email (REG-09)
        active_settings = settings or get_settings()
        if active_settings.FEATURE_EMAIL_VERIFICATION_ENABLED:
            from app.services.mfa_service import EmailVerificationService

            await EmailVerificationService.send_verification(
                db, new_user, clean_email, active_settings
            )

        await AuditService.log_event(
            db,
            event_type="user_registered",
            user_id=new_user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"username": clean_username, "email": clean_email},
        )

        try:
            await db.commit()
            await db.refresh(new_user)
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "user_already_exists",
                    "detail": "Учётная запись с указанными данными уже существует",
                },
            )

        return new_user

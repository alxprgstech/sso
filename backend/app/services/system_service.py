from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import AuthenticationException
from app.core.security import verify_password
from app.models.system import SystemConfiguration
from app.models.user import User
from app.services.audit_service import AuditService


class SystemService:
    @staticmethod
    async def get_or_create_configuration(db: AsyncSession) -> SystemConfiguration:
        """
        Возвращает единственную запись конфигурации системы (REG-02, SETUP-05).
        Если запись отсутствует, инициализирует начальное состояние.
        """
        stmt = select(SystemConfiguration).where(SystemConfiguration.id == 1)
        res = await db.execute(stmt)
        config = res.scalar_one_or_none()
        if not config:
            config = SystemConfiguration(
                id=1,
                bootstrap_completed=False,
                bootstrap_completed_at=None,
                registration_mode="closed",
                updated_at=datetime.now(timezone.utc),
            )
            db.add(config)
            await db.commit()
            await db.refresh(config)
        return config

    @staticmethod
    async def get_registration_mode(db: AsyncSession) -> str:
        """
        Возвращает актуальный режим регистрации (REG-02, REG-03).
        До завершения bootstrap регистрация безусловно закрыта ('closed').
        """
        config = await SystemService.get_or_create_configuration(db)
        if not config.bootstrap_completed:
            return "closed"
        return config.registration_mode

    @staticmethod
    async def update_registration_mode(
        db: AsyncSession,
        admin_user: User,
        admin_password: str,
        new_mode: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> SystemConfiguration:
        """
        Переключение режима регистрации администратором после повторной аутентификации (REG-02).
        """
        if not admin_user.password_credential or not verify_password(
            admin_password, admin_user.password_credential.password_hash
        ):
            await AuditService.log_event(
                db,
                event_type="admin_reauth_failed",
                user_id=admin_user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={"action": "update_registration_mode"},
            )
            raise AuthenticationException(
                "Неверный пароль администратора для подтверждения операции"
            )

        stmt = select(SystemConfiguration).where(SystemConfiguration.id == 1).with_for_update()
        res = await db.execute(stmt)
        config = res.scalar_one_or_none()
        if not config:
            config = SystemConfiguration(
                id=1,
                bootstrap_completed=True,
                bootstrap_completed_at=datetime.now(timezone.utc),
                registration_mode=new_mode,
                updated_at=datetime.now(timezone.utc),
            )
            db.add(config)
            prev_mode = "closed"
        else:
            prev_mode = config.registration_mode
            config.registration_mode = new_mode
            config.updated_at = datetime.now(timezone.utc)

        await AuditService.log_event(
            db,
            event_type="registration_mode_changed",
            user_id=admin_user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"previous_mode": prev_mode, "new_mode": new_mode},
        )
        await db.commit()
        await db.refresh(config)
        return config

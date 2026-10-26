"""Server-owned authentication assurance for browser sessions and OIDC grants.

A session is MFA-assured only when the server verified a second factor while
creating it or while explicitly elevating that exact session.  ``auth_time``,
the presence of a user session, a role name or client input never prove MFA.
"""

from __future__ import annotations

from app.config import Settings
from app.core.rbac import ROLE_ADMIN
from app.models.session import Session
from app.models.user import User

MFA_AMR_VALUES = frozenset({"otp", "hwk", "swk", "mfa"})
MFA_METHODS = ("totp", "passkey", "recovery_code")


def is_admin_user(user: User) -> bool:
    """Any server-recognised privileged identity, not only the frontend route."""
    return bool(user.is_superuser or any(role.name == ROLE_ADMIN for role in user.roles))


def has_confirmed_factor(user: User) -> bool:
    """Configured factors independent of runtime feature availability."""
    return bool(
        (user.totp_credential and user.totp_credential.is_confirmed) or user.webauthn_credentials
    )


def active_factors(user: User, settings: Settings) -> tuple[bool, bool]:
    """Return (totp, passkey) only when the factor is configured and enabled."""
    totp = bool(
        settings.FEATURE_TOTP_ENABLED and user.totp_credential and user.totp_credential.is_confirmed
    )
    passkey = bool(settings.FEATURE_PASSKEY_ENABLED and user.webauthn_credentials)
    return totp, passkey


def has_active_factor(user: User, settings: Settings) -> bool:
    return any(active_factors(user, settings))


def admin_mfa_policy_active(user: User, settings: Settings) -> bool:
    return bool(settings.REQUIRE_ADMIN_MFA and is_admin_user(user))


def admin_enrollment_required(user: User, settings: Settings) -> bool:
    """Admin with no usable factor at all needs the limited onboarding session."""
    return admin_mfa_policy_active(user, settings) and not has_active_factor(user, settings)


def admin_access_allowed(user: User, session: Session, settings: Settings) -> bool:
    if not is_admin_user(user):
        return False
    if not settings.REQUIRE_ADMIN_MFA:
        return True
    return session_is_mfa_assured(session)


def session_is_mfa_assured(session: Session) -> bool:
    return bool(session.mfa_verified and session.mfa_method in MFA_METHODS)


def amr_for_method(method: str | None, *, password_used: bool = True) -> str:
    if method == "totp":
        return "pwd otp"
    if method == "passkey":
        return "pwd hwk" if password_used else "hwk"
    if method == "recovery_code":
        return "pwd mfa"
    return "pwd"


def split_amr(value: str | None) -> list[str]:
    if not value:
        return ["pwd"]
    values = [item for item in value.split() if item]
    return values or ["pwd"]


def amr_has_mfa(values: list[str] | tuple[str, ...] | set[str]) -> bool:
    return bool(set(values) & MFA_AMR_VALUES)


def roles_for_token(user: User, settings: Settings, *, mfa_verified: bool) -> list[str]:
    """Never emit the admin role for a grant lacking required assurance."""
    roles = [role.name for role in user.roles]
    if (
        settings.REQUIRE_ADMIN_MFA
        and is_admin_user(user)
        and not mfa_verified
        and ROLE_ADMIN in roles
    ):
        roles = [role for role in roles if role != ROLE_ADMIN]
    return roles


def userinfo_roles(user: User, settings: Settings, *, token_amr: list[str]) -> list[str]:
    """UserInfo must not upgrade a grant that was issued without assurance."""
    roles = [role.name for role in user.roles]
    if (
        settings.REQUIRE_ADMIN_MFA
        and is_admin_user(user)
        and not amr_has_mfa(token_amr)
        and ROLE_ADMIN in roles
    ):
        roles = [role for role in roles if role != ROLE_ADMIN]
    return roles


def assurance_acr(mfa_verified: bool) -> str:
    return "urn:alxprgs:acr:mfa" if mfa_verified else "urn:alxprgs:acr:pwd"

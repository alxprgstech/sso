#!/usr/bin/env python3
"""Controlled, auditable recovery for an administrator who lost every factor.

This CLI requires server/DB operator access. It removes factors and revokes
sessions/grants, but it never marks a session MFA-verified and never creates a
replacement factor. After the reset the administrator must sign in, enrol a new
TOTP/Passkey and confirm it before admin access returns.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_maker
from app.models.mfa import RecoveryCode, TOTPCredential, WebAuthnCredential
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.security_state import invalidate_security_state, lock_user

REASONS = ("lost_factor", "compromised", "owner_request")


def _is_admin(user: User) -> bool:
    return bool(user.is_superuser or any(role.name == "admin" for role in user.roles))


async def admin_status(session: AsyncSession) -> int:
    users = (
        await session.execute(
            select(User)
            .where(User.is_active.is_(True), User.deletion_scheduled_for.is_(None))
            .order_by(User.username)
        )
    ).scalars()
    admins = [user for user in users if _is_admin(user)]
    if not admins:
        print("No active administrators found.")
        return 1
    for user in admins:
        recovery_count = (
            await session.scalar(
                select(func.count(RecoveryCode.id)).where(
                    RecoveryCode.user_id == user.id, RecoveryCode.is_used.is_(False)
                )
            )
            or 0
        )
        print(
            f"{user.username}: superuser={user.is_superuser} "
            f"roles={','.join(sorted(role.name for role in user.roles)) or '-'} "
            f"totp={bool(user.totp_credential and user.totp_credential.is_confirmed)} "
            f"passkeys={len(user.webauthn_credentials)} "
            f"recovery_codes={recovery_count}"
        )
    return 0


async def reset_admin_factors(
    session: AsyncSession, username: str, reason: str, confirmation: str
) -> int:
    if reason not in REASONS:
        print(f"[ERROR] reason must be one of: {', '.join(REASONS)}", file=sys.stderr)
        return 1
    if confirmation != username:
        print("[ERROR] confirmation does not match the administrator username", file=sys.stderr)
        return 1
    user = await session.scalar(select(User).where(User.username == username).with_for_update())
    if user is None or not user.is_active:
        print("[ERROR] active administrator not found", file=sys.stderr)
        return 1
    if not _is_admin(user):
        print("[ERROR] account is not an administrator", file=sys.stderr)
        return 1
    # Lock again through the shared helper to keep the account lock ordering.
    user = await lock_user(session, user.id)
    await session.execute(delete(TOTPCredential).where(TOTPCredential.user_id == user.id))
    await session.execute(delete(WebAuthnCredential).where(WebAuthnCredential.user_id == user.id))
    await session.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    await invalidate_security_state(session, user)
    await AuditService.log_event(
        session,
        event_type="admin_mfa_recovery_reset",
        user_id=user.id,
        details={"reason": reason, "reset_at": datetime.now(timezone.utc).isoformat()},
        commit=False,
    )
    await session.commit()
    print(
        "Factors removed and all sessions/grants revoked. "
        "The administrator must now sign in with the password, enrol TOTP or Passkey, "
        "and confirm it before admin access returns."
    )
    return 0


async def _run(args) -> int:
    async with async_session_maker() as session:
        if args.command == "status":
            return await admin_status(session)
        return await reset_admin_factors(session, args.username, args.reason, args.confirm)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    reset = sub.add_parser("reset-factors")
    reset.add_argument("--username", required=True)
    reset.add_argument("--reason", required=True, choices=REASONS)
    reset.add_argument(
        "--confirm",
        required=True,
        help="Repeat the exact username to confirm this offline recovery action",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()

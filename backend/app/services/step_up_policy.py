"""Explicit authentication-assurance policy for external transaction step-up.

The policy is deliberately server-owned.  A relying party may request a level
that its registered client is allowed to use, but it cannot choose factors,
downgrade the required result, or turn a partial factor into success.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from app.config import Settings
from app.models.oidc import OIDCClient
from app.models.step_up import ExternalStepUpRequest
from app.models.user import User

ASSURANCE_LEVELS = (
    "reauth_basic",
    "reauth_mfa",
    "reauth_strict",
    "reauth_password_mfa",
)
ASSURANCE_LABELS = {
    "reauth_basic": "Базовая повторная проверка",
    "reauth_mfa": "Многофакторная проверка",
    "reauth_strict": "Усиленная проверка с Passkey",
    "reauth_password_mfa": "Пароль и второй фактор",
}
METHODS = ("password", "totp", "passkey")
METHOD_LABELS = {
    "password": "Текущий пароль",
    "totp": "Код из приложения-аутентификатора",
    "passkey": "Passkey",
}
AMR = {"password": "pwd", "totp": "otp", "passkey": "hwk"}  # pragma: allowlist secret
ACTION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
PAYLOAD_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STATE_MIN_LENGTH = 16
NONCE_MIN_LENGTH = 16
CLIENT_ACTION_MAX_COUNT = 32
CLIENT_ACTION_MAX_LENGTH = 512


@dataclass(frozen=True)
class FactorAvailability:
    password: bool
    totp: bool
    passkey: bool

    def has(self, method: str) -> bool:
        return bool(getattr(self, method, False))


@dataclass(frozen=True)
class AssurancePlan:
    id: str
    methods: tuple[str, ...]
    label: str

    @property
    def amr(self) -> list[str]:
        return [AMR[method] for method in self.methods]


def available_factors(user: User, settings: Settings) -> FactorAvailability:
    """Return only factors that are usable in the current server profile.

    A configured factor behind a disabled feature is not silently accepted.
    Recovery codes are intentionally absent: they are not a transaction
    authentication factor for this protocol.
    """
    credential = user.password_credential
    password = credential is not None and not credential.requires_change
    totp = bool(
        settings.FEATURE_TOTP_ENABLED and user.totp_credential and user.totp_credential.is_confirmed
    )
    passkey = bool(settings.FEATURE_PASSKEY_ENABLED and user.webauthn_credentials)
    return FactorAvailability(password=password, totp=totp, passkey=passkey)


def _plans_for(assurance: str, factors: FactorAvailability) -> tuple[AssurancePlan, ...]:
    password_totp = factors.password and factors.totp
    password_passkey = factors.password and factors.passkey
    if assurance == "reauth_basic":
        plans = []
        if factors.password:
            plans.append(AssurancePlan("password", ("password",), "Текущий пароль"))
        if factors.passkey:
            plans.append(AssurancePlan("passkey", ("passkey",), "Passkey с проверкой пользователя"))
        return tuple(plans)
    if assurance == "reauth_mfa":
        plans = []
        if factors.passkey:
            plans.append(AssurancePlan("passkey", ("passkey",), "Passkey с проверкой пользователя"))
        if password_totp:
            plans.append(
                AssurancePlan(
                    "password_totp", ("password", "totp"), "Пароль и код из аутентификатора"
                )
            )
        return tuple(plans)
    if assurance == "reauth_password_mfa":
        plans = []
        if password_totp:
            plans.append(
                AssurancePlan(
                    "password_totp", ("password", "totp"), "Пароль и код из аутентификатора"
                )
            )
        if password_passkey:
            plans.append(
                AssurancePlan("password_passkey", ("password", "passkey"), "Пароль и Passkey")
            )
        return tuple(plans)
    if assurance == "reauth_strict":
        if password_passkey:
            return (AssurancePlan("password_passkey", ("password", "passkey"), "Пароль и Passkey"),)
        return ()
    return ()


def plans_for(assurance: str, user: User, settings: Settings) -> tuple[AssurancePlan, ...]:
    if assurance not in ASSURANCE_LEVELS:
        return ()
    return _plans_for(assurance, available_factors(user, settings))


def plan_for_id(
    assurance: str, plan_id: str, user: User, settings: Settings
) -> AssurancePlan | None:
    return next(
        (plan for plan in plans_for(assurance, user, settings) if plan.id == plan_id),
        None,
    )


def verified_methods(request: ExternalStepUpRequest) -> list[str]:
    fields = (
        ("password", request.password_verified_at),
        ("totp", request.totp_verified_at),
        ("passkey", request.passkey_verified_at),
    )
    return [method for method, value in fields if value is not None]


def plan_is_satisfied(request: ExternalStepUpRequest, plan: AssurancePlan) -> bool:
    done = set(verified_methods(request))
    return set(plan.methods) <= done


def amr_for(request: ExternalStepUpRequest, plan: AssurancePlan) -> list[str]:
    """Use the plan order, not caller input, so signed evidence is deterministic."""
    done = set(verified_methods(request))
    return [AMR[method] for method in plan.methods if method in done]


def valid_action(value: str) -> bool:
    return bool(ACTION_PATTERN.fullmatch(value))


def valid_payload_hash(value: str) -> bool:
    return bool(PAYLOAD_HASH_PATTERN.fullmatch(value))


def parse_client_levels(value: str) -> tuple[str, ...]:
    values = tuple(item for item in value.split() if item)
    if len(set(values)) != len(values) or any(item not in ASSURANCE_LEVELS for item in values):
        return ()
    return values


def parse_client_actions(value: str) -> tuple[str, ...]:
    values = tuple(item for item in value.split() if item)
    if len(set(values)) != len(values) or any(not valid_action(item) for item in values):
        return ()
    return values


def normalize_client_levels(values: Iterable[str]) -> str:
    unique = []
    for value in values:
        if value not in ASSURANCE_LEVELS:
            raise ValueError("Недопустимый уровень подтверждения")
        if value in unique:
            raise ValueError("Уровни подтверждения не должны повторяться")
        unique.append(value)
    if not unique:
        raise ValueError("Укажите хотя бы один уровень подтверждения")
    return " ".join(unique)


def normalize_client_actions(values: Iterable[str]) -> str:
    unique = []
    for value in values:
        value = value.strip()
        if not valid_action(value):
            raise ValueError("Недопустимый идентификатор действия")
        if value in unique:
            raise ValueError("Действия не должны повторяться")
        unique.append(value)
    if not unique:
        raise ValueError("Укажите хотя бы одно разрешённое действие")
    encoded = " ".join(unique)
    if len(encoded) > CLIENT_ACTION_MAX_LENGTH or len(unique) > CLIENT_ACTION_MAX_COUNT:
        raise ValueError("Слишком много разрешённых действий")
    return encoded


def client_policy_allows(client: OIDCClient, assurance: str, action: str, ttl: int) -> bool:
    if not client.step_up_enabled or client.client_type != "confidential" or not client.is_active:
        return False
    if assurance not in parse_client_levels(client.step_up_assurance_levels or ""):
        return False
    if action not in parse_client_actions(client.step_up_actions or ""):
        return False
    if not 30 <= ttl <= min(300, int(client.step_up_max_ttl_seconds or 300)):
        return False
    return True

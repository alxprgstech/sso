"""Policy unit tests: assurance cannot be raised or downgraded by caller input."""

from __future__ import annotations

import uuid

import pytest
from app.config import Settings
from app.models.mfa import TOTPCredential, WebAuthnCredential
from app.models.oidc import OIDCClient
from app.models.user import PasswordCredential, User
from app.services.step_up_policy import (
    available_factors,
    client_policy_allows,
    normalize_client_actions,
    normalize_client_levels,
    plan_for_id,
    plans_for,
)

pytestmark = pytest.mark.unit


def user_with_factors(*, password=True, totp=False, passkey=False) -> User:
    user = User(id=uuid.uuid4(), username="step_up_policy", email="step-up-policy@example.test")
    if password:
        user.password_credential = PasswordCredential(
            user_id=user.id,
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",
            requires_change=False,
        )
    if totp:
        user.totp_credential = TOTPCredential(
            user_id=user.id, encrypted_secret="synthetic", is_confirmed=True
        )
    if passkey:
        user.webauthn_credentials = [
            WebAuthnCredential(
                user_id=user.id,
                credential_id="synthetic-credential",
                public_key="00",
                sign_count=0,
            )
        ]
    return user


def settings(**overrides) -> Settings:
    values = {
        "ENVIRONMENT": "testing",
        "FEATURE_EXTERNAL_STEP_UP_ENABLED": True,
        "FEATURE_TOTP_ENABLED": True,
        "FEATURE_PASSKEY_ENABLED": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_basic_allows_password_or_passkey_but_not_recovery() -> None:
    user = user_with_factors(password=True, passkey=True)
    plans = plans_for("reauth_basic", user, settings())
    assert {plan.id for plan in plans} == {"password", "passkey"}
    assert all("recovery_code" not in plan.methods for plan in plans)


def test_totp_alone_never_satisfies_mfa() -> None:
    user = user_with_factors(password=False, totp=True)
    assert plans_for("reauth_mfa", user, settings()) == ()
    assert plans_for("reauth_password_mfa", user, settings()) == ()


def test_mfa_accepts_passkey_or_password_plus_totp_but_not_password_alone() -> None:
    user = user_with_factors(password=True, totp=True, passkey=True)
    plans = plans_for("reauth_mfa", user, settings())
    assert {plan.id for plan in plans} == {"passkey", "password_totp"}
    assert ("password",) not in {plan.methods for plan in plans}
    password_only = user_with_factors(password=True)
    assert plans_for("reauth_mfa", password_only, settings()) == ()


def test_password_mfa_requires_fresh_password() -> None:
    user = user_with_factors(password=True, totp=True, passkey=True)
    plans = plans_for("reauth_password_mfa", user, settings())
    assert {plan.id for plan in plans} == {"password_totp", "password_passkey"}
    assert all("password" in plan.methods for plan in plans)


def test_strict_requires_password_and_passkey() -> None:
    user = user_with_factors(password=True, totp=True)
    assert plans_for("reauth_strict", user, settings()) == ()
    user = user_with_factors(password=True, passkey=True)
    plan = plans_for("reauth_strict", user, settings())
    assert len(plan) == 1
    assert plan[0].methods == ("password", "passkey")


def test_disabled_features_do_not_count_as_available_factors() -> None:
    user = user_with_factors(password=True, totp=True, passkey=True)
    cfg = settings(FEATURE_TOTP_ENABLED=False, FEATURE_PASSKEY_ENABLED=False)
    factors = available_factors(user, cfg)
    assert factors.password is True
    assert factors.totp is False
    assert factors.passkey is False
    assert plans_for("reauth_mfa", user, cfg) == ()
    assert plans_for("reauth_strict", user, cfg) == ()
    assert {plan.id for plan in plans_for("reauth_basic", user, cfg)} == {"password"}


def test_temporary_password_is_not_available() -> None:
    user = user_with_factors(password=True)
    assert user.password_credential is not None
    user.password_credential.requires_change = True
    assert plans_for("reauth_basic", user, settings()) == ()


def test_unknown_plan_and_assurance_are_rejected() -> None:
    user = user_with_factors(password=True, passkey=True)
    assert plans_for("reauth_unknown", user, settings()) == ()
    assert plan_for_id("reauth_strict", "password", user, settings()) is None


def test_client_policy_requires_explicit_enablement_and_action_allowlist() -> None:
    client = OIDCClient(
        client_id="client_synthetic",
        client_name="Synthetic RP",
        client_type="confidential",
        is_active=True,
        step_up_enabled=True,
        step_up_assurance_levels="reauth_mfa",
        step_up_actions="critical_settings_change",
        step_up_max_ttl_seconds=120,
    )
    assert client_policy_allows(client, "reauth_mfa", "critical_settings_change", 60)
    assert not client_policy_allows(client, "reauth_strict", "critical_settings_change", 60)
    assert not client_policy_allows(client, "reauth_mfa", "delete_account", 60)
    assert not client_policy_allows(client, "reauth_mfa", "critical_settings_change", 121)
    client.step_up_enabled = False
    assert not client_policy_allows(client, "reauth_mfa", "critical_settings_change", 60)
    client.step_up_enabled = True
    client.client_type = "public"
    assert not client_policy_allows(client, "reauth_mfa", "critical_settings_change", 60)


def test_policy_normalization_rejects_duplicates_and_html_actions() -> None:
    with pytest.raises(ValueError):
        normalize_client_levels(["reauth_basic", "reauth_basic"])
    with pytest.raises(ValueError):
        normalize_client_actions(["<script>alert(1)</script>"])
    assert normalize_client_levels(["reauth_basic"]) == "reauth_basic"
    assert normalize_client_actions(["critical_settings_change"]) == "critical_settings_change"

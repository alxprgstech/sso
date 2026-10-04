"""Post-remediation audit replay using durable mandatory regressions.

Original assertions/doubles are preserved byte-for-byte in readiness_probes_baseline.py.
Run: python -m pytest -p tests.conftest docs/audit/test_readiness_probes.py
PostgreSQL guard/marker applies; cryptography is real. See readiness-probe-map.md.
These imported functions also run from tests/ in mandatory CI; counts overlap.
"""

from tests.test_audit_crypto_regressions import (  # noqa: F401
    test_real_crypto_rejects_adversarial_access_token,
    test_real_crypto_accepts_valid_access_and_nonce_id,
    test_sdk_requires_complete_id_token_profile,
)

from tests.test_production_keys import (  # noqa: F401
    production_values,
    test_production_rejects_unsafe_config,
    test_workers_and_restart_share_persistent_key,
    test_rotation_overlap_and_retirement,
    test_hostile_key_identifier_has_controlled_failure,
)

from tests.test_signed_token_profiles import (  # noqa: F401
    test_missing_access_claims_rejected_by_server_and_independent_sdk,
    test_wrong_claim_types_rejected_with_real_signature,
    test_id_azp_nonce_age_and_access_scope_guard,
    test_malformed_header_never_fetches_sdk_jwks,
    test_pkce_rejects_invalid_syntax_even_when_digest_matches,
    test_pkce_accepts_boundary_s256,
)

from tests.test_g8_sec_regression import (  # noqa: F401
    test_login_return_to_validation_rejects_open_redirect,
)

from tests.test_production_origin_policy import (  # noqa: F401
    test_cors_production_does_not_trust_local_origins,
)

from tests.test_smtp_tls import (  # noqa: F401
    test_verified_starttls_before_credentials,
    test_credentials_refused_without_tls_before_connection,
)

from tests.integration.test_oidc_contract_remediation_pg import (  # noqa: F401
    test_prompt_login_demands_new_password_authentication_once,
    test_prompt_none_and_client_scope_policy,
    test_logout_post_with_expired_current_hint_and_hintless_confirmation,
    test_oauth_wire_errors_duplicates_and_session_cookie_revocation_rejection,
)

from tests.integration.test_security_revision_pg import (  # noqa: F401
    test_password_change_revokes_refresh_and_userinfo_preserves_current_session,
    test_mfa_step_is_consumed_once_and_reset_invalidates_it,
    test_security_event_and_session_issue_are_serialized,
)

from tests.integration.test_verified_email_policy_pg import (  # noqa: F401
    test_required_email_rejects_password_before_mfa_and_session,
    test_required_email_rejects_legacy_refresh_access_and_code_issue,
)

from tests.integration.test_email_identity_uniqueness_pg import (  # noqa: F401
    test_user_and_admin_email_changes_bind_verification_to_exact_address,
    test_two_confirmations_cannot_assign_the_same_email_or_leak_integrity_error,
)

from tests.integration.test_reauthentication_pg import (  # noqa: F401
    test_pending_totp_preserves_active_factor_and_checks_session,
)

from tests.integration.test_distributed_auth_quota_pg import (  # noqa: F401
    test_two_process_login_quota_survives_failed_password_rollback,
)

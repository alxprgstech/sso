# Повтор исходных аудиторских проб

Исходный `test_readiness_probes.py` сохранён побайтно как [readiness_probes_baseline.py](readiness_probes_baseline.py). Он описывает старую схему и содержит явно обозначенные unit doubles. Они не способны доказать новые транзакции, distributed quotas, security revision и session binding. Архив не входит в discovery `test_*.py`; это сохранение исходного воспроизведения, а не удаление обязательной проверки.

Текущий [test_readiness_probes.py](test_readiness_probes.py) запускает те же безопасные критерии через постоянные тесты из `tests/`, которые обязательны в CI. Криптография реальная; для lifecycle используется PostgreSQL с неизменённой проверкой marker. JWKS transport в unit подаёт настоящие публичные ключи, не заменяет проверку подписи. Для негативных JWT используются все остальные корректные claims, чтобы отказ не объяснялся посторонней недостающей claim. `auth_time` обязателен в проверке SDK при запрошенном `max_age`; это явно отражено в тесте.

Команда из корня: `python -m pytest -p tests.conftest docs/audit/test_readiness_probes.py -v`. Нужны закреплённые зависимости и выделенная `TEST_DATABASE_URL` со штатным marker; используется общий `pytest.ini`. Эти результаты пересекаются с full suite и не прибавляются к нему как независимые проверки.

| Исходная функция | Постоянная регрессия / критерий |
| --- | --- |
| `test_real_crypto_rejects_adversarial_access_token` | `tests/test_audit_crypto_regressions.py`: все восемь исходных атак, server и SDK |
| `test_real_crypto_accepts_valid_access_and_nonce_id` | тот же файл: положительный реальный RSA и отказ неверного nonce |
| `test_production_rejects_missing_signing_key` | `test_production_keys.py::test_production_rejects_unsafe_config`, отдельный missing key case |
| `test_production_rejects_excess_access_ttl` | тот же parametrized config test, TTL301 и0 |
| `test_pkce_rejects_one_character_verifier` | `test_signed_token_profiles.py::test_pkce_rejects_invalid_syntax_even_when_digest_matches`, verifier `a` |
| `test_server_requires_expiration` | `test_missing_access_claims_rejected_by_server_and_independent_sdk[exp]` |
| `test_sdk_requires_iat_in_id_token` | `test_audit_crypto_regressions.py::test_sdk_requires_complete_id_token_profile[iat]` |
| `test_sdk_rejects_wrong_azp_for_multiple_audiences` | `test_signed_token_profiles.py::test_id_azp_nonce_age_and_access_scope_guard` |
| `test_sdk_preserves_scope_for_resource_authorization` | тот же guard и положительный audit crypto test |
| `test_untrusted_kid_type_returns_4xx` | `test_production_keys.py::test_hostile_key_identifier_has_controlled_failure`; SDK malformed header не вызывает fetch |
| `test_oauth_missing_grant_uses_protocol_error` | `integration/test_oidc_contract_remediation_pg.py::test_oauth_wire_errors_duplicates_and_session_cookie_revocation_rejection` |
| `test_token_response_disables_caching` | `test_prompt_login_demands_new_password_authentication_once`: действительный token exchange, no-store |
| `test_authorize_honors_prompt` | тот же тест и `test_prompt_none_and_client_scope_policy`; browser `protocol_lifecycle.spec.ts` дополнительно max_age0 |
| `test_repeated_failed_login_is_throttled` | `integration/test_distributed_auth_quota_pg.py::test_two_process_login_quota_survives_failed_password_rollback` |
| `test_totp_setup_does_not_disable_existing_factor` | `integration/test_reauthentication_pg.py::test_pending_totp_preserves_active_factor_and_checks_session` |
| `test_password_change_revokes_refresh_and_authorization_codes` | `integration/test_security_revision_pg.py::test_password_change_revokes_refresh_and_userinfo_preserves_current_session` |
| `test_required_email_checked_before_mfa_step` | `integration/test_verified_email_policy_pg.py::test_required_email_rejects_password_before_mfa_and_session` |
| `test_admin_email_change_clears_verification` | `integration/test_email_identity_uniqueness_pg.py::test_user_and_admin_email_changes_bind_verification_to_exact_address` |
| `test_mfa_step_invalidated_after_password_change` | `integration/test_security_revision_pg.py::test_mfa_step_is_consumed_once_and_reset_invalidates_it` |
| `test_revoke_does_not_delete_unbound_sso_session` | реальный HTTP/PG wire test с текущим cookie secret и последующим me200 |
| `test_cors_production_does_not_trust_local_origins` | `tests/test_production_origin_policy.py`: реальные production Settings и CORS ASGI/точный allowlist; источник main policy |
| `test_missing_secret_cannot_survive_production_config` | `test_production_rejects_unsafe_config`: empty/default session/TOTP cases |
| `test_rp_logout_accepts_post` | `integration/test_oidc_contract_remediation_pg.py::test_logout_post_with_expired_current_hint_and_hintless_confirmation` |
| `test_rp_logout_can_terminate_current_session_with_expired_hint` | тот же реальный expired-signed hint/current-session case, me401 |
| `test_production_missing_key_stays_stable_across_worker_restart` | исходная безопасная цель уточнена: missing key запрещён, существующий постоянный key одинаков в независимых workers/restart (`test_workers_and_restart_share_persistent_key`) |
| `test_refresh_after_password_change_is_rejected` | реальный revision/password test плюс `integration/test_security_event_races_pg.py` оба порядка row locks |
| `test_smtp_starttls_checks_peer_certificate` | `test_smtp_tls.py`: настоящие loopback TLS trusted/untrusted/hostname/unavailable, AUTH только после verified TLS |
| `test_required_email_applies_to_existing_grant_token_issue` | `integration/test_verified_email_policy_pg.py::test_required_email_rejects_legacy_refresh_access_and_code_issue` |

Положительные и отрицательные assertions сохранены по смыслу. Возникшие при переносе неверные тестовые предпосылки и failed попытки записываются в worklog; не меняют критерий безопасности. Окончательные команды и результаты находятся в новом re-audit и `docs/acceptance.md`.

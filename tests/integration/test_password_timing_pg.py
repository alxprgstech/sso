"""Bounded synthetic timing check; evidence of gross work equivalence, not a side-channel proof."""

import statistics
import time

import pytest
from app.config import Settings
from app.core.exceptions import AuthenticationException
from app.core.security import hash_password
from app.models.user import PasswordCredential, User
from app.services.auth_service import AuthService


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_existing_and_absent_account_have_comparable_real_hash_work(
    pg_session, record_testsuite_property
):
    password_hash = hash_password("TimingSyntheticPassword2026!")
    for index in range(8):
        user = User(username=f"timing_existing_{index}", email=f"timing{index}@example.test")
        user.password_credential = PasswordCredential(password_hash=password_hash)
        pg_session.add(user)
    await pg_session.commit()
    settings = Settings(_env_file=None, REQUIRE_VERIFIED_EMAIL=False)
    measured = {"existing": [], "absent": []}
    outward = set()
    # Distinct identifiers keep the measured scenario below the actual account
    # quotas; all sixteen requests remain below the configured source quota.
    for index in range(8):
        for kind in ("existing", "absent"):
            began = time.perf_counter()
            with pytest.raises(AuthenticationException) as failure:
                await AuthService.authenticate_user(
                    pg_session,
                    f"timing_{kind}_{index}",
                    "IncorrectSyntheticPassword2026!",
                    ip_address="198.51.100.85",
                    settings=settings,
                )
            measured[kind].append(time.perf_counter() - began)
            outward.add(
                (
                    failure.value.status_code,
                    failure.value.detail["error"],
                    failure.value.detail["detail"],
                )
            )
            await pg_session.rollback()
    assert len(outward) == 1
    medians = {kind: statistics.median(samples) for kind, samples in measured.items()}
    ratio = medians["existing"] / medians["absent"]
    for kind, median in medians.items():
        record_testsuite_property(kind + "_median_ms", round(median * 1000, 3))
    record_testsuite_property("median_ratio", round(ratio, 4))
    assert 0.2 < ratio < 5, "Gross existing/nonexistent work difference requires investigation"

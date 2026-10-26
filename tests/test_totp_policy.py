"""TOTP time-step policy: strictly increasing steps and bounded retry hints."""

from datetime import datetime, timezone

import pytest
from app.services.totp_service import replay_retry_after, totp_step_usable


@pytest.mark.parametrize(
    "matched,previous,expected",
    [
        (None, 10, False),
        (10, None, True),
        (9, 10, False),
        (10, 10, False),
        (11, 10, True),
    ],
)
def test_totp_step_usable_is_strictly_increasing(
    matched: int | None, previous: int | None, expected: bool
):
    assert totp_step_usable(matched, previous) is expected


def test_replay_retry_after_is_bounded_by_one_window():
    now = datetime.now(timezone.utc)
    current = int(now.timestamp()) // 30
    wait = replay_retry_after(current, 30, now)
    assert 0 <= wait <= 30
    # A code from an older window is spent, but the current code is available.
    assert replay_retry_after(current - 2, 30, now) == 0
    # A burned future step can push the usable window one full interval ahead.
    assert 0 <= replay_retry_after(current + 1, 30, now) <= 60

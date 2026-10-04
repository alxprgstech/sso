"""Complete application metadata and the externally provisioned test-marker boundary."""

from typing import Any

import app.models  # noqa: F401 — Explicitly register all application tables.
from app.database import Base

target_metadata = Base.metadata


def include_object(obj: Any, name: str, type_: str, reflected: bool, compare_to: Any) -> bool:
    # Owned by tests.db_guard/provisioning, never by application migrations.
    # No application table/index/constraint is exempted from drift detection.
    return not (
        type_ == "table" and name == "test_database_marker" and reflected and compare_to is None
    )

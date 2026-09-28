"""Preflight safety checks: no database connection is allowed for invalid input."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.init_fresh_ci_test_marker import main as init_ci_marker
from tests.test_ops_backup_restore_totp import (
    OpsSafetyError,
    create_owned,
    drop_owned,
    parse_test_url,
    run_checked,
    verify_base,
)


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "not a URL",
        "sqlite:///ops_test",
        "postgresql+psycopg://user:secret@localhost:5432/sso_db",
        "postgresql+psycopg://user:secret@localhost:5432/postgres",
        "postgresql+psycopg://user:secret@localhost:5432/custom_database",
        "postgresql+psycopg://user:secret@localhost/ops_test",
        "postgresql+psycopg://user:secret@localhost:5432/ops_test?service=other",
    ],
)
def test_invalid_test_dsn_rejected_without_connection(
    raw: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    connection = MagicMock(side_effect=AssertionError("Unexpected SQL connection"))
    monkeypatch.setattr("tests.test_ops_backup_restore_totp.psycopg.connect", connection)
    with pytest.raises(OpsSafetyError) as exc:
        parse_test_url(raw)
    assert "secret" not in str(exc.value)
    connection.assert_not_called()


def test_valid_explicit_test_dsn() -> None:
    url = parse_test_url("postgresql+psycopg://user:secret@localhost:5432/ops_test")
    assert url.database == "ops_test"


def test_ci_marker_refuses_a_different_server_before_sql(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://sso_user@remote.example:5432/alxprgs_sso_test",
    )
    connection = MagicMock(side_effect=AssertionError("Unexpected SQL connection"))
    monkeypatch.setattr("scripts.init_fresh_ci_test_marker.psycopg.connect", connection)
    with pytest.raises(OpsSafetyError, match="dedicated local test service"):
        init_ci_marker([])
    connection.assert_not_called()


@pytest.mark.parametrize("marker_exists,has_user_data", [(True, False), (False, True)])
def test_ci_marker_refuses_existing_marker_or_data_before_write(
    monkeypatch: pytest.MonkeyPatch, marker_exists: bool, has_user_data: bool
) -> None:
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://sso_user@localhost:5432/alxprgs_sso_test",
    )

    class ExistingDatabase:
        def __init__(self) -> None:
            self.statements: list[str] = []
            self.row: tuple | None = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            statement = str(query)
            self.statements.append(statement)
            if "current_database()" in statement:
                self.row = ("alxprgs_sso_test",)
            elif "to_regclass" in statement:
                self.row = ("test_database_marker" if marker_exists else None,)
            elif "system_configuration" in statement:
                self.row = (False, "closed")
            elif "SELECT EXISTS" in statement:
                self.row = (has_user_data,)
            return self

        def fetchone(self):
            return self.row

        def fetchall(self):
            return [
                (name,)
                for name in (
                    "users",
                    "sessions",
                    "oidc_clients",
                    "system_configuration",
                    "alembic_version",
                )
            ]

    database = ExistingDatabase()
    monkeypatch.setattr(
        "scripts.init_fresh_ci_test_marker.psycopg.connect", lambda *a, **k: database
    )
    with pytest.raises(OpsSafetyError):
        init_ci_marker([])
    assert all(
        not sql.lstrip().upper().startswith(("CREATE", "INSERT", "UPDATE", "DELETE"))
        for sql in database.statements
    )


def test_preexisting_database_rejected_before_create() -> None:
    admin = MagicMock()
    rows = iter([("postgres",), ("127.0.0.1", 5432, "start"), (True,)])
    admin.execute.side_effect = lambda *args, **kwargs: MagicMock(fetchone=lambda: next(rows))
    base = parse_test_url("postgresql+psycopg://user:secret@localhost:5432/ops_test")
    created: set[str] = set()
    with pytest.raises(OpsSafetyError, match="already exists"):
        create_owned(
            admin,
            base,
            "ops_test_existing",
            "ops_source_owner",
            "run-id",
            created,
            ("127.0.0.1", 5432, "start"),
        )
    assert created == set()
    assert all("CREATE DATABASE" not in str(call) for call in admin.execute.call_args_list)


def test_partial_create_tracks_own_database_and_never_drops_it_implicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = FakeConnection(database="postgres", database_exists=False)
    base = parse_test_url("postgresql+psycopg://user:secret@localhost:5432/ops_test")
    created: set[str] = set()

    def marker_setup_failure(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic marker setup failure")

    monkeypatch.setattr("tests.test_ops_backup_restore_totp.psycopg.connect", marker_setup_failure)
    with pytest.raises(RuntimeError, match="marker setup failure"):
        create_owned(
            admin,
            base,
            "ops_test_partial",
            "ops_source_owner",
            "run-id",
            created,
            ("127.0.0.1", 5432, "start"),
        )
    assert created == {"ops_test_partial"}
    assert not any("DROP DATABASE" in statement for statement in admin.statements)


class FakeConnection:
    def __init__(
        self,
        *,
        database: str,
        marker_row=("run-id", "ops_test_dst"),
        marker_exists=True,
        connections=0,
        fail_drop=False,
        database_exists=True,
    ):
        self.database = database
        self.marker_row = marker_row
        self.marker_exists = marker_exists
        self.connections = connections
        self.fail_drop = fail_drop
        self.database_exists = database_exists
        self.statements: list[str] = []
        self.last: tuple | None = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def execute(self, query, params=None):
        statement = str(query)
        self.statements.append(statement)
        if "DROP DATABASE" in statement and self.fail_drop:
            raise RuntimeError("DROP failed")
        if "current_database()" in statement:
            self.last = (self.database,)
        elif "inet_server_addr()" in statement:
            self.last = ("127.0.0.1", 5432, "start")
        elif "pg_database" in statement:
            self.last = (self.database_exists,)
        elif "to_regclass" in statement:
            self.last = ("marker" if self.marker_exists else None,)
        elif "SELECT run_id" in statement:
            self.last = self.marker_row
        elif "pg_stat_activity" in statement:
            self.last = (self.connections,)
        return self

    def fetchone(self):
        return self.last


@pytest.mark.parametrize(
    "marker_row,marker_exists,connections",
    [
        (("foreign", "ops_test_dst"), True, 0),
        (("run-id", "other_db"), True, 0),
        (("run-id", "ops_test_dst"), False, 0),
        (("run-id", "ops_test_dst"), True, 1),
    ],
)
def test_cleanup_preserves_unowned_or_busy_database(
    marker_row: tuple[str, str],
    marker_exists: bool,
    connections: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = FakeConnection(database="postgres", connections=connections)
    target = FakeConnection(
        database="ops_test_dst", marker_row=marker_row, marker_exists=marker_exists
    )
    monkeypatch.setattr(
        "tests.test_ops_backup_restore_totp.psycopg.connect", lambda *a, **k: target
    )
    base = parse_test_url("postgresql+psycopg://user:secret@localhost:5432/ops_test")
    with pytest.raises(OpsSafetyError):
        drop_owned(
            admin, base, "ops_test_dst", "ops_restore_owner", "run-id", ("127.0.0.1", 5432, "start")
        )
    assert not any("DROP DATABASE" in statement for statement in admin.statements)


def test_cleanup_failure_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = FakeConnection(database="postgres", fail_drop=True)
    target = FakeConnection(database="ops_test_dst")
    monkeypatch.setattr(
        "tests.test_ops_backup_restore_totp.psycopg.connect", lambda *a, **k: target
    )
    base = parse_test_url("postgresql+psycopg://user:secret@localhost:5432/ops_test")
    with pytest.raises(RuntimeError, match="DROP failed"):
        drop_owned(
            admin, base, "ops_test_dst", "ops_restore_owner", "run-id", ("127.0.0.1", 5432, "start")
        )


@pytest.mark.parametrize("marker_exists,marker_row", [(False, None), (True, ("foreign", True))])
def test_base_marker_missing_or_foreign_rejected_read_only(
    monkeypatch: pytest.MonkeyPatch, marker_exists: bool, marker_row: tuple | None
) -> None:
    class BaseConnection:
        def __init__(self):
            self.statements: list[str] = []
            self.last: tuple | None = None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def execute(self, query, params=None):
            statement = str(query)
            self.statements.append(statement)
            if "current_database()" in statement:
                self.last = ("ops_test",)
            elif "to_regclass" in statement:
                self.last = ("marker",) if marker_exists else (None,)
            else:
                self.last = marker_row
            return self

        def fetchone(self):
            return self.last

    connection = BaseConnection()
    monkeypatch.setattr(
        "tests.test_ops_backup_restore_totp.psycopg.connect", lambda *a, **k: connection
    )
    base = parse_test_url("postgresql+psycopg://user:secret@localhost:5432/ops_test")
    with pytest.raises(OpsSafetyError):
        verify_base(base)
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement in connection.statements
    )


def test_failed_backup_or_restore_command_is_visible(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "tests.test_ops_backup_restore_totp.subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 3, b"", b"private error"),
    )
    with pytest.raises(OpsSafetyError, match="exit 3") as error:
        run_checked(["psql", "-X"], env={}, cwd=Path("."))
    assert "private error" not in str(error.value)

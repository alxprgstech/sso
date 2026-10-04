"""Ignored runtime captures are distinct from tracked/new repository source."""

import subprocess

from scripts import scan_secrets_and_deps


def test_scan_includes_new_and_tracked_ignored_paths_without_reading_runtime_artifacts(
    tmp_path, monkeypatch
):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    tracked = tmp_path / "node_modules/tracked.py"
    tracked.parent.mkdir()
    token = "ghp_" + "A" * 36
    tracked.write_text(f'value="{token}"\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "node_modules/tracked.py"], cwd=tmp_path, check=True, capture_output=True
    )
    (tmp_path / ".gitignore").write_text("node_modules/\nartifacts/\n", encoding="utf-8")
    local = tmp_path / "artifacts/runtime.py"
    local.parent.mkdir()
    local.write_text(f'value="{token}"\n', encoding="utf-8")
    (tmp_path / "new.py").write_text(f'value="{token}"\n', encoding="utf-8")
    monkeypatch.setattr(scan_secrets_and_deps, "ROOT_DIR", str(tmp_path))
    errors = scan_secrets_and_deps.check_secrets_in_code()
    assert len(errors) == 2
    assert any("node_modules/tracked.py" in error for error in errors)
    assert any("new.py" in error for error in errors)
    assert not any("runtime.py" in error or token in error for error in errors)


def test_non_key_parser_fixture_does_not_exempt_other_key_headers(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    header = "-----BEGIN " + "PRIVATE KEY-----"
    (tmp_path / "parser.py").write_text(f'value="{header}\\nmalformed"\n', encoding="utf-8")
    (tmp_path / "suspect.py").write_text(f'value="{header}\\n{"A" * 80}"\n', encoding="utf-8")
    monkeypatch.setattr(scan_secrets_and_deps, "ROOT_DIR", str(tmp_path))
    errors = scan_secrets_and_deps.check_secrets_in_code()
    assert len(errors) == 1 and "suspect.py" in errors[0]

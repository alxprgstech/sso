"""Strict server result protocol; human text is never treated as success."""

import json

import pytest

from scripts import deploy_result

SHA = "a" * 40
SEQUENCE = 42


def protocol(result, *, sha=SHA, sequence=SEQUENCE, version=1):
    return deploy_result.PROTOCOL_PREFIX + json.dumps(
        {"version": version, "result": result, "sha": sha, "sequence": sequence}
    )


def test_deployed_result_marks_installed_only_after_new_installation():
    parsed = deploy_result.parse_server_output(protocol("deployed"), SHA, SEQUENCE)
    assert parsed.result == "deployed"
    assert parsed.installed is True
    assert parsed.sha == SHA
    assert parsed.legacy is False


def test_already_deployed_result_does_not_mark_installed():
    parsed = deploy_result.parse_server_output(protocol("already_deployed"), SHA, SEQUENCE)
    assert parsed.result == "already_deployed"
    assert parsed.installed is False
    assert parsed.legacy is False


def test_legacy_operator_is_explicit_and_never_silently_protocol_compatible():
    parsed = deploy_result.parse_server_output(
        f"Deployed {SHA}; sequence {SEQUENCE}\n", SHA, SEQUENCE
    )
    assert parsed.result == "deployed_legacy"
    assert parsed.installed is True  # The old success path always installed.
    assert parsed.legacy is True
    assert "legacy operator" in parsed.reason


def test_protocol_ignores_unrelated_server_output():
    raw = f"random banner\n{protocol('deployed')}\ntrailing text\n"
    assert deploy_result.parse_server_output(raw, SHA, SEQUENCE).result == "deployed"


@pytest.mark.parametrize(
    "raw",
    [
        protocol("deployed") + "\n" + protocol("deployed"),
        protocol("unknown"),
        protocol("deployed", sha="b" * 40),
        protocol("deployed", sequence=SEQUENCE + 1),
        protocol("deployed", version=2),
        deploy_result.PROTOCOL_PREFIX + "not-json",
        deploy_result.PROTOCOL_PREFIX + "[]",
        deploy_result.PROTOCOL_PREFIX
        + json.dumps({"version": 1, "result": "deployed", "sha": SHA}),
        deploy_result.PROTOCOL_PREFIX
        + json.dumps({"version": True, "result": "deployed", "sha": SHA, "sequence": SEQUENCE}),
        deploy_result.PROTOCOL_PREFIX
        + json.dumps({"version": 1, "result": 1, "sha": SHA, "sequence": SEQUENCE}),
        deploy_result.PROTOCOL_PREFIX
        + json.dumps({"version": 1, "result": "deployed", "sha": "ABC", "sequence": SEQUENCE}),
        deploy_result.PROTOCOL_PREFIX
        + json.dumps({"version": 1, "result": "deployed", "sha": SHA, "sequence": "42"}),
    ],
)
def test_malformed_protocol_is_a_hard_error(raw):
    with pytest.raises(deploy_result.ProtocolError):
        deploy_result.parse_server_output(raw, SHA, SEQUENCE)


def test_human_success_similar_to_protocol_is_not_parsed():
    raw = f"SSOCTL-RESULT: {protocol('deployed')}\nDeployed {SHA}; sequence {SEQUENCE}\n"
    parsed = deploy_result.parse_server_output(raw, SHA, SEQUENCE)
    assert parsed.result == "deployed_legacy"


def test_cli_writes_outputs_and_fails_closed_on_malformed_protocol(tmp_path, monkeypatch, capsys):
    output = tmp_path / "github-output"
    monkeypatch.setattr(
        "sys.stdin",
        type("Input", (), {"read": lambda _: protocol("already_deployed")})(),
    )
    assert (
        deploy_result.main(
            [
                "--sha",
                SHA,
                "--sequence",
                str(SEQUENCE),
                "--github-output",
                str(output),
            ]
        )
        == 0
    )
    text = output.read_text()
    assert "result=already_deployed" in text
    assert "installed=false" in text
    assert f"installed_sha={SHA}" in text

    output.unlink()
    monkeypatch.setattr(
        "sys.stdin",
        type("Input", (), {"read": lambda _: "ssoctl-result:{"})(),
    )
    assert (
        deploy_result.main(
            [
                "--sha",
                SHA,
                "--sequence",
                str(SEQUENCE),
                "--github-output",
                str(output),
            ]
        )
        == 1
    )
    assert "protocol failed" in capsys.readouterr().err
    assert not output.exists()

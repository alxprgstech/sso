"""OEM localized native output must not corrupt ownership/PID safety under UTF-8 Python."""

from types import SimpleNamespace

from scripts import manage_test_server


def test_windows_netstat_uses_structural_ascii_fields(monkeypatch):
    monkeypatch.setattr(manage_test_server.sys, "platform", "win32")
    native = "Активные подключения\r\n  TCP    127.0.0.1:5173    0.0.0.0:0    LISTENING    12345\r\n".encode(
        "cp866"
    )
    monkeypatch.setattr(
        manage_test_server.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout=native, returncode=0),
    )
    assert manage_test_server.get_pid_listening_on_port(5173) == 12345
    assert manage_test_server.get_pid_listening_on_port(5174) is None


def test_windows_tasklist_localized_missing_pid_is_safe(tmp_path, monkeypatch):
    monkeypatch.setattr(manage_test_server.sys, "platform", "win32")
    monkeypatch.setattr(manage_test_server, "get_pid_listening_on_port", lambda *args: None)
    monkeypatch.setattr(manage_test_server, "is_port_in_use", lambda *args: False)
    commands = []

    def native(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(
            returncode=0, stdout="Нет задач, отвечающих заданным критериям.".encode("cp866")
        )

    monkeypatch.setattr(manage_test_server.subprocess, "run", native)
    pidfile = tmp_path / "тест.pid"
    pidfile.write_text("12345", encoding="utf-8")
    assert manage_test_server.stop_server(str(pidfile), port=5173) == 0
    assert not pidfile.exists()
    assert ["tasklist", "/FI", "PID eq 12345", "/FO", "CSV", "/NH"] in commands

"""
ALXPRGS SSO - Тесты критериев надежности раннера кампании стабильности (GOAL-07).
Проверяют:
1. Корректность и строгость оценки критериев evaluate_soak_criteria (защита от ложноположительного отчета).
2. Отказ при досрочном завершении (<95% целевой длительности).
3. Отказ при недостаточном числе точек телеметрии (<90% ожидаемого).
4. Отказ при любых непредвиденных ошибках (unexpected_errors > 0).
5. Отказ при падении или пропуске Chromium smoke-теста.
6. Отказ при невосстановлении пула соединений PostgreSQL (cool-down).
7. Отказ при утечке портов (backend/frontend port busy).
8. Отказ при некорректных/заниженных показаниях памяти бэкенда (RSS <= 10 МБ).
9. Семантика параметра --race-attempts: выполнение заданного числа попыток для каждого сценария.
"""

from __future__ import annotations

import unittest.mock
from typing import Any

from scripts.run_overnight_stability import evaluate_soak_criteria, run_race_stage


def _make_valid_telemetry(count: int = 40, be_rss: float = 91.5) -> list[dict[str, Any]]:
    return [
        {
            "sample": i,
            "elapsed_sec": i * 30.0,
            "backend_rss_mb": be_rss,
            "frontend_rss_mb": 45.0,
            "pg_connections": 3,
            "total_ops": i * 8,
            "unexpected_errors": 0,
        }
        for i in range(1, count + 1)
    ]


def test_criteria_passes_when_all_conditions_met():
    """Этап soak должен считаться пройденным при соблюдении всех требований."""
    reasons = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40, be_rss=92.0),
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=4,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert reasons == [], f"Expected pass, got reasons: {reasons}"


def test_criteria_rejects_early_termination():
    """Досрочное завершение (<95% целевого времени) должно приводить к отказу."""
    reasons = evaluate_soak_criteria(
        duration_achieved_sec=1100.0,  # 1100 < 1140 (95% от 1200)
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40),
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=3,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert any("Early termination" in r for r in reasons)


def test_criteria_rejects_insufficient_samples():
    """Недостаточное число сэмплов (<90% ожидаемого) должно приводить к отказу."""
    reasons = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(30),  # 30 < 36 (90% от 40)
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=3,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert any("Insufficient telemetry samples" in r for r in reasons)


def test_criteria_rejects_unexpected_errors():
    """Наличие unexpected_errors > 0 должно приводить к отказу."""
    reasons = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40),
        expected_samples=40,
        unexpected_errors=1,
        browser_smoke_runs=3,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert any("Unexpected operational errors: 1" in r for r in reasons)


def test_criteria_rejects_browser_smoke_failure():
    """Сбой браузерного smoke-теста должен приводить к отказу."""
    reasons = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40),
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=3,
        browser_smoke_failed=1,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert any("Browser smoke test failures: 1" in r for r in reasons)


def test_criteria_rejects_missing_browser_smoke_long_run():
    """Отсутствие браузерного теста при длительности >=5 мин должно приводить к отказу."""
    reasons = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40),
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=0,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert any("Browser smoke tests were never executed" in r for r in reasons)


def test_criteria_rejects_unrecovered_pg_connections():
    """Невосстановленный пул соединений PostgreSQL после остановки серверов должен приводить к отказу."""
    reasons = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40),
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=3,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=5,  # Пул не очищен (5 > 2 + 1)
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert any("PostgreSQL connection pool not recovered" in r for r in reasons)


def test_criteria_rejects_port_leaks():
    """Утечка порта (бэкенда или фронтенда) должна приводить к отказу."""
    reasons_be = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40),
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=3,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=True,
        frontend_port_busy=False,
    )
    assert any("Port leak detected" in r for r in reasons_be)

    reasons_fe = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40),
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=3,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=True,
    )
    assert any("Port leak detected" in r for r in reasons_fe)


def test_criteria_rejects_low_or_zero_backend_rss():
    """Заниженный RSS бэкенда (<=10 МБ, свидетельство замера оберточного процесса) должен приводить к отказу."""
    reasons_low = evaluate_soak_criteria(
        duration_achieved_sec=1200.0,
        target_duration_sec=1200.0,
        telemetry_records=_make_valid_telemetry(40, be_rss=4.5),  # Заниженный замер
        expected_samples=40,
        unexpected_errors=0,
        browser_smoke_runs=3,
        browser_smoke_failed=0,
        pg_baseline=2,
        pg_final=2,
        backend_port_busy=False,
        frontend_port_busy=False,
    )
    assert any("Backend RSS suspiciously low" in r for r in reasons_low)


def test_race_attempts_parameter_semantics():
    """Проверка семантики параметра attempts: N попыток на КАЖДЫЙ сценарий матрицы."""
    mock_pytest_out = (
        "tests/integration/test_concurrency_pg.py::test_concurrent_auth_code_redemption_pg PASSED\n"
        "tests/integration/test_concurrency_pg.py::test_concurrent_user_registration_race_pg PASSED\n"
        "tests/integration/test_concurrency_pg.py::test_concurrent_recovery_code_burn_pg PASSED\n"
        "tests/integration/test_concurrency_pg.py::test_concurrent_refresh_token_rotation_and_replay_pg PASSED\n"
        "tests/integration/test_concurrency_pg.py::test_distributed_rate_limiting_registration_pg PASSED\n"
    )

    with (
        unittest.mock.patch("subprocess.run") as mock_run,
        unittest.mock.patch("psycopg.connect") as mock_conn_ctx,
    ):
        mock_proc = unittest.mock.MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = mock_pytest_out
        mock_proc.stderr = ""
        mock_run.return_value = mock_proc

        mock_cur = unittest.mock.MagicMock()
        # 1. ungranted_locks = 0, 2. system_configuration = (1, True, 'closed'), 3. replay_audits = 10
        mock_cur.fetchone.side_effect = [
            (0,),
            (1, True, "closed"),
            (10,),
        ]
        mock_conn = unittest.mock.MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn_ctx.return_value = mock_conn

        # Запускаем с attempts=3
        res = run_race_stage(
            attempts=3, test_db_url="postgresql+psycopg://test:test@localhost:5433/test"
        )

        assert res["status"] == "passed"
        assert res["attempts_per_scenario"] == 3
        assert res["iterations_completed"] == 3
        assert res["pg_state_verified"] is True

        for scen, counts in res["results"].items():
            assert counts["passed"] == 3, (
                f"Scenario {scen} expected 3 passes, got {counts['passed']}"
            )
            assert counts["failed"] == 0

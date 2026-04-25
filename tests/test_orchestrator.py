"""Tests for a_sdlc.orchestrator."""

from unittest.mock import ANY, patch

import pytest

from a_sdlc.orchestrator import main


@pytest.fixture
def mock_executor():
    with patch("a_sdlc.orchestrator.Executor") as m:
        yield m


@pytest.fixture
def mock_load_config():
    with patch("a_sdlc.orchestrator.load_daemon_config") as m:
        m.return_value = {"notifications": []}
        yield m


@pytest.fixture
def mock_update_run():
    with patch("a_sdlc.orchestrator._update_run") as m:
        yield m


@pytest.fixture
def mock_read_run():
    with patch("a_sdlc.executor._read_run") as m:
        yield m


def test_orchestrator_main_success(mock_executor, mock_load_config, mock_update_run):
    """Verify orchestrator main loop success path."""
    mock_instance = mock_executor.return_value
    mock_instance.execute_objective.return_value = {"status": "completed", "completed": 3}

    with (
        patch("sys.argv", ["orchestrator", "--run-id", "R1", "--goal", "test goal"]),
        patch("a_sdlc.notifications.run_notification_hooks") as mock_notify,
    ):
        main()

    # Verify run state updates
    assert mock_update_run.call_count >= 2
    mock_update_run.assert_any_call("R1", pid=ANY, status="running")
    mock_update_run.assert_any_call("R1", status="completed", outcome={"status": "completed", "completed": 3})

    # Verify notification triggered
    mock_notify.assert_called_once_with("R1", {"status": "completed", "completed": 3}, mock_load_config.return_value)


def test_orchestrator_reads_goal_from_run_state(mock_executor, mock_load_config, mock_update_run, mock_read_run):
    """Verify orchestrator reads goal from run state if not on CLI."""
    mock_read_run.return_value = {"description": "saved goal"}
    mock_instance = mock_executor.return_value
    mock_instance.execute_objective.return_value = {"status": "completed"}

    with (
        patch("sys.argv", ["orchestrator", "--run-id", "R2"]),
        patch("a_sdlc.notifications.run_notification_hooks"),
    ):
        main()

    mock_instance.execute_objective.assert_called_once()
    assert mock_instance.execute_objective.call_args.kwargs["description"] == "saved goal"


def test_orchestrator_fails_if_no_goal(mock_executor, mock_load_config, mock_update_run, mock_read_run):
    """Verify orchestrator exits if no goal provided or found."""
    mock_read_run.return_value = None

    with (
        patch("sys.argv", ["orchestrator", "--run-id", "R3"]),
        pytest.raises(SystemExit) as exc,
    ):
        main()

    assert exc.value.code == 1
    mock_update_run.assert_any_call("R3", status="failed", error="Missing goal description")


def test_orchestrator_exception_handling(mock_executor, mock_load_config, mock_update_run):
    """Verify orchestrator marks run as failed on exception."""
    mock_instance = mock_executor.return_value
    mock_instance.execute_objective.side_effect = RuntimeError("boom")

    with (
        patch("sys.argv", ["orchestrator", "--run-id", "R4", "--goal", "fail me"]),
        pytest.raises(SystemExit) as exc,
    ):
        main()

    assert exc.value.code == 1
    mock_update_run.assert_any_call("R4", status="failed", error="boom")

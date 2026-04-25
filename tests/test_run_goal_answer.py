
import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from a_sdlc.cli import main


@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    runs.mkdir()
    monkeypatch.setattr("a_sdlc.executor._RUNS_DIR", runs)
    return runs

def test_run_goal_spawns_orchestrator(runner, runs_dir):
    with patch("subprocess.Popen") as mock_popen, \
         patch("shutil.which", return_value="/usr/local/bin/claude"):

        mock_popen.return_value = MagicMock(pid=12345)

        result = runner.invoke(main, ["run", "goal", "Add JWT auth", "--max-concurrency", "5"])

        assert result.exit_code == 0
        assert "Goal execution started!" in result.output
        assert "Run ID:" in result.output
        assert "PID:           12345" in result.output

        # Verify run state file
        run_files = list(runs_dir.glob("R-*.json"))
        assert len(run_files) == 1
        with open(run_files[0]) as f:
            data = json.load(f)
            assert data["type"] == "pipeline"
            assert data["goal"] == "Add JWT auth"
            assert data["max_concurrency"] == 5
            assert data["status"] == "running"

        # Verify subprocess call
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        cmd = args[0]
        assert "a_sdlc.orchestrator" in cmd
        assert "--run-id" in cmd
        assert "--max-concurrency" in cmd
        assert "5" in cmd

def test_run_answer_updates_state(runner, runs_dir):
    # Create a mock run state file awaiting clarification
    run_id = "R-test1234"
    run_file = runs_dir / f"{run_id}.json"
    initial_data = {
        "run_id": run_id,
        "type": "pipeline",
        "status": "awaiting_clarification",
        "answers": []
    }
    with open(run_file, "w") as f:
        json.dump(initial_data, f)

    result = runner.invoke(main, ["run", "answer", run_id, "-m", "use RS256"])

    assert result.exit_code == 0
    assert f"Answer provided. Run {run_id} resumed." in result.output

    with open(run_file) as f:
        data = json.load(f)
        assert data["status"] == "running"
        assert len(data["answers"]) == 1
        assert data["answers"][0]["message"] == "use RS256"

def test_run_control_updates_state(runner, runs_dir):
    run_id = "R-test5678"
    run_file = runs_dir / f"{run_id}.json"
    initial_data = {
        "run_id": run_id,
        "type": "pipeline",
        "status": "running",
        "controls": []
    }
    with open(run_file, "w") as f:
        json.dump(initial_data, f)

    result = runner.invoke(main, ["run", "control", "PROJ-T00001", "--action", "pause", "--run-id", run_id])

    assert result.exit_code == 0
    assert "Control action 'pause' issued for PROJ-T00001" in result.output

    with open(run_file) as f:
        data = json.load(f)
        assert len(data["controls"]) == 1
        assert data["controls"][0]["item_id"] == "PROJ-T00001"
        assert data["controls"][0]["action"] == "pause"

def test_run_comment_updates_state(runner, runs_dir):
    run_id = "R-test9012"
    run_file = runs_dir / f"{run_id}.json"
    initial_data = {
        "run_id": run_id,
        "type": "pipeline",
        "status": "running",
        "comments": []
    }
    with open(run_file, "w") as f:
        json.dump(initial_data, f)

    result = runner.invoke(main, ["run", "comment", "PROJ-P0001", "-m", "Focus on auth", "--run-id", run_id])

    assert result.exit_code == 0
    assert "Comment posted" in result.output # Note: the actual message might be different, let me check cli.py

    with open(run_file) as f:
        data = json.load(f)
        assert len(data["comments"]) == 1
        assert data["comments"][0]["artifact_id"] == "PROJ-P0001"
        assert data["comments"][0]["message"] == "Focus on auth"

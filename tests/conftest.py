"""Global test safety guards.

Prevents any test from accidentally spawning real Claude or Gemini CLI sessions,
which would consume API tokens. All subprocess calls with 'claude' or 'gemini'
in the command are blocked unless the caller has properly mocked subprocess.
"""

import subprocess

import pytest

_real_popen = subprocess.Popen
_real_run = subprocess.run


class _GuardPopen(_real_popen):
    """Popen subclass that blocks real claude/gemini CLI invocations during tests.

    Inherits from the real Popen so that ``subprocess.Popen[bytes]`` type
    annotations (used by the MCP library) remain valid.
    """

    def __init__(self, cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)):  # noqa: SIM108
            binary = str(cmd[0]) if cmd else ""
        else:
            binary = str(cmd)
        if "claude" in binary.lower() or "gemini" in binary.lower():
            raise RuntimeError(
                f"Test attempted to spawn a real CLI session: {cmd!r}. "
                "Ensure subprocess.Popen is properly mocked."
            )
        super().__init__(cmd, *args, **kwargs)


def _guard_run(cmd, *args, **kwargs):
    """Block real claude/gemini CLI invocations during tests."""
    if isinstance(cmd, (list, tuple)):  # noqa: SIM108
        binary = str(cmd[0]) if cmd else ""
    else:
        binary = str(cmd)
    if "claude" in binary.lower() or "gemini" in binary.lower():
        raise RuntimeError(
            f"Test attempted to spawn a real CLI session: {cmd!r}. "
            "Ensure subprocess.run is properly mocked."
        )
    return _real_run(cmd, *args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def _block_real_cli_sessions():
    """Global safety guard: prevent any test from spawning real Claude/Gemini sessions."""
    subprocess.Popen = _GuardPopen
    subprocess.run = _guard_run
    yield
    subprocess.Popen = _real_popen
    subprocess.run = _real_run

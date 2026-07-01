"""Tests for the local project-identity marker (.sdlc/project.json)."""

from pathlib import Path

import pytest

from a_sdlc.core.project_marker import (
    find_marker,
    find_root_for,
    read_marker,
    render_marker_content,
    write_marker,
)


def test_write_read_roundtrip(tmp_path: Path) -> None:
    write_marker(tmp_path, "proj-1", shortname="PRJ1", name="Project One")
    data = read_marker(tmp_path)
    assert data == {"id": "proj-1", "shortname": "PRJ1", "name": "Project One"}


def test_find_marker_walks_up(tmp_path: Path) -> None:
    write_marker(tmp_path, "proj-1", shortname="PRJ1", name="Project One")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    marker = find_marker(nested)
    assert marker is not None
    assert marker["id"] == "proj-1"
    assert Path(marker["root"]) == tmp_path.resolve()


def test_find_root_for_matches_id(tmp_path: Path) -> None:
    write_marker(tmp_path, "proj-1", shortname="PRJ1")
    assert find_root_for("proj-1", tmp_path) == tmp_path.resolve()
    assert find_root_for("other", tmp_path) is None


def test_read_marker_absent(tmp_path: Path) -> None:
    assert read_marker(tmp_path) is None


@pytest.mark.parametrize("bad_id", ["", "   ", "\n"])
def test_write_marker_rejects_empty_id(tmp_path: Path, bad_id: str) -> None:
    """An empty/whitespace id would write a marker that read_marker rejects,
    so writing must fail loudly instead of producing a silently-broken file."""
    with pytest.raises(ValueError, match="non-empty"):
        write_marker(tmp_path, bad_id)
    # Nothing should have been written.
    assert read_marker(tmp_path) is None


@pytest.mark.parametrize("bad_id", ["", "   "])
def test_render_marker_content_rejects_empty_id(bad_id: str) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        render_marker_content(bad_id)

"""Local project-identity marker (``.sdlc/project.json``).

Replaces the server-side ``projects.path`` column. A repository identifies its
a-sdlc project locally through this marker, so the shared database never stores
device-specific filesystem paths. This lets the same project be worked on from
multiple machines (or containers) against one central database without path
collisions.

Resolution walks up from a start directory to the nearest ``.sdlc/project.json``.
The marker records the project ``id`` (the DB primary key), plus ``shortname``
and ``name`` for display and for re-linking a fresh checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Marker location relative to a project root.
MARKER_RELPATH = Path(".sdlc") / "project.json"


def marker_path(project_root: Path | str) -> Path:
    """Return the marker path for a given project root."""
    return Path(project_root) / MARKER_RELPATH


def write_marker(
    project_root: Path | str,
    project_id: str,
    shortname: str | None = None,
    name: str | None = None,
) -> Path:
    """Write ``.sdlc/project.json`` under *project_root*.

    Creates the ``.sdlc`` directory if needed and returns the marker path.

    Raises:
        ValueError: if *project_id* is empty or whitespace-only. ``read_marker``
            rejects markers without a non-empty id, so writing one would appear
            to succeed while cwd-based resolution silently fails.
    """
    if not project_id or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    path = marker_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"id": project_id}
    if shortname is not None:
        payload["shortname"] = shortname
    if name is not None:
        payload["name"] = name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def read_marker(project_root: Path | str) -> dict[str, Any] | None:
    """Read the marker under *project_root*.

    Returns the parsed dict (guaranteed to contain a non-empty ``id``), or
    ``None`` when the marker is absent, unreadable, malformed, or missing an id.
    """
    path = marker_path(project_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("id"):
        return data
    return None


def render_marker_content(
    project_id: str,
    shortname: str | None = None,
    name: str | None = None,
) -> str:
    """Render marker file contents without writing to disk.

    Used by ``create_project()`` in remote deployments, where the server returns
    file specs for the client to write locally.

    Raises:
        ValueError: if *project_id* is empty or whitespace-only.
    """
    if not project_id or not project_id.strip():
        raise ValueError("project_id must be a non-empty string")
    payload: dict[str, Any] = {"id": project_id}
    if shortname is not None:
        payload["shortname"] = shortname
    if name is not None:
        payload["name"] = name
    return json.dumps(payload, indent=2) + "\n"


def find_marker(start: Path | str | None = None) -> dict[str, Any] | None:
    """Walk up from *start* (default cwd) to the nearest project marker.

    Returns the marker dict augmented with a ``root`` key (the project root
    directory as a string), or ``None`` when no marker is found in the tree.
    """
    base = (Path(start) if start is not None else Path.cwd()).resolve()
    for directory in [base, *base.parents]:
        data = read_marker(directory)
        if data:
            return {**data, "root": str(directory)}
    return None


def find_root_for(project_id: str, start: Path | str | None = None) -> Path | None:
    """Return the project root whose marker ``id`` matches *project_id*.

    Walks up from *start* (default cwd). Used to locate a project's on-disk
    ``.sdlc/artifacts`` directory when only the project id is known.
    """
    base = (Path(start) if start is not None else Path.cwd()).resolve()
    for directory in [base, *base.parents]:
        data = read_marker(directory)
        if data and data.get("id") == project_id:
            return directory
    return None

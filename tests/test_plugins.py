"""Tests for plugin system."""

from pathlib import Path

import pytest

from a_sdlc.artifacts.base import Artifact, ArtifactType
from a_sdlc.artifacts.local import LocalArtifactPlugin, remove_stale_markdown
from a_sdlc.plugins.base import Task, TaskPriority, TaskStatus


def test_task_dataclass() -> None:
    """Test Task dataclass creation."""
    task = Task(
        id="TASK-001",
        title="Test Task",
        description="A test task",
        status=TaskStatus.PENDING,
        priority=TaskPriority.HIGH,
    )

    assert task.id == "TASK-001"
    assert task.title == "Test Task"
    assert task.status == TaskStatus.PENDING
    assert task.priority == TaskPriority.HIGH


def test_task_to_dict() -> None:
    """Test Task serialization."""
    task = Task(
        id="TASK-001",
        title="Test Task",
        description="A test task",
    )

    data = task.to_dict()

    assert data["id"] == "TASK-001"
    assert data["title"] == "Test Task"
    assert data["status"] == "pending"
    assert data["priority"] == "medium"


def test_task_from_dict() -> None:
    """Test Task deserialization."""
    data = {
        "id": "TASK-001",
        "title": "Test Task",
        "description": "A test task",
        "status": "in_progress",
        "priority": "high",
        "created_at": "2025-01-21T12:00:00",
        "updated_at": "2025-01-21T12:00:00",
    }

    task = Task.from_dict(data)

    assert task.id == "TASK-001"
    assert task.status == TaskStatus.IN_PROGRESS
    assert task.priority == TaskPriority.HIGH


def test_task_from_dict_backward_compatibility() -> None:
    """Test Task deserialization with old format (plain string implementation_steps)."""
    data = {
        "id": "TASK-001",
        "title": "Test Task",
        "description": "A test task",
        "status": "pending",
        "priority": "medium",
        "implementation_steps": ["Step 1", "Step 2", "Step 3"],  # Old format: plain strings
        "created_at": "2025-01-21T12:00:00",
        "updated_at": "2025-01-21T12:00:00",
    }

    task = Task.from_dict(data)

    assert task.id == "TASK-001"
    assert len(task.implementation_steps) == 3
    # Should be converted to ImplementationStep objects
    assert task.implementation_steps[0].title == "Step 1"
    assert task.implementation_steps[0].description == ""


def test_task_from_dict_rich_implementation_steps() -> None:
    """Test Task deserialization with new format (rich implementation_steps)."""
    data = {
        "id": "TASK-001",
        "title": "Test Task",
        "description": "A test task",
        "status": "pending",
        "implementation_steps": [
            {
                "title": "Create config dataclass",
                "description": "Define configuration structure",
                "code_hint": "@dataclass\nclass Config:\n    pass",
                "test_expectation": "Config instantiates without errors",
            },
            {
                "title": "Add loader",
                "description": "Load from environment",
            },
        ],
        "goal": "Set up OAuth configuration",
        "prd_ref": "auth-feature.md",
        "key_requirements": ["Support Google OAuth", "Support GitHub OAuth"],
        "technical_notes": ["Use existing patterns", "Follow ConfigLoader"],
        "deliverables": ["OAuth config class", "Loader function"],
        "exclusions": ["UI changes", "Token refresh"],
        "scope_constraint": "Only modify auth module",
        "created_at": "2025-01-21T12:00:00",
        "updated_at": "2025-01-21T12:00:00",
    }

    task = Task.from_dict(data)

    assert task.id == "TASK-001"
    assert len(task.implementation_steps) == 2
    assert task.implementation_steps[0].title == "Create config dataclass"
    assert task.implementation_steps[0].code_hint == "@dataclass\nclass Config:\n    pass"
    assert task.implementation_steps[0].test_expectation == "Config instantiates without errors"
    assert task.implementation_steps[1].code_hint is None  # Optional field not provided

    # New fields
    assert task.goal == "Set up OAuth configuration"
    assert task.prd_ref == "auth-feature.md"
    assert len(task.key_requirements) == 2
    assert len(task.technical_notes) == 2
    assert len(task.deliverables) == 2
    assert len(task.exclusions) == 2
    assert task.scope_constraint == "Only modify auth module"


def test_task_to_dict_with_new_fields() -> None:
    """Test Task serialization includes new fields."""
    from a_sdlc.plugins.base import ImplementationStep

    task = Task(
        id="TASK-001",
        title="Test Task",
        description="A test task",
        goal="Achieve something",
        prd_ref="feature.md",
        key_requirements=["Req 1", "Req 2"],
        technical_notes=["Note 1"],
        deliverables=["Output 1"],
        exclusions=["Not this"],
        scope_constraint="Only modify X",
        implementation_steps=[
            ImplementationStep(
                title="Step 1",
                description="Do step 1",
                code_hint="def foo():\n    pass",
                test_expectation="Test passes",
            )
        ],
    )

    data = task.to_dict()

    assert data["goal"] == "Achieve something"
    assert data["prd_ref"] == "feature.md"
    assert data["key_requirements"] == ["Req 1", "Req 2"]
    assert data["technical_notes"] == ["Note 1"]
    assert data["deliverables"] == ["Output 1"]
    assert data["exclusions"] == ["Not this"]
    assert data["scope_constraint"] == "Only modify X"
    assert len(data["implementation_steps"]) == 1
    assert data["implementation_steps"][0]["title"] == "Step 1"
    assert data["implementation_steps"][0]["code_hint"] == "def foo():\n    pass"


# ---------------------------------------------------------------------------
# Artifact format plumbing (ArtifactType.format, stem ids, dual extensions)
# ---------------------------------------------------------------------------

HTML_TYPES = [
    ArtifactType.CODEBASE_SUMMARY,
    ArtifactType.ARCHITECTURE,
    ArtifactType.DATA_MODEL,
    ArtifactType.KEY_WORKFLOWS,
    ArtifactType.DIRECTORY_STRUCTURE,
]
MD_TYPES = [ArtifactType.REQUIREMENTS, ArtifactType.CODE_QUALITY]


def test_artifact_type_format_property() -> None:
    """Scan artifact types are 'html'; requirements/code-quality stay 'md'."""
    for artifact_type in HTML_TYPES:
        assert artifact_type.format == "html"
        assert artifact_type.to_filename() == f"{artifact_type.value}.html"
    for artifact_type in MD_TYPES:
        assert artifact_type.format == "md"
        assert artifact_type.to_filename() == f"{artifact_type.value}.md"

    # Spot-check the exact filenames from the acceptance criteria
    assert ArtifactType.ARCHITECTURE.to_filename() == "architecture.html"
    assert ArtifactType.REQUIREMENTS.to_filename() == "requirements.md"


def test_from_filename_both_extensions_and_index_none() -> None:
    """from_filename resolves .md, .html, and bare stems; index.html is None."""
    assert ArtifactType.from_filename("data-model.html") is ArtifactType.DATA_MODEL
    assert ArtifactType.from_filename("data-model.md") is ArtifactType.DATA_MODEL
    assert ArtifactType.from_filename("data-model") is ArtifactType.DATA_MODEL
    assert ArtifactType.from_filename("requirements.md") is ArtifactType.REQUIREMENTS
    assert ArtifactType.from_filename("architecture.html") is ArtifactType.ARCHITECTURE

    # index.html is the viewer shell, never an artifact
    assert ArtifactType.from_filename("index.html") is None
    assert ArtifactType.from_filename("unknown-thing.html") is None
    assert ArtifactType.from_filename("random-notes.md") is None


def test_stem_based_ids_reproducible(tmp_path: Path) -> None:
    """Artifact ids are bare stems for both formats and stable across re-scans."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "architecture.html").write_text(
        "<html><head><title>System Architecture</title></head><body></body></html>",
        encoding="utf-8",
    )
    (artifacts_dir / "requirements.md").write_text("# Requirements\n", encoding="utf-8")

    plugin = LocalArtifactPlugin({"artifacts_dir": str(artifacts_dir)})

    first_ids = [a.id for a in plugin.list_artifacts()]
    assert first_ids == ["architecture", "requirements"]

    # Re-scan (rewrite) the html artifact; ids must not change
    (artifacts_dir / "architecture.html").write_text(
        "<html><head><title>System Architecture v2</title></head><body></body></html>",
        encoding="utf-8",
    )
    second_ids = [a.id for a in plugin.list_artifacts()]
    assert second_ids == first_ids

    # from_file also produces bare stem ids and extracts HTML titles
    html_artifact = Artifact.from_file(
        str(artifacts_dir / "architecture.html"),
        (artifacts_dir / "architecture.html").read_text(encoding="utf-8"),
    )
    assert html_artifact.id == "architecture"
    assert html_artifact.artifact_type is ArtifactType.ARCHITECTURE
    assert html_artifact.title == "System Architecture v2"

    # Unknown .html files are rejected instead of coerced to CODEBASE_SUMMARY
    with pytest.raises(ValueError):
        Artifact.from_file("whatever/index.html", "<html></html>")


def test_html_wins_when_both_exist_warns(tmp_path: Path) -> None:
    """When both extensions exist for a scan type, .html wins with a warning."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "architecture.html").write_text(
        "<html><head><title>HTML Architecture</title></head><body></body></html>",
        encoding="utf-8",
    )
    (artifacts_dir / "architecture.md").write_text("# Legacy MD Architecture\n", encoding="utf-8")

    plugin = LocalArtifactPlugin({"artifacts_dir": str(artifacts_dir)})

    with pytest.warns(UserWarning, match="architecture.html"):
        artifacts = plugin.list_artifacts()

    assert len(artifacts) == 1
    assert artifacts[0].id == "architecture"
    assert "HTML Architecture" in artifacts[0].content


def test_get_pending_publish_skips_html(tmp_path: Path) -> None:
    """get_pending_publish excludes HTML artifacts (Confluence HTML deferred)."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "architecture.html").write_text(
        "<html><head><title>Architecture</title></head><body></body></html>",
        encoding="utf-8",
    )
    (artifacts_dir / "code-quality.md").write_text("# Code Quality\n", encoding="utf-8")

    plugin = LocalArtifactPlugin({"artifacts_dir": str(artifacts_dir)})

    pending_ids = [a.id for a in plugin.get_pending_publish()]
    assert pending_ids == ["code-quality"]


# ---------------------------------------------------------------------------
# Stale markdown deletion (remove_stale_markdown) and index.html exclusion
# ---------------------------------------------------------------------------

SCAN_STEMS = [
    "architecture",
    "codebase-summary",
    "data-model",
    "directory-structure",
    "key-workflows",
]


def test_stale_md_deletion_exact_names_only(tmp_path: Path) -> None:
    """Only the 5 exact scan names are deleted; lookalikes/protected survive."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    # All five scan artifacts: legacy .md plus the .html replacement
    for stem in SCAN_STEMS:
        (artifacts_dir / f"{stem}.md").write_text(f"# {stem}\n", encoding="utf-8")
        (artifacts_dir / f"{stem}.html").write_text("<html></html>", encoding="utf-8")

    # Sixth lookalike .md (even with an .html sibling) must survive
    (artifacts_dir / "architecture-notes.md").write_text("# Notes\n", encoding="utf-8")
    (artifacts_dir / "architecture-notes.html").write_text("<html></html>", encoding="utf-8")

    # Protected markdown artifacts must never be touched
    (artifacts_dir / "code-quality.md").write_text("# Code Quality\n", encoding="utf-8")
    (artifacts_dir / "requirements.md").write_text("# Requirements\n", encoding="utf-8")

    deleted = remove_stale_markdown(artifacts_dir)

    assert sorted(deleted) == sorted(f"{stem}.md" for stem in SCAN_STEMS)
    for stem in SCAN_STEMS:
        assert not (artifacts_dir / f"{stem}.md").exists()
        assert (artifacts_dir / f"{stem}.html").exists()  # replacements untouched
    assert (artifacts_dir / "architecture-notes.md").exists()
    assert (artifacts_dir / "code-quality.md").exists()
    assert (artifacts_dir / "requirements.md").exists()


def test_deletion_requires_html_sibling(tmp_path: Path) -> None:
    """A legacy .md is kept when its .html replacement does not exist."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    # md with html sibling → deleted; md without sibling → kept
    (artifacts_dir / "architecture.md").write_text("# Architecture\n", encoding="utf-8")
    (artifacts_dir / "architecture.html").write_text("<html></html>", encoding="utf-8")
    (artifacts_dir / "data-model.md").write_text("# Data Model\n", encoding="utf-8")

    deleted = remove_stale_markdown(artifacts_dir)

    assert deleted == ["architecture.md"]
    assert not (artifacts_dir / "architecture.md").exists()
    assert (artifacts_dir / "data-model.md").exists()


def test_deletion_defensive_on_degraded_states(tmp_path: Path) -> None:
    """Missing directory or empty directory returns [] without raising."""
    assert remove_stale_markdown(tmp_path / "does-not-exist") == []

    empty_dir = tmp_path / "artifacts"
    empty_dir.mkdir()
    assert remove_stale_markdown(empty_dir) == []
    # Also accepts a string path
    assert remove_stale_markdown(str(empty_dir)) == []


def test_index_html_excluded_from_ingestion(tmp_path: Path) -> None:
    """index.html (viewer shell) is never ingested as an artifact."""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "index.html").write_text(
        "<html><head><title>Artifact Viewer</title></head></html>", encoding="utf-8"
    )
    (artifacts_dir / "architecture.html").write_text(
        "<html><head><title>Architecture</title></head></html>", encoding="utf-8"
    )

    plugin = LocalArtifactPlugin({"artifacts_dir": str(artifacts_dir)})

    ids = [a.id for a in plugin.list_artifacts()]
    assert ids == ["architecture"]

    # sync_from_local also skips the viewer shell
    target = LocalArtifactPlugin({"artifacts_dir": str(tmp_path / "synced")})
    synced = target.sync_from_local(str(artifacts_dir))
    assert synced == 1
    assert [a.id for a in target.list_artifacts()] == ["architecture"]



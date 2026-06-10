"""Tests for the mutating workflow templates (SDLC-T00263).

Validates that scan.md documents the scaffold -> fill -> validate workflow,
the composable diagram vocabulary, the canonical grounding-read snippet, and
the exactly-scoped stale markdown deletion; that update.md mandates whole-file
regeneration; and that publish.md documents the HTML publish skip.
"""

import re
from pathlib import Path

import pytest

from a_sdlc.artifacts.validator import DIAGRAM_CLASSES, INDEX_KEY, MANIFESTS

TEMPLATES_DIR = Path(__file__).parent.parent / "src" / "a_sdlc" / "templates"


@pytest.fixture(scope="module")
def scan_content() -> str:
    return (TEMPLATES_DIR / "scan.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def update_content() -> str:
    return (TEMPLATES_DIR / "update.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def publish_content() -> str:
    return (TEMPLATES_DIR / "publish.md").read_text(encoding="utf-8")


def test_scan_template_references_scaffold_validate_retry_logcorrection(scan_content):
    """scan.md documents scaffold -> fill -> validate with retry + evidence."""
    # Scaffold and validate CLI commands
    assert "a-sdlc artifacts scaffold" in scan_content
    assert "a-sdlc artifacts validate" in scan_content
    # Retry policy: max 2 retries, log_correction per failed attempt
    assert "max 2 retries" in scan_content.lower()
    assert "log_correction" in scan_content
    # Completion gated on the evidence file
    assert ".sdlc/.cache/validation.json" in scan_content
    assert '"passed": true' in scan_content
    # Scaffold precedes fill, fill precedes validate, validate precedes finalize
    idx_scaffold = scan_content.index("a-sdlc artifacts scaffold")
    idx_fill = scan_content.index("Fill `<main>`")
    idx_validate = scan_content.index("a-sdlc artifacts validate")
    assert idx_scaffold < idx_fill < idx_validate


def test_scan_template_documents_section_pattern(scan_content):
    """scan.md documents the section pattern, flat TOC, and no nested details."""
    assert '<section id="kebab-id">' in scan_content
    assert "<details open>" in scan_content
    assert "<summary><h2>" in scan_content
    assert '<li><a href="#kebab-id">' in scan_content
    assert "no nested `<details>`" in scan_content


def test_scan_template_diagram_classes_match_validator_vocabulary(scan_content):
    """Every class in the validator's DIAGRAM_CLASSES is documented in scan.md."""
    # Classes used in HTML recipe snippets
    documented: set[str] = set()
    for match in re.finditer(r'class="([^"]+)"', scan_content):
        documented.update(match.group(1).split())
    # Classes mentioned in prose as `.class` or `.class.class`
    for match in re.finditer(r"\.([a-z][a-z-]*)", scan_content):
        documented.add(match.group(1))

    missing = set(DIAGRAM_CLASSES) - documented
    assert not missing, f"Diagram classes not documented in scan.md: {sorted(missing)}"


def test_scan_template_documents_validator_required_sections(scan_content):
    """Every required <section id> in the validator MANIFESTS appears in scan.md.

    Pins the Phase 4.2 required-sections table against the validator manifest
    so the two cannot drift apart silently.
    """
    table_start = scan_content.index("Required Sections (manifest)")
    table_end = scan_content.index("####", table_start)
    table = scan_content[table_start:table_end]

    for artifact_type, manifest in MANIFESTS.items():
        if artifact_type == INDEX_KEY:
            continue
        for section_id in manifest.required_sections:
            assert f"`{section_id}`" in table, (
                f"Required section id {section_id!r} for {artifact_type!r} "
                "missing from scan.md Phase 4.2 table"
            )


def test_scan_template_forbids_active_content(scan_content):
    """scan.md explicitly forbids script/onclick/SVG/img/style attributes."""
    assert "<script>" in scan_content
    assert "onclick" in scan_content
    assert "<svg>" in scan_content
    assert "<img>" in scan_content
    assert "`style` attributes" in scan_content


def test_scan_template_has_delimited_grounding_snippet(scan_content):
    """The canonical grounding-read snippet is present and clearly delimited."""
    start_marker = "<!-- grounding-read-snippet:start -->"
    end_marker = "<!-- grounding-read-snippet:end -->"
    assert start_marker in scan_content
    assert end_marker in scan_content

    start = scan_content.index(start_marker)
    end = scan_content.index(end_marker)
    assert start < end

    snippet = scan_content[start + len(start_marker) : end]
    # Prefers .html, falls back to .md, context-free artifact placeholder
    assert "{name}.html" in snippet
    assert "{name}.md" in snippet
    # Markdown-only artifacts are excluded from the fallback rule
    assert "code-quality.md" in snippet
    assert "requirements.md" in snippet


def test_scan_template_deletion_scoped_to_exact_names(scan_content):
    """Stale .md deletion lists exactly the five scan artifact filenames."""
    deletion_start = scan_content.index("Delete Stale Markdown")
    deletion_section = scan_content[deletion_start:]

    for name in (
        "architecture.md",
        "codebase-summary.md",
        "data-model.md",
        "directory-structure.md",
        "key-workflows.md",
    ):
        assert name in deletion_section, f"{name} missing from deletion step"

    # The markdown-by-design artifacts are explicitly protected
    assert "code-quality.md" in deletion_section
    assert "requirements.md" in deletion_section
    assert "NEVER" in deletion_section
    # Deletion requires the .html sibling to exist
    assert ".html` sibling" in deletion_section


def test_update_template_mandates_whole_file_regeneration_never_patch(update_content):
    """update.md keeps section-level detection but forbids patch-editing HTML."""
    lower = update_content.lower()
    # Section-level detection retained for deciding WHAT to regenerate
    assert "section-level change detection" in lower
    # Whole-file regeneration rule
    assert "whole-file" in lower
    assert "never patch-edit html" in lower
    # Validation gate after regeneration
    assert "a-sdlc artifacts validate" in update_content
    # Checksums keyed on .html filenames
    assert '"architecture.html"' in update_content


def test_status_template_uses_html_artifact_names():
    """status.md tables/examples reference .html artifact names."""
    content = (TEMPLATES_DIR / "status.md").read_text(encoding="utf-8")
    for name in (
        "directory-structure.html",
        "codebase-summary.html",
        "architecture.html",
        "data-model.html",
        "key-workflows.html",
    ):
        assert name in content, f"{name} missing from status.md"


def test_publish_template_documents_html_skip(publish_content):
    """publish.md documents that HTML scan artifacts are skipped (deferred)."""
    # Matches the CLI push guard message
    assert (
        "scan artifacts are HTML — Confluence publish for HTML is deferred"
        in publish_content
    )
    assert "follow-up PRD" in publish_content
    # Markdown artifacts still publish
    assert "code-quality.md" in publish_content
    assert "requirements.md" in publish_content


ARTIFACT_TEMPLATES_DIR = (
    Path(__file__).parent.parent / "src" / "a_sdlc" / "artifact_templates"
)

GROUNDING_FILES = [
    TEMPLATES_DIR / "ideate.md",
    TEMPLATES_DIR / "prd-generate.md",
    TEMPLATES_DIR / "prd-architect.md",
    TEMPLATES_DIR / "prd-investigate.md",
    TEMPLATES_DIR / "prd-split.md",
    TEMPLATES_DIR / "task-split.md",
    TEMPLATES_DIR / "task-create.md",
    TEMPLATES_DIR / "task-start.md",
    TEMPLATES_DIR / "sprint-run.md",
    TEMPLATES_DIR / "investigate.md",
    TEMPLATES_DIR / "ask.md",
    TEMPLATES_DIR / "init.md",
    TEMPLATES_DIR / "_round-table-blocks.md",
    TEMPLATES_DIR / "sonar-scan.md",
    ARTIFACT_TEMPLATES_DIR / "claude-md.template.md",
    ARTIFACT_TEMPLATES_DIR / "gemini-md.template.md",
]

_SNIPPET_START = b"<!-- grounding-read-snippet:start -->"
_SNIPPET_END = b"<!-- grounding-read-snippet:end -->"


def _extract_grounding_snippet_bytes(path: Path) -> bytes:
    """Extract the delimited grounding-read block, inclusive of both markers.

    Operates on raw bytes (not ``read_text``) so newline differences such as
    a CRLF copy of an LF canonical block cannot slip through translation.
    """
    data = path.read_bytes()
    assert data.count(_SNIPPET_START) == 1, (
        f"{path.name}: expected exactly one start marker, "
        f"found {data.count(_SNIPPET_START)}"
    )
    assert data.count(_SNIPPET_END) == 1, (
        f"{path.name}: expected exactly one end marker, "
        f"found {data.count(_SNIPPET_END)}"
    )
    start = data.index(_SNIPPET_START)
    end = data.index(_SNIPPET_END) + len(_SNIPPET_END)
    assert start < end, f"{path.name}: end marker precedes start marker"
    return data[start:end]


@pytest.mark.parametrize("template_path", GROUNDING_FILES, ids=lambda p: p.name)
def test_grounding_snippet_identical_across_16_files(template_path):
    """Each grounding file carries scan.md's snippet block verbatim.

    The raw byte slice between (and including) the start/end HTML-comment
    markers must be byte-identical to the canonical block in scan.md —
    verbatim copies, no per-file rewording and no newline drift such as a
    CRLF copy of an LF canonical (SDLC-T00264). Covers 14 skill templates
    plus the two init artifact templates that generate fresh CLAUDE.md /
    GEMINI.md files.
    """
    canonical = _extract_grounding_snippet_bytes(TEMPLATES_DIR / "scan.md")
    copy = _extract_grounding_snippet_bytes(template_path)
    assert copy == canonical, (
        f"{template_path.name}: grounding-read snippet block differs from the "
        "canonical block in scan.md — copies must be byte-identical"
    )

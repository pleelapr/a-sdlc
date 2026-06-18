"""End-to-end integration sweep for HTML scan artifacts (PRD SDLC-P0041).

AC -> test mapping (this module is the PRD's acceptance-criteria closure;
AC-004/NFR-002 live in ``tests/test_artifact_overhead.py`` and AC-005 in
``tests/test_artifact_security.py``):

==========  ===============================================================
AC-001      ``test_fresh_scan_produces_5_plus_index_all_valid`` --
            scaffold via the real CLI, fill ``<main>`` with realistic
            content (ported from ``example-artifacts/``), validate via the
            real CLI: 6 files, zero errors, passing ``validation.json``.
AC-002 /    ``test_artifacts_self_contained_no_external_refs`` -- every
NFR-001     generated file AND every shipped ``example-artifacts/*.html``
            contains no ``http(s)://``, no ``<script``, no external-loading
            elements; every ``href`` is a fragment or a relative ``*.html``
            link. This is the automated proxy for the ``file://`` criterion;
            the manual ``file://`` smoke (TOC jumps, sections collapse,
            diagrams render, nav resolves) was performed in a browser on the
            example artifacts earlier in the PRD lifecycle (SDLC-T00266 /
            design Appendix A preview review).
AC-003 /    ``test_update_regenerates_whole_file_ids_preserved`` -- a filled
NFR-004 /   artifact is regenerated WHOLE-FILE (fresh skeleton + changed
FR-008      content, never patch-edited), still validates, and every
            required section id is identical pre/post.
AC-006      ``test_legacy_md_project_detected_then_replaced_after_rescan``
            -- a project holding only the 5 legacy ``.md`` artifacts is
            detected as scanned (same dual-extension check as
            ``get_context()`` in ``src/a_sdlc/server/project_tools.py``);
            after a simulated rescan (scaffold + fill + validate +
            ``remove_stale_markdown``) the ``.html`` files exist, the five
            exact-name ``.md`` files are gone, and the ``code-quality.md``
            lookalike survives.
AC-007      ``test_validator_failure_blocks_scan_and_logs_correction`` --
            an invalid artifact makes ``a-sdlc artifacts validate`` exit 1,
            the error lands in ``validation.json`` (``passed: false``), and
            the scan template's evidence contract requires that passing
            ``validation.json`` (with logged corrections per failed
            attempt) before the scan may complete.
==========  ===============================================================
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from a_sdlc.artifacts.local import remove_stale_markdown
from a_sdlc.artifacts.validator import (
    MANIFESTS,
    SCAN_ARTIFACT_FILENAMES,
    scaffold,
    validate_directory,
    validate_file,
)
from a_sdlc.cli import main

EXAMPLES_DIR = Path(__file__).parent.parent / "example-artifacts"
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pre_migration"
SCAN_TEMPLATE = (
    Path(__file__).parent.parent / "src" / "a_sdlc" / "templates" / "scan.md"
)

#: The five scan artifact stems -- mirrors the ``artifact_names`` list used
#: by ``get_context()`` in ``src/a_sdlc/server/project_tools.py``.
ARTIFACT_STEMS = [
    "architecture",
    "codebase-summary",
    "data-model",
    "directory-structure",
    "key-workflows",
]

ALL_HTML_FILES = sorted([*SCAN_ARTIFACT_FILENAMES, "index.html"])

_MAIN_RE = re.compile(r"<main>.*?</main>", re.DOTALL)
_TOC_RE = re.compile(r'<nav aria-label="Contents">.*?</nav>', re.DOTALL)
_HREF_RE = re.compile(r'href="([^"]*)"')
_VALID_HREF_RE = re.compile(
    r"^(#[A-Za-z][A-Za-z0-9_-]*|[A-Za-z0-9_-]+\.html(#[A-Za-z][A-Za-z0-9_-]*)?)$"
)
_SECTION_ID_RE = re.compile(r'<section id="([^"]+)"')


def _fill_from_example(skeleton_path: Path, example_path: Path) -> None:
    """Transplant the example artifact's TOC and <main> into a skeleton.

    This reproduces the documented scan recipe (scaffold -> agent fills the
    <main> slot and TOC) using realistic, validator-passing content.
    """
    skeleton = skeleton_path.read_text(encoding="utf-8")
    example = example_path.read_text(encoding="utf-8")
    main_match = _MAIN_RE.search(example)
    toc_match = _TOC_RE.search(example)
    assert main_match is not None, f"{example_path.name} has no <main> region"
    assert toc_match is not None, f"{example_path.name} has no Contents nav"
    skeleton = _TOC_RE.sub(lambda _m: toc_match.group(0), skeleton, count=1)
    skeleton = _MAIN_RE.sub(lambda _m: main_match.group(0), skeleton, count=1)
    skeleton_path.write_text(skeleton, encoding="utf-8", newline="\n")


def _scaffold_and_fill(directory: Path, project_name: str) -> None:
    """Scaffold the six skeletons and fill the five artifact mains."""
    scaffold(directory, project_name)
    for stem in ARTIFACT_STEMS:
        _fill_from_example(directory / f"{stem}.html", EXAMPLES_DIR / f"{stem}.html")
    # index.html ships with a pre-filled "artifacts" section -- no fill needed.


@pytest.fixture(scope="module")
def filled_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A complete, realistic artifacts directory (5 filled + index)."""
    directory = tmp_path_factory.mktemp("filled_artifacts")
    _scaffold_and_fill(directory, "integration-project")
    return directory


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# AC-001 -- fresh scan E2E through the real CLI
# ---------------------------------------------------------------------------


def test_fresh_scan_produces_5_plus_index_all_valid(runner: CliRunner) -> None:
    """AC-001: scaffold -> fill -> validate yields 6 files with zero errors."""
    with runner.isolated_filesystem():
        result = runner.invoke(main, ["artifacts", "scaffold", "--project-name", "fresh-scan"])
        assert result.exit_code == 0, result.output

        artifacts_dir = Path(".sdlc") / "artifacts"
        for stem in ARTIFACT_STEMS:
            _fill_from_example(artifacts_dir / f"{stem}.html", EXAMPLES_DIR / f"{stem}.html")

        result = runner.invoke(main, ["artifacts", "validate"])
        assert result.exit_code == 0, result.output

        files = sorted(p.name for p in artifacts_dir.glob("*.html"))
        assert files == ALL_HTML_FILES

        evidence = json.loads(
            (Path(".sdlc") / ".cache" / "validation.json").read_text(encoding="utf-8")
        )
    assert evidence["passed"] is True
    assert len(evidence["results"]) == 6
    assert all(entry["errors"] == [] for entry in evidence["results"])


# ---------------------------------------------------------------------------
# AC-002 / NFR-001 -- self-containment (automated file:// proxy)
# ---------------------------------------------------------------------------


def test_artifacts_self_contained_no_external_refs(filled_dir: Path) -> None:
    """AC-002/NFR-001: no network refs, no script, relative links only.

    Covers every freshly generated file AND every shipped example artifact.
    See the module docstring for the manual file:// smoke provenance.
    """
    targets = sorted(filled_dir.glob("*.html")) + sorted(EXAMPLES_DIR.glob("*.html"))
    assert len(targets) >= 12  # 6 generated + 6 shipped examples

    forbidden_markers = ("http://", "https://", "<script", "<img", "<link", "<iframe", "src=", "url(", "@import")
    for path in targets:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for marker in forbidden_markers:
            assert marker not in lowered, (
                f"{path} contains forbidden external/active marker {marker!r}"
            )
        for href in _HREF_RE.findall(text):
            assert _VALID_HREF_RE.match(href), (
                f"{path} link {href!r} is not a fragment or relative *.html href"
            )


# ---------------------------------------------------------------------------
# AC-003 / NFR-004 / FR-008 -- whole-file regeneration preserves ids
# ---------------------------------------------------------------------------


def test_update_regenerates_whole_file_ids_preserved(
    filled_dir: Path, tmp_path: Path
) -> None:
    """AC-003: regenerate whole-file with changed content; ids identical."""
    original = (filled_dir / "architecture.html").read_text(encoding="utf-8")
    ids_before = _SECTION_ID_RE.findall(original)
    required = MANIFESTS["architecture"].required_sections
    assert set(required) <= set(ids_before)

    # Whole-file regeneration (FR-008): a FRESH skeleton is scaffolded and
    # filled from scratch -- the old file is never patch-edited.
    scaffold(tmp_path, "integration-project")
    regenerated_path = tmp_path / "architecture.html"
    _fill_from_example(regenerated_path, EXAMPLES_DIR / "architecture.html")
    regenerated = regenerated_path.read_text(encoding="utf-8")
    regenerated = regenerated.replace(
        "</summary>",
        "</summary><p>Updated after a code change: the storage layer notes "
        "were regenerated in this scan pass.</p>",
        1,
    )
    regenerated_path.write_text(regenerated, encoding="utf-8", newline="\n")

    # Sibling files so the index-link / nav checks resolve where needed.
    for stem in ARTIFACT_STEMS:
        if stem != "architecture":
            _fill_from_example(tmp_path / f"{stem}.html", EXAMPLES_DIR / f"{stem}.html")

    result = validate_file(regenerated_path)
    assert result.passed, f"Regenerated artifact failed validation: {result.errors}"

    ids_after = _SECTION_ID_RE.findall(regenerated)
    assert ids_after == ids_before, "Section ids must be stable across re-scans"
    assert set(required) <= set(ids_after)
    assert regenerated != original, "Regeneration must actually change content"


# ---------------------------------------------------------------------------
# AC-006 -- legacy markdown project transition
# ---------------------------------------------------------------------------


def _detected_artifacts(artifacts_dir: Path) -> list[str]:
    """Replicate get_context()'s dual-extension scan detection.

    Mirrors ``src/a_sdlc/server/project_tools.py`` (get_context): a stem
    counts as scanned when either ``{name}.html`` or legacy ``{name}.md``
    exists. (``get_context`` itself is an MCP tool bound to a live server/DB,
    so the check is replicated here verbatim rather than imported.)
    """
    available = []
    if artifacts_dir.is_dir():
        for name in ARTIFACT_STEMS:
            if (artifacts_dir / f"{name}.html").is_file() or (
                artifacts_dir / f"{name}.md"
            ).is_file():
                available.append(name)
    return available


def test_legacy_md_project_detected_then_replaced_after_rescan(tmp_path: Path) -> None:
    """AC-006: md-only project counts as scanned; rescan swaps md -> html."""
    artifacts_dir = tmp_path / ".sdlc" / "artifacts"
    artifacts_dir.mkdir(parents=True)
    for stem in ARTIFACT_STEMS:
        shutil.copyfile(FIXTURE_DIR / f"{stem}.md", artifacts_dir / f"{stem}.md")
    # Markdown-by-design lookalike that must never be touched (DD-7).
    (artifacts_dir / "code-quality.md").write_text(
        "# Code Quality Report\n\nNo issues.\n", encoding="utf-8"
    )

    # 1. Legacy detection: all five count as scanned -> status "complete".
    detected = _detected_artifacts(artifacts_dir)
    assert detected == ARTIFACT_STEMS
    assert len(detected) == len(ARTIFACT_STEMS)  # get_context -> "complete"

    # 2. Simulated rescan: scaffold + fill + validate, then markdown cleanup.
    _scaffold_and_fill(artifacts_dir, "legacy-project")
    results, skipped = validate_directory(artifacts_dir)
    assert all(r.passed for r in results), [
        (r.file, r.errors) for r in results if r.errors
    ]
    # Markdown files are skipped by the validator, never failed.
    assert set(skipped) == {f"{stem}.md" for stem in ARTIFACT_STEMS} | {"code-quality.md"}

    deleted = remove_stale_markdown(artifacts_dir)
    assert sorted(deleted) == sorted(f"{stem}.md" for stem in ARTIFACT_STEMS)

    # 3. Post-rescan state: html present, exact-name md gone, lookalike kept.
    assert sorted(p.name for p in artifacts_dir.glob("*.html")) == ALL_HTML_FILES
    for stem in ARTIFACT_STEMS:
        assert not (artifacts_dir / f"{stem}.md").exists()
    assert (artifacts_dir / "code-quality.md").is_file()
    assert _detected_artifacts(artifacts_dir) == ARTIFACT_STEMS


# ---------------------------------------------------------------------------
# AC-007 -- validator failure blocks scan completion with evidence
# ---------------------------------------------------------------------------


def test_validator_failure_blocks_scan_and_logs_correction(runner: CliRunner) -> None:
    """AC-007: invalid artifact -> exit 1 + failing validation.json evidence."""
    with runner.isolated_filesystem():
        runner.invoke(main, ["artifacts", "scaffold", "--project-name", "broken-scan"])
        artifacts_dir = Path(".sdlc") / "artifacts"
        for stem in ARTIFACT_STEMS:
            _fill_from_example(artifacts_dir / f"{stem}.html", EXAMPLES_DIR / f"{stem}.html")

        # Corrupt one artifact with active content (NFR-003 violation).
        target = artifacts_dir / "architecture.html"
        corrupted = target.read_text(encoding="utf-8").replace(
            "</main>", "<script>alert(1)</script></main>", 1
        )
        target.write_text(corrupted, encoding="utf-8", newline="\n")

        result = runner.invoke(main, ["artifacts", "validate"])
        assert result.exit_code == 1, result.output

        evidence = json.loads(
            (Path(".sdlc") / ".cache" / "validation.json").read_text(encoding="utf-8")
        )

    # Evidence is written on FAILURE too, with the blocking error recorded.
    assert evidence["passed"] is False
    by_file = {entry["file"]: entry for entry in evidence["results"]}
    architecture_errors = " ".join(by_file["architecture.html"]["errors"])
    assert "script" in architecture_errors
    # Only the corrupted file fails; the rest of the scan output is clean.
    clean = [f for f, entry in by_file.items() if not entry["errors"]]
    assert len(clean) == 5

    # The scan template's evidence contract: completion is blocked until
    # validation.json reports passed=true, with corrections logged per
    # failed attempt and a hard stop after the retry budget.
    scan_template = SCAN_TEMPLATE.read_text(encoding="utf-8")
    assert '"passed": true' in scan_template
    assert ".sdlc/.cache/validation.json" in scan_template
    assert "max 2 retries" in scan_template
    assert "log_correction" in scan_template
    assert "There is no override" in scan_template

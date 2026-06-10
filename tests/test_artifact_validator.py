"""Tests for the HTML artifact validator contract (SDLC-P0041).

Covers: golden fixtures (one per artifact type + index), one mutation fixture
per validator rule asserting its specific error, the scaffold-then-validate
composition test (anti-drift gate), aria-current variation, the verbatim
summary-marker CSS, and the frozen validation.json schema.
"""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from a_sdlc.artifacts import validator as val
from a_sdlc.artifacts.base import ArtifactType
from a_sdlc.cli import main

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

SECTION_TITLES = {
    "overview": "Overview",
    "key-concepts": "Key Concepts",
    "technology-stack": "Technology Stack",
    "component-overview": "Component Overview",
    "data-flow": "Data Flow",
    "entities": "Entities",
    "workflows": "Workflows",
    "repository-structure": "Repository Structure",
}

FILLER = (
    "This section documents the relevant aspects of the codebase in enough "
    "detail to satisfy the validator minimum content requirement."
)


def _section_html(sec_id: str, title: str, body: str | None = None) -> str:
    if body is None:
        body = f"<p>{title}: {FILLER}</p>"
    return (
        f'<section id="{sec_id}">\n<details open>\n'
        f"<summary><h2>{title}</h2></summary>\n{body}\n</details>\n</section>"
    )


def fill_artifact(
    path: Path,
    sections: list[tuple[str, str]] | None = None,
    bodies: dict[str, str] | None = None,
    toc_ids: list[str] | None = None,
) -> None:
    """Fill a scaffolded skeleton's <main> slot and TOC with valid sections."""
    if sections is None:
        artifact_type = ArtifactType.from_filename(path.name)
        assert artifact_type is not None
        required = val.MANIFESTS[artifact_type.value].required_sections
        sections = [(sec_id, SECTION_TITLES[sec_id]) for sec_id in required]
    bodies = bodies or {}
    html = path.read_text(encoding="utf-8")
    body_html = "\n".join(
        _section_html(sec_id, title, bodies.get(sec_id)) for sec_id, title in sections
    )
    html = re.sub(
        r"<main>.*?</main>",
        lambda _m: f"<main>\n{body_html}\n</main>",
        html,
        flags=re.DOTALL,
    )
    ids = toc_ids if toc_ids is not None else [sec_id for sec_id, _ in sections]
    toc = "".join(
        f'<li><a href="#{sec_id}">{SECTION_TITLES.get(sec_id, sec_id)}</a></li>'
        for sec_id in ids
    )
    html = html.replace("<ul></ul>", f"<ul>{toc}</ul>", 1)
    path.write_text(html, encoding="utf-8", newline="\n")


def make_valid_dir(tmp_path: Path, project: str = "TestProj") -> Path:
    """Scaffold + minimally fill all five artifacts (index needs no filling)."""
    directory = tmp_path / "artifacts"
    val.scaffold(directory, project)
    for filename in val.SCAN_ARTIFACT_FILENAMES:
        fill_artifact(directory / filename)
    return directory


def make_dir_with_arch(tmp_path: Path, **fill_kwargs: object) -> Path:
    """Valid directory where architecture.html is filled with custom args."""
    directory = tmp_path / "artifacts"
    val.scaffold(directory, "TestProj")
    for filename in val.SCAN_ARTIFACT_FILENAMES:
        if filename == "architecture.html":
            fill_artifact(directory / filename, **fill_kwargs)  # type: ignore[arg-type]
        else:
            fill_artifact(directory / filename)
    return directory


def _result(directory: Path, filename: str) -> val.ValidationResult:
    results, _ = val.validate_directory(directory)
    return {r.file: r for r in results}[filename]


def _errors(directory: Path, filename: str = "architecture.html") -> list[str]:
    return _result(directory, filename).errors


def _mutate(directory: Path, filename: str, old: str, new: str) -> None:
    path = directory / filename
    html = path.read_text(encoding="utf-8")
    assert old in html, f"mutation anchor not found in {filename}: {old!r}"
    path.write_text(html.replace(old, new, 1), encoding="utf-8", newline="\n")


def _inject_main(directory: Path, snippet: str, filename: str = "architecture.html") -> None:
    """Insert a snippet at the end of the first top-level section's content."""
    _mutate(directory, filename, "</details>\n</section>", f"{snippet}\n</details>\n</section>")


@pytest.fixture
def valid_dir(tmp_path: Path) -> Path:
    return make_valid_dir(tmp_path)


def _assert_error(errors: list[str], *fragments: str) -> None:
    """Assert one error message contains all the given fragments."""
    for error in errors:
        if all(fragment in error for fragment in fragments):
            return
    raise AssertionError(f"no error containing {fragments!r} in: {errors!r}")


# ---------------------------------------------------------------------------
# Golden fixtures: one per artifact type + index (clean pass)
# ---------------------------------------------------------------------------


class TestGoldenFixtures:
    @pytest.mark.parametrize("filename", [*val.SCAN_ARTIFACT_FILENAMES, "index.html"])
    def test_golden_passes_clean(self, valid_dir: Path, filename: str) -> None:
        result = _result(valid_dir, filename)
        assert result.errors == []
        assert result.warnings == []
        assert result.passed


# ---------------------------------------------------------------------------
# Composition contract (anti-drift gate) + scaffold behavior
# ---------------------------------------------------------------------------


class TestScaffoldComposition:
    def test_scaffold_then_validate_composition(self, tmp_path: Path) -> None:
        """Scaffold output + minimal valid main content MUST pass validate."""
        directory = make_valid_dir(tmp_path)
        results, skipped = val.validate_directory(directory)
        assert len(results) == 6
        failures = [(r.file, r.errors) for r in results if not r.passed]
        assert failures == []
        assert skipped == []

    def test_scaffold_writes_six_files(self, tmp_path: Path) -> None:
        written = val.scaffold(tmp_path / "out", "Proj")
        assert len(written) == 6
        assert {p.name for p in written} == {*val.SCAN_ARTIFACT_FILENAMES, "index.html"}

    def test_scaffold_titles_use_project_name(self, tmp_path: Path) -> None:
        directory = tmp_path / "out"
        val.scaffold(directory, "MyProj")
        html = (directory / "architecture.html").read_text(encoding="utf-8")
        assert "<title>Architecture — MyProj</title>" in html
        index = (directory / "index.html").read_text(encoding="utf-8")
        assert "<title>Artifacts — MyProj</title>" in index

    def test_scaffold_timestamp_in_footer(self, tmp_path: Path) -> None:
        directory = tmp_path / "out"
        val.scaffold(directory, "Proj", timestamp="2026-06-09")
        html = (directory / "data-model.html").read_text(encoding="utf-8")
        assert "Generated by a-sdlc scan · 2026-06-09" in html

    def test_nav_strip_aria_current_varies_per_page(self, tmp_path: Path) -> None:
        directory = tmp_path / "out"
        val.scaffold(directory, "Proj")
        for filename in [*val.SCAN_ARTIFACT_FILENAMES, "index.html"]:
            html = (directory / filename).read_text(encoding="utf-8")
            marked = re.findall(r'<a href="([^"]+)" aria-current="page">', html)
            assert marked == [filename]

    def test_marker_css_matches_design_verbatim(self) -> None:
        """User-approved summary-marker CSS copied exactly from design 3.2."""
        marker_rules = (
            "summary{cursor:pointer;padding:.7rem 0;list-style:none;display:flex;"
            "align-items:baseline;gap:.6rem}",
            "summary::-webkit-details-marker{display:none}",
            'summary::before{content:"\\25B8";flex:none;color:var(--muted);'
            "font-size:1.25rem;line-height:1}",
            'details[open]>summary::before{content:"\\25BE"}',
        )
        for template in ("artifact.template.html", "index.template.html"):
            text = val._load_template(template)
            for rule in marker_rules:
                assert rule in text, f"{template} missing marker rule: {rule}"

    def test_skeleton_has_zero_js_and_external_refs(self) -> None:
        for template in ("artifact.template.html", "index.template.html"):
            text = val._load_template(template).lower()
            assert "<script" not in text
            assert "http://" not in text
            assert "https://" not in text
            assert "@import" not in text
            assert "url(" not in text

    def test_skeleton_css_classes_within_vocabulary(self) -> None:
        text = val._load_template("artifact.template.html")
        style_match = re.search(r"<style>(.*?)</style>", text, re.DOTALL)
        assert style_match is not None
        classes = set(re.findall(r"\.([a-zA-Z][a-zA-Z-]*)", style_match.group(1)))
        assert classes <= val.DIAGRAM_CLASSES


# ---------------------------------------------------------------------------
# Mutation fixtures: one per validator rule, asserting the specific error
# ---------------------------------------------------------------------------


class TestParseIntegrity:
    def test_unclosed_tag(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<div class="box">unclosed')
        _assert_error(_errors(valid_dir), "[parse]")

    def test_unexpected_closing_tag(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, "<p>text</p></article>")
        _assert_error(_errors(valid_dir), "[parse]", "</article>")


class TestStructureContract:
    def test_missing_required_section(self, tmp_path: Path) -> None:
        directory = make_dir_with_arch(
            tmp_path, sections=[("component-overview", "Component Overview")]
        )
        _assert_error(_errors(directory), "[structure]", "missing required section id 'data-flow'")

    def test_details_without_open(self, valid_dir: Path) -> None:
        _mutate(valid_dir, "architecture.html", "<details open>", "<details>")
        _assert_error(_errors(valid_dir), "[structure]", "open attribute")

    def test_nested_details(self, valid_dir: Path) -> None:
        _inject_main(
            valid_dir, "<details open><summary><h2>Inner</h2></summary><p>x</p></details>"
        )
        _assert_error(_errors(valid_dir), "[structure]", "nested <details>")

    def test_summary_without_h2(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "architecture.html",
            "<summary><h2>Component Overview</h2></summary>",
            "<summary>Component Overview</summary>",
        )
        _assert_error(_errors(valid_dir), "[structure]", "<summary> must contain an <h2>")

    def test_nested_toc_list(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "architecture.html",
            "</ul>\n</nav>",
            '<li>More<ul><li><a href="#component-overview">CO</a></li></ul></li></ul>\n</nav>',
        )
        _assert_error(_errors(valid_dir), "[structure]", "TOC must be a flat list")

    def test_duplicate_id_in_main(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<p id="component-overview">dup</p>')
        _assert_error(_errors(valid_dir), "[structure]", "duplicate id 'component-overview'")

    def test_index_nav_missing_artifact_link(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "index.html",
            '    <a href="data-model.html">Data Model</a>\n',
            "",
        )
        _assert_error(
            _errors(valid_dir, "index.html"), "[structure]", "missing links", "data-model.html"
        )

    def test_index_artifact_link_does_not_resolve(self, valid_dir: Path) -> None:
        (valid_dir / "data-model.html").unlink()
        _assert_error(
            _errors(valid_dir, "index.html"),
            "[structure]",
            "'data-model.html' does not resolve",
        )


class TestAnchorResolution:
    def test_dangling_toc_anchor(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "architecture.html",
            "</ul>\n</nav>",
            '<li><a href="#nope">Nope</a></li></ul>\n</nav>',
        )
        _assert_error(_errors(valid_dir), "[anchors]", "dangling TOC anchor '#nope'")

    def test_orphan_section_not_in_toc(self, valid_dir: Path) -> None:
        extra = _section_html("extras", "Extras")
        _mutate(valid_dir, "architecture.html", "</main>", f"{extra}\n</main>")
        _assert_error(_errors(valid_dir), "[anchors]", "section 'extras' is not linked")


class TestForbiddenContent:
    def test_script_tag(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, "<script>alert(1)</script>")
        _assert_error(_errors(valid_dir), "[forbidden]", "<script>")

    def test_event_handler_attribute(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<div class="box" onclick="alert(1)">x</div>')
        _assert_error(_errors(valid_dir), "[forbidden]", "onclick")

    def test_inline_style_attribute(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<p style="color:red">styled</p>')
        _assert_error(_errors(valid_dir), "[forbidden]", "inline style attribute")

    def test_data_uri(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<a href="data:text/html,hi">x</a>')
        _assert_error(_errors(valid_dir), "[forbidden]", "'data:' URI")

    def test_url_in_style_block(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "architecture.html",
            "</style>",
            "body{background:url(https://evil.example/x.png)}\n</style>",
        )
        _assert_error(_errors(valid_dir), "[forbidden]", "url() or @import")

    def test_import_in_style_block(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "architecture.html",
            "</style>",
            '@import "https://evil.example/x.css";\n</style>',
        )
        _assert_error(_errors(valid_dir), "[forbidden]", "url() or @import")

    def test_external_link_element(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "architecture.html",
            '<meta charset="utf-8">',
            '<meta charset="utf-8">\n<link rel="stylesheet" href="https://cdn.example/x.css">',
        )
        _assert_error(_errors(valid_dir), "[forbidden]", "<link>")

    def test_meta_http_equiv(self, valid_dir: Path) -> None:
        _mutate(
            valid_dir,
            "architecture.html",
            '<meta charset="utf-8">',
            '<meta charset="utf-8">\n<meta http-equiv="refresh" content="0">',
        )
        _assert_error(_errors(valid_dir), "[forbidden]", "http-equiv")


class TestMainAllowlist:
    def test_disallowed_tag(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, "<aside><p>x</p></aside>")
        _assert_error(_errors(valid_dir), "[allowlist]", "<aside>")

    def test_disallowed_attribute(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<p title="tip">x</p>')
        _assert_error(_errors(valid_dir), "[allowlist]", "attribute 'title'")

    def test_class_outside_vocabulary(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<div class="shiny">x</div>')
        _assert_error(_errors(valid_dir), "[allowlist]", "class 'shiny'")

    def test_external_href_in_main(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, '<a href="https://example.com/">x</a>')
        _assert_error(_errors(valid_dir), "[allowlist]", "href 'https://example.com/'")


class TestEscaping:
    def test_unescaped_lt(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, "<p>1 < 2</p>")
        _assert_error(_errors(valid_dir), "[escaping]", "unescaped '<'")

    def test_unescaped_amp(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, "<p>fish & chips</p>")
        _assert_error(_errors(valid_dir), "[escaping]", "unescaped '&'")

    def test_escaped_content_passes(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, "<p><code>&lt;script&gt;alert(1)&lt;/script&gt;</code></p>")
        assert _errors(valid_dir) == []


class TestSemanticEmptiness:
    def test_empty_required_section(self, tmp_path: Path) -> None:
        directory = make_dir_with_arch(tmp_path, bodies={"data-flow": "<p></p>"})
        _assert_error(_errors(directory), "[content]", "'data-flow'", "insufficient content")

    def test_placeholder_todo(self, tmp_path: Path) -> None:
        directory = make_dir_with_arch(
            tmp_path,
            bodies={"data-flow": "<p>TODO: write the data flow section content here later.</p>"},
        )
        _assert_error(_errors(directory), "[content]", "placeholder text ('TODO')")

    def test_placeholder_lorem(self, tmp_path: Path) -> None:
        directory = make_dir_with_arch(
            tmp_path,
            bodies={"data-flow": "<p>Lorem ipsum dolor sit amet, consectetur adipiscing.</p>"},
        )
        _assert_error(_errors(directory), "[content]", "placeholder text ('lorem')")

    def test_empty_list_in_main(self, valid_dir: Path) -> None:
        _inject_main(valid_dir, "<ul></ul>")
        _assert_error(_errors(valid_dir), "[content]", "empty <ul>/<ol>")

    def test_duplicate_section_content(self, tmp_path: Path) -> None:
        body = "<p>Identical content body used twice to trigger duplication detection.</p>"
        directory = make_dir_with_arch(
            tmp_path, bodies={"component-overview": body, "data-flow": body}
        )
        _assert_error(_errors(directory), "[content]", "duplicate content")


class TestA11y:
    def test_missing_lang(self, valid_dir: Path) -> None:
        _mutate(valid_dir, "architecture.html", '<html lang="en">', "<html>")
        _assert_error(_errors(valid_dir), "[a11y]", "lang")

    def test_two_h1(self, valid_dir: Path) -> None:
        _mutate(valid_dir, "architecture.html", "</header>", "<h1>Extra</h1>\n</header>")
        _assert_error(_errors(valid_dir), "[a11y]", "exactly one <h1>", "found 2")

    def test_skipped_heading_level(self, valid_dir: Path) -> None:
        _mutate(valid_dir, "architecture.html", "</summary>", "</summary>\n<h4>Too deep</h4>")
        _assert_error(_errors(valid_dir), "[a11y]", "skipped heading level", "h2 -> h4")

    def test_nav_missing_aria_label(self, valid_dir: Path) -> None:
        _mutate(valid_dir, "architecture.html", '<nav aria-label="Contents">', "<nav>")
        _assert_error(_errors(valid_dir), "[a11y]", "<nav> missing aria-label")


class TestSizeBudget:
    def test_oversize_is_warning_not_error(self, tmp_path: Path) -> None:
        # Pad past the manifest budget (whatever it currently is) so the
        # fixture keeps exercising the warn path across budget revisions.
        filler = "Architecture content padding. "
        repeats = val.MANIFESTS["architecture"].size_budget // len(filler) + 1
        long_body = "<p>" + (filler * repeats) + "</p>"
        directory = make_dir_with_arch(tmp_path, bodies={"data-flow": long_body})
        result = _result(directory, "architecture.html")
        assert result.errors == []
        assert result.passed
        assert any("[size]" in w and "exceeds budget" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Skip rules: md-format and unknown files are skipped, never failed
# ---------------------------------------------------------------------------


class TestSkipRules:
    def test_md_artifacts_skipped(self, valid_dir: Path) -> None:
        (valid_dir / "code-quality.md").write_text("# Code Quality\n", encoding="utf-8")
        (valid_dir / "requirements.md").write_text("# Requirements\n", encoding="utf-8")
        results, skipped = val.validate_directory(valid_dir)
        assert "code-quality.md" in skipped
        assert "requirements.md" in skipped
        assert all(r.passed for r in results)
        assert {r.file for r in results} == {*val.SCAN_ARTIFACT_FILENAMES, "index.html"}

    def test_unknown_html_skipped(self, valid_dir: Path) -> None:
        (valid_dir / "scratch.html").write_text("<p>not an artifact", encoding="utf-8")
        results, skipped = val.validate_directory(valid_dir)
        assert "scratch.html" in skipped
        assert all(r.passed for r in results)

    def test_validate_file_rejects_unknown(self, tmp_path: Path) -> None:
        path = tmp_path / "scratch.html"
        path.write_text("<p>x</p>", encoding="utf-8")
        with pytest.raises(ValueError, match="Not a validatable"):
            val.validate_file(path)


# ---------------------------------------------------------------------------
# validation.json evidence (frozen schema)
# ---------------------------------------------------------------------------


class TestValidationEvidence:
    def test_validation_json_schema(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            directory = Path(".sdlc") / "artifacts"
            val.scaffold(directory, "Proj")
            for filename in val.SCAN_ARTIFACT_FILENAMES:
                fill_artifact(directory / filename)

            result = runner.invoke(main, ["artifacts", "validate"])
            assert result.exit_code == 0, result.output

            evidence = Path(".sdlc") / ".cache" / "validation.json"
            assert evidence.exists()
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        assert set(payload) == {
            "schema_version",
            "generated_at",
            "directory",
            "passed",
            "results",
            "skipped",
        }
        assert payload["schema_version"] == 1
        assert payload["passed"] is True
        assert payload["skipped"] == []
        assert len(payload["results"]) == 6
        for entry in payload["results"]:
            assert set(entry) == {"file", "type", "errors", "warnings"}
            assert entry["errors"] == []
        assert {entry["type"] for entry in payload["results"]} == {
            "index",
            "codebase-summary",
            "architecture",
            "data-model",
            "key-workflows",
            "directory-structure",
        }

    def test_evidence_written_on_failure(self, tmp_path: Path) -> None:
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            directory = Path(".sdlc") / "artifacts"
            val.scaffold(directory, "Proj")  # unfilled <main> -> structure errors

            result = runner.invoke(main, ["artifacts", "validate"])
            assert result.exit_code == 1

            evidence = Path(".sdlc") / ".cache" / "validation.json"
            assert evidence.exists()
            payload = json.loads(evidence.read_text(encoding="utf-8"))

        assert payload["passed"] is False
        failing = [e for e in payload["results"] if e["errors"]]
        assert failing

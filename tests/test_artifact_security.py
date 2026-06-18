"""Adversarial security regression suite for the HTML artifact contract (SDLC-P0041).

This is the ADVERSARIAL/regression layer that complements the per-rule unit
tests in ``tests/test_artifact_validator.py`` (do not duplicate those):

- **Escaping fixtures** (``tests/fixtures/escaping/``): static malicious-content
  artifact files, one per forbidden construct from design 3.4, plus one fully
  valid file (``architecture.html``) whose ``<main>`` carries properly escaped
  ``&lt;script&gt;`` / ``&amp;`` / ``&lt;`` and MUST pass clean (AC-005, DD-12).
- Each rejection asserts the SPECIFIC validator error category, not merely a
  non-zero result (QA rule). The parametrized rejection list is the regression
  gate: a new bypass fixture that unexpectedly validates clean fails CI.
- Validator failure writes the offending error into ``validation.json`` evidence
  (AC-007 at unit level).

The companion route-traversal corpus lives in
``tests/test_ui.py::TestArtifactRouteAdversarial``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from a_sdlc.artifacts import validator as val

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "escaping"

#: The fully-valid fixture whose escaped code excerpt must validate clean.
VALID_FIXTURE = "architecture.html"


def _validate(fixture_name: str) -> val.ValidationResult:
    """Validate a fixture file as an ``architecture`` artifact."""
    return val.validate_file(FIXTURES_DIR / fixture_name, "architecture", FIXTURES_DIR)


def _has_error(errors: list[str], *fragments: str) -> bool:
    """True when one error message contains ALL the given fragments."""
    return any(all(frag in error for frag in fragments) for error in errors)


def _assert_error(errors: list[str], *fragments: str) -> None:
    assert _has_error(errors, *fragments), f"no error containing {fragments!r} in: {errors!r}"


# ---------------------------------------------------------------------------
# AC-005 / DD-12: escaping is enforced on the raw <main> source
# ---------------------------------------------------------------------------


class TestEscapingRegression:
    """Escaped entities pass as text; raw forms fail with the specific error."""

    def test_valid_escaped_code_excerpt_passes_clean(self) -> None:
        """`&lt;script&gt;`, `&amp;`, `&lt;` as escaped text validate with zero errors."""
        result = _validate(VALID_FIXTURE)
        assert result.errors == [], result.errors
        assert result.warnings == []
        assert result.passed

    def test_raw_script_fails_forbidden(self) -> None:
        """Raw `<script>` in text is rejected as forbidden active content (not escaping)."""
        _assert_error(_validate("raw_script_in_text.html").errors, "[forbidden]", "<script>")

    def test_raw_lt_fails_escaping(self) -> None:
        """A bare `<` in a code excerpt is an [escaping] error, not silently accepted."""
        _assert_error(_validate("bare_lt_in_code.html").errors, "[escaping]", "unescaped '<'")

    def test_raw_amp_fails_escaping(self) -> None:
        """A bare `&` in a code excerpt is an [escaping] error."""
        _assert_error(_validate("bare_amp_in_code.html").errors, "[escaping]", "unescaped '&'")

    def test_escaped_text_distinct_from_raw_tag(self) -> None:
        """DD-12 nuance: `&lt;script` as escaped TEXT passes; raw `<script` fails."""
        assert _validate(VALID_FIXTURE).passed
        assert not _validate("raw_script_in_text.html").passed


# ---------------------------------------------------------------------------
# Forbidden-construct rejection corpus (design 3.4) -- the regression gate.
# Each entry: (fixture filename, *required fragments of one specific error).
# Adding a new bypass fixture that validates clean will fail these tests.
# ---------------------------------------------------------------------------

REJECTION_CORPUS: list[tuple[str, tuple[str, ...]]] = [
    ("raw_script_in_text.html", ("[forbidden]", "<script>")),
    ("bare_lt_in_code.html", ("[escaping]", "unescaped '<'")),
    ("bare_amp_in_code.html", ("[escaping]", "unescaped '&'")),
    ("onclick_attribute.html", ("[forbidden]", "onclick")),
    ("style_attribute.html", ("[forbidden]", "inline style attribute")),
    ("data_uri.html", ("[forbidden]", "'data:' URI")),
    ("javascript_uri.html", ("[forbidden]", "'javascript:' URI")),
    ("form_element.html", ("[forbidden]", "<form>")),
    ("svg_element.html", ("[forbidden]", "<svg>")),
    ("img_element.html", ("[forbidden]", "<img>")),
    ("iframe_element.html", ("[forbidden]", "<iframe>")),
    ("base_element.html", ("[forbidden]", "<base>")),
    ("link_element.html", ("[forbidden]", "<link>")),
    ("external_href.html", ("[allowlist]", "href 'https://evil.example/x.html'")),
    ("meta_http_equiv.html", ("[forbidden]", "http-equiv")),
    ("url_in_style.html", ("[forbidden]", "url() or @import")),
    ("import_in_style.html", ("[forbidden]", "url() or @import")),
]


class TestForbiddenConstructRejection:
    @pytest.mark.parametrize(
        "fixture,fragments", REJECTION_CORPUS, ids=[name for name, _ in REJECTION_CORPUS]
    )
    def test_construct_rejected_with_specific_error(
        self, fixture: str, fragments: tuple[str, ...]
    ) -> None:
        result = _validate(fixture)
        assert not result.passed, f"{fixture} unexpectedly validated clean"
        _assert_error(result.errors, *fragments)

    def test_corpus_covers_every_fixture_file(self) -> None:
        """Every fixture file on disk is exercised (no orphaned/forgotten bypass)."""
        all_files = {p.name for p in FIXTURES_DIR.glob("*") if p.is_file()}
        non_html = {name for name in all_files if not name.endswith(".html")}
        assert not non_html, f"non-.html files in escaping fixture dir: {non_html}"
        on_disk = all_files - {VALID_FIXTURE}
        in_corpus = {name for name, _ in REJECTION_CORPUS}
        assert on_disk == in_corpus, (
            f"fixtures not pinned by a rejection test: {on_disk - in_corpus}; "
            f"corpus entries without a fixture: {in_corpus - on_disk}"
        )


# ---------------------------------------------------------------------------
# AC-007 (unit level): a validator failure writes the error into validation.json
# ---------------------------------------------------------------------------


class TestEvidenceCapturesSecurityFailure:
    def test_validation_json_records_forbidden_error(self, tmp_path: Path) -> None:
        """A forbidden construct blocks (passed=False) and the error is in evidence."""
        directory = tmp_path / ".sdlc" / "artifacts"
        directory.mkdir(parents=True)
        # Copy the raw-script fixture in as a real artifact filename so it is
        # validated under the architecture manifest with no incidental noise.
        malicious = (FIXTURES_DIR / "raw_script_in_text.html").read_text(encoding="utf-8")
        (directory / "architecture.html").write_text(malicious, encoding="utf-8", newline="\n")

        results, skipped = val.validate_directory(directory)
        evidence_path = tmp_path / ".sdlc" / ".cache" / "validation.json"
        payload = val.write_evidence(directory, results, skipped, evidence_path)

        assert payload["passed"] is False
        assert evidence_path.exists()

        on_disk = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert on_disk["passed"] is False
        arch = next(r for r in on_disk["results"] if r["file"] == "architecture.html")
        assert _has_error(arch["errors"], "[forbidden]", "<script>"), arch["errors"]

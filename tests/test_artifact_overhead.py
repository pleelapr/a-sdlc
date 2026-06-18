"""AC-004 / NFR-002 byte-based structural-overhead gate (design DD-11).

Policy (revised 2026-06-10)
---------------------------
The PRD (SDLC-P0041) bounds HTML artifact size against the markdown
baseline (AC-004 / NFR-002). The REVISED, user-approved gate is:

- per file:     bytes(HTML) <= max(baseline * 1.8, baseline + 6 KiB)
- corpus total: sum(HTML bytes over the five artifacts)
                <= sum(baseline bytes) * 1.6

Rationale for the revision: the original "<= baseline +10%" form was
measured unsatisfiable on 2026-06-10 (task SDLC-T00267) -- the scaffold
chrome alone is ~4.1 KB fixed per file, which already exceeds 10% of every
baseline, and markdown->HTML markup inflates content a further ~25-75%
(measured per-file ratios 1.407 / 1.667 / 1.761 / 3.625 / 1.491; corpus
~1.55x). The PRD owner approved the revised bounds; see the PRD's Revision
History and design Appendix C. The +6 KiB absolute floor exists for tiny
artifacts (directory-structure, 1.6 KB) where fixed chrome dominates any
ratio; the 1.6x corpus cap keeps the aggregate honest below the 1.8x
per-file ceiling.

Methodology (unchanged -- DD-11)
--------------------------------
Measured deterministically in BYTES (no tokenizer dependency) against the
frozen pre-migration fixtures in ``tests/fixtures/pre_migration/``
(provenance: SDLC-T00258; expected sizes are read dynamically from
``baseline_sizes.json`` -- never hardcoded).

For each of the five artifact types this module:

1. Scaffolds the real HTML skeleton via ``a_sdlc.artifacts.validator.scaffold``
   (the same chrome every scan produces: head, inlined ``<style>``, nav
   strip, footer).
2. Ports the frozen markdown fixture's content into the ``<main>`` slot via
   a deterministic, near-minimal markdown->HTML conversion using only the
   validator's ``<main>`` vocabulary:

   - ``#``/``##`` headings -> top-level ``<section id><details open>
     <summary><h2>`` blocks (the contract's section pattern) + one flat TOC
     entry per section,
   - ``###+`` headings -> ``<h3>``/``<h4>`` (clamped so no levels skip),
   - fenced code blocks -> ``<pre><code>`` with HTML escaping,
   - pipe tables -> ``<table>/<tr>/<th|td>`` (separator row dropped),
   - bullet lists -> ``<ul>/<li>``,
   - paragraphs -> ``<p>`` with ``**bold**`` -> ``<strong>`` and
     `` `code` `` -> ``<code>``; ``&``/``<`` escaped.

3. Asserts the per-file bound ``len(html.encode("utf-8")) <=
   max(baseline_bytes * 1.8, baseline_bytes + 6144)`` and the corpus bound
   ``sum(html bytes) <= sum(baseline bytes) * 1.6``.

Anti-gaming guards (the port must be FAITHFUL, not thinned):

- ``test_port_preserves_fixture_content`` asserts the ported ``<main>``
  retains >= 90% of the fixture's non-whitespace characters (the small
  delta is markdown syntax -- ``**``, ``|``, ``#``, backticks -- that
  legitimately becomes markup).
- ``test_port_is_contract_conformant_markup`` runs the shipped validator
  over each port and asserts zero parse / forbidden / allowlist / escaping /
  anchor / a11y errors, so the measured bytes are those of real,
  contract-shaped artifact HTML. (Manifest required-section ids and
  required-section minimum-content checks are excluded: the frozen fixtures
  come from a different project, so their section names legitimately differ
  from this repo's manifests.)
"""

from __future__ import annotations

import html as html_mod
import json
import math
import re
from pathlib import Path

import pytest

from a_sdlc.artifacts.validator import MANIFESTS, scaffold, validate_file

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "pre_migration"
BASELINE_PATH = FIXTURE_DIR / "baseline_sizes.json"

#: Per-file ratio ceiling: bytes(HTML) <= baseline * 1.8 (AC-004, revised
#: 2026-06-10 -- see module docstring).
PER_FILE_MAX_RATIO = 1.8

#: Per-file absolute floor: bytes(HTML) <= baseline + 6 KiB always allowed,
#: so fixed scaffold chrome cannot fail tiny artifacts on ratio alone.
PER_FILE_FLOOR_BYTES = 6144

#: Five-artifact corpus ceiling: sum(HTML) <= sum(baseline) * 1.6.
CORPUS_MAX_RATIO = 1.6


def per_file_budget(baseline_bytes: int) -> float:
    """Revised AC-004 per-file byte budget: max(x1.8, +6 KiB)."""
    return max(baseline_bytes * PER_FILE_MAX_RATIO, baseline_bytes + PER_FILE_FLOOR_BYTES)

#: Anti-thinning guard: minimum share of the fixture's non-whitespace
#: characters that must survive into the ported <main> text content.
MIN_CONTENT_RETENTION = 0.90

#: Error categories that must be clean on the ported markup. Structure and
#: content checks are manifest-bound (required section ids belong to this
#: repo's artifacts, not the foreign-project fixtures) and are excluded.
_PORT_CLEAN_CATEGORIES = ("[parse]", "[forbidden]", "[allowlist]", "[escaping]", "[anchors]", "[a11y]")

_HEADING_TOP_RE = re.compile(r"^(#{1,2})\s+(.*)$")
_HEADING_SUB_RE = re.compile(r"^(#{3,6})\s+(.*)$")
_LIST_ITEM_RE = re.compile(r"^\s*[-*]\s+(.*)$")
_TABLE_SEP_CELL_RE = re.compile(r":?-+:?")
_MAIN_RE = re.compile(r"<main>(.*)</main>", re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def _load_baseline() -> dict[str, dict[str, int | str]]:
    with BASELINE_PATH.open(encoding="utf-8") as fh:
        baseline: dict[str, dict[str, int | str]] = json.load(fh)
    return baseline


BASELINE = _load_baseline()
FIXTURE_NAMES = sorted(BASELINE)


# ---------------------------------------------------------------------------
# Deterministic markdown -> contract HTML port (see module docstring)
# ---------------------------------------------------------------------------


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "section"


def _inline(text: str) -> str:
    text = html_mod.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


class _Section:
    def __init__(self, section_id: str, title: str) -> None:
        self.id = section_id
        self.title = title
        self.parts: list[str] = []
        self.last_heading_level = 2  # the <h2> in <summary>


def _convert_markdown(md: str) -> list[_Section]:
    """Convert fixture markdown to contract-vocabulary section blocks."""
    lines = md.split("\n")
    sections: list[_Section] = []
    paragraph: list[str] = []

    def current() -> _Section:
        if not sections:
            sections.append(_Section("preamble", "Preamble"))
        return sections[-1]

    def flush_paragraph() -> None:
        if paragraph:
            current().parts.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        if line.startswith("```"):  # fenced code block
            flush_paragraph()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # closing fence
            current().parts.append(
                "<pre><code>" + html_mod.escape("\n".join(code_lines)) + "</code></pre>"
            )
            continue

        top = _HEADING_TOP_RE.match(line)
        if top:
            flush_paragraph()
            title = top.group(2).strip()
            slug = _slugify(title)
            existing = {s.id for s in sections}
            candidate, n = slug, 2
            while candidate in existing:
                candidate = f"{slug}-{n}"
                n += 1
            sections.append(_Section(candidate, title))
            i += 1
            continue

        sub = _HEADING_SUB_RE.match(line)
        if sub:
            flush_paragraph()
            section = current()
            # Clamp into the allowed h3/h4 range without skipping levels.
            level = min(len(sub.group(1)), 4, section.last_heading_level + 1)
            level = max(level, 3)
            section.last_heading_level = level
            section.parts.append(f"<h{level}>{_inline(sub.group(2).strip())}</h{level}>")
            i += 1
            continue

        if line.startswith("|"):  # pipe table
            flush_paragraph()
            rows: list[str] = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            parts = ["<table>"]
            for row_index, row in enumerate(rows):
                cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
                if row_index == 1 and all(
                    _TABLE_SEP_CELL_RE.fullmatch(cell or "-") for cell in cells
                ):
                    continue  # markdown separator row has no HTML equivalent
                tag = "th" if row_index == 0 else "td"
                parts.append(
                    "<tr>" + "".join(f"<{tag}>{_inline(cell)}</{tag}>" for cell in cells) + "</tr>"
                )
            parts.append("</table>")
            current().parts.append("".join(parts))
            continue

        if _LIST_ITEM_RE.match(line):  # bullet list (flat)
            flush_paragraph()
            items: list[str] = []
            while i < len(lines):
                item = _LIST_ITEM_RE.match(lines[i])
                if not item:
                    break
                items.append(f"<li>{_inline(item.group(1))}</li>")
                i += 1
            current().parts.append("<ul>" + "".join(items) + "</ul>")
            continue

        if not line.strip():
            flush_paragraph()
            i += 1
            continue

        paragraph.append(line.strip())
        i += 1

    flush_paragraph()
    return sections


def _build_port(skeleton_html: str, sections: list[_Section]) -> str:
    """Frame converted sections in the real scaffold chrome (TOC + <main>)."""
    toc = "".join(
        f'<li><a href="#{s.id}">{html_mod.escape(s.title, quote=False)}</a></li>'
        for s in sections
    )
    main_blocks = [
        f'<section id="{s.id}"><details open><summary><h2>{_inline(s.title)}</h2></summary>\n'
        + "\n".join(s.parts)
        + "\n</details></section>"
        for s in sections
    ]
    html = re.sub(
        r"<main>.*?</main>",
        lambda _m: "<main>\n" + "\n".join(main_blocks) + "\n</main>",
        skeleton_html,
        flags=re.DOTALL,
    )
    return html.replace("<ul></ul>", f"<ul>{toc}</ul>", 1)


@pytest.fixture(scope="module")
def ported_artifacts(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Scaffold once, then port every frozen fixture into its skeleton."""
    directory = tmp_path_factory.mktemp("overhead")
    # Project name matches the fixtures' origin repository; it only affects
    # the <title> slot and is byte-irrelevant to the size gate.
    scaffold(directory, "realmforge")
    ports: dict[str, Path] = {}
    for fixture_name in FIXTURE_NAMES:
        stem = fixture_name.removesuffix(".md")
        markdown = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
        html_path = directory / f"{stem}.html"
        skeleton = html_path.read_text(encoding="utf-8")
        port = _build_port(skeleton, _convert_markdown(markdown))
        html_path.write_text(port, encoding="utf-8", newline="\n")
        ports[fixture_name] = html_path
    return ports


def _nonwhitespace_len(text: str) -> int:
    return len(re.sub(r"\s", "", text))


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_port_preserves_fixture_content(
    fixture_name: str, ported_artifacts: dict[str, Path]
) -> None:
    """Anti-thinning guard: the port carries essentially all fixture text."""
    markdown = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    html = ported_artifacts[fixture_name].read_text(encoding="utf-8")
    main_match = _MAIN_RE.search(html)
    assert main_match is not None
    main_text = html_mod.unescape(_TAG_RE.sub("", main_match.group(1)))

    md_chars = _nonwhitespace_len(markdown)
    html_chars = _nonwhitespace_len(main_text)
    retention = html_chars / md_chars
    assert retention >= MIN_CONTENT_RETENTION, (
        f"Ported <main> of {fixture_name} retains only {retention:.3f} of the "
        f"fixture's non-whitespace characters (minimum {MIN_CONTENT_RETENTION}). "
        "The overhead measurement is only honest for a faithful port."
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_port_is_contract_conformant_markup(
    fixture_name: str, ported_artifacts: dict[str, Path]
) -> None:
    """The measured bytes are real contract-shaped HTML, not junk markup."""
    path = ported_artifacts[fixture_name]
    result = validate_file(path)
    relevant = [
        error
        for error in result.errors
        if error.startswith(_PORT_CLEAN_CATEGORIES)
    ]
    assert not relevant, (
        f"Ported {path.name} produced non-manifest validator errors: {relevant}"
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_per_file_overhead_within_revised_budget(
    fixture_name: str, ported_artifacts: dict[str, Path]
) -> None:
    """AC-004 / NFR-002 (revised 2026-06-10): per-file byte bound.

    bytes(HTML port) <= max(baseline * 1.8, baseline + 6 KiB).
    """
    baseline_bytes = int(BASELINE[fixture_name]["bytes"])
    port_bytes = len(
        ported_artifacts[fixture_name].read_text(encoding="utf-8").encode("utf-8")
    )
    budget = per_file_budget(baseline_bytes)

    assert port_bytes <= budget, (
        f"PER-FILE OVERHEAD GATE FAILED for {fixture_name}: HTML port is "
        f"{port_bytes} bytes vs baseline {baseline_bytes} bytes -> ratio "
        f"{port_bytes / baseline_bytes:.3f}; budget "
        f"max({baseline_bytes} * {PER_FILE_MAX_RATIO}, {baseline_bytes} + "
        f"{PER_FILE_FLOOR_BYTES}) = {budget:.0f} bytes. Do not thin the ported "
        "content to pass -- investigate chrome or markup growth instead."
    )


def test_corpus_overhead_within_revised_budget(
    ported_artifacts: dict[str, Path],
) -> None:
    """AC-004 / NFR-002 (revised 2026-06-10): five-artifact corpus bound.

    sum(HTML port bytes) <= sum(markdown baseline bytes) * 1.6.
    """
    baseline_total = sum(int(BASELINE[name]["bytes"]) for name in FIXTURE_NAMES)
    port_total = sum(
        len(ported_artifacts[name].read_text(encoding="utf-8").encode("utf-8"))
        for name in FIXTURE_NAMES
    )
    budget = baseline_total * CORPUS_MAX_RATIO

    assert port_total <= budget, (
        f"CORPUS OVERHEAD GATE FAILED: HTML ports total {port_total} bytes vs "
        f"baseline total {baseline_total} bytes -> ratio "
        f"{port_total / baseline_total:.3f} (budget {CORPUS_MAX_RATIO}). Do not "
        "thin the ported content to pass -- investigate chrome or markup growth."
    )


@pytest.mark.parametrize("fixture_name", FIXTURE_NAMES)
def test_validator_size_budget_pinned_to_frozen_baseline(fixture_name: str) -> None:
    """Budget-drift guard: validator MANIFESTS budgets derive from the baselines.

    For each baseline-backed artifact type the shipped validator budget must
    equal ceil(max(baseline * 1.8, baseline + 6 KiB)) computed from the frozen
    ``baseline_sizes.json``. If either the manifest or the baseline changes
    independently, this test fails.
    """
    stem = fixture_name.removesuffix(".md")
    baseline_bytes = int(BASELINE[fixture_name]["bytes"])
    expected_budget = math.ceil(per_file_budget(baseline_bytes))

    assert MANIFESTS[stem].size_budget == expected_budget, (
        f"MANIFESTS[{stem!r}].size_budget is {MANIFESTS[stem].size_budget} but the "
        f"frozen baseline ({baseline_bytes} bytes) implies "
        f"ceil(max({baseline_bytes} * {PER_FILE_MAX_RATIO}, {baseline_bytes} + "
        f"{PER_FILE_FLOOR_BYTES})) = {expected_budget}. Validator budgets must "
        "stay pinned to the frozen pre-migration baselines."
    )

"""HTML artifact generation/validation contract (SDLC-P0041).

Single source of truth for the HTML artifact contract:

- Shared vocabulary constants (tags / attributes / diagram classes) consumed
  by both the skeleton templates and the validator allowlist.
- ``scaffold()`` writes the six skeleton files from package-data templates
  (``artifact.template.html`` / ``index.template.html``).
- ``validate_file()`` / ``validate_directory()`` implement the blocking
  validation gate using only the stdlib ``html.parser``.
- ``write_evidence()`` writes the ``.sdlc/.cache/validation.json`` evidence.

validation.json schema (FROZEN -- downstream consumers depend on it)::

    {
      "schema_version": 1,
      "generated_at": "<ISO-8601 UTC timestamp>",
      "directory": "<validated directory>",
      "passed": <bool>,                 // true when no file has errors
      "results": [                      // one entry per validated HTML file
        {
          "file": "<filename>",
          "type": "<artifact type value or 'index'>",
          "errors": ["<message>", ...],
          "warnings": ["<message>", ...]
        }
      ],
      "skipped": ["<filename>", ...]    // md-format and unknown files
    }

Validation scope rules (design 3.4): parse integrity, forbidden content,
a11y, and size budget are whole-file checks; structure contract, TOC anchor
resolution, the tag/attr/class allowlist, escaping, and semantic emptiness
are scoped to ``<main>``. Markdown-format artifacts (``code-quality.md``,
``requirements.md``) and unknown files are skipped, never failed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from importlib import resources
from pathlib import Path

from a_sdlc.artifacts.base import ArtifactType

# ---------------------------------------------------------------------------
# Shared vocabulary -- single source for skeleton authoring and the validator
# allowlist. The skeleton templates must only use items from this vocabulary;
# the composition test (scaffold output passes validate) enforces no drift.
# ---------------------------------------------------------------------------

#: Tags allowed inside <main> (design 3.6).
MAIN_ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "section", "details", "summary", "h2", "h3", "h4", "p", "ul", "ol", "li",
        "table", "thead", "tbody", "tr", "th", "td", "pre", "code", "strong", "em",
        "a", "figure", "figcaption", "div", "span", "br", "hr",
    }
)

#: Attributes allowed inside <main> (design 3.6).
MAIN_ALLOWED_ATTRS: frozenset[str] = frozenset(
    {"id", "class", "href", "open", "scope", "colspan", "rowspan"}
)

#: Composable diagram class vocabulary (DD-4). ``fallback`` is allowed but
#: never required.
DIAGRAM_CLASSES: frozenset[str] = frozenset(
    {"diagram", "row", "box", "arrow", "down", "group", "group-label", "fallback"}
)

#: HTML void elements -- never pushed on the parse-integrity tag stack.
VOID_ELEMENTS: frozenset[str] = frozenset(
    {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }
)

#: Elements rejected anywhere in the file (active / external content, NFR-003).
FORBIDDEN_ELEMENTS: frozenset[str] = frozenset(
    {
        "script", "img", "link", "base", "form", "svg", "iframe", "object",
        "embed", "audio", "video", "applet", "frame", "frameset",
    }
)

#: The six-link nav strip: (filename, label) in display order (FR-005).
NAV_LINKS: tuple[tuple[str, str], ...] = (
    ("index.html", "Index"),
    ("codebase-summary.html", "Summary"),
    ("architecture.html", "Architecture"),
    ("data-model.html", "Data Model"),
    ("key-workflows.html", "Workflows"),
    ("directory-structure.html", "Directory"),
)

#: The five scan artifact filenames (index.html is chrome, not an artifact).
SCAN_ARTIFACT_FILENAMES: tuple[str, ...] = tuple(f for f, _ in NAV_LINKS[1:])

INDEX_KEY = "index"

#: Minimum non-whitespace characters per required section (check 7).
MIN_SECTION_CHARS = 40


@dataclass(frozen=True)
class Manifest:
    """Per-file structure contract: required section ids + size budget."""

    required_sections: tuple[str, ...]
    size_budget: int  # bytes; warn threshold = max(md baseline * 1.8, + 6 KiB) (check 9)


#: Declarative manifest: required <section id> values per artifact type plus
#: a dedicated "index" entry (DD-6). Size budgets follow the revised AC-004 /
#: NFR-002 rule (2026-06-10): max(markdown baseline * 1.8, baseline + 6144)
#: using the frozen pre-migration baselines in
#: tests/fixtures/pre_migration/baseline_sizes.json (the original "+10%"
#: budgets were measured unsatisfiable). The "index" entry is navigation
#: chrome with no markdown predecessor; its budget is a fixed allowance.
MANIFESTS: dict[str, Manifest] = {
    "codebase-summary": Manifest(("overview", "key-concepts", "technology-stack"), 18_315),
    "architecture": Manifest(("component-overview", "data-flow"), 64_953),
    "data-model": Manifest(("entities",), 17_237),
    "key-workflows": Manifest(("workflows",), 40_364),
    "directory-structure": Manifest(("repository-structure",), 7_805),
    INDEX_KEY: Manifest(("artifacts",), 12_000),
}

_HEADING_RE = re.compile(r"^h([1-6])$")
_ENTITY_RE = re.compile(r"&(?:[a-zA-Z][a-zA-Z0-9]{1,31}|#[0-9]{1,7}|#[xX][0-9a-fA-F]{1,6});")
_FRAGMENT_HREF_RE = re.compile(r"^#[A-Za-z][A-Za-z0-9_-]*$")
_RELATIVE_HTML_HREF_RE = re.compile(r"^[A-Za-z0-9_-]+\.html(?:#[A-Za-z][A-Za-z0-9_-]*)?$")
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_BAD_URI_RE = re.compile(r"^\s*(?:data|javascript)\s*:", re.IGNORECASE)
_STYLE_EXTERNAL_RE = re.compile(r"url\s*\(|@import", re.IGNORECASE)
_RAW_SCRIPT_RE = re.compile(r"<\s*script", re.IGNORECASE)
_MAIN_REGION_RE = re.compile(r"<main(?:\s[^>]*)?>(.*)</main\s*>", re.DOTALL | re.IGNORECASE)
_TODO_RE = re.compile(r"\bTODO\b")
_LOREM_RE = re.compile(r"\blorem\b", re.IGNORECASE)


@dataclass
class ValidationResult:
    """Outcome of validating a single HTML file."""

    file: str
    type: str | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.file,
            "type": self.type,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# Template loading / scaffold (DD-1)
# ---------------------------------------------------------------------------


def _load_template(template_name: str) -> str:
    """Load a bundled HTML template from artifact_templates/ package data."""
    try:
        ref = resources.files("a_sdlc").joinpath("artifact_templates").joinpath(template_name)
        return ref.read_text(encoding="utf-8")
    except (TypeError, AttributeError, FileNotFoundError):
        fallback = Path(__file__).parent.parent / "artifact_templates" / template_name
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
        raise FileNotFoundError(f"Template not found: {template_name}") from None


def _set_aria_current(html: str, filename: str) -> str:
    """Mark this page's own nav link with aria-current="page" (varies per page)."""
    return html.replace(
        f'<a href="{filename}">', f'<a href="{filename}" aria-current="page">', 1
    )


def scaffold(dest_dir: Path, project_name: str, timestamp: str | None = None) -> list[Path]:
    """Write the six HTML skeleton files into dest_dir.

    Args:
        dest_dir: Target directory (created if missing).
        project_name: Project name for <title> slots.
        timestamp: Footer timestamp; defaults to today's date.

    Returns:
        List of written file paths (5 artifact skeletons + index.html).
    """
    ts = timestamp or datetime.now().strftime("%Y-%m-%d")
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    artifact_tpl = _load_template("artifact.template.html")
    for artifact_type in ArtifactType:
        if artifact_type.format != "html":
            continue
        filename = artifact_type.to_filename()
        html = (
            artifact_tpl.replace("{{artifact_title}}", artifact_type.to_title())
            .replace("{{project_name}}", project_name)
            .replace("{{timestamp}}", ts)
        )
        html = _set_aria_current(html, filename)
        path = dest_dir / filename
        path.write_text(html, encoding="utf-8", newline="\n")
        written.append(path)

    index_tpl = _load_template("index.template.html")
    html = index_tpl.replace("{{project_name}}", project_name).replace("{{timestamp}}", ts)
    html = _set_aria_current(html, "index.html")
    index_path = dest_dir / "index.html"
    index_path.write_text(html, encoding="utf-8", newline="\n")
    written.append(index_path)

    return written


# ---------------------------------------------------------------------------
# Event collector (stdlib html.parser; DD-12)
# ---------------------------------------------------------------------------


class _Collector(HTMLParser):
    """Collects structural facts via a hand-built tag stack over parser events.

    HTMLParser is non-validating, so parse integrity is implemented here:
    void elements are never pushed; mismatched/unclosed tracked tags are
    reported as [parse] errors.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.parse_errors: list[str] = []
        self.forbidden: list[str] = []
        self.allowlist_errors: list[str] = []
        self.structure_errors: list[str] = []
        # Document facts
        self.html_lang: str | None = None
        self.h1_count = 0
        self.headings: list[tuple[int, int]] = []  # (level, line)
        self.navs: list[tuple[str | None, int]] = []  # (aria-label, line)
        self.style_text: list[str] = []
        # Nav strip / TOC
        self.artifact_links: list[tuple[str, bool]] = []  # (href, has aria-current)
        self.toc_links: list[str] = []
        # <main> facts
        self.sections: list[dict[str, object]] = []  # {id, line, text: list[str]}
        self.main_ids: list[str] = []
        self.empty_lists: list[int] = []  # line numbers
        # Internal state
        self._in_style = False
        self._in_main = False
        self._in_summary = False
        self._summary_has_h2 = False
        self._main_level = -1
        self._details_depth = 0
        self._nav_labels: list[str | None] = []
        self._toc_ul_depth = 0
        self._current_section: dict[str, object] | None = None
        self._list_counts: list[list[int]] = []  # [line, li-count] per open ul/ol in main

    # -- helpers ------------------------------------------------------------

    def _line(self) -> int:
        return self.getpos()[0]

    def _nav_label(self) -> str | None:
        return self._nav_labels[-1] if self._nav_labels else None

    # -- parser events ------------------------------------------------------

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        line = self._line()
        attrs_d = dict(attrs)

        # Whole-file forbidden content (check 4)
        if tag in FORBIDDEN_ELEMENTS:
            self.forbidden.append(f"[forbidden] line {line}: <{tag}> element is not allowed")
        if tag == "meta" and "http-equiv" in attrs_d:
            self.forbidden.append(f"[forbidden] line {line}: <meta http-equiv> is not allowed")
        for name, value in attrs:
            if name.startswith("on"):
                self.forbidden.append(
                    f"[forbidden] line {line}: event handler attribute '{name}' is not allowed"
                )
            if name == "style":
                self.forbidden.append(
                    f"[forbidden] line {line}: inline style attribute is not allowed"
                )
            if value is not None and _BAD_URI_RE.match(value):
                scheme = value.split(":", 1)[0].strip().lower()
                self.forbidden.append(
                    f"[forbidden] line {line}: '{scheme}:' URI is not allowed"
                )

        # Document facts
        if tag == "html":
            self.html_lang = attrs_d.get("lang")
        heading = _HEADING_RE.match(tag)
        if heading:
            level = int(heading.group(1))
            self.headings.append((level, line))
            if level == 1:
                self.h1_count += 1
            if level == 2 and self._in_summary:
                self._summary_has_h2 = True
        if tag == "nav":
            label = attrs_d.get("aria-label")
            self.navs.append((label, line))
            self._nav_labels.append(label)
        if tag == "a" and self._nav_labels:
            href = attrs_d.get("href") or ""
            if self._nav_label() == "Artifacts":
                self.artifact_links.append((href, "aria-current" in attrs_d))
            elif self._nav_label() == "Contents":
                self.toc_links.append(href)
        if tag == "ul" and self._nav_label() == "Contents":
            if self._toc_ul_depth >= 1:
                self.structure_errors.append(
                    f"[structure] line {line}: TOC must be a flat list (nested <ul>)"
                )
            self._toc_ul_depth += 1
        if tag == "style":
            self._in_style = True

        # <main>-scoped collection (checks 2/3/5/7)
        if self._in_main and tag != "main":
            self._collect_main_element(tag, attrs, attrs_d, line)

        if tag == "main":
            self._in_main = True

        if tag not in VOID_ELEMENTS:
            self.stack.append(tag)
            if tag == "main":
                self._main_level = len(self.stack)

    def _collect_main_element(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
        attrs_d: dict[str, str | None],
        line: int,
    ) -> None:
        # Allowlist (check 5)
        if tag not in MAIN_ALLOWED_TAGS:
            self.allowlist_errors.append(
                f"[allowlist] line {line}: tag <{tag}> is not allowed in <main>"
            )
        for name, value in attrs:
            if name not in MAIN_ALLOWED_ATTRS:
                self.allowlist_errors.append(
                    f"[allowlist] line {line}: attribute '{name}' is not allowed in <main>"
                )
            elif name == "class":
                for cls in (value or "").split():
                    if cls not in DIAGRAM_CLASSES:
                        self.allowlist_errors.append(
                            f"[allowlist] line {line}: class '{cls}' is not in the "
                            f"diagram vocabulary"
                        )
            elif name == "href":
                href = value or ""
                if not (_FRAGMENT_HREF_RE.match(href) or _RELATIVE_HTML_HREF_RE.match(href)):
                    self.allowlist_errors.append(
                        f"[allowlist] line {line}: href '{href}' must be '#fragment' "
                        f"or relative '*.html'"
                    )
            elif name == "id" and not _ID_RE.match(value or ""):
                self.allowlist_errors.append(
                    f"[allowlist] line {line}: invalid id '{value}'"
                )

        if "id" in attrs_d and attrs_d["id"]:
            self.main_ids.append(str(attrs_d["id"]))

        # Top-level sections (direct children of <main>)
        if tag == "section" and len(self.stack) == self._main_level:
            section_id = attrs_d.get("id")
            if not section_id:
                self.structure_errors.append(
                    f"[structure] line {line}: top-level <section> missing id"
                )
            self._current_section = {"id": section_id or "", "line": line, "text": []}
            self.sections.append(self._current_section)

        # Structure rules: details open / nested details / summary h2 (check 2)
        if tag == "details":
            if self._details_depth >= 1:
                self.structure_errors.append(
                    f"[structure] line {line}: nested <details> are not allowed"
                )
            elif len(self.stack) == self._main_level + 1 and "open" not in attrs_d:
                self.structure_errors.append(
                    f"[structure] line {line}: top-level <details> must carry the open attribute"
                )
            self._details_depth += 1
        if tag == "summary":
            self._in_summary = True
            self._summary_has_h2 = False

        # Empty-list placeholder detection (check 7)
        if tag in ("ul", "ol"):
            self._list_counts.append([line, 0])
        if tag == "li" and self._list_counts:
            self._list_counts[-1][1] += 1

    def handle_endtag(self, tag: str) -> None:
        line = self._line()
        if tag in VOID_ELEMENTS:
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        elif tag in self.stack:
            top = self.stack[-1] if self.stack else "?"
            self.parse_errors.append(
                f"[parse] line {line}: mismatched closing tag </{tag}> (expected </{top}>)"
            )
            while self.stack and self.stack[-1] != tag:
                self.stack.pop()
            if self.stack:
                self.stack.pop()
        else:
            self.parse_errors.append(f"[parse] line {line}: unexpected closing tag </{tag}>")
            return

        if tag == "main":
            self._in_main = False
        elif tag == "style":
            self._in_style = False
        elif tag == "nav":
            if self._nav_labels:
                self._nav_labels.pop()
        elif tag == "ul" and self._nav_label() == "Contents":
            self._toc_ul_depth = max(0, self._toc_ul_depth - 1)
        elif self._in_main:
            if tag == "details":
                self._details_depth = max(0, self._details_depth - 1)
            elif tag == "summary":
                if not self._summary_has_h2:
                    self.structure_errors.append(
                        f"[structure] line {line}: <summary> must contain an <h2> heading"
                    )
                self._in_summary = False
            elif tag in ("ul", "ol") and self._list_counts:
                start_line, count = self._list_counts.pop()
                if count == 0:
                    self.empty_lists.append(start_line)
            elif tag == "section" and len(self.stack) < self._main_level + 1:
                self._current_section = None

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_text.append(data)
        elif self._in_main and self._current_section is not None and not self._in_summary:
            text_list = self._current_section["text"]
            assert isinstance(text_list, list)
            text_list.append(data)

    def finish(self) -> None:
        """Close the parser and report any unclosed tags."""
        self.close()
        if self.stack:
            self.parse_errors.append(f"[parse] unclosed tag(s): {', '.join(self.stack)}")


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------


def _line_of_offset(raw: str, offset: int) -> int:
    return raw.count("\n", 0, offset) + 1


def _check_escaping(raw: str) -> list[str]:
    """Check 6: escaping on the RAW SOURCE of the <main> region."""
    errors: list[str] = []
    match = _MAIN_REGION_RE.search(raw)
    if not match:
        return errors
    region = match.group(1)
    base = match.start(1)
    for amp in re.finditer(r"&", region):
        if not _ENTITY_RE.match(region, amp.start()):
            line = _line_of_offset(raw, base + amp.start())
            errors.append(f"[escaping] line {line}: unescaped '&' (use &amp;)")
    for lt in re.finditer(r"<", region):
        nxt = region[lt.start() + 1 : lt.start() + 2]
        if not (nxt.isalpha() or nxt in ("/", "!")):
            line = _line_of_offset(raw, base + lt.start())
            errors.append(f"[escaping] line {line}: unescaped '<' (use &lt;)")
    return errors


def _check_structure(
    collector: _Collector,
    manifest_key: str,
    manifest: Manifest,
    path: Path,
    directory: Path,
) -> list[str]:
    """Check 2: structure contract against the declarative manifest."""
    errors = list(collector.structure_errors)

    nav_labels = {label for label, _ in collector.navs}
    if "Artifacts" not in nav_labels:
        errors.append('[structure] missing <nav aria-label="Artifacts">')
    else:
        hrefs = {href for href, _ in collector.artifact_links}
        missing = [f for f, _ in NAV_LINKS if f not in hrefs]
        if missing:
            errors.append(f"[structure] Artifacts nav is missing links: {', '.join(missing)}")
        current = [href for href, has in collector.artifact_links if has]
        if current != [path.name]:
            errors.append(
                f'[structure] aria-current="page" must mark exactly this page '
                f"({path.name}); found: {current or 'none'}"
            )

    if manifest_key != INDEX_KEY and "Contents" not in nav_labels:
        errors.append('[structure] missing <nav aria-label="Contents"> (TOC)')

    section_ids = [str(s["id"]) for s in collector.sections if s["id"]]
    for required in manifest.required_sections:
        if required not in section_ids:
            errors.append(f"[structure] missing required section id '{required}'")

    seen: set[str] = set()
    for sid in collector.main_ids:
        if sid in seen:
            errors.append(f"[structure] duplicate id '{sid}' in <main>")
        seen.add(sid)

    if manifest_key == INDEX_KEY:
        for filename in SCAN_ARTIFACT_FILENAMES:
            if not (directory / filename).exists():
                errors.append(
                    f"[structure] artifact link '{filename}' does not resolve (file missing)"
                )

    return errors


def _check_anchors(collector: _Collector, manifest_key: str) -> list[str]:
    """Check 3: TOC anchors resolve in both directions (no orphans)."""
    errors: list[str] = []
    if manifest_key == INDEX_KEY:
        return errors  # index has no Contents nav

    fragments: set[str] = set()
    for href in collector.toc_links:
        if not href.startswith("#"):
            errors.append(f"[anchors] TOC link '{href}' must be a '#fragment'")
            continue
        fragment = href[1:]
        fragments.add(fragment)
        if fragment not in collector.main_ids:
            errors.append(
                f"[anchors] dangling TOC anchor '{href}' (no matching id in <main>)"
            )
    for section in collector.sections:
        sid = str(section["id"])
        if sid and sid not in fragments:
            errors.append(f"[anchors] section '{sid}' is not linked in the TOC")
    return errors


def _check_content(collector: _Collector, manifest: Manifest) -> list[str]:
    """Check 7: semantic emptiness, placeholders, duplicate sections."""
    errors: list[str] = []
    texts: dict[str, str] = {}
    for section in collector.sections:
        sid = str(section["id"])
        text_list = section["text"]
        assert isinstance(text_list, list)
        text = "".join(text_list)
        texts[sid] = text
        if _TODO_RE.search(text):
            errors.append(f"[content] section '{sid}' contains placeholder text ('TODO')")
        if _LOREM_RE.search(text):
            errors.append(f"[content] section '{sid}' contains placeholder text ('lorem')")

    for required in manifest.required_sections:
        if required not in texts:
            continue  # absence reported by the structure check
        chars = len(re.sub(r"\s", "", texts[required]))
        if chars < MIN_SECTION_CHARS:
            errors.append(
                f"[content] required section '{required}' has insufficient content "
                f"({chars} chars < {MIN_SECTION_CHARS})"
            )

    for line in collector.empty_lists:
        errors.append(f"[content] line {line}: empty <ul>/<ol> (placeholder)")

    normalized: dict[str, str] = {}
    for sid, text in texts.items():
        norm = " ".join(text.split()).lower()
        if not norm:
            continue
        if norm in normalized:
            errors.append(
                f"[content] sections '{normalized[norm]}' and '{sid}' have duplicate content"
            )
        else:
            normalized[norm] = sid
    return errors


def _check_a11y(collector: _Collector) -> list[str]:
    """Check 8: lang, single h1, heading levels, nav labels."""
    errors: list[str] = []
    if not collector.html_lang:
        errors.append("[a11y] <html> must declare lang")
    if collector.h1_count != 1:
        errors.append(f"[a11y] document must have exactly one <h1> (found {collector.h1_count})")
    prev = 0
    for level, line in collector.headings:
        if level > prev + 1:
            errors.append(f"[a11y] line {line}: skipped heading level (h{prev} -> h{level})")
        prev = level
    for label, line in collector.navs:
        if not label:
            errors.append(f"[a11y] line {line}: <nav> missing aria-label")
    return errors


# ---------------------------------------------------------------------------
# Public validation API
# ---------------------------------------------------------------------------


def validate_file(
    path: Path,
    manifest_key: str | None = None,
    directory: Path | None = None,
) -> ValidationResult:
    """Validate one HTML artifact file against its manifest.

    Args:
        path: HTML file to validate.
        manifest_key: MANIFESTS key ('index' or an artifact type value);
            derived from the filename when omitted.
        directory: Directory context for index link resolution
            (defaults to the file's parent).

    Returns:
        ValidationResult with errors and warnings.

    Raises:
        ValueError: If the file does not map to a known manifest entry.
    """
    if manifest_key is None:
        if path.name == "index.html":
            manifest_key = INDEX_KEY
        else:
            artifact_type = ArtifactType.from_filename(path.name)
            if artifact_type is None or artifact_type.format != "html":
                raise ValueError(f"Not a validatable HTML artifact: {path.name}")
            manifest_key = artifact_type.value
    try:
        manifest = MANIFESTS[manifest_key]
    except KeyError as exc:
        raise ValueError(f"Unknown manifest key: {manifest_key}") from exc
    directory = directory or path.parent

    raw = path.read_text(encoding="utf-8")
    collector = _Collector()
    collector.feed(raw)
    collector.finish()

    errors: list[str] = []
    warnings: list[str] = []

    # 1. Parse integrity (whole file)
    errors.extend(collector.parse_errors)
    # 2. Structure contract (<main> + chrome)
    errors.extend(_check_structure(collector, manifest_key, manifest, path, directory))
    # 3. TOC anchor resolution (<main>-scoped)
    errors.extend(_check_anchors(collector, manifest_key))
    # 4. No external/active content (whole file)
    errors.extend(collector.forbidden)
    style_text = "".join(collector.style_text)
    if _STYLE_EXTERNAL_RE.search(style_text):
        errors.append("[forbidden] <style> block must not contain url() or @import")
    if _RAW_SCRIPT_RE.search(raw):
        message = "[forbidden] raw '<script' sequence found in source"
        if message not in errors and not any("<script>" in e for e in errors):
            errors.append(message)
    # 5. <main> allowlist
    errors.extend(collector.allowlist_errors)
    # 6. Escaping (raw source, <main> region)
    errors.extend(_check_escaping(raw))
    # 7. Semantic emptiness (<main>-scoped)
    errors.extend(_check_content(collector, manifest))
    # 8. A11y (whole file)
    errors.extend(_check_a11y(collector))
    # 9. Size budget (whole file, warning only)
    size = len(raw.encode("utf-8"))
    if size > manifest.size_budget:
        warnings.append(
            f"[size] {size} bytes exceeds budget of {manifest.size_budget} bytes "
            f"for '{manifest_key}'"
        )

    return ValidationResult(file=path.name, type=manifest_key, errors=errors, warnings=warnings)


def validate_directory(directory: Path) -> tuple[list[ValidationResult], list[str]]:
    """Validate all HTML artifacts in a directory.

    Markdown-format artifacts and unknown files are skipped, never failed.

    Args:
        directory: Artifacts directory (e.g. .sdlc/artifacts).

    Returns:
        (results, skipped_filenames) tuple.
    """
    results: list[ValidationResult] = []
    skipped: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        if path.suffix == ".md":
            skipped.append(path.name)
            continue
        if path.suffix != ".html":
            skipped.append(path.name)
            continue
        if path.name == "index.html":
            results.append(validate_file(path, INDEX_KEY, directory))
            continue
        artifact_type = ArtifactType.from_filename(path.name)
        if artifact_type is None or artifact_type.format != "html":
            skipped.append(path.name)
            continue
        results.append(validate_file(path, artifact_type.value, directory))
    return results, skipped


def build_evidence(
    directory: Path,
    results: list[ValidationResult],
    skipped: list[str],
) -> dict[str, object]:
    """Build the frozen validation.json payload (schema in module docstring)."""
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "directory": str(directory),
        "passed": all(r.passed for r in results),
        "results": [r.to_dict() for r in results],
        "skipped": list(skipped),
    }


def write_evidence(
    directory: Path,
    results: list[ValidationResult],
    skipped: list[str],
    evidence_path: Path,
) -> dict[str, object]:
    """Write validation.json evidence, creating parent directories if missing.

    Returns:
        The payload that was written.
    """
    payload = build_evidence(directory, results, skipped)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return payload

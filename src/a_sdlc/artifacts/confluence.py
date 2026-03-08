"""
Confluence Cloud integration plugin for artifact storage.

Publishes SDLC artifacts to Confluence as wiki pages, converting
markdown to Atlassian Document Format (ADF) for Cloud API v2.

Also supports PRD (Product Requirements Document) operations with
selective pull/push from Confluence.
"""

import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

from a_sdlc.artifacts.base import Artifact, ArtifactPlugin, ArtifactType
from a_sdlc.artifacts.prd import PRD
from a_sdlc.plugins.atlassian import APITokenAuth, AtlassianClient
from a_sdlc.plugins.atlassian.client import AtlassianAPIError


class StorageToMarkdownConverter:
    """Convert Confluence Storage Format (XHTML) to Markdown.

    Handles Confluence-specific elements and converts them to
    readable markdown format.

    Supported elements:
        - Headings (h1-h6)
        - Paragraphs
        - Bullet lists (nested)
        - Numbered lists (nested)
        - Code blocks (with language hints)
        - Tables (with headers)
        - Horizontal rules
        - Inline formatting (bold, italic, code, links, strikethrough)
        - Confluence panels (info/warning/note) -> blockquotes with emoji
        - Code macros -> fenced code blocks
        - Images -> markdown image syntax
        - Expand macros -> details sections
        - Status macros -> text labels
    """

    # Confluence namespace mapping
    NAMESPACES = {
        "ac": "http://example.com/ac",  # Atlassian Cloud macros
        "ri": "http://example.com/ri",  # Resource identifiers
    }

    def convert(self, storage_content: str) -> str:
        """Convert Confluence storage format to markdown.

        Args:
            storage_content: XHTML storage format content.

        Returns:
            Markdown string.
        """
        if not storage_content or not storage_content.strip():
            return ""

        # Pre-process: decode HTML entities (like &harr;) BEFORE XML parsing
        # This prevents XML parse errors from named HTML entities
        preprocessed = html.unescape(storage_content)

        # Wrap content to handle namespace prefixes
        wrapped = self._wrap_with_namespaces(preprocessed)

        try:
            root = ET.fromstring(wrapped)
            result = self._convert_element(root).strip()
            return result
        except ET.ParseError:
            # If XML parsing fails, return raw content with basic cleanup
            return self._fallback_conversion(storage_content)

    def _wrap_with_namespaces(self, content: str) -> str:
        """Wrap content with namespace declarations.

        Args:
            content: Raw storage content.

        Returns:
            Content wrapped in a root element with namespaces.
        """
        return f"""<root xmlns:ac="http://example.com/ac" xmlns:ri="http://example.com/ri">{content}</root>"""

    def _convert_element(self, element: ET.Element, indent: int = 0) -> str:
        """Recursively convert an element to markdown.

        Args:
            element: XML element to convert.
            indent: Current indentation level for nested lists.

        Returns:
            Markdown string.
        """
        tag = self._get_local_tag(element.tag)
        text = element.text or ""
        tail = element.tail or ""

        result = ""

        # Handle different element types
        if tag == "root":
            result = self._convert_children(element, indent)

        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            # Only extract direct text, not macro descendants
            heading_text = self._get_direct_text(element)
            result = f"\n{'#' * level} {heading_text}\n"
            # Process any child macros separately
            for child in element:
                child_tag = self._get_local_tag(child.tag)
                if child_tag in ("ac:structured-macro", "structured-macro"):
                    result += self._convert_macro(child)

        elif tag == "p":
            para_text = self._convert_inline_content(element, collapse_whitespace=False)
            if para_text.strip():
                result = f"\n{para_text}\n"

        elif tag == "ul":
            result = self._convert_list(element, ordered=False, indent=indent)

        elif tag == "ol":
            result = self._convert_list(element, ordered=True, indent=indent)

        elif tag == "li":
            li_content = self._convert_inline_content(element)
            prefix = "  " * indent
            result = f"{prefix}- {li_content}\n"
            # Handle nested lists
            for child in element:
                child_tag = self._get_local_tag(child.tag)
                if child_tag in ("ul", "ol"):
                    result += self._convert_element(child, indent + 1)

        elif tag == "pre":
            code = self._get_text_content(element)
            result = f"\n```\n{code}\n```\n"

        elif tag == "code":
            result = f"`{self._get_text_content(element)}`"

        elif tag == "strong" or tag == "b":
            result = f"**{self._convert_inline_content(element)}**"

        elif tag == "em" or tag == "i":
            result = f"*{self._convert_inline_content(element)}*"

        elif tag == "s" or tag == "del" or tag == "strike":
            result = f"~~{self._convert_inline_content(element)}~~"

        elif tag == "a":
            href = element.get("href", "")
            link_text = self._get_text_content(element)
            result = f"[{link_text}]({href})"

        elif tag == "br":
            result = "\n"

        elif tag == "hr":
            result = "\n---\n"

        elif tag == "table":
            result = self._convert_table(element)

        elif tag == "ac:structured-macro" or tag == "structured-macro":
            result = self._convert_macro(element)

        elif tag == "ac:image" or tag == "image":
            result = self._convert_image(element)

        else:
            # For unknown elements, include text and process children
            result = text + self._convert_children(element, indent)

        return result + tail

    def _get_local_tag(self, tag: str) -> str:
        """Extract local tag name from namespaced tag.

        Args:
            tag: Full tag name possibly with namespace.

        Returns:
            Local tag name (lowercase for consistent matching).
        """
        if "}" in tag:
            tag = tag.split("}")[1]
        return tag.lower()

    def _convert_children(self, element: ET.Element, indent: int = 0) -> str:
        """Convert all children of an element.

        Args:
            element: Parent element.
            indent: Current indentation level.

        Returns:
            Concatenated markdown from children.
        """
        result = ""
        for child in element:
            result += self._convert_element(child, indent)
        return result

    def _get_text_content(self, element: ET.Element) -> str:
        """Get all text content from element and descendants.

        Args:
            element: Element to extract text from.

        Returns:
            Combined text content.
        """
        text = "".join(element.itertext())
        return text.replace("<![CDATA[", "").replace("]]>", "")

    def _get_direct_text(self, element: ET.Element) -> str:
        """Get text content excluding macro descendants.

        Recursively extracts text from the element and its children,
        but skips content inside macro elements (ac:structured-macro, structured-macro).

        Args:
            element: Element to extract text from.

        Returns:
            Text content excluding macro content.
        """
        parts = []
        if element.text:
            parts.append(element.text)
        for child in element:
            child_tag = self._get_local_tag(child.tag)
            # Skip macro element content - they're handled separately
            if child_tag not in ("ac:structured-macro", "structured-macro"):
                # Recursively get text from non-macro children
                parts.append(self._get_direct_text(child))
            # Always include tail (text after closing tag) for all elements
            if child.tail:
                parts.append(child.tail)
        return "".join(parts).strip()

    def _convert_inline_content(self, element: ET.Element, collapse_whitespace: bool = True) -> str:
        """Convert element content preserving inline formatting.

        Args:
            element: Element to convert.
            collapse_whitespace: If True, collapse all whitespace to single spaces.
                               If False, preserve newlines from block elements.

        Returns:
            Markdown with inline formatting.
        """
        result = element.text or ""

        for child in element:
            child_tag = self._get_local_tag(child.tag)
            # Skip nested lists - they're handled separately by _convert_list()
            if child_tag in ("ul", "ol"):
                continue
            result += self._convert_element(child, 0)

        if collapse_whitespace:
            # Collapse all whitespace to single spaces (for inline contexts)
            return " ".join(result.split())
        else:
            # Preserve newlines, only collapse horizontal whitespace
            result = re.sub(r'[ \t]+', ' ', result)  # Collapse spaces/tabs
            result = re.sub(r'\n{3,}', '\n\n', result)  # Max 2 consecutive newlines
            return result.strip()

    def _convert_list(
        self, element: ET.Element, ordered: bool, indent: int
    ) -> str:
        """Convert a list element.

        Args:
            element: ul or ol element.
            ordered: True for numbered list.
            indent: Current indentation level.

        Returns:
            Markdown list.
        """
        result = ""
        idx = 1

        for child in element:
            child_tag = self._get_local_tag(child.tag)
            if child_tag == "li":
                li_content = self._convert_inline_content(child)
                prefix = "  " * indent

                if ordered:
                    result += f"{prefix}{idx}. {li_content}\n"
                    idx += 1
                else:
                    result += f"{prefix}- {li_content}\n"

                # Handle nested lists within li
                for nested in child:
                    nested_tag = self._get_local_tag(nested.tag)
                    if nested_tag in ("ul", "ol"):
                        result += self._convert_list(
                            nested, nested_tag == "ol", indent + 1
                        )

        return result

    def _convert_table(self, element: ET.Element) -> str:
        """Convert a table element.

        Args:
            element: table element.

        Returns:
            Markdown table.
        """
        rows: list[list[str]] = []
        has_header = False

        for child in element:
            child_tag = self._get_local_tag(child.tag)

            if child_tag == "thead":
                has_header = True
                for tr in child:
                    if self._get_local_tag(tr.tag) == "tr":
                        row = self._extract_table_row(tr)
                        rows.append(row)

            elif child_tag == "tbody":
                for tr in child:
                    if self._get_local_tag(tr.tag) == "tr":
                        row = self._extract_table_row(tr)
                        rows.append(row)

            elif child_tag == "tr":
                row = self._extract_table_row(child)
                rows.append(row)

        if not rows:
            return ""

        # Build markdown table
        result = "\n"

        # If no explicit header, treat first row as header
        if not has_header and rows:
            has_header = True

        for i, row in enumerate(rows):
            result += "| " + " | ".join(row) + " |\n"

            # Add separator after header row
            if i == 0 and has_header:
                result += "| " + " | ".join(["---"] * len(row)) + " |\n"

        return result + "\n"

    def _extract_table_row(self, tr: ET.Element) -> list[str]:
        """Extract cells from a table row.

        Args:
            tr: tr element.

        Returns:
            List of cell contents.
        """
        cells: list[str] = []
        for cell in tr:
            cell_tag = self._get_local_tag(cell.tag)
            if cell_tag in ("td", "th"):
                content = self._convert_inline_content(cell).strip()
                cells.append(content)
        return cells

    def _convert_macro(self, element: ET.Element) -> str:
        """Convert Confluence macro to markdown.

        Args:
            element: ac:structured-macro element.

        Returns:
            Markdown representation.
        """
        macro_name = element.get("{http://example.com/ac}name") or element.get("name", "")

        # Handle different macro types
        if macro_name in ("info", "warning", "note", "tip"):
            return self._convert_panel_macro(element, macro_name)

        elif macro_name == "panel":
            # Extract panelType parameter (e.g., "info", "warning")
            panel_type = "info"  # default
            for param in element.iter():
                param_tag = self._get_local_tag(param.tag)
                if param_tag in ("ac:parameter", "parameter"):
                    param_name = param.get("{http://example.com/ac}name") or param.get("name", "")
                    if param_name == "panelType":
                        panel_type = param.text or "info"
                        break
            return self._convert_panel_macro(element, panel_type)

        elif macro_name == "code":
            return self._convert_code_macro(element)

        elif macro_name == "expand":
            return self._convert_expand_macro(element)

        elif macro_name == "status":
            return self._convert_status_macro(element)

        elif macro_name == "toc":
            return "\n[TOC]\n"

        elif macro_name in ("mermaid", "drawio", "diagram"):
            return self._convert_diagram_macro(element)

        else:
            # For unknown macros, try to extract rich-text-body with block separation
            body = self._find_macro_body(element)
            if body is not None:
                content = self._convert_children(body)
                if content.strip():
                    return f"\n{content}\n"
            return ""

    def _convert_diagram_macro(self, element: ET.Element) -> str:
        """Convert diagram macros to fenced code blocks."""
        macro_name = element.get("{http://example.com/ac}name") or element.get("name", "")
        content = ""

        # Check plain-text-body
        for child in element.iter():
            tag = self._get_local_tag(child.tag)
            if tag in ("plain-text-body", "ac:plain-text-body"):
                content = "".join(child.itertext()).strip()
                break

        # Fallback: use _find_macro_body which checks both rich-text-body and plain-text-body
        if not content:
            body = self._find_macro_body(element)
            if body is not None:
                content = "".join(body.itertext()).strip()

        if content:
            content = content.replace("<![CDATA[", "").replace("]]>", "").strip()
            return f"\n```{macro_name}\n{content}\n```\n"
        return ""

    def _convert_panel_macro(self, element: ET.Element, panel_type: str) -> str:
        """Convert panel macro to blockquote with emoji.

        Args:
            element: Macro element.
            panel_type: Type of panel (info, warning, note, tip).

        Returns:
            Markdown blockquote.
        """
        emoji_map = {
            "info": "ℹ️",
            "warning": "⚠️",
            "note": "📝",
            "tip": "💡",
        }
        emoji = emoji_map.get(panel_type, "")

        body = self._find_macro_body(element)
        if body is not None:
            content = self._convert_children(body).strip()
            lines = content.split("\n")
            quoted = "\n".join(f"> {line}" for line in lines)
            return f"\n> {emoji} **{panel_type.upper()}**\n{quoted}\n"

        return ""

    def _convert_code_macro(self, element: ET.Element) -> str:
        """Convert code macro to fenced code block.

        Args:
            element: Code macro element.

        Returns:
            Markdown fenced code block.
        """
        language = ""

        # Try to find language parameter
        for param in element.iter():
            param_tag = self._get_local_tag(param.tag)
            if param_tag in ("ac:parameter", "parameter"):
                param_name = param.get("{http://example.com/ac}name") or param.get("name", "")
                if param_name == "language":
                    language = param.text or ""
                    break

        # Find code content
        body = self._find_macro_body(element)
        code = self._get_text_content(body) if body is not None else ""

        return f"\n```{language}\n{code}\n```\n"

    def _convert_expand_macro(self, element: ET.Element) -> str:
        """Convert expand macro to details section.

        Args:
            element: Expand macro element.

        Returns:
            Markdown details section.
        """
        title = "Click to expand"

        # Find title parameter
        for param in element.iter():
            param_tag = self._get_local_tag(param.tag)
            if param_tag in ("ac:parameter", "parameter"):
                param_name = param.get("{http://example.com/ac}name") or param.get("name", "")
                if param_name == "title":
                    title = param.text or title
                    break

        body = self._find_macro_body(element)
        if body is not None:
            content = self._convert_children(body).strip()
            return f"\n<details>\n<summary>{title}</summary>\n\n{content}\n\n</details>\n"

        return ""

    def _convert_status_macro(self, element: ET.Element) -> str:
        """Convert status macro to text label.

        Args:
            element: Status macro element.

        Returns:
            Markdown text badge.
        """
        color = "grey"
        title = "Status"

        for param in element.iter():
            param_tag = self._get_local_tag(param.tag)
            if param_tag in ("ac:parameter", "parameter"):
                param_name = param.get("{http://example.com/ac}name") or param.get("name", "")
                if param_name == "colour" or param_name == "color":
                    color = param.text or color
                elif param_name == "title":
                    title = param.text or title

        return f"[{title}]"

    def _convert_image(self, element: ET.Element) -> str:
        """Convert image element to markdown.

        Args:
            element: ac:image element.

        Returns:
            Markdown image.
        """
        # Try to find attachment reference
        for child in element:
            child_tag = self._get_local_tag(child.tag)
            if child_tag in ("ri:attachment", "attachment"):
                filename = child.get("{http://example.com/ri}filename") or child.get("filename", "")
                if filename:
                    return f"![{filename}]({filename})"

            elif child_tag in ("ri:url", "url"):
                url = child.get("{http://example.com/ri}value") or child.get("value", "")
                if url:
                    return f"![]({url})"

        return ""

    def _find_macro_body(self, element: ET.Element) -> ET.Element | None:
        """Find the rich-text-body or plain-text-body in a macro.

        Args:
            element: Macro element.

        Returns:
            Body element if found, None otherwise.
        """
        for child in element.iter():
            child_tag = self._get_local_tag(child.tag)
            if child_tag in (
                "ac:rich-text-body",
                "rich-text-body",
                "ac:plain-text-body",
                "plain-text-body",
            ):
                return child
        return None

    def _fallback_conversion(self, content: str) -> str:
        """Fallback conversion when XML parsing fails.

        Performs basic HTML tag stripping and entity conversion.

        Args:
            content: Raw storage content.

        Returns:
            Cleaned text.
        """
        # Remove XML/HTML tags
        text = re.sub(r"<[^>]+>", "", content)

        # Convert common entities
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&amp;", "&")
        text = text.replace("&quot;", '"')
        text = text.replace("&apos;", "'")
        text = text.replace("&nbsp;", " ")

        return text.strip()


class MarkdownToADFConverter:
    """Convert markdown to Atlassian Document Format (ADF).

    Supports basic markdown elements:
    - Headings (h1-h6)
    - Paragraphs
    - Bold, italic, code (inline)
    - Code blocks with language
    - Bullet lists
    - Numbered lists
    - Links
    - Horizontal rules
    - Tables (basic)
    """

    def convert(self, markdown: str) -> dict:
        """Convert markdown string to ADF document.

        Args:
            markdown: Markdown content.

        Returns:
            ADF document structure.
        """
        content: list[dict[str, Any]] = []
        lines = markdown.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i]

            # Code blocks
            if line.startswith("```"):
                block, i = self._parse_code_block(lines, i)
                content.append(block)
                continue

            # Headings
            if line.startswith("#"):
                content.append(self._parse_heading(line))
                i += 1
                continue

            # Horizontal rule
            if re.match(r"^(-{3,}|_{3,}|\*{3,})$", line.strip()):
                content.append({"type": "rule"})
                i += 1
                continue

            # Bullet list
            if re.match(r"^\s*[-*]\s+", line):
                block, i = self._parse_bullet_list(lines, i)
                content.append(block)
                continue

            # Numbered list
            if re.match(r"^\s*\d+\.\s+", line):
                block, i = self._parse_numbered_list(lines, i)
                content.append(block)
                continue

            # Table
            if "|" in line and i + 1 < len(lines) and re.match(r"^\|[-:\s|]+\|$", lines[i + 1].strip()):
                block, i = self._parse_table(lines, i)
                content.append(block)
                continue

            # Paragraph (non-empty lines)
            if line.strip():
                content.append(self._parse_paragraph(line))

            i += 1

        return {
            "type": "doc",
            "version": 1,
            "content": content,
        }

    def _parse_inline(self, text: str) -> list[dict]:
        """Parse inline markdown elements.

        Args:
            text: Text with potential inline formatting.

        Returns:
            List of ADF inline nodes.
        """
        nodes: list[dict] = []

        # Pattern for inline elements
        pattern = r"(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\))"
        parts = re.split(pattern, text)

        for part in parts:
            if not part:
                continue

            # Code
            if part.startswith("`") and part.endswith("`"):
                nodes.append({
                    "type": "text",
                    "text": part[1:-1],
                    "marks": [{"type": "code"}],
                })
            # Bold
            elif part.startswith("**") and part.endswith("**"):
                nodes.append({
                    "type": "text",
                    "text": part[2:-2],
                    "marks": [{"type": "strong"}],
                })
            # Italic (asterisk or underscore)
            elif (part.startswith("*") and part.endswith("*")) or (part.startswith("_") and part.endswith("_")):
                nodes.append({
                    "type": "text",
                    "text": part[1:-1],
                    "marks": [{"type": "em"}],
                })
            # Link
            elif part.startswith("["):
                match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", part)
                if match:
                    nodes.append({
                        "type": "text",
                        "text": match.group(1),
                        "marks": [{"type": "link", "attrs": {"href": match.group(2)}}],
                    })
            # Plain text
            else:
                nodes.append({"type": "text", "text": part})

        return nodes if nodes else [{"type": "text", "text": text}]

    def _parse_heading(self, line: str) -> dict:
        """Parse markdown heading."""
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            level = len(match.group(1))
            text = match.group(2)
            return {
                "type": "heading",
                "attrs": {"level": level},
                "content": self._parse_inline(text),
            }
        return {"type": "paragraph", "content": [{"type": "text", "text": line}]}

    def _parse_paragraph(self, line: str) -> dict:
        """Parse paragraph with inline formatting."""
        return {
            "type": "paragraph",
            "content": self._parse_inline(line),
        }

    def _parse_code_block(self, lines: list[str], start: int) -> tuple[dict, int]:
        """Parse fenced code block."""
        first_line = lines[start]
        language = first_line[3:].strip() or None

        code_lines: list[str] = []
        i = start + 1

        while i < len(lines):
            if lines[i].startswith("```"):
                i += 1
                break
            code_lines.append(lines[i])
            i += 1

        block: dict[str, Any] = {
            "type": "codeBlock",
            "content": [{"type": "text", "text": "\n".join(code_lines)}],
        }
        if language:
            block["attrs"] = {"language": language}

        return block, i

    def _parse_bullet_list(self, lines: list[str], start: int) -> tuple[dict, int]:
        """Parse bullet list."""
        items: list[dict] = []
        i = start

        while i < len(lines):
            match = re.match(r"^\s*[-*]\s+(.+)$", lines[i])
            if match:
                items.append({
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": self._parse_inline(match.group(1))},
                    ],
                })
                i += 1
            else:
                break

        return {"type": "bulletList", "content": items}, i

    def _parse_numbered_list(self, lines: list[str], start: int) -> tuple[dict, int]:
        """Parse numbered list."""
        items: list[dict] = []
        i = start

        while i < len(lines):
            match = re.match(r"^\s*\d+\.\s+(.+)$", lines[i])
            if match:
                items.append({
                    "type": "listItem",
                    "content": [
                        {"type": "paragraph", "content": self._parse_inline(match.group(1))},
                    ],
                })
                i += 1
            else:
                break

        return {"type": "orderedList", "content": items}, i

    def _parse_table(self, lines: list[str], start: int) -> tuple[dict, int]:
        """Parse markdown table."""
        rows: list[dict] = []
        i = start

        # Header row
        header_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
        rows.append({
            "type": "tableRow",
            "content": [
                {
                    "type": "tableHeader",
                    "content": [{"type": "paragraph", "content": self._parse_inline(cell)}],
                }
                for cell in header_cells
            ],
        })
        i += 2  # Skip separator row

        # Data rows
        while i < len(lines) and "|" in lines[i]:
            cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows.append({
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "content": [{"type": "paragraph", "content": self._parse_inline(cell)}],
                    }
                    for cell in cells
                ],
            })
            i += 1

        return {"type": "table", "content": rows}, i


class ConfluencePlugin(ArtifactPlugin):
    """Store artifacts as Confluence wiki pages.

    This plugin publishes SDLC artifacts to Confluence Cloud,
    converting markdown to ADF format and managing page hierarchy.

    Configuration:
        - base_url: Atlassian site URL (e.g., https://company.atlassian.net)
        - email: Atlassian account email
        - api_token: API token (or set ATLASSIAN_API_TOKEN env var)
        - space_key: Confluence space key (e.g., 'PROJ')
        - parent_page_id: Optional parent page ID (manual override)
        - root_page_title: Auto-create root page with this title (default: 'ASDLC')
        - page_title_prefix: Prefix for page titles (default: '[SDLC]')
        - subfolders: Map artifact types to subfolder names (e.g., {'requirements': 'PRDs'})

    Page Hierarchy:
        Space Root
        └── {root_page_title} (e.g., "ASDLC")
            ├── [SDLC] Architecture
            ├── [SDLC] Codebase Summary
            ├── PRDs (subfolder for requirements)
            │   └── [SDLC] Requirements
            └── ...
    """

    DEFAULT_PREFIX = "[SDLC]"
    DEFAULT_ROOT_TITLE = "ASDLC"

    def __init__(self, config: dict) -> None:
        """Initialize Confluence plugin.

        Args:
            config: Configuration with base_url, space_key, etc.
        """
        super().__init__(config)

        self.base_url = config.get("base_url", "")
        self.email = config.get("email", "")
        self.api_token = config.get("api_token", "")
        self.space_key = config.get("space_key", "")
        self.parent_page_id = config.get("parent_page_id")  # Manual override
        self.root_page_title = config.get("root_page_title", self.DEFAULT_ROOT_TITLE)
        self.page_title_prefix = config.get("page_title_prefix", self.DEFAULT_PREFIX)
        self.subfolders = config.get("subfolders", {})  # e.g., {"requirements": "PRDs"}

        self._client: AtlassianClient | None = None
        self._converter = MarkdownToADFConverter()
        self._page_cache: dict[str, dict] = {}
        self._parent_page_cache: dict[str, str] = {}  # Cache for parent page IDs

    def _check_configured(self) -> None:
        """Verify plugin is properly configured."""
        if not self.base_url or not self.space_key:
            raise RuntimeError(
                "Confluence plugin not configured. Run: a-sdlc plugins configure confluence"
            )

    def _get_client(self) -> AtlassianClient:
        """Get or create Atlassian client."""
        if self._client is None:
            auth = APITokenAuth(email=self.email, api_token=self.api_token)
            self._client = AtlassianClient(self.base_url, auth)
        return self._client

    def _get_page_title(self, artifact: Artifact) -> str:
        """Generate Confluence page title for artifact."""
        return f"{self.page_title_prefix} {artifact.title}"

    def _find_page_by_title(self, title: str) -> dict | None:
        """Find a Confluence page by title in the configured space.

        Args:
            title: Page title to search for (exact match).

        Returns:
            Page dict if found, None otherwise.
        """
        client = self._get_client()

        # Use CQL to search - note: CQL title search is "contains", not exact match
        # So we search by space and then filter for exact title match
        cql = f'space = "{self.space_key}" AND type = "page"'

        try:
            response = client.get(
                "/wiki/rest/api/content",
                params={"cql": cql, "expand": "version,body.storage,space", "limit": 100},
            )

            results = response.get("results", []) if isinstance(response, dict) else []

            # Filter for exact title match AND correct space
            for page in results:
                page_title = page.get("title", "")
                page_space = page.get("space", {}).get("key", "")

                if page_title == title and page_space == self.space_key:
                    return page

        except AtlassianAPIError:
            pass

        return None

    def _get_or_create_page(self, title: str, parent_id: str | None = None) -> str:
        """Find existing page or create a new empty container page.

        Used for auto-creating root pages and subfolder pages in the hierarchy.

        Args:
            title: Page title to find/create.
            parent_id: Optional parent page ID.

        Returns:
            Page ID (existing or newly created).
        """
        # Check cache first
        cache_key = f"page:{title}"
        if cache_key in self._parent_page_cache:
            return self._parent_page_cache[cache_key]

        # Check if page exists
        existing = self._find_page_by_title(title)
        if existing:
            page_id = existing["id"]
            self._parent_page_cache[cache_key] = page_id
            return page_id

        # Create empty container page with minimal ADF content
        client = self._get_client()
        page_data: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": self.space_key},
            "body": {
                "atlas_doc_format": {
                    "value": json.dumps({
                        "type": "doc",
                        "version": 1,
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [
                                    {"type": "text", "text": "Container page for SDLC artifacts."}
                                ],
                            }
                        ],
                    }),
                    "representation": "atlas_doc_format",
                },
            },
        }
        if parent_id:
            page_data["ancestors"] = [{"id": parent_id}]

        response = client.post("/wiki/rest/api/content", page_data)
        page_id = response["id"] if isinstance(response, dict) else ""

        # Cache the result
        self._parent_page_cache[cache_key] = page_id
        return page_id

    def _get_parent_page_id(self, artifact: Artifact) -> str | None:
        """Get or create the appropriate parent page for an artifact.

        Implements hierarchy: root_page → subfolder (if configured) → artifact

        Priority:
        1. Manual parent_page_id override (if set in config)
        2. Auto-created hierarchy based on root_page_title and subfolders

        Args:
            artifact: Artifact being stored.

        Returns:
            Parent page ID, or None if no hierarchy configured.
        """
        # Manual override takes precedence
        if self.parent_page_id:
            return self.parent_page_id

        # No root page configured means no hierarchy
        if not self.root_page_title:
            return None

        # Cache key for the artifact type's parent
        cache_key = f"parent:{artifact.artifact_type.value}"
        if cache_key in self._parent_page_cache:
            return self._parent_page_cache[cache_key]

        # 1. Get or create root page (e.g., "ASDLC")
        root_id = self._get_or_create_page(self.root_page_title)

        # 2. Check if this artifact type needs a subfolder
        subfolder_name = self.subfolders.get(artifact.artifact_type.value)

        if subfolder_name:
            # Create subfolder under root (e.g., "PRDs" under "ASDLC")
            parent_id = self._get_or_create_page(subfolder_name, parent_id=root_id)
        else:
            # Direct child of root
            parent_id = root_id

        # Cache for future calls
        self._parent_page_cache[cache_key] = parent_id
        return parent_id

    def _create_page(self, artifact: Artifact) -> dict:
        """Create a new Confluence page.

        Args:
            artifact: Artifact to create page for.

        Returns:
            Created page dict from API.
        """
        client = self._get_client()
        title = self._get_page_title(artifact)

        # Convert markdown to ADF
        adf_content = self._converter.convert(artifact.content)

        # Add metadata panel at top
        metadata_panel = self._create_metadata_panel(artifact)
        adf_content["content"].insert(0, metadata_panel)

        page_data: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": self.space_key},
            "body": {
                "atlas_doc_format": {
                    "value": json.dumps(adf_content),
                    "representation": "atlas_doc_format",
                },
            },
        }

        # Set parent page using hierarchy (auto-create root/subfolders if needed)
        parent_id = self._get_parent_page_id(artifact)
        if parent_id:
            page_data["ancestors"] = [{"id": parent_id}]

        response = client.post("/wiki/rest/api/content", page_data)
        return response if isinstance(response, dict) else {}

    def _update_page(self, page_id: str, artifact: Artifact, version: int) -> dict:
        """Update an existing Confluence page.

        Args:
            page_id: Confluence page ID.
            artifact: Artifact with updated content.
            version: Current page version (will be incremented).

        Returns:
            Updated page dict from API.
        """
        client = self._get_client()
        title = self._get_page_title(artifact)

        # Convert markdown to ADF
        adf_content = self._converter.convert(artifact.content)

        # Add metadata panel at top
        metadata_panel = self._create_metadata_panel(artifact)
        adf_content["content"].insert(0, metadata_panel)

        page_data = {
            "type": "page",
            "title": title,
            "version": {"number": version + 1},
            "body": {
                "atlas_doc_format": {
                    "value": json.dumps(adf_content),
                    "representation": "atlas_doc_format",
                },
            },
        }

        response = client.put(f"/wiki/rest/api/content/{page_id}", page_data)
        return response if isinstance(response, dict) else {}

    def _create_metadata_panel(self, artifact: Artifact) -> dict:
        """Create ADF panel with artifact metadata."""
        return {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "SDLC Artifact", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": f" | Type: {artifact.artifact_type.to_title()}"},
                        {"type": "text", "text": f" | Version: {artifact.version}"},
                        {"type": "text", "text": f" | Updated: {artifact.updated_at.strftime('%Y-%m-%d %H:%M')}"},
                    ],
                },
            ],
        }

    def _parse_confluence_page(self, page: dict) -> Artifact:
        """Parse Confluence page into Artifact object.

        Converts Confluence storage format to markdown for local use.
        """
        title = page.get("title", "")

        # Remove prefix from title
        if title.startswith(self.page_title_prefix):
            title = title[len(self.page_title_prefix):].strip()

        # Determine artifact type from title
        artifact_type = ArtifactType.CODEBASE_SUMMARY
        for atype in ArtifactType:
            if atype.to_title().lower() in title.lower():
                artifact_type = atype
                break

        # Get page content (storage format)
        body = page.get("body", {})
        storage_content = body.get("storage", {}).get("value", "") if "storage" in body else ""

        # Convert storage format to markdown
        converter = StorageToMarkdownConverter()
        markdown_content = converter.convert(storage_content)

        # Parse dates
        version_info = page.get("version", {})
        when = version_info.get("when", "")

        return Artifact(
            id=artifact_type.value,
            artifact_type=artifact_type,
            title=title,
            content=markdown_content,
            version=str(version_info.get("number", 1)),
            updated_at=datetime.fromisoformat(when.replace("Z", "+00:00")) if when else datetime.now(),
            external_id=page.get("id"),
            external_url=f"{self.base_url}/wiki{page.get('_links', {}).get('webui', '')}",
        )

    def store_artifact(self, artifact: Artifact) -> str:
        """Store artifact as Confluence page.

        Creates a new page or updates existing one.
        """
        self._check_configured()

        title = self._get_page_title(artifact)
        existing_page = self._find_page_by_title(title)

        try:
            if existing_page:
                # Update existing page
                page_id = existing_page["id"]
                version = existing_page.get("version", {}).get("number", 1)
                page = self._update_page(page_id, artifact, version)
            else:
                # Create new page
                page = self._create_page(artifact)

            if page and "id" in page:
                artifact.external_id = page["id"]
                artifact.external_url = f"{self.base_url}/wiki{page.get('_links', {}).get('webui', '')}"
                self._page_cache[artifact.id] = page
                return page["id"]

        except AtlassianAPIError as e:
            raise RuntimeError(f"Failed to store artifact in Confluence: {e}") from e

        return artifact.id

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Retrieve artifact from Confluence.

        Args:
            artifact_id: Either local artifact ID or Confluence page ID.
        """
        self._check_configured()
        client = self._get_client()

        # If it looks like a page ID (numeric), fetch directly
        if artifact_id.isdigit():
            try:
                response = client.get(
                    f"/wiki/rest/api/content/{artifact_id}",
                    params={"expand": "version,body.storage"},
                )
                if isinstance(response, dict):
                    return self._parse_confluence_page(response)
            except AtlassianAPIError:
                pass
        else:
            # Search by constructed title
            artifact_type = ArtifactType.from_filename(f"{artifact_id}.md")
            if artifact_type:
                title = f"{self.page_title_prefix} {artifact_type.to_title()}"
                page = self._find_page_by_title(title)
                if page:
                    return self._parse_confluence_page(page)

        return None

    def list_artifacts(self, artifact_type: ArtifactType | None = None) -> list[Artifact]:
        """List SDLC artifacts under the ASDLC hierarchy.

        Only returns artifacts that are children of the root page or its
        configured subfolders, not pages from anywhere in the space.
        """
        self._check_configured()
        client = self._get_client()

        # Find the root page (don't create during listing)
        root_page = self._find_page_by_title(self.root_page_title)
        if not root_page:
            return []

        root_id = root_page["id"]
        all_pages: list[dict] = []

        # Get direct children of ASDLC root
        try:
            response = client.get(
                f"/wiki/rest/api/content/{root_id}/child/page",
                params={"expand": "version,body.storage", "limit": 100},
            )
            all_pages.extend(response.get("results", []) if isinstance(response, dict) else [])
        except AtlassianAPIError:
            pass

        # Get children from each configured subfolder
        for subfolder_name in self.subfolders.values():
            try:
                subfolder_page = self._find_page_by_title(subfolder_name)
                if subfolder_page:
                    response = client.get(
                        f"/wiki/rest/api/content/{subfolder_page['id']}/child/page",
                        params={"expand": "version,body.storage", "limit": 100},
                    )
                    all_pages.extend(response.get("results", []) if isinstance(response, dict) else [])
            except AtlassianAPIError:
                continue

        # Filter by title prefix and convert to artifacts
        artifacts = []
        for page in all_pages:
            title = page.get("title", "")
            if not title.startswith(self.page_title_prefix):
                continue

            artifact = self._parse_confluence_page(page)
            if artifact_type is None or artifact.artifact_type == artifact_type:
                artifacts.append(artifact)

        return sorted(artifacts, key=lambda a: a.id)

    def delete_artifact(self, artifact_id: str) -> None:
        """Delete artifact page from Confluence.

        Note: This permanently deletes the Confluence page.
        """
        self._check_configured()
        client = self._get_client()

        # Find page ID
        page_id = artifact_id if artifact_id.isdigit() else None

        if not page_id:
            # Search by title
            artifact_type = ArtifactType.from_filename(f"{artifact_id}.md")
            if artifact_type:
                title = f"{self.page_title_prefix} {artifact_type.to_title()}"
                page = self._find_page_by_title(title)
                if page:
                    page_id = page["id"]

        if not page_id:
            raise KeyError(f"Artifact not found: {artifact_id}")

        try:
            client.delete(f"/wiki/rest/api/content/{page_id}")
        except AtlassianAPIError as e:
            raise RuntimeError(f"Failed to delete Confluence page: {e}") from e

    def publish_all(self, local_artifacts_dir: str) -> dict[str, str]:
        """Publish all local artifacts to Confluence.

        Args:
            local_artifacts_dir: Path to .sdlc/artifacts/ directory.

        Returns:
            Dict mapping artifact IDs to Confluence page URLs.
        """
        from pathlib import Path

        published: dict[str, str] = {}
        artifacts_dir = Path(local_artifacts_dir)

        if not artifacts_dir.exists():
            return published

        for md_file in artifacts_dir.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            artifact = Artifact.from_file(str(md_file), content)

            try:
                self.store_artifact(artifact)
                if artifact.external_url:
                    published[artifact.id] = artifact.external_url
            except RuntimeError:
                # Continue with other artifacts on failure
                pass

        return published

    def get_confluence_instructions(self, artifact: Artifact) -> str:
        """Generate instructions for manual Confluence page creation.

        Returns:
            Markdown-formatted instructions.
        """
        title = self._get_page_title(artifact)

        return f"""## Create Confluence Page

**To create this artifact in Confluence:**

1. Navigate to space: `{self.space_key}`
2. Create a new page with title: `{title}`
3. Copy the markdown content below

**Page Title:** `{title}`
**Space:** `{self.space_key}`
{f"**Parent Page ID:** `{self.parent_page_id}`" if self.parent_page_id else ""}

---

After creating the page manually, the link will be tracked on next sync.
"""

    # ==========================================================================
    # PRD (Product Requirements Document) Methods
    # ==========================================================================

    PRD_FOLDER_NAME = "PRDs"  # Default subfolder for PRDs under root

    def _get_prds_folder_id(self) -> str:
        """Get or create the PRDs folder under the root page.

        Returns:
            Page ID of the PRDs folder.
        """
        # Cache key for PRDs folder
        cache_key = "folder:prds"
        if cache_key in self._parent_page_cache:
            return self._parent_page_cache[cache_key]

        # Get or create root page first
        root_id = self._get_or_create_page(self.root_page_title)

        # Get or create PRDs folder under root
        folder_name = self.subfolders.get("requirements", self.PRD_FOLDER_NAME)
        folder_id = self._get_or_create_page(folder_name, parent_id=root_id)

        self._parent_page_cache[cache_key] = folder_id
        return folder_id

    def list_prds(self) -> list[dict]:
        """List all PRD pages under the PRDs subfolder.

        Returns:
            List of dicts with 'id', 'title', and 'url' for each PRD page.
        """
        self._check_configured()
        client = self._get_client()

        prds_folder_id = self._get_prds_folder_id()

        # Use child pages endpoint instead of CQL (more reliable)
        try:
            response = client.get(
                f"/wiki/rest/api/content/{prds_folder_id}/child/page",
                params={"expand": "version", "limit": 100},
            )

            results = response.get("results", []) if isinstance(response, dict) else []

            prds = []
            for page in results:
                title = page.get("title", "")
                # Remove prefix if present
                if title.startswith(self.page_title_prefix):
                    title = title[len(self.page_title_prefix):].strip()

                prds.append({
                    "id": page.get("id"),
                    "title": title,
                    "url": f"{self.base_url}/wiki{page.get('_links', {}).get('webui', '')}",
                    "version": page.get("version", {}).get("number", 1),
                })

            return sorted(prds, key=lambda p: p["title"])

        except AtlassianAPIError:
            return []

    def get_prd_page(self, title: str) -> dict | None:
        """Get specific PRD page by title.

        Args:
            title: PRD title (with or without prefix).

        Returns:
            Page dict if found, None otherwise.
        """
        self._check_configured()

        # Try with and without prefix
        titles_to_try = [
            title,
            f"{self.page_title_prefix} {title}",
        ]

        for try_title in titles_to_try:
            page = self._find_page_by_title(try_title)
            if page:
                return page

        return None

    def pull_prd(self, title: str) -> PRD:
        """Pull PRD from Confluence and convert to markdown.

        Args:
            title: PRD title in Confluence.

        Returns:
            PRD object with markdown content.

        Raises:
            KeyError: If PRD not found in Confluence.
        """
        self._check_configured()
        client = self._get_client()

        # Find page by title
        page = self.get_prd_page(title)
        if not page:
            raise KeyError(f"PRD not found in Confluence: {title}")

        page_id = page.get("id")

        # Get page content in storage format
        try:
            response = client.get(
                f"/wiki/rest/api/content/{page_id}",
                params={"expand": "body.storage,version"},
            )
        except AtlassianAPIError as e:
            raise RuntimeError(f"Failed to fetch PRD from Confluence: {e}") from e

        # Extract content
        body = response.get("body", {}) if isinstance(response, dict) else {}
        storage_content = body.get("storage", {}).get("value", "")

        # Convert storage format to markdown
        converter = StorageToMarkdownConverter()
        markdown_content = converter.convert(storage_content)

        # Extract title (remove prefix if present)
        page_title = response.get("title", title) if isinstance(response, dict) else title
        if page_title.startswith(self.page_title_prefix):
            page_title = page_title[len(self.page_title_prefix):].strip()

        # Create PRD object
        from a_sdlc.artifacts.prd import PRD, _slugify

        version_info = response.get("version", {}) if isinstance(response, dict) else {}
        when = version_info.get("when", "")

        return PRD(
            id=_slugify(page_title),
            title=page_title,
            content=markdown_content,
            version=str(version_info.get("number", 1)),
            updated_at=datetime.fromisoformat(when.replace("Z", "+00:00")) if when else datetime.now(),
            external_id=page_id,
            external_url=f"{self.base_url}/wiki{response.get('_links', {}).get('webui', '')}" if isinstance(response, dict) else None,
        )

    def push_prd(self, prd: PRD) -> str:
        """Push PRD to Confluence under PRDs subfolder.

        Creates a new page or updates existing one.

        Args:
            prd: PRD to push.

        Returns:
            Confluence page ID.
        """
        self._check_configured()
        client = self._get_client()

        title = f"{self.page_title_prefix} {prd.title}"
        existing_page = self._find_page_by_title(title)

        # Convert markdown to ADF
        adf_content = self._converter.convert(prd.content)

        # Add metadata panel at top
        metadata_panel = {
            "type": "panel",
            "attrs": {"panelType": "info"},
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "Product Requirements Document", "marks": [{"type": "strong"}]},
                        {"type": "text", "text": f" | Version: {prd.version}"},
                        {"type": "text", "text": f" | Updated: {prd.updated_at.strftime('%Y-%m-%d %H:%M')}"},
                    ],
                },
            ],
        }
        adf_content["content"].insert(0, metadata_panel)

        try:
            if existing_page:
                # Update existing page
                page_id = existing_page["id"]
                version = existing_page.get("version", {}).get("number", 1)

                page_data = {
                    "type": "page",
                    "title": title,
                    "version": {"number": version + 1},
                    "body": {
                        "atlas_doc_format": {
                            "value": json.dumps(adf_content),
                            "representation": "atlas_doc_format",
                        },
                    },
                }

                response = client.put(f"/wiki/rest/api/content/{page_id}", page_data)
            else:
                # Create new page under PRDs folder
                prds_folder_id = self._get_prds_folder_id()

                page_data: dict[str, Any] = {
                    "type": "page",
                    "title": title,
                    "space": {"key": self.space_key},
                    "ancestors": [{"id": prds_folder_id}],
                    "body": {
                        "atlas_doc_format": {
                            "value": json.dumps(adf_content),
                            "representation": "atlas_doc_format",
                        },
                    },
                }

                response = client.post("/wiki/rest/api/content", page_data)

            if response and isinstance(response, dict) and "id" in response:
                prd.external_id = response["id"]
                prd.external_url = f"{self.base_url}/wiki{response.get('_links', {}).get('webui', '')}"
                return response["id"]

        except AtlassianAPIError as e:
            raise RuntimeError(f"Failed to push PRD to Confluence: {e}") from e

        return prd.id

    def delete_prd(self, title_or_id: str) -> None:
        """Delete a PRD page from Confluence.

        Args:
            title_or_id: PRD title or Confluence page ID.

        Raises:
            KeyError: If PRD not found.
        """
        self._check_configured()
        client = self._get_client()

        # Find page ID
        page_id = title_or_id if title_or_id.isdigit() else None

        if not page_id:
            page = self.get_prd_page(title_or_id)
            if page:
                page_id = page.get("id")

        if not page_id:
            raise KeyError(f"PRD not found: {title_or_id}")

        try:
            client.delete(f"/wiki/rest/api/content/{page_id}")
        except AtlassianAPIError as e:
            raise RuntimeError(f"Failed to delete PRD from Confluence: {e}") from e

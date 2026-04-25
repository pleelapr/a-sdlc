"""Thread context assembly for agent prompts.

Implements FR-015 through FR-018 and NFR-001 from SDLC-P0031:
- Hierarchical thread context: Task thread + parent PRD thread + sprint thread
- Conversation log formatting with persona attribution
- Truncation with most-recent priority, user interventions always preserved
- Configurable token limit (default ~10K tokens)

Persona loading and parsing (FR-001 through FR-003):
- Persona definitions loaded from markdown files with structured frontmatter
- Project-level persona overrides take precedence over built-in personas
- Graceful degradation when persona files are missing or malformed
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Built-in personas directory (sibling to this module)
PERSONA_DIR = Path(__file__).parent / "personas"

# Sections extracted from persona markdown body into the returned dict.
# Order matters: these are checked in sequence when scanning headers.
_EXTRACTED_SECTIONS = (
    "Triggers",
    "Behavioral Mindset",
    "Focus Areas",
    "Key Actions",
)

# Maps extracted section header text to the dict key used in the return value.
_SECTION_KEY_MAP: dict[str, str] = {
    "Triggers": "triggers",
    "Behavioral Mindset": "behavioral_mindset",
    "Focus Areas": "focus_areas",
    "Key Actions": "key_actions",
}

# Default token budget for thread context (NFR-001).
# Approximate: 1 token ~ 4 characters for English text.
DEFAULT_TOKEN_LIMIT = 10_000
CHARS_PER_TOKEN = 4

# Signal Protocol Instructions (FR-011 through FR-014)
SIGNAL_PROTOCOL_INSTRUCTIONS = """
## Signal Protocol

Your output must contain specific structured blocks to signal completion, handoff, or clarification. These blocks MUST be triple-dash delimited and follow a YAML-like key-value format.

### 1. Phase Completion (---PHASE-SIGNAL---)
Use this when you have finished your assigned phase and are ready to hand off to the next phase in the pipeline.
```
---PHASE-SIGNAL---
work_type: <pm|design|split|implement|qa>
artifact_ids: <comma-separated list of created/modified artifact IDs>
next_work_type: <challenge|pm|design|split|implement|qa|none>
starting_phase: <pm|design|split|implement|qa>
summary: <brief summary of what was accomplished>
---END-PHASE-SIGNAL---
```

### 2. Thread Entry (---THREAD-ENTRY---)
Use this to post an update, decision, or challenge to the artifact's discussion thread.
```
---THREAD-ENTRY---
entry_type: <comment|decision|challenge|revision|user_intervention>
content: <JSON-encoded string or detailed markdown text>
---END-THREAD-ENTRY---
```

### 3. Clarification Needed (---CLARIFICATION-NEEDED---)
Use this if you are blocked and need user input before proceeding.
```
---CLARIFICATION-NEEDED---
question: <your specific question to the user>
context: <background on why you are asking>
options: <optional list of choices for the user>
---END-CLARIFICATION-NEEDED---
```

### 4. Failure Triage (---FAILURE-TRIAGE---)
Use this if a task or phase has failed and you are diagnosing the next step.
```
---FAILURE-TRIAGE---
decision: <retry|skip|redesign|escalate>
reason: <your analysis of the failure>
new_work_items: <optional JSON list of new tasks to create>
---END-FAILURE-TRIAGE---
```
"""


@dataclass
class ThreadEntry:
    """A single entry in an artifact's discussion thread.

    Mirrors the ``artifact_threads`` table schema but is used
    in-memory for assembly and formatting.
    """

    artifact_type: str
    artifact_id: str
    entry_type: str
    content: str = ""
    agent_persona: str = ""
    round_number: int = 1
    created_at: str = ""
    # Metadata fields (optional, not always present)
    run_id: str = ""
    agent_id: str = ""
    parent_thread_id: int | None = None
    id: int | None = None

    @property
    def is_user_intervention(self) -> bool:
        """Whether this entry is a user intervention (FR-018)."""
        return self.entry_type == "user_intervention"

    @property
    def display_persona(self) -> str:
        """Human-readable persona name for formatting.

        Strips the 'sdlc-' prefix and title-cases the result.
        E.g., 'sdlc-backend-engineer' -> 'Backend Engineer'.
        """
        persona = self.agent_persona or "Unknown"
        if persona.startswith("sdlc-"):
            persona = persona[5:]
        return persona.replace("-", " ").title()

    @property
    def display_label(self) -> str:
        """Full attribution label for conversation log formatting (FR-016).

        Format: "[Persona, Round N]" or "[User, intervention]" for user entries.
        """
        if self.is_user_intervention:
            return "[User, intervention]"
        return f"[{self.display_persona}, Round {self.round_number}]"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)


def entries_from_db_rows(rows: list[dict[str, Any]]) -> list[ThreadEntry]:
    """Convert database rows (dicts) to ThreadEntry objects.

    Handles the mapping from DB column names to ThreadEntry fields.
    Unknown keys are silently ignored to be forward-compatible.

    Args:
        rows: List of dicts from Database.get_thread_entries().

    Returns:
        List of ThreadEntry instances.
    """
    entries: list[ThreadEntry] = []
    # Fields that ThreadEntry.__init__ accepts
    known_fields = {f.name for f in ThreadEntry.__dataclass_fields__.values()}
    for row in rows:
        filtered = {k: v for k, v in row.items() if k in known_fields}
        # Ensure content is a string (DB may return None)
        if filtered.get("content") is None:
            filtered["content"] = ""
        if filtered.get("agent_persona") is None:
            filtered["agent_persona"] = ""
        entries.append(ThreadEntry(**filtered))
    return entries


def _parse_persona_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter from persona markdown content.

    Splits on ``---`` markers and extracts key-value pairs from the
    frontmatter block.  Does NOT depend on pyyaml -- only handles
    simple ``key: value`` lines and basic multi-line continuation
    (indented lines appended to the previous key).

    Args:
        content: Raw markdown string with optional ``---`` frontmatter.

    Returns:
        A 2-tuple of ``(metadata_dict, markdown_body)``.
        If no valid frontmatter delimiters are found, returns an empty
        dict and the full content as the body.
    """
    # Frontmatter must start at the very beginning of the file
    stripped = content.lstrip("\n")
    if not stripped.startswith("---"):
        return {}, content

    # Find the closing --- marker (skip the opening one)
    first_marker = stripped.index("---")
    rest = stripped[first_marker + 3 :]
    second_marker = rest.find("\n---")
    if second_marker == -1:
        return {}, content

    frontmatter_block = rest[:second_marker].strip()
    body = rest[second_marker + 4 :].lstrip("\n")  # skip past \n---

    metadata: dict[str, str] = {}
    current_key: str | None = None

    for line in frontmatter_block.splitlines():
        # Continuation line (indented, belongs to previous key)
        if line and line[0] in (" ", "\t") and current_key is not None:
            metadata[current_key] += " " + line.strip()
            continue

        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key:
            metadata[key] = value
            current_key = key

    return metadata, body


def _extract_markdown_sections(body: str) -> dict[str, str]:
    """Extract named sections from persona markdown body.

    Scans for ``## {Section Name}`` headers matching the entries in
    :data:`_SECTION_KEY_MAP` and captures all text between the
    matched header and the next ``##`` header (or end of string).

    Args:
        body: Markdown body text (after frontmatter has been stripped).

    Returns:
        Dictionary mapping section keys (e.g. ``"behavioral_mindset"``)
        to their extracted content (trimmed of leading/trailing whitespace).
        Only sections that are actually found in the body are included.
    """
    sections: dict[str, str] = {}
    lines = body.splitlines()
    current_section: str | None = None
    current_lines: list[str] = []

    for line in lines:
        # Check if this line is a ## header
        if line.startswith("## "):
            # Flush the previous section if it was one we are extracting
            if current_section is not None:
                key = _SECTION_KEY_MAP.get(current_section)
                if key:
                    sections[key] = "\n".join(current_lines).strip()

            header_text = line[3:].strip()
            if header_text in _SECTION_KEY_MAP:
                current_section = header_text
                current_lines = []
            else:
                # A section we do not extract -- stop capturing
                current_section = None
                current_lines = []
        elif current_section is not None:
            current_lines.append(line)

    # Flush the last section if it was being captured
    if current_section is not None:
        key = _SECTION_KEY_MAP.get(current_section)
        if key:
            sections[key] = "\n".join(current_lines).strip()

    return sections


def load_persona(
    persona_type: str,
    project_dir: str | None = None,
) -> dict[str, str | list[str] | None]:
    """Load and parse a persona definition from markdown.

    Resolution order:
    1. ``{project_dir}/.sdlc/personas/{persona_type}.md`` (project override)
    2. Built-in ``src/a_sdlc/personas/{persona_type}.md``

    If *persona_type* does not start with ``"sdlc-"``, the prefix is
    prepended automatically (e.g. ``"architect"`` becomes
    ``"sdlc-architect"``).

    Args:
        persona_type: Persona identifier, e.g. ``"sdlc-backend-engineer"``
            or just ``"backend-engineer"``.
        project_dir: Optional path to the project root. When provided,
            the function checks for a project-level override first.

    Returns:
        Dictionary with the following keys:

        - ``name`` (str): Persona name from frontmatter or derived from type.
        - ``description`` (str | None): Persona description.
        - ``category`` (str | None): Persona category (e.g. ``"sdlc"``).
        - ``tools`` (list[str]): List of tool names (parsed from comma-
          separated frontmatter value).
        - ``memory`` (list[str]): Memory key list.
        - ``triggers`` (str | None): Content of the Triggers section.
        - ``behavioral_mindset`` (str | None): Content of the Behavioral
          Mindset section.
        - ``focus_areas`` (str | None): Content of the Focus Areas section.
        - ``key_actions`` (str | None): Content of the Key Actions section.
        - ``raw_content`` (str): Full markdown body (after frontmatter).
        - ``source_path`` (str): Absolute path to the file that was loaded.
    """
    # Normalize persona type
    if not persona_type.startswith("sdlc-"):
        persona_type = f"sdlc-{persona_type}"

    filename = f"{persona_type}.md"

    # Resolution: project override first, then built-in
    resolved_path: Path | None = None

    if project_dir:
        override_path = Path(project_dir) / ".sdlc" / "personas" / filename
        if override_path.is_file():
            resolved_path = override_path
            logger.debug("Using project persona override: %s", override_path)

    if resolved_path is None:
        builtin_path = PERSONA_DIR / filename
        if builtin_path.is_file():
            resolved_path = builtin_path
            logger.debug("Using built-in persona: %s", builtin_path)

    # If no file found, return minimal persona (graceful degradation)
    if resolved_path is None:
        logger.warning(
            "Persona file not found for '%s'; returning minimal persona.",
            persona_type,
        )
        return _minimal_persona(persona_type)

    try:
        content = resolved_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Failed to read persona file %s: %s; returning minimal persona.",
            resolved_path,
            exc,
        )
        return _minimal_persona(persona_type)

    try:
        metadata, body = _parse_persona_frontmatter(content)
        sections = _extract_markdown_sections(body)
    except Exception as exc:
        logger.warning(
            "Failed to parse persona file %s: %s; returning partial persona.",
            resolved_path,
            exc,
        )
        return {
            **_minimal_persona(persona_type),
            "raw_content": content,
            "source_path": str(resolved_path),
        }

    # Build tools list from comma-separated string
    tools_raw = metadata.get("tools", "")
    tools = [t.strip() for t in tools_raw.split(",") if t.strip()]

    # Build memory list (currently always single value, but support CSV)
    memory_raw = metadata.get("memory", "")
    memory = [m.strip() for m in memory_raw.split(",") if m.strip()]

    return {
        "name": metadata.get("name", persona_type),
        "description": metadata.get("description"),
        "category": metadata.get("category"),
        "tools": tools,
        "memory": memory,
        "triggers": sections.get("triggers"),
        "behavioral_mindset": sections.get("behavioral_mindset"),
        "focus_areas": sections.get("focus_areas"),
        "key_actions": sections.get("key_actions"),
        "raw_content": body,
        "source_path": str(resolved_path),
    }


def _minimal_persona(persona_type: str) -> dict[str, str | list[str] | None]:
    """Return a minimal persona dict when the file is unavailable.

    Provides safe defaults so callers never need to handle ``None``
    returns from :func:`load_persona`.
    """
    return {
        "name": persona_type,
        "description": None,
        "category": None,
        "tools": [],
        "memory": [],
        "triggers": None,
        "behavioral_mindset": None,
        "focus_areas": None,
        "key_actions": None,
        "raw_content": "",
        "source_path": "",
    }


def estimate_tokens(text: str) -> int:
    """Estimate token count from character length.

    Uses a simple 4-chars-per-token heuristic. This is deliberately
    conservative (over-estimates) to avoid exceeding context limits.

    Args:
        text: Input text.

    Returns:
        Estimated token count.
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def format_entry(entry: ThreadEntry) -> str:
    """Format a single thread entry as a conversation log line (FR-016).

    Format:
        [Persona, Round N]: <content>
        [User, intervention]: <message>

    Args:
        entry: Thread entry to format.

    Returns:
        Formatted string.
    """
    content = entry.content.strip() if entry.content else "(no content)"
    return f"{entry.display_label}: {content}"


def _format_section_header(artifact_type: str, artifact_id: str) -> str:
    """Format a section header for a thread context block.

    Args:
        artifact_type: Type ('task', 'prd', 'sprint').
        artifact_id: Artifact identifier.

    Returns:
        Markdown-style header.
    """
    type_label = artifact_type.upper()
    return f"### {type_label} Thread: {artifact_id}"


@dataclass
class ThreadContext:
    """Assembled hierarchical thread context ready for prompt injection.

    Contains formatted text and metadata about what was included/truncated.
    """

    text: str
    """The formatted thread context text to inject into a prompt."""

    total_entries: int = 0
    """Total number of entries across all levels before truncation."""

    included_entries: int = 0
    """Number of entries included in the output."""

    truncated_entries: int = 0
    """Number of entries that were truncated (summarized or dropped)."""

    levels: list[str] = field(default_factory=list)
    """Artifact levels included (e.g., ['task', 'prd', 'sprint'])."""

    estimated_tokens: int = 0
    """Estimated token count of the output text."""


def assemble_thread_context(
    entries_by_level: dict[tuple[str, str], list[ThreadEntry]],
    token_limit: int = DEFAULT_TOKEN_LIMIT,
    level_order: list[tuple[str, str]] | None = None,
) -> ThreadContext:
    """Assemble hierarchical thread context from multiple artifact levels.

    Implements FR-015 (hierarchical assembly), FR-017 (truncation with
    most-recent priority), and FR-018 (user interventions never truncated).

    The hierarchy is typically: task -> PRD -> sprint (most specific first).
    Each level gets its own section header, and entries within each level
    are displayed in chronological order.

    Truncation strategy (FR-017):
    1. User intervention entries are ALWAYS included (FR-018).
    2. Most recent entries are prioritized over older ones.
    3. Older entries that are dropped are replaced with a summary line.
    4. The task level (most specific) gets priority over parent levels.

    Args:
        entries_by_level: Dict mapping (artifact_type, artifact_id) to
            their thread entries. Example:
            {
                ("task", "PROJ-T00001"): [entry1, entry2],
                ("prd", "PROJ-P0001"): [entry3, entry4],
                ("sprint", "PROJ-S0001"): [entry5],
            }
        token_limit: Maximum estimated tokens for the output (NFR-001).
        level_order: Optional explicit ordering of levels. If not provided,
            defaults to: task levels first, then prd, then sprint (most
            specific first).

    Returns:
        ThreadContext with formatted text and metadata.
    """
    if not entries_by_level:
        return ThreadContext(text="", levels=[])

    # Determine level order: task -> prd -> sprint (FR-015)
    if level_order is None:
        type_priority = {"task": 0, "prd": 1, "design": 2, "sprint": 3}
        level_order = sorted(
            entries_by_level.keys(),
            key=lambda k: (type_priority.get(k[0], 99), k[1]),
        )

    # Count total entries
    total_entries = sum(len(entries) for entries in entries_by_level.values())

    # Separate user interventions (FR-018: always included)
    interventions_by_level: dict[tuple[str, str], list[ThreadEntry]] = {}
    regular_by_level: dict[tuple[str, str], list[ThreadEntry]] = {}

    for key, entries in entries_by_level.items():
        interventions_by_level[key] = [e for e in entries if e.is_user_intervention]
        regular_by_level[key] = [e for e in entries if not e.is_user_intervention]

    # Format all user interventions first (these are mandatory)
    mandatory_parts: list[str] = []
    for key in level_order:
        if key not in interventions_by_level:
            continue
        interventions = interventions_by_level[key]
        if interventions:
            for entry in interventions:
                mandatory_parts.append(format_entry(entry))

    mandatory_text = "\n".join(mandatory_parts)
    mandatory_tokens = estimate_tokens(mandatory_text) if mandatory_text else 0

    # Budget remaining for regular entries
    remaining_budget = max(0, token_limit - mandatory_tokens)

    # Build sections for regular entries, prioritizing by level order
    sections: list[str] = []
    included_count = len(mandatory_parts)
    truncated_count = 0
    levels_included: list[str] = []

    for key in level_order:
        artifact_type, artifact_id = key
        regular = regular_by_level.get(key, [])
        interventions = interventions_by_level.get(key, [])

        if not regular and not interventions:
            continue

        # Start building this section
        header = _format_section_header(artifact_type, artifact_id)
        header_tokens = estimate_tokens(header + "\n\n")

        if remaining_budget < header_tokens + estimate_tokens("(truncated)\n"):
            # No budget left even for a header; skip remaining levels
            truncated_count += len(regular)
            continue

        remaining_budget -= header_tokens
        section_lines: list[str] = [header]

        # Add interventions for this level (already counted in mandatory)
        for entry in interventions:
            section_lines.append(format_entry(entry))

        # Add regular entries, most recent first in priority
        # But display in chronological order
        if regular:
            # Try to fit all regular entries
            all_formatted = [format_entry(e) for e in regular]
            all_text = "\n".join(all_formatted)
            all_tokens = estimate_tokens(all_text)

            if all_tokens <= remaining_budget:
                # All entries fit
                section_lines.extend(all_formatted)
                remaining_budget -= all_tokens
                included_count += len(regular)
            else:
                # Need to truncate: keep most recent, summarize older
                # Work backward from most recent until budget exhausted
                kept_lines: list[str] = []
                kept_tokens = 0
                dropped = 0
                summary_budget = estimate_tokens(
                    "(... N earlier entries omitted ...)\n"
                )

                for entry in reversed(regular):
                    line = format_entry(entry)
                    line_tokens = estimate_tokens(line + "\n")
                    if kept_tokens + line_tokens + summary_budget <= remaining_budget:
                        kept_lines.insert(0, line)
                        kept_tokens += line_tokens
                    else:
                        dropped += 1

                if dropped > 0:
                    summary = f"_(... {dropped} earlier entries omitted ...)_"
                    section_lines.append(summary)
                    truncated_count += dropped

                section_lines.extend(kept_lines)
                remaining_budget -= kept_tokens + (
                    estimate_tokens(summary + "\n") if dropped > 0 else 0
                )
                included_count += len(kept_lines)

        levels_included.append(f"{artifact_type}:{artifact_id}")
        sections.append("\n".join(section_lines))

    # Assemble final text
    parts: list[str] = []
    if sections:
        parts.append("## Thread Context\n")
        parts.extend(sections)

    # Append any mandatory interventions that were not part of a section
    # (this handles edge cases where interventions exist for levels we skipped)
    standalone_interventions: list[str] = []
    for key in level_order:
        if key not in interventions_by_level:
            continue
        artifact_type, artifact_id = key
        level_key = f"{artifact_type}:{artifact_id}"
        if level_key not in levels_included and interventions_by_level[key]:
            if not standalone_interventions:
                standalone_interventions.append(
                    "### User Interventions (from truncated levels)"
                )
            for entry in interventions_by_level[key]:
                standalone_interventions.append(format_entry(entry))
            levels_included.append(level_key)

    if standalone_interventions:
        parts.append("\n".join(standalone_interventions))

    final_text = "\n\n".join(parts) if parts else ""
    final_tokens = estimate_tokens(final_text)

    return ThreadContext(
        text=final_text,
        total_entries=total_entries,
        included_entries=included_count,
        truncated_entries=truncated_count,
        levels=levels_included,
        estimated_tokens=final_tokens,
    )


def build_thread_context_for_task(
    task_id: str,
    task_data: dict[str, Any],
    db: Any | None = None,
    run_id: str | None = None,
    token_limit: int = DEFAULT_TOKEN_LIMIT,
) -> ThreadContext:
    """Build hierarchical thread context for a task prompt (FR-015).

    Assembles: task thread + parent PRD thread + sprint thread (if available).

    This is the primary entry point for prompt builders. It queries the
    database for thread entries at each level and assembles them into
    a formatted, truncated context block.

    Args:
        task_id: Task identifier (e.g., 'PROJ-T00001').
        task_data: Task metadata dict (must contain 'prd_id', optionally
            'sprint_id' derived from PRD).
        db: Optional Database instance. If None, uses get_db().
        run_id: Optional execution run to scope entries to.
        token_limit: Maximum estimated tokens (default 10K).

    Returns:
        ThreadContext ready for prompt injection.
    """
    if db is None:
        from a_sdlc.core.database import get_db
        db = get_db()

    entries_by_level: dict[tuple[str, str], list[ThreadEntry]] = {}
    level_order: list[tuple[str, str]] = []

    # Level 1: Task thread
    task_entries = db.get_thread_entries(
        artifact_type="task", artifact_id=task_id, run_id=run_id
    )
    if task_entries:
        key = ("task", task_id)
        entries_by_level[key] = entries_from_db_rows(task_entries)
        level_order.append(key)

    # Level 2: Parent PRD thread
    prd_id = task_data.get("prd_id")
    if prd_id:
        prd_entries = db.get_thread_entries(
            artifact_type="prd", artifact_id=prd_id, run_id=run_id
        )
        if prd_entries:
            key = ("prd", prd_id)
            entries_by_level[key] = entries_from_db_rows(prd_entries)
            level_order.append(key)

    # Level 3: Sprint thread (derived from PRD's sprint_id)
    sprint_id = task_data.get("sprint_id")
    if sprint_id:
        sprint_entries = db.get_thread_entries(
            artifact_type="sprint", artifact_id=sprint_id, run_id=run_id
        )
        if sprint_entries:
            key = ("sprint", sprint_id)
            entries_by_level[key] = entries_from_db_rows(sprint_entries)
            level_order.append(key)

    return assemble_thread_context(
        entries_by_level=entries_by_level,
        token_limit=token_limit,
        level_order=level_order,
    )


def build_thread_context_for_prd(
    prd_id: str,
    prd_data: dict[str, Any],
    db: Any | None = None,
    run_id: str | None = None,
    token_limit: int = DEFAULT_TOKEN_LIMIT,
) -> ThreadContext:
    """Build hierarchical thread context for a PRD prompt.

    Assembles: PRD thread + sprint thread (if available).

    Args:
        prd_id: PRD identifier.
        prd_data: PRD metadata dict (optionally contains 'sprint_id').
        db: Optional Database instance.
        run_id: Optional execution run to scope entries to.
        token_limit: Maximum estimated tokens.

    Returns:
        ThreadContext ready for prompt injection.
    """
    if db is None:
        from a_sdlc.core.database import get_db
        db = get_db()

    entries_by_level: dict[tuple[str, str], list[ThreadEntry]] = {}
    level_order: list[tuple[str, str]] = []

    # Level 1: PRD thread
    prd_entries = db.get_thread_entries(
        artifact_type="prd", artifact_id=prd_id, run_id=run_id
    )
    if prd_entries:
        key = ("prd", prd_id)
        entries_by_level[key] = entries_from_db_rows(prd_entries)
        level_order.append(key)

    # Level 2: Sprint thread
    sprint_id = prd_data.get("sprint_id")
    if sprint_id:
        sprint_entries = db.get_thread_entries(
            artifact_type="sprint", artifact_id=sprint_id, run_id=run_id
        )
        if sprint_entries:
            key = ("sprint", sprint_id)
            entries_by_level[key] = entries_from_db_rows(sprint_entries)
            level_order.append(key)

    return assemble_thread_context(
        entries_by_level=entries_by_level,
        token_limit=token_limit,
        level_order=level_order,
    )


def build_pm_prompt(
    goal: str,
    project_context: dict[str, Any],
    thread_history: str = "",
    goal_file_content: str | None = None,
) -> str:
    """Build PM agent prompt with goal interpretation protocol (FR-004).

    The PM agent is the entry point for 'run goal'. It discovers
    existing state and determines the starting phase for the pipeline.
    """
    import json
    persona = load_persona("sdlc-product-manager")

    goal_section = f"## User Goal\n\n{goal}\n"
    if goal_file_content:
        goal_section += f"\n## Detailed Specification\n\n{goal_file_content}\n"

    project_section = f"## Project Context\n\n{json.dumps(project_context, indent=2)}\n"

    return f"""{persona["raw_content"]}

{goal_section}

{project_section}

{thread_history}

## Goal Interpretation Protocol

You have been given a natural language goal. Before creating anything new, DISCOVER what already exists.

### Step 1: Understand the Goal
Parse the user's goal description for entity references (PRD-P001), keyword references, and intent signals.

### Step 2: Discover Existing Work
Call these MCP tools in order:
1. mcp__asdlc__get_context()
2. mcp__asdlc__list_prds()
3. mcp__asdlc__list_sprints()

For relevant PRDs:
4. mcp__asdlc__get_prd(prd_id)
5. mcp__asdlc__get_design(prd_id)
6. mcp__asdlc__list_tasks(prd_id=prd_id)

### Step 3: Determine Starting Phase
Based on discovery results, emit the appropriate starting signal:

| Existing State | Starting Phase | Signal |
|---------------|----------------|--------|
| Nothing matches goal | `pm` | Create new PRD(s) |
| PRD exists, status=draft | `pm` | Refine existing PRD |
| PRD approved, no design | `design` | Create architecture design |
| Design exists, no tasks | `split` | Split PRD into tasks |
| Tasks exist, pending | `implement` | Queue implementation |

{SIGNAL_PROTOCOL_INSTRUCTIONS}
"""


def build_design_prompt(
    prd_ids: list[str],
    thread_history: str = "",
) -> str:
    """Build Architect prompt for design phase (FR-005)."""
    persona = load_persona("sdlc-architect")
    prds_list = ", ".join(prd_ids)

    return f"""{persona["raw_content"]}

## Your Assignment
Create the architecture design for the following PRDs: {prds_list}.

### Instructions
1. Use mcp__asdlc__get_prd(prd_id) to read the requirement source.
2. Use mcp__asdlc__create_design(prd_id) to create the design document.
3. Write architectural decisions, component maps, and data models to the design file.

{thread_history}

{SIGNAL_PROTOCOL_INSTRUCTIONS}
"""


def build_split_prompt(
    prd_ids: list[str],
    thread_history: str = "",
) -> str:
    """Build Architect prompt for task splitting phase (FR-006)."""
    persona = load_persona("sdlc-architect")
    prds_list = ", ".join(prd_ids)

    return f"""{persona["raw_content"]}

## Your Assignment
Split the following PRDs into implementation tasks: {prds_list}.

### Instructions
1. Use mcp__asdlc__get_prd(prd_id) and mcp__asdlc__get_design(prd_id) to understand the requirements and architecture.
2. Use mcp__asdlc__create_task() or mcp__asdlc__split_prd() to generate the task tree.
3. Ensure tasks are structured by component and include explicit dependencies.

{thread_history}

{SIGNAL_PROTOCOL_INSTRUCTIONS}
"""


def build_challenger_prompt(
    artifact_type: str,
    artifact_id: str,
    artifact_content: str,
    checklist: list[str],
    thread_history: str = "",
    persona_type: str = "sdlc-architect",
) -> str:
    """Build a challenger review prompt (FR-007)."""
    persona = load_persona(persona_type)
    checklist_text = "\n".join([f"- {item}" for item in checklist])

    return f"""{persona["raw_content"]}

## Your Assignment: CHALLENGER
You are performing a critical review of a {artifact_type} ({artifact_id}).

### Artifact Content
```markdown
{artifact_content}
```

### Review Checklist
{checklist_text}

### Instructions
1. Evaluate the artifact against EVERY item in the checklist.
2. Identify gaps, contradictions, or missing details.
3. Output your findings as structured objections in a ---THREAD-ENTRY--- block.
4. **READ-ONLY**: You are not allowed to modify files or artifacts during this phase.

{thread_history}

{SIGNAL_PROTOCOL_INSTRUCTIONS}
"""


def build_revision_prompt(
    artifact_type: str,
    artifact_id: str,
    objections: list[dict[str, Any]],
    thread_history: str = "",
) -> str:
    """Build author prompt for revision after challenge (FR-008)."""
    import json
    # Author persona is typically PM for PRD, Architect for Design/Split
    persona_type = "sdlc-product-manager" if artifact_type == "prd" else "sdlc-architect"
    persona = load_persona(persona_type)

    objections_text = json.dumps(objections, indent=2)

    return f"""{persona["raw_content"]}

## Your Assignment: REVISION
Your {artifact_type} ({artifact_id}) has been challenged with the following objections.

### Objections
{objections_text}

### Instructions
1. Read the artifact and the objections.
2. Address each objection by modifying the artifact file.
3. Once all objections are addressed, signal completion.

{thread_history}

{SIGNAL_PROTOCOL_INSTRUCTIONS}
"""


def build_engineer_prompt(
    task_id: str,
    task: dict[str, Any],
    thread_history: str = "",
    persona_type: str = "sdlc-backend-engineer",
    dispatch_info: str = "",
) -> str:
    """Build engineer prompt wrapping existing task builder (FR-009)."""
    from a_sdlc.server import build_execute_task_prompt
    persona = load_persona(persona_type)

    base_prompt = build_execute_task_prompt(task_id, task, dispatch_info=dispatch_info)

    return f"""{persona["raw_content"]}

{thread_history}

{base_prompt}
"""


def build_qa_prompt(
    sprint_id: str,
    task_outcomes: list[dict[str, Any]],
    thread_history: str = "",
) -> str:
    """Build QA prompt for sprint verification (FR-010)."""
    import json
    persona = load_persona("sdlc-qa-engineer")
    outcomes_text = json.dumps(task_outcomes, indent=2)

    return f"""{persona["raw_content"]}

## Your Assignment: QA VERIFICATION
Verify the implementation of sprint {sprint_id}.

### Task Outcomes
{outcomes_text}

### Instructions (v2)
1. Use mcp__asdlc__get_sprint_quality_report() to identify gaps.
2. Run tests to verify acceptance criteria.
3. Signal sprint readiness or identify blockers.

{thread_history}

{SIGNAL_PROTOCOL_INSTRUCTIONS}
"""


def build_failure_triage_prompt(
    failed_item: str,
    error_output: str,
    thread_history: str = "",
    retry_count: int = 0,
) -> str:
    """Build failure triage prompt for Architect (FR-010a)."""
    persona = load_persona("sdlc-architect")

    return f"""{persona["raw_content"]}

## Your Assignment: FAILURE TRIAGE
The following item failed during execution: {failed_item}.

### Error Output
```
{error_output}
```

### Context
- Retry count: {retry_count}

### Instructions
1. Diagnose why the failure occurred.
2. Decide whether to retry, skip, redesign, or escalate.
3. Emit a ---FAILURE-TRIAGE--- signal with your decision and reasoning.

{thread_history}

{SIGNAL_PROTOCOL_INSTRUCTIONS}
"""


def parse_signal(output: str, signal_type: str) -> dict[str, str] | None:
    """Parse a structured signal block from agent output (FR-011 through FR-014).

    Searches *output* for a delimited block matching the given *signal_type*
    and extracts key-value pairs from the YAML-like content.

    Supported signal types:
    - ``PHASE-SIGNAL``
    - ``CLARIFICATION-NEEDED``
    - ``THREAD-ENTRY``
    - ``FAILURE-TRIAGE``

    The block format is::

        ---{signal_type}---
        key: value
        key2: value2
        ---END-{signal_type}---

    The end marker also accepts ``---END-SIGNAL---`` as a generic terminator
    for backwards compatibility.

    Args:
        output: Full text output from an agent, which may contain a signal
            block among other prose.
        signal_type: The signal type to look for (e.g. ``"PHASE-SIGNAL"``).

    Returns:
        Dictionary of parsed key-value pairs if the signal block is found,
        or ``None`` if no matching block exists in *output*.
    """
    # Build regex to find the signal block.
    # Accept both ---END-{signal_type}--- and ---END-SIGNAL--- as terminators.
    pattern = re.compile(
        rf"---{re.escape(signal_type)}---\s*\n"
        rf"(.*?)"
        rf"\n\s*---END-(?:{re.escape(signal_type)}|SIGNAL)---",
        re.DOTALL,
    )

    match = pattern.search(output)
    if match is None:
        return None

    block = match.group(1).strip()
    result: dict[str, str] = {}
    current_key: str | None = None

    for line in block.splitlines():
        # Continuation line (indented, belongs to previous key)
        if line and line[0] in (" ", "\t") and current_key is not None:
            result[current_key] += " " + line.strip()
            continue

        if ":" not in line:
            continue

        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key:
            result[key] = value
            current_key = key

    return result if result else None


def _format_thread_entries(entries: list[dict[str, Any]]) -> list[str]:
    """Format a list of thread entry dicts into display lines.

    This is a convenience wrapper for callers that work with raw dicts
    (e.g. from the task spec's simplified thread history format) rather
    than :class:`ThreadEntry` dataclass instances.

    Each entry dict should contain:
    - ``persona`` (str): Agent persona identifier.
    - ``round_number`` (int): Round number for attribution.
    - ``entry_type`` (str): Type of entry (implementation, review, etc.).
    - ``content`` (str): Entry content text.

    The output format is::

        [Persona, Round N, entry_type]: content

    Args:
        entries: List of entry dicts.

    Returns:
        List of formatted strings, one per entry.
    """
    lines: list[str] = []
    for entry in entries:
        persona = entry.get("persona", "Unknown")
        round_num = entry.get("round_number", 0)
        entry_type = entry.get("entry_type", "unknown")
        content = entry.get("content", "(no content)")

        # Format persona display name
        display_persona = persona
        if display_persona.startswith("sdlc-"):
            display_persona = display_persona[5:]
        display_persona = display_persona.replace("-", " ").title()

        lines.append(
            f"[{display_persona}, Round {round_num}, {entry_type}]: {content}"
        )
    return lines

"""
Product Requirements Document (PRD) data model and plugin interface.

Supports multiple PRDs per project with selective sync from Confluence.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


def _slugify(title: str) -> str:
    """Convert title to URL-friendly slug.

    Args:
        title: Human-readable title.

    Returns:
        Lowercase slug with hyphens.

    Examples:
        "Feature Auth" -> "feature-auth"
        "Payment System v2" -> "payment-system-v2"
    """
    import re

    slug = title.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


@dataclass
class PRD:
    """Product Requirements Document.

    Represents a single PRD that can be stored locally or synced with
    Confluence. Each project can have multiple PRDs for different features.

    PRDs can optionally be assigned to a sprint. When assigned, all tasks
    under this PRD are considered part of that sprint.

    Attributes:
        id: Slug identifier (e.g., "feature-auth").
        title: Display title (e.g., "Feature Auth").
        content: Markdown content.
        version: Semantic version string.
        sprint_id: Optional sprint assignment (None = backlog).
        created_at: Creation timestamp.
        updated_at: Last modification timestamp.
        external_id: Confluence page ID (if synced).
        external_url: Confluence page URL (if synced).
        metadata: Custom fields for extensibility.
    """

    id: str
    title: str
    content: str
    version: str = "1.0.0"
    sprint_id: str | None = None  # Sprint this PRD belongs to
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    external_id: str | None = None
    external_url: str | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert PRD to dictionary representation.

        Returns:
            Dict suitable for JSON serialization.
        """
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "version": self.version,
            "sprint_id": self.sprint_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "external_id": self.external_id,
            "external_url": self.external_url,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PRD":
        """Create PRD from dictionary representation.

        Args:
            data: Dict with PRD fields.

        Returns:
            PRD instance.
        """
        return cls(
            id=data["id"],
            title=data["title"],
            content=data["content"],
            version=data.get("version", "1.0.0"),
            sprint_id=data.get("sprint_id"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(),
            external_id=data.get("external_id"),
            external_url=data.get("external_url"),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_file(cls, filepath: str, content: str) -> "PRD":
        """Create PRD from file content.

        Args:
            filepath: Path to PRD file.
            content: Markdown content.

        Returns:
            PRD instance.
        """
        import os
        from pathlib import Path

        path = Path(filepath)
        filename = path.stem  # Remove .md extension

        # Extract title from first heading or use filename
        title = filename.replace("-", " ").title()
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Generate slug from filename (which should already be a slug)
        prd_id = _slugify(filename)

        return cls(
            id=prd_id,
            title=title,
            content=content,
            updated_at=datetime.fromtimestamp(os.path.getmtime(filepath))
            if os.path.exists(filepath)
            else datetime.now(),
        )

    @classmethod
    def from_title(cls, title: str, content: str = "") -> "PRD":
        """Create PRD from a title.

        Generates ID from title automatically.

        Args:
            title: Human-readable title.
            content: Markdown content (optional).

        Returns:
            PRD instance with auto-generated ID.
        """
        return cls(
            id=_slugify(title),
            title=title,
            content=content,
        )

    def get_sections(self) -> dict[str, str]:
        """Parse content into sections.

        Returns:
            Dict mapping section names to content.
        """
        return extract_sections(self.content)

    def update_section_content(self, section_name: str, new_content: str) -> None:
        """Update specific section.

        Args:
            section_name: Name of section to update.
            new_content: New content for the section.
        """
        self.content = update_section(self.content, section_name, new_content)
        self.updated_at = datetime.now()

    def bump_version_auto(self, bump_type: str) -> None:
        """Bump version using semantic versioning.

        Args:
            bump_type: "major", "minor", or "patch".
        """
        self.version = bump_version(self.version, bump_type)
        self.updated_at = datetime.now()


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse semantic version string.

    Args:
        version: Version string (e.g., "1.2.3").

    Returns:
        Tuple of (major, minor, patch).

    Examples:
        parse_version("1.2.3") -> (1, 2, 3)
        parse_version("2.0.1") -> (2, 0, 1)
    """
    major, minor, patch = version.split(".")
    return (int(major), int(minor), int(patch))


def bump_version(current: str, bump_type: str) -> str:
    """Bump semantic version.

    Args:
        current: Current version (e.g., "1.2.3").
        bump_type: "major", "minor", or "patch".

    Returns:
        New version string.

    Examples:
        bump_version("1.2.3", "major") -> "2.0.0"
        bump_version("1.2.3", "minor") -> "1.3.0"
        bump_version("1.2.3", "patch") -> "1.2.4"
    """
    major, minor, patch = parse_version(current)

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:  # patch
        return f"{major}.{minor}.{patch + 1}"


def extract_sections(markdown: str) -> dict[str, str]:
    """Parse markdown into section dictionary.

    Args:
        markdown: Markdown content with ## sections.

    Returns:
        Dict mapping section names to content.

    Examples:
        "## Goals\\nContent\\n## Requirements\\nMore" ->
        {"Goals": "Content", "Requirements": "More"}
    """
    sections = {}
    current_section = None
    current_content = []

    for line in markdown.split("\n"):
        if line.startswith("## "):
            if current_section:
                sections[current_section] = "\n".join(current_content).strip()
            current_section = line[3:].strip()
            current_content = []
        elif current_section:
            current_content.append(line)

    if current_section:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def update_section(markdown: str, section_name: str, new_content: str) -> str:
    """Update specific section in markdown.

    Args:
        markdown: Original markdown content.
        section_name: Name of section to update.
        new_content: New content for the section.

    Returns:
        Updated markdown content.

    Raises:
        KeyError: If section not found.
    """
    sections = extract_sections(markdown)

    if section_name not in sections:
        raise KeyError(f"Section not found: {section_name}")

    sections[section_name] = new_content

    # Reconstruct markdown (preserve order by parsing again)
    result = []
    current_section = None

    for line in markdown.split("\n"):
        if line.startswith("## "):
            current_section = line[3:].strip()
            result.append(line)
            if current_section in sections:
                result.append(sections[current_section])
        elif not current_section or not line.strip():
            # Keep header content and blank lines
            if not any(line.startswith("## ") for line in [line]):
                result.append(line)

    return "\n".join(result)


def detect_change_type(original: str, updated: str) -> str:
    """Detect type of change between two markdown documents.

    Args:
        original: Original markdown content.
        updated: Updated markdown content.

    Returns:
        "structural" (sections added/removed),
        "content" (significant content changes), or
        "typo" (minor text changes).
    """
    original_sections = extract_sections(original)
    updated_sections = extract_sections(updated)

    # Structural: sections added/removed
    if set(original_sections.keys()) != set(updated_sections.keys()):
        return "structural"

    # Compare content magnitude
    total_diff = sum(
        abs(len(original_sections.get(s, "")) - len(updated_sections.get(s, "")))
        for s in set(original_sections.keys()) | set(updated_sections.keys())
    )

    if total_diff > 200:  # Significant changes
        return "content"
    else:
        return "typo"


class PRDPlugin(ABC):
    """Base interface for PRD storage plugins.

    Plugins handle the storage and retrieval of PRDs,
    whether that's local file storage or external systems
    like Confluence.
    """

    def __init__(self, config: dict) -> None:
        """Initialize plugin with configuration.

        Args:
            config: Plugin-specific configuration dict.
        """
        self.config = config

    @abstractmethod
    def store_prd(self, prd: PRD) -> str:
        """Store a PRD.

        Args:
            prd: PRD to store.

        Returns:
            PRD ID (may be external ID if stored externally).
        """
        pass

    @abstractmethod
    def get_prd(self, prd_id: str) -> PRD | None:
        """Retrieve a PRD by ID.

        Args:
            prd_id: ID of PRD to retrieve (slug or external ID).

        Returns:
            PRD if found, None otherwise.
        """
        pass

    @abstractmethod
    def list_prds(self) -> list[PRD]:
        """List all PRDs.

        Returns:
            List of PRDs.
        """
        pass

    @abstractmethod
    def delete_prd(self, prd_id: str) -> None:
        """Delete a PRD.

        Args:
            prd_id: ID of PRD to delete.

        Raises:
            KeyError: If PRD doesn't exist.
        """
        pass

    def update_prd(self, prd_id: str, content: str, version: str | None = None) -> None:
        """Update an existing PRD's content.

        Default implementation retrieves, modifies, and stores the PRD.
        Plugins may override for more efficient updates.

        Args:
            prd_id: ID of PRD to update.
            content: New markdown content.
            version: New version string (optional).

        Raises:
            KeyError: If PRD doesn't exist.
        """
        prd = self.get_prd(prd_id)
        if prd is None:
            raise KeyError(f"PRD not found: {prd_id}")

        prd.content = content
        prd.updated_at = datetime.now()
        if version:
            prd.version = version

        self.store_prd(prd)

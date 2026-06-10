"""
Local file-based artifact storage plugin.

Stores artifacts as markdown files in .sdlc/artifacts/ directory,
maintaining compatibility with the existing file-based workflow.
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

from a_sdlc.artifacts.base import Artifact, ArtifactPlugin, ArtifactType

# Exact-name allowlist for legacy markdown cleanup (DD-7). Only these five
# scan artifact stems are ever eligible for stale-.md deletion; everything
# else (notably requirements.md and code-quality.md, which remain markdown
# by design) must never be touched.
STALE_MARKDOWN_ALLOWLIST: frozenset[str] = frozenset(
    {
        "architecture",
        "codebase-summary",
        "data-model",
        "directory-structure",
        "key-workflows",
    }
)


def remove_stale_markdown(artifacts_dir: Path | str) -> list[str]:
    """Remove legacy ``.md`` scan artifacts replaced by ``.html`` siblings.

    Scoped to the exact five scan artifact names in
    ``STALE_MARKDOWN_ALLOWLIST``. A ``.md`` file is deleted only when its
    ``.html`` replacement exists on disk; if the replacement is missing,
    the markdown is kept as the source of truth. Invoked by the scan
    workflow only after validation passes — never auto-invoked here.

    Defensive by design: a missing directory, already-deleted files, or
    permission errors produce a ``UserWarning`` at most, never an exception.

    Args:
        artifacts_dir: Path to the ``.sdlc/artifacts`` directory.

    Returns:
        Names of the deleted markdown files (e.g., ``['architecture.md']``).
    """
    directory = Path(artifacts_dir)
    deleted: list[str] = []

    try:
        if not directory.is_dir():
            return deleted
    except OSError as exc:
        warnings.warn(
            f"Could not access artifacts directory {directory}: {exc}",
            UserWarning,
            stacklevel=2,
        )
        return deleted

    for stem in sorted(STALE_MARKDOWN_ALLOWLIST):
        md_path = directory / f"{stem}.md"
        html_path = directory / f"{stem}.html"
        try:
            if not md_path.is_file():
                continue
            if not html_path.is_file():
                # No .html replacement yet — keep the legacy markdown.
                continue
            md_path.unlink()
            deleted.append(md_path.name)
        except OSError as exc:
            warnings.warn(
                f"Could not remove stale markdown {md_path}: {exc}",
                UserWarning,
                stacklevel=2,
            )

    return deleted


class LocalArtifactPlugin(ArtifactPlugin):
    """Store artifacts as local markdown files.

    This plugin maintains backward compatibility with the existing
    .sdlc/artifacts/ directory structure while adding metadata tracking.

    Configuration:
        - artifacts_dir: Directory for artifacts (default: .sdlc/artifacts/)
        - metadata_file: JSON file for tracking metadata (default: .sdlc/artifacts/.metadata.json)
    """

    DEFAULT_ARTIFACTS_DIR = ".sdlc/artifacts"
    METADATA_FILE = ".metadata.json"

    def __init__(self, config: dict) -> None:
        """Initialize local plugin.

        Args:
            config: Configuration with artifacts_dir, etc.
        """
        super().__init__(config)

        self.artifacts_dir = Path(config.get("artifacts_dir", self.DEFAULT_ARTIFACTS_DIR))
        self._metadata: dict[str, dict] = {}
        self._load_metadata()

    def _get_metadata_path(self) -> Path:
        """Get path to metadata file."""
        return self.artifacts_dir / self.METADATA_FILE

    def _load_metadata(self) -> None:
        """Load metadata from file."""
        metadata_path = self._get_metadata_path()
        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    self._metadata = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._metadata = {}
        else:
            self._metadata = {}

    def _save_metadata(self) -> None:
        """Save metadata to file."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self._get_metadata_path()
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(self._metadata, f, indent=2)

    def _get_artifact_path(self, artifact_id: str) -> Path:
        """Get canonical path to artifact file.

        The extension is delegated to ArtifactType.format ('html' for scan
        artifacts, 'md' for requirements/code-quality). Unknown artifact ids
        default to '.md'.
        """
        if artifact_id.endswith((".md", ".html")):
            return self.artifacts_dir / artifact_id

        artifact_type = ArtifactType.from_filename(artifact_id)
        extension = artifact_type.format if artifact_type is not None else "md"
        return self.artifacts_dir / f"{artifact_id}.{extension}"

    def _resolve_existing_path(self, artifact_id: str) -> Path | None:
        """Resolve artifact id to an existing file on disk.

        Prefers the canonical extension for the artifact type; falls back to
        the alternate extension for legacy/migration states (e.g., a scan
        artifact still on disk as '.md').
        """
        preferred = self._get_artifact_path(artifact_id)
        if preferred.exists():
            return preferred

        alt_suffix = ".md" if preferred.suffix == ".html" else ".html"
        alternate = preferred.with_suffix(alt_suffix)
        return alternate if alternate.exists() else None

    def store_artifact(self, artifact: Artifact) -> str:
        """Store artifact as markdown file."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Write markdown content
        artifact_path = self._get_artifact_path(artifact.id)
        artifact_path.write_text(artifact.content, encoding="utf-8")

        # Store metadata
        self._metadata[artifact.id] = {
            "artifact_type": artifact.artifact_type.value,
            "title": artifact.title,
            "version": artifact.version,
            "created_at": artifact.created_at.isoformat(),
            "updated_at": artifact.updated_at.isoformat(),
            "external_id": artifact.external_id,
            "external_url": artifact.external_url,
            "metadata": artifact.metadata,
        }
        self._save_metadata()

        return artifact.id

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        """Retrieve artifact from file."""
        artifact_path = self._resolve_existing_path(artifact_id)

        if artifact_path is None:
            return None

        content = artifact_path.read_text(encoding="utf-8")

        # Get metadata if available
        metadata = self._metadata.get(artifact_id, {})

        # Determine artifact type
        artifact_type_str = metadata.get("artifact_type")
        if artifact_type_str:
            artifact_type = ArtifactType(artifact_type_str)
        else:
            artifact_type = ArtifactType.from_filename(artifact_id) or ArtifactType.CODEBASE_SUMMARY

        # Extract title from content or metadata
        title = metadata.get("title", artifact_type.to_title())
        if not title:
            for line in content.split("\n"):
                if line.startswith("# "):
                    title = line[2:].strip()
                    break

        return Artifact(
            id=artifact_id,
            artifact_type=artifact_type,
            title=title,
            content=content,
            version=metadata.get("version", "1.0.0"),
            created_at=datetime.fromisoformat(metadata["created_at"]) if "created_at" in metadata else datetime.fromtimestamp(artifact_path.stat().st_ctime),
            updated_at=datetime.fromisoformat(metadata["updated_at"]) if "updated_at" in metadata else datetime.fromtimestamp(artifact_path.stat().st_mtime),
            external_id=metadata.get("external_id"),
            external_url=metadata.get("external_url"),
            metadata=metadata.get("metadata", {}),
        )

    def list_artifacts(self, artifact_type: ArtifactType | None = None) -> list[Artifact]:
        """List all artifacts, optionally filtered by type."""
        if not self.artifacts_dir.exists():
            return []

        artifacts: list[Artifact] = []

        # index.html is the artifact viewer shell, not an artifact
        html_stems = {f.stem for f in self.artifacts_dir.glob("*.html") if f.stem != "index"}
        md_stems = {f.stem for f in self.artifacts_dir.glob("*.md")}

        for stem in sorted(html_stems & md_stems):
            resolved = self._resolve_existing_path(stem)
            winner = resolved.name if resolved is not None else f"{stem}.html"
            warnings.warn(
                f"Both {stem}.html and {stem}.md exist; using {winner}",
                UserWarning,
                stacklevel=2,
            )

        for artifact_id in sorted(html_stems | md_stems):
            artifact = self.get_artifact(artifact_id)

            if artifact is not None and (artifact_type is None or artifact.artifact_type == artifact_type):
                artifacts.append(artifact)

        return sorted(artifacts, key=lambda a: a.id)

    def delete_artifact(self, artifact_id: str) -> None:
        """Delete artifact file(s) and metadata."""
        artifact_path = self._resolve_existing_path(artifact_id)

        if artifact_path is None:
            raise KeyError(f"Artifact not found: {artifact_id}")

        # Remove both extension variants if present (legacy/migration states)
        for suffix in (".html", ".md"):
            candidate = artifact_path.with_suffix(suffix)
            if candidate.exists():
                candidate.unlink()

        # Remove metadata
        if artifact_id in self._metadata:
            del self._metadata[artifact_id]
            self._save_metadata()

    def update_external_link(self, artifact_id: str, external_id: str, external_url: str) -> None:
        """Update external system link for an artifact.

        Used when artifact is published to Confluence or other external system.

        Args:
            artifact_id: Local artifact ID.
            external_id: External system ID (e.g., Confluence page ID).
            external_url: External system URL.
        """
        if artifact_id not in self._metadata:
            self._metadata[artifact_id] = {}

        self._metadata[artifact_id]["external_id"] = external_id
        self._metadata[artifact_id]["external_url"] = external_url
        self._metadata[artifact_id]["updated_at"] = datetime.now().isoformat()
        self._save_metadata()

    def get_pending_publish(self) -> list[Artifact]:
        """Get artifacts that haven't been published to external system.

        Returns:
            List of artifacts without external_id. HTML-format artifacts are
            excluded: Confluence publish for HTML is deferred (see DD-9).
        """
        return [
            a
            for a in self.list_artifacts()
            if not a.external_id and a.artifact_type.format != "html"
        ]

    def get_stale_artifacts(self) -> list[Artifact]:
        """Get artifacts that have been modified since last publish.

        Returns:
            List of artifacts with local changes newer than external.
        """
        stale: list[Artifact] = []

        for artifact in self.list_artifacts():
            if artifact.external_id:
                # Compare file modification time with metadata updated_at
                artifact_path = self._resolve_existing_path(artifact.id)
                if artifact_path is not None:
                    file_mtime = datetime.fromtimestamp(artifact_path.stat().st_mtime)
                    if file_mtime > artifact.updated_at:
                        stale.append(artifact)

        return stale

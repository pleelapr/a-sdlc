"""
Local file-based artifact storage plugin.

Stores artifacts as markdown files in .sdlc/artifacts/ directory,
maintaining compatibility with the existing file-based workflow.
"""

import json
from datetime import datetime
from pathlib import Path

from a_sdlc.artifacts.base import Artifact, ArtifactPlugin, ArtifactType


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
                with open(metadata_path) as f:
                    self._metadata = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._metadata = {}
        else:
            self._metadata = {}

    def _save_metadata(self) -> None:
        """Save metadata to file."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self._get_metadata_path()
        with open(metadata_path, "w") as f:
            json.dump(self._metadata, f, indent=2)

    def _get_artifact_path(self, artifact_id: str) -> Path:
        """Get path to artifact file."""
        # Ensure .md extension
        filename = artifact_id if artifact_id.endswith(".md") else f"{artifact_id}.md"
        return self.artifacts_dir / filename

    def store_artifact(self, artifact: Artifact) -> str:
        """Store artifact as markdown file."""
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Write markdown content
        artifact_path = self._get_artifact_path(artifact.id)
        artifact_path.write_text(artifact.content)

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
        artifact_path = self._get_artifact_path(artifact_id)

        if not artifact_path.exists():
            return None

        content = artifact_path.read_text()

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

        for md_file in self.artifacts_dir.glob("*.md"):
            artifact_id = md_file.stem
            artifact = self.get_artifact(artifact_id)

            if artifact is not None and (artifact_type is None or artifact.artifact_type == artifact_type):
                artifacts.append(artifact)

        return sorted(artifacts, key=lambda a: a.id)

    def delete_artifact(self, artifact_id: str) -> None:
        """Delete artifact file and metadata."""
        artifact_path = self._get_artifact_path(artifact_id)

        if not artifact_path.exists():
            raise KeyError(f"Artifact not found: {artifact_id}")

        artifact_path.unlink()

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
            List of artifacts without external_id.
        """
        return [a for a in self.list_artifacts() if not a.external_id]

    def get_stale_artifacts(self) -> list[Artifact]:
        """Get artifacts that have been modified since last publish.

        Returns:
            List of artifacts with local changes newer than external.
        """
        stale: list[Artifact] = []

        for artifact in self.list_artifacts():
            if artifact.external_id:
                # Compare file modification time with metadata updated_at
                artifact_path = self._get_artifact_path(artifact.id)
                if artifact_path.exists():
                    file_mtime = datetime.fromtimestamp(artifact_path.stat().st_mtime)
                    if file_mtime > artifact.updated_at:
                        stale.append(artifact)

        return stale

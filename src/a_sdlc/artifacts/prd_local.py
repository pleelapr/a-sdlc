"""
Local file-based PRD storage plugin.

Stores PRDs as markdown files in .sdlc/prds/ directory,
with metadata tracking for Confluence sync status.
"""

import json
from datetime import datetime
from pathlib import Path

from a_sdlc.artifacts.prd import PRD, PRDPlugin


class LocalPRDPlugin(PRDPlugin):
    """Store PRDs as local markdown files.

    This plugin stores PRDs in .sdlc/prds/ directory with metadata
    tracking for Confluence synchronization.

    Configuration:
        - prds_dir: Directory for PRDs (default: .sdlc/prds/)
        - metadata_file: JSON file for tracking metadata (default: .sdlc/prds/.metadata.json)

    Directory Structure:
        .sdlc/prds/
        ├── feature-auth.md
        ├── payment-system.md
        └── .metadata.json
    """

    DEFAULT_PRDS_DIR = ".sdlc/prds"
    METADATA_FILE = ".metadata.json"

    def __init__(self, config: dict) -> None:
        """Initialize local PRD plugin.

        Args:
            config: Configuration with prds_dir, etc.
        """
        super().__init__(config)

        self.prds_dir = Path(config.get("prds_dir", self.DEFAULT_PRDS_DIR))
        self._metadata: dict[str, dict] = {}
        self._load_metadata()

    def _get_metadata_path(self) -> Path:
        """Get path to metadata file."""
        return self.prds_dir / self.METADATA_FILE

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
        self.prds_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = self._get_metadata_path()
        with open(metadata_path, "w") as f:
            json.dump(self._metadata, f, indent=2)

    def _get_prd_path(self, prd_id: str) -> Path:
        """Get path to PRD file.

        Args:
            prd_id: PRD ID (slug).

        Returns:
            Path to the markdown file.
        """
        # Ensure .md extension
        filename = prd_id if prd_id.endswith(".md") else f"{prd_id}.md"
        return self.prds_dir / filename

    def store_prd(self, prd: PRD) -> str:
        """Store PRD as markdown file.

        Args:
            prd: PRD to store.

        Returns:
            PRD ID.
        """
        self.prds_dir.mkdir(parents=True, exist_ok=True)

        # Write markdown content
        prd_path = self._get_prd_path(prd.id)
        prd_path.write_text(prd.content)

        # Store metadata
        self._metadata[prd.id] = {
            "title": prd.title,
            "version": prd.version,
            "created_at": prd.created_at.isoformat(),
            "updated_at": prd.updated_at.isoformat(),
            "external_id": prd.external_id,
            "external_url": prd.external_url,
            "metadata": prd.metadata,
        }
        self._save_metadata()

        return prd.id

    def get_prd(self, prd_id: str) -> PRD | None:
        """Retrieve PRD from file.

        Args:
            prd_id: PRD ID (slug).

        Returns:
            PRD if found, None otherwise.
        """
        prd_path = self._get_prd_path(prd_id)

        if not prd_path.exists():
            return None

        content = prd_path.read_text()

        # Get metadata if available
        metadata = self._metadata.get(prd_id, {})

        # Extract title from content or metadata
        title = metadata.get("title", prd_id.replace("-", " ").title())
        for line in content.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break

        return PRD(
            id=prd_id,
            title=title,
            content=content,
            version=metadata.get("version", "1.0.0"),
            created_at=datetime.fromisoformat(metadata["created_at"])
            if "created_at" in metadata
            else datetime.fromtimestamp(prd_path.stat().st_ctime),
            updated_at=datetime.fromisoformat(metadata["updated_at"])
            if "updated_at" in metadata
            else datetime.fromtimestamp(prd_path.stat().st_mtime),
            external_id=metadata.get("external_id"),
            external_url=metadata.get("external_url"),
            metadata=metadata.get("metadata", {}),
        )

    def list_prds(self) -> list[PRD]:
        """List all PRDs.

        Returns:
            List of PRDs sorted by ID.
        """
        if not self.prds_dir.exists():
            return []

        prds: list[PRD] = []

        for md_file in self.prds_dir.glob("*.md"):
            prd_id = md_file.stem
            prd = self.get_prd(prd_id)

            if prd is not None:
                prds.append(prd)

        return sorted(prds, key=lambda p: p.id)

    def delete_prd(self, prd_id: str) -> None:
        """Delete PRD file and metadata.

        Args:
            prd_id: PRD ID to delete.

        Raises:
            KeyError: If PRD doesn't exist.
        """
        prd_path = self._get_prd_path(prd_id)

        if not prd_path.exists():
            raise KeyError(f"PRD not found: {prd_id}")

        prd_path.unlink()

        # Remove metadata
        if prd_id in self._metadata:
            del self._metadata[prd_id]
            self._save_metadata()

    def update_external_link(
        self, prd_id: str, external_id: str, external_url: str
    ) -> None:
        """Update external system link for a PRD.

        Used when PRD is published to Confluence.

        Args:
            prd_id: Local PRD ID.
            external_id: External system ID (e.g., Confluence page ID).
            external_url: External system URL.
        """
        if prd_id not in self._metadata:
            self._metadata[prd_id] = {}

        self._metadata[prd_id]["external_id"] = external_id
        self._metadata[prd_id]["external_url"] = external_url
        self._metadata[prd_id]["updated_at"] = datetime.now().isoformat()
        self._save_metadata()

    def get_pending_push(self) -> list[PRD]:
        """Get PRDs that haven't been pushed to external system.

        Returns:
            List of PRDs without external_id.
        """
        return [p for p in self.list_prds() if not p.external_id]

    def get_stale_prds(self) -> list[PRD]:
        """Get PRDs that have been modified since last push.

        Returns:
            List of PRDs with local changes newer than external.
        """
        stale: list[PRD] = []

        for prd in self.list_prds():
            if prd.external_id:
                # Compare file modification time with metadata updated_at
                prd_path = self._get_prd_path(prd.id)
                if prd_path.exists():
                    file_mtime = datetime.fromtimestamp(prd_path.stat().st_mtime)
                    if file_mtime > prd.updated_at:
                        stale.append(prd)

        return stale

    def find_by_title(self, title: str) -> PRD | None:
        """Find a PRD by its title (case-insensitive).

        Args:
            title: PRD title to search for.

        Returns:
            PRD if found, None otherwise.
        """
        title_lower = title.lower()
        for prd in self.list_prds():
            if prd.title.lower() == title_lower:
                return prd
        return None

    def exists(self, prd_id: str) -> bool:
        """Check if a PRD exists.

        Args:
            prd_id: PRD ID to check.

        Returns:
            True if PRD exists, False otherwise.
        """
        return self._get_prd_path(prd_id).exists()

    def add_update_history(
        self,
        prd_id: str,
        version: str,
        change_type: str,
        sections_modified: list[str],
        summary: str,
    ) -> None:
        """Add entry to PRD update history.

        Args:
            prd_id: PRD ID.
            version: New version after update.
            change_type: "major", "minor", or "patch".
            sections_modified: List of section names changed.
            summary: Brief description of changes.
        """
        if prd_id not in self._metadata:
            self._metadata[prd_id] = {}

        if "update_history" not in self._metadata[prd_id]:
            self._metadata[prd_id]["update_history"] = []

        self._metadata[prd_id]["update_history"].append(
            {
                "version": version,
                "timestamp": datetime.now().isoformat(),
                "change_type": change_type,
                "sections_modified": sections_modified,
                "summary": summary,
            }
        )

        self._metadata[prd_id]["version"] = version
        self._metadata[prd_id]["updated_at"] = datetime.now().isoformat()

        self._save_metadata()

    def get_update_history(self, prd_id: str) -> list[dict]:
        """Get update history for a PRD.

        Args:
            prd_id: PRD ID.

        Returns:
            List of update history entries, or empty list if none.
        """
        if prd_id not in self._metadata:
            return []

        return self._metadata[prd_id].get("update_history", [])

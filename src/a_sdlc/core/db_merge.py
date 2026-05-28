"""Data merge engine for incrementally merging a-sdlc data into an existing database.

Extends :class:`DataImporter` with ID-collision resolution: when a source
entity's primary key already exists in the target, the merger bumps the ID
to the next available value and cascades FK references via an in-memory
remap table.

Usage::

    from a_sdlc.core.db_merge import DataMerger

    merger = DataMerger(
        source_db_path="/path/to/source/data.db",
        target_url="postgresql://user:pass@host/dbname",
    )
    result = merger.run()
    print(result.rows_remapped, result.id_remap_summary)
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session

from a_sdlc.core.db_import import (
    DataImporter,
    ImportResult,
    _coerce_datetimes,
    _row_to_model,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Entity ID formats: table_name -> (prefix_char, zero_padding)
ENTITY_ID_FORMATS: dict[str, tuple[str, int]] = {
    "sprints": ("S", 4),  # {shortname}-S{n:04d}
    "prds": ("P", 4),  # {shortname}-P{n:04d}
    "tasks": ("T", 5),  # {shortname}-T{n:05d}
    "worktrees": ("W", 4),  # {shortname}-W{n:04d}
    "designs": ("D", 4),  # {shortname}-D{n:04d}  (follows same pattern)
}

# FK columns per table -> which remap dict to use (keyed by referenced table)
FK_COLUMNS: dict[str, dict[str, str]] = {
    "sprints": {"project_id": "projects"},
    "prds": {"project_id": "projects", "sprint_id": "sprints"},
    "tasks": {"project_id": "projects", "prd_id": "prds"},
    "designs": {"project_id": "projects", "prd_id": "prds"},
    "worktrees": {
        "project_id": "projects",
        "prd_id": "prds",
        "sprint_id": "sprints",
    },
    "reviews": {"project_id": "projects", "task_id": "tasks"},
    "requirements": {"project_id": "projects", "prd_id": "prds"},
    "requirement_links": {"requirement_id": "requirements", "task_id": "tasks"},
    "ac_verifications": {"requirement_id": "requirements", "task_id": "tasks"},
    "external_config": {"project_id": "projects"},
    "audit_log": {"project_id": "projects"},
    "challenge_records": {"project_id": "projects"},
}

# Tables with auto-increment integer PKs (omit PK on insert, let DB assign)
AUTO_INCREMENT_TABLES: frozenset[str] = frozenset(
    {
        "sync_mappings",
        "external_config",
        "reviews",
        "audit_log",
        "ac_verifications",
        "challenge_records",
    }
)

# Entity type -> table name for sync_mapping local_id remap
_SYNC_ENTITY_TABLE: dict[str, str] = {
    "sprint": "sprints",
    "prd": "prds",
    "task": "tasks",
}

# Regex for parsing entity IDs like "PROJ-T00001" or "PROJ-S0001"
_ENTITY_ID_RE = re.compile(r"^(.+)-([A-Z])(\d+)$")

# Regex for requirement IDs like "PROJ-P0001:FR-001"
_REQUIREMENT_ID_RE = re.compile(r"^(.+?):(.+)$")


# ---------------------------------------------------------------------------
# DataMerger
# ---------------------------------------------------------------------------


class DataMerger(DataImporter):
    """Import engine that merges source data into an existing target database.

    When entity IDs collide, the merger bumps them to the next available
    sequence number and cascades FK references.  Projects with a matching
    ``id`` in the target are skipped (their children are still imported
    and re-parented).
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["force"] = True  # merge always allows non-empty target
        super().__init__(*args, **kwargs)
        # Per-table remap: _id_remaps["sprints"]["OLD-S0001"] = "OLD-S0002"
        self._id_remaps: dict[str, dict[str, str]] = defaultdict(dict)
        self._merge_stats: dict[str, int] = {"skipped": 0, "remapped": 0}

    # -- Hook overrides ---------------------------------------------------

    def _prepare_target(
        self,
        session: Session,
        tables_to_import: list[str],
        target_engine: Engine,
    ) -> None:
        """No-op: keep existing data in target."""

    def _import_row(
        self,
        session: Session,
        table_name: str,
        row: dict[str, Any],
        result: ImportResult,
    ) -> None:
        """Import a single row with ID-collision resolution."""
        # 1. Apply FK remaps
        row = self._remap_fks(table_name, row)

        # 2. Dispatch to table-specific handler
        if table_name == "projects":
            self._import_project(session, row, result)
        elif table_name == "requirements":
            self._import_requirement(session, row, result)
        elif table_name == "requirement_links":
            self._import_requirement_link(session, row, result)
        elif table_name == "sync_mappings":
            self._import_sync_mapping(session, row, result)
        elif table_name in AUTO_INCREMENT_TABLES:
            self._import_auto_increment(session, table_name, row, result)
        elif table_name in ENTITY_ID_FORMATS:
            self._import_entity(session, table_name, row, result)
        else:
            # Fallback: plain insert (shouldn't happen for known tables)
            model = _row_to_model(table_name, row)
            session.add(model)

    def _verify_counts(
        self,
        target_engine: Engine,
        row_counts: dict[str, dict[str, int]],
    ) -> list[str]:
        """Skip strict row-count verification for merge (counts won't match 1:1)."""
        return []

    def _migrate_content_files(self) -> int:
        """Copy content files, renaming those whose IDs were bumped."""
        # Path 1: Source is a ContentBackend (S3)
        if self.source_content_backend is not None:
            return self._migrate_content_from_backend_with_remap()

        # Path 2: Local filesystem (existing logic with renames)
        if self.source_content_dir is None:
            from a_sdlc.core.content import get_data_dir

            source_dir = get_data_dir() / "content"
        else:
            source_dir = self.source_content_dir

        if not source_dir.exists():
            logger.warning("Source content directory not found: %s", source_dir)
            return 0

        backend = self.target_content_backend
        if backend is None:
            logger.warning("No target content backend configured; skipping content migration")
            return 0
        migrated = 0

        from a_sdlc.core.content import LocalContentBackend, get_data_dir

        target_base: Path | None = None
        if isinstance(backend, LocalContentBackend):
            target_base = get_data_dir() / "content"

        for md_file in sorted(source_dir.rglob("*.md")):
            relative = md_file.relative_to(source_dir)
            content = md_file.read_text(encoding="utf-8")

            # Rename file if entity ID was remapped
            relative_str = str(relative)
            for _table, remap in self._id_remaps.items():
                for old_id, new_id in remap.items():
                    if old_id in relative_str:
                        relative_str = relative_str.replace(old_id, new_id)
            relative = Path(relative_str)

            target_path = str(target_base / relative) if target_base is not None else str(relative)
            try:
                backend.write_content(target_path, content)
                migrated += 1
            except Exception as exc:
                logger.warning("Failed to migrate content file %s: %s", relative, exc)

        return migrated

    def _migrate_content_from_backend_with_remap(self) -> int:
        """Copy content from a source ContentBackend with ID remap applied to keys.

        Returns:
            Number of files migrated.
        """
        assert self.source_content_backend is not None
        assert self.target_content_backend is not None
        source = self.source_content_backend
        target = self.target_content_backend
        all_keys = source.list_content_recursive("", suffix=".md")
        migrated = 0
        for key in all_keys:
            content = source.read_content(key)
            if content is None:
                continue
            # Apply ID remaps to the key path
            target_key = key
            for _table, remap in self._id_remaps.items():
                for old_id, new_id in remap.items():
                    if old_id in target_key:
                        target_key = target_key.replace(old_id, new_id)
            try:
                target.write_content(target_key, content)
                migrated += 1
            except Exception as exc:
                logger.warning("Failed to migrate content %s: %s", key, exc)
        return migrated

    # -- Row processing helpers -------------------------------------------

    def _remap_fks(self, table_name: str, row: dict[str, Any]) -> dict[str, Any]:
        """Apply FK remaps to the row based on ``FK_COLUMNS``."""
        fk_spec = FK_COLUMNS.get(table_name, {})
        for col, ref_table in fk_spec.items():
            val = row.get(col)
            if val is not None and val in self._id_remaps[ref_table]:
                row[col] = self._id_remaps[ref_table][val]
        return row

    def _import_project(
        self,
        session: Session,
        row: dict[str, Any],
        result: ImportResult,
    ) -> None:
        """Import a project row; skip if it already exists in target."""
        project_id = row.get("id")
        if project_id and self._id_exists_in_target(session, "projects", project_id):
            # Record identity mapping so child FKs resolve
            self._id_remaps["projects"][project_id] = project_id
            self._merge_stats["skipped"] += 1
            result.rows_skipped += 1
            logger.info("Skipping existing project: %s", project_id)
            return
        model = _row_to_model("projects", row)
        session.add(model)

    def _import_entity(
        self,
        session: Session,
        table_name: str,
        row: dict[str, Any],
        result: ImportResult,
    ) -> None:
        """Import a string-ID entity (sprint, PRD, task, design, worktree).

        If the ID collides, bump to the next available sequence number.
        """
        entity_id = row.get("id", "")
        if entity_id and self._id_exists_in_target(session, table_name, entity_id):
            new_id = self._bump_id(session, table_name, entity_id)
            self._id_remaps[table_name][entity_id] = new_id
            row["id"] = new_id
            # Update file_path if present
            if row.get("file_path") and entity_id in row["file_path"]:
                row["file_path"] = row["file_path"].replace(entity_id, new_id)
            self._merge_stats["remapped"] += 1
            result.rows_remapped += 1
            result.id_remap_summary[table_name] = result.id_remap_summary.get(table_name, 0) + 1
            logger.info("Remapped %s ID: %s -> %s", table_name, entity_id, new_id)

        model = _row_to_model(table_name, row)
        session.add(model)

    def _import_requirement(
        self,
        session: Session,
        row: dict[str, Any],
        result: ImportResult,
    ) -> None:
        """Import a requirement, updating ID if its parent PRD was remapped."""
        req_id = row.get("id", "")
        prd_id = row.get("prd_id", "")

        # If the PRD was remapped, update the requirement ID prefix
        if prd_id in self._id_remaps.get("prds", {}):
            old_prd_id = prd_id
            new_prd_id = self._id_remaps["prds"][old_prd_id]
            # Requirement IDs are {prd_id}:{req_number}
            match = _REQUIREMENT_ID_RE.match(req_id)
            if match:
                req_suffix = match.group(2)
                new_req_id = f"{new_prd_id}:{req_suffix}"
                self._id_remaps["requirements"][req_id] = new_req_id
                row["id"] = new_req_id
                row["prd_id"] = new_prd_id
                result.rows_remapped += 1
                self._merge_stats["remapped"] += 1
            else:
                # Non-standard format, just remap prd_id
                row["prd_id"] = new_prd_id
        elif req_id and self._id_exists_in_target(session, "requirements", req_id):
            # Same requirement already exists; skip
            self._id_remaps["requirements"][req_id] = req_id
            self._merge_stats["skipped"] += 1
            result.rows_skipped += 1
            return

        model = _row_to_model("requirements", row)
        session.add(model)

    def _import_requirement_link(
        self,
        session: Session,
        row: dict[str, Any],
        result: ImportResult,
    ) -> None:
        """Import a requirement_link, remapping composite PK fields."""
        req_id = row.get("requirement_id", "")
        task_id = row.get("task_id", "")

        if req_id in self._id_remaps.get("requirements", {}):
            row["requirement_id"] = self._id_remaps["requirements"][req_id]
        if task_id in self._id_remaps.get("tasks", {}):
            row["task_id"] = self._id_remaps["tasks"][task_id]

        model = _row_to_model("requirement_links", row)
        session.add(model)

    def _import_sync_mapping(
        self,
        session: Session,
        row: dict[str, Any],
        result: ImportResult,
    ) -> None:
        """Import a sync_mapping, remapping local_id based on entity_type."""
        entity_type = row.get("entity_type", "")
        local_id = row.get("local_id", "")
        ref_table = _SYNC_ENTITY_TABLE.get(entity_type)

        if ref_table and local_id in self._id_remaps.get(ref_table, {}):
            row["local_id"] = self._id_remaps[ref_table][local_id]

        # Strip auto-increment PK
        row.pop("id", None)
        model = _row_to_model("sync_mappings", row)
        session.add(model)

    def _import_auto_increment(
        self,
        session: Session,
        table_name: str,
        row: dict[str, Any],
        result: ImportResult,
    ) -> None:
        """Import an auto-increment entity, stripping the source PK."""
        old_id = row.pop("id", None)
        row = _coerce_datetimes(row)
        model = _row_to_model(table_name, {**row})
        session.add(model)
        session.flush()
        # Record remap if we had an old ID
        if old_id is not None and hasattr(model, "id") and model.id is not None:
            self._id_remaps[table_name][str(old_id)] = str(model.id)

    # -- ID management helpers -------------------------------------------

    def _id_exists_in_target(
        self,
        session: Session,
        table_name: str,
        entity_id: str,
    ) -> bool:
        """Check whether a primary-key value already exists in the target."""
        result = session.execute(
            text(f"SELECT 1 FROM {table_name} WHERE id = :id"),  # noqa: S608
            {"id": entity_id},
        )
        return result.first() is not None

    def _bump_id(
        self,
        session: Session,
        table_name: str,
        entity_id: str,
    ) -> str:
        """Generate the next available ID by bumping the numeric suffix.

        Considers both existing rows in the target DB and any IDs already
        remapped during this batch.
        """
        match = _ENTITY_ID_RE.match(entity_id)
        if not match:
            # Can't parse — append _merge suffix as fallback
            return f"{entity_id}_merge"

        shortname = match.group(1)
        prefix_char = match.group(2)
        fmt = ENTITY_ID_FORMATS.get(table_name)
        padding = fmt[1] if fmt else len(match.group(3))

        # Find max numeric suffix in target
        like_pattern = f"{shortname}-{prefix_char}%"
        result = session.execute(
            text(f"SELECT id FROM {table_name} WHERE id LIKE :pattern"),  # noqa: S608
            {"pattern": like_pattern},
        )
        max_num = 0
        for (existing_id,) in result:
            m = _ENTITY_ID_RE.match(existing_id)
            if m and m.group(1) == shortname and m.group(2) == prefix_char:
                max_num = max(max_num, int(m.group(3)))

        # Also check remaps from this batch
        for _old, new in self._id_remaps.get(table_name, {}).items():
            m = _ENTITY_ID_RE.match(new)
            if m and m.group(1) == shortname and m.group(2) == prefix_char:
                max_num = max(max_num, int(m.group(3)))

        new_num = max_num + 1
        return f"{shortname}-{prefix_char}{new_num:0{padding}d}"

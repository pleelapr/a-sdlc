"""
ORM-based database operations for a-sdlc using SQLModel/SQLAlchemy sessions.

Drop-in replacement for ``Database`` in ``core/database.py``.  Every public
method has the same signature and returns ``dict[str, Any]`` (or list/bool)
so that callers do not need to change.

Usage::

    from a_sdlc.core.session_database import SessionDatabase, get_session_db

    db = SessionDatabase()          # uses default StorageConfig
    project = db.create_project("proj-1", "My Project", "/tmp/proj")
"""

from __future__ import annotations

import contextlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from a_sdlc.core.engine import create_all_tables, get_engine, get_session
from a_sdlc.core.models import (
    AcVerification,
    AuditLog,
    ChallengeRecord,
    Design,
    ExternalConfig,
    Prd,
    Project,
    Requirement,
    RequirementLink,
    Review,
    SchemaVersion,
    Sprint,
    SyncMapping,
    Task,
    Worktree,
)
from a_sdlc.core.storage_config import StorageConfig

# Schema version matching database.py
SCHEMA_VERSION = 15


def _utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def _model_to_dict(obj: Any) -> dict[str, Any]:
    """Convert a SQLModel instance to a plain dict.

    Converts ``datetime`` values to ISO-8601 strings for API compatibility.
    """
    if obj is None:
        return {}
    d = {}
    for key in obj.__class__.model_fields:
        val = getattr(obj, key, None)
        # Convert datetime objects to ISO strings for API compatibility
        if isinstance(val, datetime):
            val = val.isoformat()
        d[key] = val
    return d


class SessionDatabase:
    """SQLModel/SQLAlchemy session-based database manager for a-sdlc.

    API-compatible replacement for :class:`Database`.  All public methods
    return ``dict[str, Any]`` or ``list[dict[str, Any]]`` to preserve
    backward compatibility with existing callers.
    """

    VALID_REVIEWER_TYPES = ("self", "subagent")
    VALID_VERDICTS = ("pass", "fail", "approve", "request_changes", "escalate")

    def __init__(
        self,
        config: StorageConfig | None = None,
        engine: Engine | None = None,
        db_path: Path | None = None,
    ) -> None:
        """Initialize the SessionDatabase.

        Args:
            config: Optional StorageConfig. If ``None`` and no engine/db_path
                is supplied, uses the default singleton.
            engine: Optional pre-built engine (useful for tests).
            db_path: Legacy compatibility -- if provided, builds a SQLite URL
                from this path.
        """
        if engine is not None:
            self._engine = engine
        elif db_path is not None:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            cfg = StorageConfig(database_url=f"sqlite:///{db_path}")
            self._engine = get_engine(cfg)
        else:
            self._engine = get_engine(config)

        # Ensure tables exist
        create_all_tables(self._engine)

        # Ensure schema_version row exists
        with self._session() as session:
            sv = session.get(SchemaVersion, SCHEMA_VERSION)
            if sv is None:
                session.add(SchemaVersion(version=SCHEMA_VERSION))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _session(self) -> Session:
        """Return a context-managed session (use with ``with``)."""
        return get_session(self._engine)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Shortname utilities
    # ------------------------------------------------------------------

    @staticmethod
    def validate_shortname(shortname: str) -> tuple[bool, str]:
        """Validate a project shortname."""
        if not shortname:
            return False, "Shortname cannot be empty"
        if len(shortname) != 4:
            return False, "Shortname must be exactly 4 characters"
        if not re.match(r"^[A-Z]{4}$", shortname):
            return False, "Shortname must contain only uppercase letters (A-Z)"
        return True, ""

    @staticmethod
    def _generate_shortname_candidate(name: str) -> str:
        """Generate a 4-char shortname candidate from project name."""
        clean = re.sub(r"[^a-zA-Z]", "", name).upper()
        consonants = re.sub(r"[AEIOU]", "", clean)
        if len(consonants) >= 4:
            return consonants[:4]
        if len(clean) >= 4:
            return clean[:4]
        return (clean + "XXXX")[:4]

    def generate_unique_shortname(self, name: str) -> str:
        """Generate a unique shortname for a new project."""
        base = self._generate_shortname_candidate(name)
        with self._session() as session:
            if not session.exec(select(Project).where(Project.shortname == base)).first():
                return base
            for suffix in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
                candidate = base[:3] + suffix
                if not session.exec(
                    select(Project).where(Project.shortname == candidate)
                ).first():
                    return candidate
        return base  # fallback

    def is_shortname_available(self, shortname: str) -> bool:
        """Check if a shortname is available."""
        with self._session() as session:
            return (
                session.exec(
                    select(Project).where(Project.shortname == shortname)
                ).first()
                is None
            )

    # ==================================================================
    # Project Operations
    # ==================================================================

    def create_project(
        self,
        project_id: str,
        name: str,
        path: str | None = None,
        shortname: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a new project."""
        if shortname is None:
            shortname = self.generate_unique_shortname(name)
        else:
            is_valid, error_msg = self.validate_shortname(shortname)
            if not is_valid:
                raise ValueError(error_msg)
            if not self.is_shortname_available(shortname):
                raise ValueError(f"Shortname '{shortname}' is already in use")

        now = _utcnow()
        project = Project(
            id=project_id,
            shortname=shortname,
            name=name,
            path=path,
            created_at=now,
            last_accessed=now,
        )
        with self._session() as session:
            session.add(project)
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        """Get project by ID."""
        with self._session() as session:
            obj = session.get(Project, project_id)
            return _model_to_dict(obj) if obj else None

    def get_project_by_path(self, path: str) -> dict[str, Any] | None:
        """Get project by filesystem path."""
        with self._session() as session:
            obj = session.exec(select(Project).where(Project.path == path)).first()
            return _model_to_dict(obj) if obj else None

    def get_project_by_shortname(self, shortname: str) -> dict[str, Any] | None:
        """Get project by shortname."""
        with self._session() as session:
            obj = session.exec(
                select(Project).where(Project.shortname == shortname)
            ).first()
            return _model_to_dict(obj) if obj else None

    def update_project_path(
        self, project_id: str, new_path: str
    ) -> dict[str, Any] | None:
        """Update project filesystem path."""
        with self._session() as session:
            existing = session.exec(
                select(Project).where(Project.path == new_path, Project.id != project_id)
            ).first()
            if existing:
                raise ValueError(f"Path '{new_path}' is already used by another project")
            obj = session.get(Project, project_id)
            if not obj:
                return None
            obj.path = new_path
            obj.last_accessed = _utcnow()
            session.add(obj)
        return self.get_project(project_id)

    def list_projects(self) -> list[dict[str, Any]]:
        """List all projects ordered by last accessed."""
        with self._session() as session:
            results = session.exec(
                select(Project).order_by(Project.last_accessed.desc())  # type: ignore[union-attr]
            ).all()
            return [_model_to_dict(r) for r in results]

    def get_all_projects_with_stats(self) -> list[dict[str, Any]]:
        """Get all projects with aggregated stats.

        Note: Uses raw SQL for the complex aggregation query.
        """
        with self._session() as session:
            rows = session.exec(
                text("""
                SELECT
                    p.*,
                    COALESCE(t_counts.total_tasks, 0) AS total_tasks,
                    COALESCE(t_counts.pending, 0) AS tasks_pending,
                    COALESCE(t_counts.in_progress, 0) AS tasks_in_progress,
                    COALESCE(t_counts.completed, 0) AS tasks_completed,
                    COALESCE(t_counts.blocked, 0) AS tasks_blocked,
                    COALESCE(prd_counts.total_prds, 0) AS total_prds,
                    COALESCE(sprint_counts.total_sprints, 0) AS total_sprints,
                    active_sprint.title AS active_sprint_title,
                    active_sprint.id AS active_sprint_id
                FROM projects p
                LEFT JOIN (
                    SELECT project_id,
                           COUNT(*) AS total_tasks,
                           SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                           SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress,
                           SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                           SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) AS blocked
                    FROM tasks GROUP BY project_id
                ) t_counts ON p.id = t_counts.project_id
                LEFT JOIN (
                    SELECT project_id, COUNT(*) AS total_prds
                    FROM prds GROUP BY project_id
                ) prd_counts ON p.id = prd_counts.project_id
                LEFT JOIN (
                    SELECT project_id, COUNT(*) AS total_sprints
                    FROM sprints GROUP BY project_id
                ) sprint_counts ON p.id = sprint_counts.project_id
                LEFT JOIN (
                    SELECT project_id, id, title
                    FROM sprints s1
                    WHERE status = 'active'
                      AND id = (
                          SELECT MAX(s2.id) FROM sprints s2
                          WHERE s2.project_id = s1.project_id
                            AND s2.status = 'active'
                      )
                ) active_sprint ON p.id = active_sprint.project_id
                ORDER BY p.last_accessed DESC
                """)
            )
            return [dict(r._mapping) for r in rows]

    def get_most_recent_project(self) -> dict[str, Any] | None:
        """Get the most recently accessed project."""
        with self._session() as session:
            obj = session.exec(
                select(Project).order_by(Project.last_accessed.desc()).limit(1)  # type: ignore[union-attr]
            ).first()
            return _model_to_dict(obj) if obj else None

    def update_project_accessed(self, project_id: str) -> None:
        """Update project's last_accessed timestamp."""
        with self._session() as session:
            obj = session.get(Project, project_id)
            if obj:
                obj.last_accessed = _utcnow()
                session.add(obj)

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and all associated data."""
        with self._session() as session:
            obj = session.get(Project, project_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    # ==================================================================
    # PRD Operations
    # ==================================================================

    def create_prd(
        self,
        prd_id: str,
        project_id: str,
        title: str,
        file_path: str | None = None,
        status: str = "draft",
        source: str | None = None,
        sprint_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a new PRD."""
        now = _utcnow()
        prd = Prd(
            id=prd_id,
            project_id=project_id,
            sprint_id=sprint_id,
            title=title,
            file_path=file_path,
            status=status,
            source=source,
            created_at=now,
            updated_at=now,
        )
        with self._session() as session:
            session.add(prd)
        return self.get_prd(prd_id)

    def get_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get PRD by ID."""
        with self._session() as session:
            obj = session.get(Prd, prd_id)
            return _model_to_dict(obj) if obj else None

    def list_prds(
        self,
        project_id: str,
        sprint_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List PRDs for a project with optional filters."""
        with self._session() as session:
            stmt = select(Prd).where(Prd.project_id == project_id)
            if sprint_id is not None:
                if sprint_id == "":
                    stmt = stmt.where(Prd.sprint_id.is_(None))  # type: ignore[union-attr]
                else:
                    stmt = stmt.where(Prd.sprint_id == sprint_id)
            if status:
                stmt = stmt.where(Prd.status == status)
            stmt = stmt.order_by(Prd.updated_at.desc())  # type: ignore[union-attr]
            return [_model_to_dict(r) for r in session.exec(stmt).all()]

    def update_prd(self, prd_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update PRD fields with status transition timestamp tracking."""
        if not kwargs:
            return self.get_prd(prd_id)

        now = _utcnow()
        kwargs["updated_at"] = now

        new_status = kwargs.get("status")
        if new_status:
            current = self.get_prd(prd_id)
            if new_status == "draft":
                kwargs.setdefault("ready_at", None)
                kwargs.setdefault("split_at", None)
                kwargs.setdefault("completed_at", None)
            elif new_status == "ready":
                if current and not current.get("ready_at"):
                    kwargs["ready_at"] = now
                kwargs.setdefault("split_at", None)
                kwargs.setdefault("completed_at", None)
            elif new_status == "split":
                if current and not current.get("split_at"):
                    kwargs["split_at"] = now
                kwargs.setdefault("completed_at", None)
            elif new_status == "completed":
                kwargs.setdefault("completed_at", now)

        with self._session() as session:
            obj = session.get(Prd, prd_id)
            if not obj:
                return None
            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            session.add(obj)
        return self.get_prd(prd_id)

    def delete_prd(self, prd_id: str) -> bool:
        """Delete a PRD."""
        with self._session() as session:
            obj = session.get(Prd, prd_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def get_next_prd_id(self, project_id: str) -> str:
        """Generate next PRD ID for a project."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        shortname = project["shortname"]
        prefix = f"{shortname}-P"
        with self._session() as session:
            result = session.exec(
                text(
                    "SELECT MAX(CAST(SUBSTR(id, :offset) AS INTEGER)) "
                    "FROM prds WHERE project_id = :pid AND id LIKE :pattern"
                ),
                params={"offset": len(prefix) + 1, "pid": project_id, "pattern": f"{prefix}%"},
            ).one()
            max_num = result[0] or 0
        return f"{shortname}-P{max_num + 1:04d}"

    # ==================================================================
    # Task Operations
    # ==================================================================

    def create_task(
        self,
        task_id: str,
        project_id: str,
        title: str,
        file_path: str | None = None,
        status: str = "pending",
        priority: str = "medium",
        prd_id: str | None = None,
        component: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a new task."""
        now = _utcnow()
        task = Task(
            id=task_id,
            project_id=project_id,
            prd_id=prd_id,
            title=title,
            file_path=file_path,
            status=status,
            priority=priority,
            component=component,
            created_at=now,
            updated_at=now,
        )
        with self._session() as session:
            session.add(task)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID."""
        with self._session() as session:
            obj = session.get(Task, task_id)
            return _model_to_dict(obj) if obj else None

    def list_tasks(
        self,
        project_id: str,
        status: str | None = None,
        prd_id: str | None = None,
        sprint_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks with optional filters."""
        with self._session() as session:
            if sprint_id:
                rows = session.exec(
                    text(
                        "SELECT t.* FROM tasks t "
                        "LEFT JOIN prds p ON t.prd_id = p.id "
                        "WHERE t.project_id = :pid "
                        "AND (p.sprint_id = :sid OR (t.prd_id IS NULL AND :sid2 = '')) "
                        + ("AND t.status = :status " if status else "")
                        + ("AND t.prd_id = :prd_id " if prd_id else "")
                        + "ORDER BY t.created_at DESC"
                    ),
                    params={
                        "pid": project_id,
                        "sid": sprint_id,
                        "sid2": sprint_id,
                        **({"status": status} if status else {}),
                        **({"prd_id": prd_id} if prd_id else {}),
                    },
                )
                return [dict(r._mapping) for r in rows]
            else:
                stmt = select(Task).where(Task.project_id == project_id)
                if status:
                    stmt = stmt.where(Task.status == status)
                if prd_id:
                    stmt = stmt.where(Task.prd_id == prd_id)
                stmt = stmt.order_by(Task.created_at.desc())  # type: ignore[union-attr]
                return [_model_to_dict(r) for r in session.exec(stmt).all()]

    def list_tasks_by_sprint(
        self,
        project_id: str,
        sprint_id: str,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List tasks for a sprint (derived via PRD relationship)."""
        with self._session() as session:
            q = (
                "SELECT t.*, p.sprint_id as derived_sprint_id "
                "FROM tasks t "
                "INNER JOIN prds p ON t.prd_id = p.id "
                "WHERE t.project_id = :pid AND p.sprint_id = :sid "
            )
            params: dict[str, Any] = {"pid": project_id, "sid": sprint_id}
            if status:
                q += "AND t.status = :status "
                params["status"] = status
            q += "ORDER BY t.created_at DESC"
            rows = session.exec(text(q), params=params)
            return [dict(r._mapping) for r in rows]

    def update_task(self, task_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update task fields."""
        if not kwargs:
            return self.get_task(task_id)

        now = _utcnow()
        kwargs["updated_at"] = now

        new_status = kwargs.get("status")
        if new_status:
            if new_status == "in_progress":
                current = self.get_task(task_id)
                if current and not current.get("started_at"):
                    kwargs["started_at"] = now
                kwargs.setdefault("completed_at", None)
            elif new_status == "completed":
                kwargs.setdefault("completed_at", now)
            elif new_status == "pending":
                kwargs.setdefault("started_at", None)
                kwargs.setdefault("completed_at", None)
            elif new_status == "blocked":
                kwargs.setdefault("completed_at", None)

        with self._session() as session:
            obj = session.get(Task, task_id)
            if not obj:
                return None
            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            session.add(obj)
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        with self._session() as session:
            obj = session.get(Task, task_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def get_next_task_id(self, project_id: str) -> str:
        """Generate next task ID for a project."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        shortname = project["shortname"]
        prefix = f"{shortname}-T"
        with self._session() as session:
            result = session.exec(
                text(
                    "SELECT MAX(CAST(SUBSTR(id, :offset) AS INTEGER)) "
                    "FROM tasks WHERE project_id = :pid AND id LIKE :pattern"
                ),
                params={"offset": len(prefix) + 1, "pid": project_id, "pattern": f"{prefix}%"},
            ).one()
            max_num = result[0] or 0
        return f"{shortname}-T{max_num + 1:05d}"

    # ==================================================================
    # Sprint Operations
    # ==================================================================

    def create_sprint(
        self,
        sprint_id: str,
        project_id: str,
        title: str,
        goal: str = "",
        status: str = "planned",
    ) -> dict[str, Any] | None:
        """Create a new sprint."""
        now = _utcnow()
        sprint = Sprint(
            id=sprint_id,
            project_id=project_id,
            title=title,
            goal=goal,
            status=status,
            created_at=now,
        )
        with self._session() as session:
            session.add(sprint)
        return self.get_sprint(sprint_id)

    def get_sprint(self, sprint_id: str) -> dict[str, Any] | None:
        """Get sprint by ID with PRD and task summary."""
        with self._session() as session:
            obj = session.get(Sprint, sprint_id)
            if not obj:
                return None
            sprint = _model_to_dict(obj)

            # Count PRDs
            prd_count = session.exec(
                select(func.count()).where(Prd.sprint_id == sprint_id)  # type: ignore[arg-type]
            ).one()
            sprint["prd_count"] = prd_count

            # Task counts via PRD relationship
            rows = session.exec(
                text(
                    "SELECT t.status, COUNT(*) as count "
                    "FROM tasks t INNER JOIN prds p ON t.prd_id = p.id "
                    "WHERE p.sprint_id = :sid GROUP BY t.status"
                ),
                params={"sid": sprint_id},
            )
            sprint["task_counts"] = {r._mapping["status"]: r._mapping["count"] for r in rows}
            return sprint

    def list_sprints(self, project_id: str) -> list[dict[str, Any]]:
        """List all sprints for a project."""
        with self._session() as session:
            results = session.exec(
                select(Sprint)
                .where(Sprint.project_id == project_id)
                .order_by(Sprint.created_at.desc())  # type: ignore[union-attr]
            ).all()
            return [_model_to_dict(r) for r in results]

    def update_sprint(self, sprint_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update sprint fields."""
        if not kwargs:
            return self.get_sprint(sprint_id)

        new_status = kwargs.get("status")
        if new_status:
            now = _utcnow()
            if new_status == "active":
                kwargs.setdefault("started_at", now)
                kwargs.setdefault("completed_at", None)
            elif new_status == "completed":
                kwargs.setdefault("completed_at", now)
            elif new_status == "planned":
                kwargs.setdefault("started_at", None)
                kwargs.setdefault("completed_at", None)

        with self._session() as session:
            obj = session.get(Sprint, sprint_id)
            if not obj:
                return None
            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            session.add(obj)
        return self.get_sprint(sprint_id)

    def delete_sprint(self, sprint_id: str) -> bool:
        """Delete a sprint."""
        with self._session() as session:
            obj = session.get(Sprint, sprint_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    def get_sprint_prds(self, sprint_id: str) -> list[dict[str, Any]]:
        """Get all PRDs assigned to a sprint."""
        with self._session() as session:
            results = session.exec(
                select(Prd)
                .where(Prd.sprint_id == sprint_id)
                .order_by(Prd.updated_at.desc())  # type: ignore[union-attr]
            ).all()
            return [_model_to_dict(r) for r in results]

    def assign_prd_to_sprint(
        self, prd_id: str, sprint_id: str | None
    ) -> dict[str, Any] | None:
        """Assign a PRD to a sprint (or unassign by passing None)."""
        return self.update_prd(prd_id, sprint_id=sprint_id)

    def get_next_sprint_id(self, project_id: str) -> str:
        """Generate next sprint ID for a project."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        shortname = project["shortname"]
        prefix = f"{shortname}-S"
        with self._session() as session:
            result = session.exec(
                text(
                    "SELECT MAX(CAST(SUBSTR(id, :offset) AS INTEGER)) "
                    "FROM sprints WHERE project_id = :pid AND id LIKE :pattern"
                ),
                params={"offset": len(prefix) + 1, "pid": project_id, "pattern": f"{prefix}%"},
            ).one()
            max_num = result[0] or 0
        return f"{shortname}-S{max_num + 1:04d}"

    # ==================================================================
    # Design Operations
    # ==================================================================

    def create_design(
        self,
        design_id: str,
        prd_id: str,
        project_id: str,
        file_path: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a new design document."""
        now = _utcnow()
        design = Design(
            id=design_id,
            prd_id=prd_id,
            project_id=project_id,
            file_path=file_path,
            created_at=now,
            updated_at=now,
        )
        with self._session() as session:
            session.add(design)
        return self.get_design(design_id)

    def get_design(self, design_id: str) -> dict[str, Any] | None:
        """Get design by ID."""
        with self._session() as session:
            obj = session.get(Design, design_id)
            return _model_to_dict(obj) if obj else None

    def get_design_by_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get design by parent PRD ID."""
        with self._session() as session:
            obj = session.exec(select(Design).where(Design.prd_id == prd_id)).first()
            return _model_to_dict(obj) if obj else None

    def list_designs(self, project_id: str) -> list[dict[str, Any]]:
        """List all designs for a project."""
        with self._session() as session:
            results = session.exec(
                select(Design)
                .where(Design.project_id == project_id)
                .order_by(Design.updated_at.desc())  # type: ignore[union-attr]
            ).all()
            return [_model_to_dict(r) for r in results]

    def update_design(self, design_id: str, **kwargs: Any) -> dict[str, Any] | None:
        """Update design fields."""
        if not kwargs:
            return self.get_design(design_id)
        kwargs["updated_at"] = _utcnow()
        with self._session() as session:
            obj = session.get(Design, design_id)
            if not obj:
                return None
            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            session.add(obj)
        return self.get_design(design_id)

    def delete_design(self, design_id: str) -> bool:
        """Delete a design."""
        with self._session() as session:
            obj = session.get(Design, design_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    # ==================================================================
    # Sync Mapping Operations
    # ==================================================================

    def create_sync_mapping(
        self,
        entity_type: str,
        local_id: str,
        external_system: str,
        external_id: str,
    ) -> dict[str, Any]:
        """Create a sync mapping for external system integration."""
        now = _utcnow()
        with self._session() as session:
            # Upsert: check if exists first
            existing = session.exec(
                select(SyncMapping).where(
                    SyncMapping.entity_type == entity_type,
                    SyncMapping.local_id == local_id,
                    SyncMapping.external_system == external_system,
                )
            ).first()
            if existing:
                existing.external_id = external_id
                existing.last_synced = now
                session.add(existing)
                session.flush()
                return _model_to_dict(existing)
            else:
                mapping = SyncMapping(
                    entity_type=entity_type,
                    local_id=local_id,
                    external_system=external_system,
                    external_id=external_id,
                    last_synced=now,
                )
                session.add(mapping)
                session.flush()
                return _model_to_dict(mapping)

    def get_sync_mapping(
        self, entity_type: str, local_id: str, external_system: str
    ) -> dict[str, Any] | None:
        """Get sync mapping for an entity."""
        with self._session() as session:
            obj = session.exec(
                select(SyncMapping).where(
                    SyncMapping.entity_type == entity_type,
                    SyncMapping.local_id == local_id,
                    SyncMapping.external_system == external_system,
                )
            ).first()
            return _model_to_dict(obj) if obj else None

    def get_sync_mapping_by_external(
        self, entity_type: str, external_system: str, external_id: str
    ) -> dict[str, Any] | None:
        """Get sync mapping by external ID."""
        with self._session() as session:
            obj = session.exec(
                select(SyncMapping).where(
                    SyncMapping.entity_type == entity_type,
                    SyncMapping.external_system == external_system,
                    SyncMapping.external_id == external_id,
                )
            ).first()
            return _model_to_dict(obj) if obj else None

    def list_sync_mappings(
        self, entity_type: str | None = None, external_system: str | None = None
    ) -> list[dict[str, Any]]:
        """List all sync mappings, optionally filtered."""
        with self._session() as session:
            stmt = select(SyncMapping)
            if entity_type:
                stmt = stmt.where(SyncMapping.entity_type == entity_type)
            if external_system:
                stmt = stmt.where(SyncMapping.external_system == external_system)
            stmt = stmt.order_by(SyncMapping.last_synced.desc())  # type: ignore[union-attr]
            return [_model_to_dict(r) for r in session.exec(stmt).all()]

    def update_sync_mapping(
        self,
        entity_type: str,
        local_id: str,
        external_system: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Update sync mapping fields."""
        if not kwargs:
            return self.get_sync_mapping(entity_type, local_id, external_system)
        kwargs["last_synced"] = _utcnow()
        with self._session() as session:
            obj = session.exec(
                select(SyncMapping).where(
                    SyncMapping.entity_type == entity_type,
                    SyncMapping.local_id == local_id,
                    SyncMapping.external_system == external_system,
                )
            ).first()
            if not obj:
                return None
            for k, v in kwargs.items():
                if hasattr(obj, k):
                    setattr(obj, k, v)
            session.add(obj)
        return self.get_sync_mapping(entity_type, local_id, external_system)

    def delete_sync_mapping(
        self, entity_type: str, local_id: str, external_system: str
    ) -> bool:
        """Delete a sync mapping."""
        with self._session() as session:
            obj = session.exec(
                select(SyncMapping).where(
                    SyncMapping.entity_type == entity_type,
                    SyncMapping.local_id == local_id,
                    SyncMapping.external_system == external_system,
                )
            ).first()
            if not obj:
                return False
            session.delete(obj)
            return True

    # ==================================================================
    # External Config Operations
    # ==================================================================

    def get_external_config(
        self, project_id: str, system: str
    ) -> dict[str, Any] | None:
        """Get external system configuration for a project."""
        with self._session() as session:
            obj = session.exec(
                select(ExternalConfig).where(
                    ExternalConfig.project_id == project_id,
                    ExternalConfig.system == system,
                )
            ).first()
            if not obj:
                return None
            result = _model_to_dict(obj)
            if result.get("config"):
                result["config"] = json.loads(result["config"])
            return result

    def set_external_config(
        self, project_id: str, system: str, config: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Set external system configuration for a project."""
        now = _utcnow()
        config_json = json.dumps(config)
        with self._session() as session:
            existing = session.exec(
                select(ExternalConfig).where(
                    ExternalConfig.project_id == project_id,
                    ExternalConfig.system == system,
                )
            ).first()
            if existing:
                existing.config = config_json
                existing.updated_at = now
                session.add(existing)
            else:
                session.add(
                    ExternalConfig(
                        project_id=project_id,
                        system=system,
                        config=config_json,
                        created_at=now,
                        updated_at=now,
                    )
                )
        return self.get_external_config(project_id, system)

    def delete_external_config(self, project_id: str, system: str) -> bool:
        """Delete external system configuration."""
        with self._session() as session:
            obj = session.exec(
                select(ExternalConfig).where(
                    ExternalConfig.project_id == project_id,
                    ExternalConfig.system == system,
                )
            ).first()
            if not obj:
                return False
            session.delete(obj)
            return True

    def list_external_configs(self, project_id: str) -> list[dict[str, Any]]:
        """List all external configurations for a project."""
        with self._session() as session:
            results = session.exec(
                select(ExternalConfig)
                .where(ExternalConfig.project_id == project_id)
                .order_by(ExternalConfig.system)
            ).all()
            out = []
            for obj in results:
                d = _model_to_dict(obj)
                if d.get("config"):
                    d["config"] = json.loads(d["config"])
                out.append(d)
            return out

    # ==================================================================
    # Review Operations
    # ==================================================================

    def create_review(
        self,
        task_id: str,
        project_id: str,
        round_num: int,
        reviewer_type: str,
        verdict: str,
        findings: str | None = None,
        test_output: str | None = None,
    ) -> dict[str, Any]:
        """Create a new review record."""
        if reviewer_type not in self.VALID_REVIEWER_TYPES:
            raise ValueError(
                f"Invalid reviewer_type: {reviewer_type!r}. "
                f"Must be one of {self.VALID_REVIEWER_TYPES}"
            )
        if verdict not in self.VALID_VERDICTS:
            raise ValueError(
                f"Invalid verdict: {verdict!r}. "
                f"Must be one of {self.VALID_VERDICTS}"
            )
        now = _utcnow()
        review = Review(
            task_id=task_id,
            project_id=project_id,
            round=round_num,
            reviewer_type=reviewer_type,
            verdict=verdict,
            findings=findings,
            test_output=test_output,
            created_at=now,
        )
        with self._session() as session:
            session.add(review)
            session.flush()
            return _model_to_dict(review)

    def get_reviews_for_task(self, task_id: str) -> list[dict[str, Any]]:
        """Get all reviews for a task."""
        with self._session() as session:
            results = session.exec(
                select(Review)
                .where(Review.task_id == task_id)
                .order_by(Review.round, Review.created_at)  # type: ignore[arg-type]
            ).all()
            return [_model_to_dict(r) for r in results]

    def get_latest_approved_review(self, task_id: str) -> dict[str, Any] | None:
        """Get the most recent approved/passed review for a task."""
        with self._session() as session:
            obj = session.exec(
                select(Review)
                .where(
                    Review.task_id == task_id,
                    Review.verdict.in_(["pass", "approve"]),  # type: ignore[union-attr]
                )
                .order_by(Review.created_at.desc())  # type: ignore[union-attr]
                .limit(1)
            ).first()
            return _model_to_dict(obj) if obj else None

    # ==================================================================
    # Audit Log Operations
    # ==================================================================

    def append_audit_log(
        self,
        project_id: str,
        action_type: str,
        outcome: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        target_entity: str | None = None,
        details: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        """Append an entry to the audit log."""
        details_str: str | None = None
        if details is not None:
            details_str = json.dumps(details) if isinstance(details, dict) else str(details)

        now = _utcnow()
        entry = AuditLog(
            project_id=project_id,
            agent_id=agent_id,
            run_id=run_id,
            action_type=action_type,
            target_entity=target_entity,
            outcome=outcome,
            details=details_str,
            created_at=now,
        )
        with self._session() as session:
            session.add(entry)
            session.flush()
            return _model_to_dict(entry)

    def get_audit_log(
        self,
        project_id: str,
        agent_id: str | None = None,
        run_id: str | None = None,
        action_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get audit log entries with optional filters."""
        with self._session() as session:
            stmt = select(AuditLog).where(AuditLog.project_id == project_id)
            if agent_id is not None:
                stmt = stmt.where(AuditLog.agent_id == agent_id)
            if run_id is not None:
                stmt = stmt.where(AuditLog.run_id == run_id)
            if action_type is not None:
                stmt = stmt.where(AuditLog.action_type == action_type)
            stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)  # type: ignore[union-attr]
            return [_model_to_dict(r) for r in session.exec(stmt).all()]

    # ==================================================================
    # Worktree Operations
    # ==================================================================

    def get_next_worktree_id(self, project_id: str) -> str:
        """Generate next worktree ID for a project."""
        project = self.get_project(project_id)
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        shortname = project["shortname"]
        with self._session() as session:
            count = session.exec(
                select(func.count()).where(Worktree.project_id == project_id)  # type: ignore[arg-type]
            ).one()
        return f"{shortname}-W{count + 1:04d}"

    def create_worktree(
        self,
        worktree_id: str,
        project_id: str,
        prd_id: str,
        branch_name: str,
        path: str,
        sprint_id: str | None = None,
        status: str = "active",
    ) -> dict[str, Any] | None:
        """Create a new worktree record."""
        now = _utcnow()
        wt = Worktree(
            id=worktree_id,
            project_id=project_id,
            prd_id=prd_id,
            sprint_id=sprint_id,
            branch_name=branch_name,
            path=path,
            status=status,
            created_at=now,
        )
        with self._session() as session:
            session.add(wt)
        return self.get_worktree(worktree_id)

    def get_worktree(self, worktree_id: str) -> dict[str, Any] | None:
        """Get worktree by ID."""
        with self._session() as session:
            obj = session.get(Worktree, worktree_id)
            return _model_to_dict(obj) if obj else None

    def get_worktree_by_prd(self, prd_id: str) -> dict[str, Any] | None:
        """Get the active worktree for a PRD."""
        with self._session() as session:
            obj = session.exec(
                select(Worktree)
                .where(Worktree.prd_id == prd_id, Worktree.status == "active")
                .order_by(Worktree.created_at.desc())  # type: ignore[union-attr]
                .limit(1)
            ).first()
            return _model_to_dict(obj) if obj else None

    def list_worktrees(
        self,
        project_id: str,
        status: str | None = None,
        sprint_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List worktrees for a project with optional filters."""
        with self._session() as session:
            stmt = select(Worktree).where(Worktree.project_id == project_id)
            if status:
                stmt = stmt.where(Worktree.status == status)
            if sprint_id:
                stmt = stmt.where(Worktree.sprint_id == sprint_id)
            stmt = stmt.order_by(Worktree.created_at.desc())  # type: ignore[union-attr]
            return [_model_to_dict(r) for r in session.exec(stmt).all()]

    def update_worktree(
        self, worktree_id: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """Update worktree fields."""
        if not kwargs:
            return self.get_worktree(worktree_id)
        allowed_fields = {"status", "cleaned_at", "pr_url", "path", "branch_name", "sprint_id"}
        invalid_keys = set(kwargs.keys()) - allowed_fields
        if invalid_keys:
            raise ValueError(
                f"Invalid worktree fields: {invalid_keys}. Allowed: {allowed_fields}"
            )
        new_status = kwargs.get("status")
        if new_status and new_status in ("completed", "abandoned"):
            kwargs.setdefault("cleaned_at", _utcnow())
        with self._session() as session:
            obj = session.get(Worktree, worktree_id)
            if not obj:
                return None
            for k, v in kwargs.items():
                setattr(obj, k, v)
            session.add(obj)
        return self.get_worktree(worktree_id)

    def delete_worktree(self, worktree_id: str) -> bool:
        """Delete a worktree record."""
        with self._session() as session:
            obj = session.get(Worktree, worktree_id)
            if not obj:
                return False
            session.delete(obj)
            return True

    # ==================================================================
    # Requirements CRUD
    # ==================================================================

    def upsert_requirement(
        self,
        id: str,
        prd_id: str,
        req_type: str,
        req_number: str,
        summary: str,
        depth: str = "structural",
    ) -> dict[str, Any]:
        """Insert or replace a requirement record."""
        with self._session() as session:
            existing = session.get(Requirement, id)
            if existing:
                existing.prd_id = prd_id
                existing.req_type = req_type
                existing.req_number = req_number
                existing.summary = summary
                existing.depth = depth
                session.flush()
                session.refresh(existing)
                return _model_to_dict(existing)
            record = Requirement(
                id=id,
                prd_id=prd_id,
                req_type=req_type,
                req_number=req_number,
                summary=summary,
                depth=depth,
            )
            session.add(record)
            session.flush()
            session.refresh(record)
            return _model_to_dict(record)

    def get_requirement(self, requirement_id: str) -> dict[str, Any] | None:
        """Get a single requirement by ID."""
        with self._session() as session:
            obj = session.get(Requirement, requirement_id)
            return _model_to_dict(obj) if obj else None

    def get_requirements(
        self, prd_id: str, req_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all requirements for a PRD, optionally filtered by type."""
        with self._session() as session:
            stmt = select(Requirement).where(Requirement.prd_id == prd_id)
            if req_type is not None:
                stmt = stmt.where(Requirement.req_type == req_type)
            stmt = stmt.order_by(Requirement.req_number)  # type: ignore[arg-type]
            rows = session.exec(stmt).all()
            return [_model_to_dict(r) for r in rows]

    def delete_requirements(self, prd_id: str) -> int:
        """Delete all requirements for a PRD."""
        with self._session() as session:
            stmt = select(Requirement).where(Requirement.prd_id == prd_id)
            rows = session.exec(stmt).all()
            count = len(rows)
            for r in rows:
                session.delete(r)
            return count

    # ==================================================================
    # Requirement Links CRUD
    # ==================================================================

    def link_task_requirement(self, requirement_id: str, task_id: str) -> dict[str, Any]:
        """Link a task to a requirement (idempotent)."""
        with self._session() as session:
            existing = session.get(RequirementLink, (requirement_id, task_id))
            if existing:
                return _model_to_dict(existing)
            link = RequirementLink(requirement_id=requirement_id, task_id=task_id)
            session.add(link)
            session.flush()
            session.refresh(link)
            return _model_to_dict(link)

    def get_task_requirements(self, task_id: str) -> list[dict[str, Any]]:
        """Get all requirements linked to a task, with verification status."""
        with self._session() as session:
            rows = session.execute(
                text("""
                    SELECT r.*, rl.created_at as linked_at,
                           CASE WHEN av.id IS NOT NULL THEN 1 ELSE 0 END as verified,
                           av.verified_by, av.evidence_type, av.evidence, av.verified_at
                    FROM requirement_links rl
                    INNER JOIN requirements r ON rl.requirement_id = r.id
                    LEFT JOIN ac_verifications av
                        ON av.requirement_id = r.id AND av.task_id = rl.task_id
                    WHERE rl.task_id = :task_id
                    ORDER BY r.req_number
                """),
                {"task_id": task_id},
            ).mappings().all()
            return [dict(r) for r in rows]

    def get_requirement_tasks(self, requirement_id: str) -> list[dict[str, Any]]:
        """Get all tasks linked to a requirement."""
        with self._session() as session:
            rows = session.execute(
                text("""
                    SELECT t.* FROM requirement_links rl
                    INNER JOIN tasks t ON rl.task_id = t.id
                    WHERE rl.requirement_id = :req_id
                    ORDER BY t.id
                """),
                {"req_id": requirement_id},
            ).mappings().all()
            return [dict(r) for r in rows]

    def get_orphaned_requirements(self, prd_id: str) -> list[dict[str, Any]]:
        """Get requirements with zero linked tasks."""
        with self._session() as session:
            rows = session.execute(
                text("""
                    SELECT r.* FROM requirements r
                    LEFT JOIN requirement_links rl ON r.id = rl.requirement_id
                    WHERE r.prd_id = :prd_id AND rl.requirement_id IS NULL
                    ORDER BY r.req_number
                """),
                {"prd_id": prd_id},
            ).mappings().all()
            return [dict(r) for r in rows]

    def get_coverage_stats(self, prd_id: str) -> dict[str, Any]:
        """Compute requirement coverage statistics for a PRD."""
        with self._session() as session:
            total_row = session.execute(
                text("SELECT COUNT(*) as cnt FROM requirements WHERE prd_id = :prd_id"),
                {"prd_id": prd_id},
            ).mappings().first()
            total = total_row["cnt"] if total_row else 0

            linked_row = session.execute(
                text("""
                    SELECT COUNT(DISTINCT r.id) as cnt
                    FROM requirements r
                    INNER JOIN requirement_links rl ON r.id = rl.requirement_id
                    WHERE r.prd_id = :prd_id
                """),
                {"prd_id": prd_id},
            ).mappings().first()
            linked = linked_row["cnt"] if linked_row else 0

            orphaned = total - linked

            type_rows = session.execute(
                text("""
                    SELECT r.req_type,
                           COUNT(*) as total,
                           COUNT(rl.requirement_id) as linked
                    FROM requirements r
                    LEFT JOIN (
                        SELECT DISTINCT requirement_id FROM requirement_links
                    ) rl ON r.id = rl.requirement_id
                    WHERE r.prd_id = :prd_id
                    GROUP BY r.req_type
                """),
                {"prd_id": prd_id},
            ).mappings().all()

            by_type = {
                row["req_type"]: {"total": row["total"], "linked": row["linked"]}
                for row in type_rows
            }

            return {
                "total": total,
                "linked": linked,
                "orphaned": orphaned,
                "by_type": by_type,
            }

    # ==================================================================
    # AC Verifications CRUD
    # ==================================================================

    def record_ac_verification(
        self,
        requirement_id: str,
        task_id: str,
        verified_by: str,
        evidence_type: str,
        evidence: str,
    ) -> dict[str, Any]:
        """Record acceptance-criteria verification evidence (upsert)."""
        with self._session() as session:
            # Check for existing record
            existing = session.exec(
                select(AcVerification).where(
                    AcVerification.requirement_id == requirement_id,
                    AcVerification.task_id == task_id,
                )
            ).first()
            if existing:
                existing.verified_by = verified_by
                existing.evidence_type = evidence_type
                existing.evidence = evidence
                existing.verified_at = _utcnow()
                session.flush()
                session.refresh(existing)
                return _model_to_dict(existing)
            record = AcVerification(
                requirement_id=requirement_id,
                task_id=task_id,
                verified_by=verified_by,
                evidence_type=evidence_type,
                evidence=evidence,
            )
            session.add(record)
            session.flush()
            session.refresh(record)
            return _model_to_dict(record)

    def get_ac_verifications(self, task_id: str) -> list[dict[str, Any]]:
        """Get all AC verifications for a task."""
        with self._session() as session:
            stmt = (
                select(AcVerification)
                .where(AcVerification.task_id == task_id)
                .order_by(AcVerification.verified_at)  # type: ignore[arg-type]
            )
            rows = session.exec(stmt).all()
            return [_model_to_dict(r) for r in rows]

    def get_unverified_acs(self, task_id: str) -> list[dict[str, Any]]:
        """Get AC requirements linked to a task but not yet verified."""
        with self._session() as session:
            rows = session.execute(
                text("""
                    SELECT r.* FROM requirement_links rl
                    INNER JOIN requirements r ON rl.requirement_id = r.id
                    LEFT JOIN ac_verifications av
                        ON av.requirement_id = r.id AND av.task_id = rl.task_id
                    WHERE rl.task_id = :task_id AND av.id IS NULL
                    ORDER BY r.req_number
                """),
                {"task_id": task_id},
            ).mappings().all()
            return [dict(r) for r in rows]

    # ==================================================================
    # Challenge Records
    # ==================================================================

    def create_challenge_round(
        self,
        artifact_type: str,
        artifact_id: str,
        round_number: int,
        objections: str,
        challenger_context: str | None = None,
    ) -> dict[str, Any]:
        """Create a new challenge round for an artifact."""
        with self._session() as session:
            record = ChallengeRecord(
                artifact_type=artifact_type,
                artifact_id=artifact_id,
                round_number=round_number,
                objections=objections,
                challenger_context=challenger_context,
            )
            session.add(record)
            session.flush()
            session.refresh(record)
            return _model_to_dict(record)

    def update_challenge_round(
        self,
        artifact_type: str,
        artifact_id: str,
        round_number: int,
        responses: str | None = None,
        verdict: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        """Update specific fields of a challenge round."""
        with self._session() as session:
            stmt = select(ChallengeRecord).where(
                ChallengeRecord.artifact_type == artifact_type,
                ChallengeRecord.artifact_id == artifact_id,
                ChallengeRecord.round_number == round_number,
            )
            record = session.exec(stmt).first()
            if not record:
                return None
            if responses is not None:
                record.responses = responses
            if verdict is not None:
                record.verdict = verdict
            if status is not None:
                record.status = status
            session.flush()
            session.refresh(record)
            return _model_to_dict(record)

    def get_challenge_rounds(
        self, artifact_type: str, artifact_id: str
    ) -> list[dict[str, Any]]:
        """Get all challenge rounds for an artifact, ordered by round number."""
        with self._session() as session:
            stmt = (
                select(ChallengeRecord)
                .where(
                    ChallengeRecord.artifact_type == artifact_type,
                    ChallengeRecord.artifact_id == artifact_id,
                )
                .order_by(ChallengeRecord.round_number)  # type: ignore[arg-type]
            )
            rows = session.exec(stmt).all()
            results = []
            for row in rows:
                d = _model_to_dict(row)
                for field in ("objections", "responses"):
                    if d.get(field):
                        with contextlib.suppress(json.JSONDecodeError, TypeError):
                            d[field] = json.loads(d[field])
                results.append(d)
            return results

    def get_challenge_status(
        self, artifact_type: str, artifact_id: str
    ) -> dict[str, Any]:
        """Get summary status of challenge rounds for an artifact."""
        with self._session() as session:
            stmt = select(
                ChallengeRecord.status, func.count().label("cnt")
            ).where(
                ChallengeRecord.artifact_type == artifact_type,
                ChallengeRecord.artifact_id == artifact_id,
            ).group_by(ChallengeRecord.status)
            rows = session.exec(stmt).all()

            total = sum(r[1] for r in rows)
            counts = {r[0]: r[1] for r in rows}

            latest_row = session.exec(
                select(ChallengeRecord)
                .where(
                    ChallengeRecord.artifact_type == artifact_type,
                    ChallengeRecord.artifact_id == artifact_id,
                )
                .order_by(ChallengeRecord.round_number.desc())  # type: ignore[attr-defined]
                .limit(1)
            ).first()

            return {
                "total_rounds": total,
                "latest_status": latest_row.status if latest_row else None,
                "open_count": counts.get("open", 0),
                "closed_count": counts.get("closed", 0),
            }


# ======================================================================
# Global singleton
# ======================================================================

_session_db: SessionDatabase | None = None


def get_session_db() -> SessionDatabase:
    """Get or create the global SessionDatabase instance."""
    global _session_db
    if _session_db is None:
        _session_db = SessionDatabase()
    return _session_db

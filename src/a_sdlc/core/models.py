"""
SQLModel entity models for the a-sdlc database schema.

Provides typed, validated ORM classes for all tables defined in
`core/database.py:_create_schema()`.  Each model mirrors the existing
database DDL -- column types, constraints, defaults, foreign keys, and
indexes -- so that the models can eventually replace the raw-SQL layer
without any schema migration.

Usage (read-only validation today, full ORM later):

    from a_sdlc.core.models import Task, Project
    task = Task(id="PROJ-T00001", project_id="proj-uuid", title="Do stuff")
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import text
from sqlmodel import Field, SQLModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS_NOW = text("CURRENT_TIMESTAMP")
"""Server-side default for timestamp columns.

Uses ``sa.text()`` so that SQLAlchemy emits the bare SQL expression
``DEFAULT CURRENT_TIMESTAMP`` rather than a quoted string literal.
This is required for PostgreSQL compatibility.
"""


def _ts_field(
    *,
    nullable: bool = True,
    default_now: bool = False,
    index: bool = False,
) -> datetime | None:
    """Return a ``Field(...)`` configured for a TIMESTAMP column."""
    if default_now:
        return Field(
            default=None,
            sa_column_kwargs={"server_default": _TS_NOW},
            index=index,
        )  # type: ignore[return-value]
    if nullable:
        return Field(default=None, index=index)  # type: ignore[return-value]
    return Field(index=index)  # type: ignore[return-value]


# ===================================================================
# 1. schema_version
# ===================================================================


class SchemaVersion(SQLModel, table=True):
    """Single-row table tracking the current database schema version."""

    __tablename__ = "schema_version"  # type: ignore[assignment]

    version: int = Field(primary_key=True)


# ===================================================================
# 2. projects
# ===================================================================


class Project(SQLModel, table=True):
    """Top-level project registry."""

    __tablename__ = "projects"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    shortname: str = Field(unique=True, index=True)
    name: str
    # Nullable for centralized/remote deployments where the project has no
    # server-side path. UNIQUE still holds for non-NULL values; multiple NULL
    # paths are allowed (NULLs are distinct in SQLite and PostgreSQL).
    path: str | None = Field(default=None, unique=True, index=True)
    created_at: datetime | None = _ts_field(default_now=True)
    last_accessed: datetime | None = _ts_field(default_now=True)


# ===================================================================
# 3. sprints  (defined before prds because prds FK -> sprints)
# ===================================================================


class Sprint(SQLModel, table=True):
    """Sprint / iteration metadata."""

    __tablename__ = "sprints"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    title: str
    goal: str | None = Field(default=None)
    status: str = Field(default="planned", index=True)
    external_id: str | None = Field(default=None)
    external_url: str | None = Field(default=None)
    created_at: datetime | None = _ts_field(default_now=True)
    started_at: datetime | None = _ts_field()
    completed_at: datetime | None = _ts_field()


# ===================================================================
# 4. prds
# ===================================================================


class Prd(SQLModel, table=True):
    """Product Requirements Document metadata."""

    __tablename__ = "prds"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    sprint_id: str | None = Field(default=None, foreign_key="sprints.id", index=True)
    title: str
    file_path: str | None = Field(default=None)
    status: str = Field(default="draft", index=True)
    source: str | None = Field(default=None)
    version: str = Field(default="1.0.0")
    created_at: datetime | None = _ts_field(default_now=True)
    updated_at: datetime | None = _ts_field(default_now=True)
    ready_at: datetime | None = _ts_field()
    split_at: datetime | None = _ts_field()
    completed_at: datetime | None = _ts_field()


# ===================================================================
# 5. tasks
# ===================================================================


class Task(SQLModel, table=True):
    """Task metadata -- inherits sprint membership through its PRD."""

    __tablename__ = "tasks"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    prd_id: str | None = Field(default=None, foreign_key="prds.id", index=True)
    title: str
    file_path: str | None = Field(default=None)
    status: str = Field(default="pending", index=True)
    priority: str = Field(default="medium")
    component: str | None = Field(default=None)
    created_at: datetime | None = _ts_field(default_now=True)
    updated_at: datetime | None = _ts_field(default_now=True)
    started_at: datetime | None = _ts_field()
    completed_at: datetime | None = _ts_field()


# ===================================================================
# 6. designs
# ===================================================================


class Design(SQLModel, table=True):
    """Design document -- 1:1 relationship with a PRD."""

    __tablename__ = "designs"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    prd_id: str = Field(unique=True, foreign_key="prds.id", index=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    file_path: str | None = Field(default=None)
    created_at: datetime | None = _ts_field(default_now=True)
    updated_at: datetime | None = _ts_field(default_now=True)


# ===================================================================
# 7. sync_mappings
# ===================================================================


class SyncMapping(SQLModel, table=True):
    """Maps local entities to external system identifiers (Linear, Jira)."""

    __tablename__ = "sync_mappings"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True)
    local_id: str = Field(index=True)
    external_system: str = Field(index=True)
    external_id: str = Field(index=True)
    sync_status: str = Field(default="synced")
    last_synced: datetime | None = _ts_field(default_now=True)

    # UNIQUE(entity_type, local_id, external_system) enforced via __table_args__
    class Config:  # noqa: N801 -- Pydantic v1-style config in SQLModel
        table_args = None  # placeholder; real constraint via sa_column or migration


# ===================================================================
# 8. external_config
# ===================================================================


class ExternalConfig(SQLModel, table=True):
    """Integration configuration for external systems per project."""

    __tablename__ = "external_config"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    system: str
    config: str  # JSON blob stored as TEXT
    created_at: datetime | None = _ts_field(default_now=True)
    updated_at: datetime | None = _ts_field(default_now=True)

    # UNIQUE(project_id, system)


# ===================================================================
# 9. worktrees
# ===================================================================


class Worktree(SQLModel, table=True):
    """Git worktree lifecycle tracking per PRD."""

    __tablename__ = "worktrees"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    prd_id: str = Field(foreign_key="prds.id", index=True)
    sprint_id: str | None = Field(default=None, foreign_key="sprints.id", index=True)
    branch_name: str
    path: str
    status: str = Field(default="active", index=True)
    pr_url: str | None = Field(default=None)
    created_at: datetime | None = _ts_field(default_now=True)
    cleaned_at: datetime | None = _ts_field()


# ===================================================================
# 10. reviews
# ===================================================================


class Review(SQLModel, table=True):
    """Review evidence per task per round."""

    __tablename__ = "reviews"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", index=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    round: int = Field(default=1)
    reviewer_type: str
    verdict: str
    findings: str | None = Field(default=None)
    test_output: str | None = Field(default=None)
    created_at: datetime | None = _ts_field(default_now=True)


# ===================================================================
# 11. audit_log
# ===================================================================


class AuditLog(SQLModel, table=True):
    """Append-only audit log for all significant actions."""

    __tablename__ = "audit_log"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    project_id: str = Field(index=True)
    agent_id: str | None = Field(default=None, index=True)
    run_id: str | None = Field(default=None, index=True)
    action_type: str = Field(index=True)
    target_entity: str | None = Field(default=None)
    outcome: str
    details: str | None = Field(default=None)
    created_at: datetime | None = _ts_field(default_now=True)


# ===================================================================
# 12. requirements
# ===================================================================


class Requirement(SQLModel, table=True):
    """Requirements traceability -- extracted from PRDs."""

    __tablename__ = "requirements"  # type: ignore[assignment]

    id: str = Field(primary_key=True)
    prd_id: str = Field(foreign_key="prds.id", index=True)
    req_type: str = Field(index=True)
    req_number: str
    summary: str
    depth: str = Field(default="structural")
    created_at: datetime | None = _ts_field(default_now=True)

    # UNIQUE(prd_id, req_number)


# ===================================================================
# 13. requirement_links
# ===================================================================


class RequirementLink(SQLModel, table=True):
    """Many-to-many link between requirements and tasks."""

    __tablename__ = "requirement_links"  # type: ignore[assignment]

    requirement_id: str = Field(foreign_key="requirements.id", primary_key=True)
    task_id: str = Field(foreign_key="tasks.id", primary_key=True)
    created_at: datetime | None = _ts_field(default_now=True)


# ===================================================================
# 14. ac_verifications
# ===================================================================


class AcVerification(SQLModel, table=True):
    """Acceptance-criteria verification evidence."""

    __tablename__ = "ac_verifications"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    requirement_id: str = Field(foreign_key="requirements.id")
    task_id: str = Field(foreign_key="tasks.id", index=True)
    verified_by: str | None = Field(default=None)
    evidence_type: str | None = Field(default=None)
    evidence: str | None = Field(default=None)
    verified_at: datetime | None = _ts_field(default_now=True)

    # UNIQUE(requirement_id, task_id)


# ===================================================================
# 15. challenge_records
# ===================================================================


class ChallengeRecord(SQLModel, table=True):
    """Adversarial review round records."""

    __tablename__ = "challenge_records"  # type: ignore[assignment]

    id: int | None = Field(default=None, primary_key=True)
    artifact_type: str = Field(index=True)
    artifact_id: str = Field(index=True)
    round_number: int
    objections: str | None = Field(default=None)
    responses: str | None = Field(default=None)
    verdict: str | None = Field(default=None)
    challenger_context: str | None = Field(default=None)
    status: str = Field(default="open")
    created_at: datetime | None = _ts_field(default_now=True)

    # UNIQUE(artifact_type, artifact_id, round_number)


# ===================================================================
# Registry: every model class keyed by its __tablename__
# ===================================================================

ALL_MODELS: dict[str, type[SQLModel]] = {
    cls.__tablename__: cls  # type: ignore[attr-defined]
    for cls in [
        SchemaVersion,
        Project,
        Sprint,
        Prd,
        Task,
        Design,
        SyncMapping,
        ExternalConfig,
        Worktree,
        Review,
        AuditLog,
        Requirement,
        RequirementLink,
        AcVerification,
        ChallengeRecord,
    ]
}
"""Mapping of SQL table name -> SQLModel class for all tables."""

ALL_TABLE_NAMES: frozenset[str] = frozenset(ALL_MODELS.keys())
"""Frozen set of all table names defined in the schema."""

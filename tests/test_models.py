"""
Tests for ``a_sdlc.core.models`` -- SQLModel entity definitions.

Validates:
- Every v15 schema table has a corresponding model
- Models can be instantiated with valid data
- Pydantic validation enforces types and nullability
- Default values match the DDL expectations
- The ALL_MODELS registry is complete
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest
from pydantic import ValidationError

from a_sdlc.core.database import SCHEMA_VERSION
from a_sdlc.core.models import (
    ALL_MODELS,
    ALL_TABLE_NAMES,
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

# -----------------------------------------------------------------------
# Helpers -- extract table names from the raw DDL to compare dynamically
# -----------------------------------------------------------------------

def _ddl_table_names() -> set[str]:
    """Parse CREATE TABLE names from `_create_schema` source code.

    This avoids hardcoding table names in the test; the source of truth
    is the DDL string inside ``database.py``.
    """
    import inspect

    from a_sdlc.core.database import Database

    src = inspect.getsource(Database._create_schema)
    return set(re.findall(r"CREATE TABLE (\w+)", src))


# -----------------------------------------------------------------------
# Registry completeness
# -----------------------------------------------------------------------


class TestRegistry:
    """ALL_MODELS / ALL_TABLE_NAMES must cover every DDL table."""

    def test_all_ddl_tables_have_models(self):
        """Every CREATE TABLE in the DDL has a matching model."""
        ddl_tables = _ddl_table_names()
        missing = ddl_tables - ALL_TABLE_NAMES
        assert not missing, f"DDL tables without models: {sorted(missing)}"

    def test_no_extra_models_beyond_ddl(self):
        """No model claims a table that does not exist in the DDL."""
        ddl_tables = _ddl_table_names()
        extra = ALL_TABLE_NAMES - ddl_tables
        assert not extra, f"Models without DDL tables: {sorted(extra)}"

    def test_model_count_matches_ddl(self):
        """Number of models matches number of DDL tables."""
        ddl_tables = _ddl_table_names()
        assert len(ALL_MODELS) == len(ddl_tables)

    def test_all_table_names_is_frozen(self):
        """ALL_TABLE_NAMES is a frozenset (immutable)."""
        assert isinstance(ALL_TABLE_NAMES, frozenset)

    def test_schema_version_is_current(self):
        """Dynamic check: SCHEMA_VERSION from database.py matches v15."""
        # Uses the imported constant rather than hardcoding 15.
        assert SCHEMA_VERSION >= 15


# -----------------------------------------------------------------------
# Model instantiation -- happy path
# -----------------------------------------------------------------------


class TestInstantiation:
    """Each model can be constructed with minimal valid fields."""

    def test_schema_version(self):
        obj = SchemaVersion(version=SCHEMA_VERSION)
        assert obj.version == SCHEMA_VERSION

    def test_project(self):
        obj = Project(id="p1", shortname="PROJ", name="My Project", path="/tmp/proj")
        assert obj.shortname == "PROJ"
        assert obj.path == "/tmp/proj"

    def test_sprint(self):
        obj = Sprint(id="s1", project_id="p1", title="Sprint 1")
        assert obj.status == "planned"
        assert obj.goal is None

    def test_prd(self):
        obj = Prd(id="prd1", project_id="p1", title="Requirements")
        assert obj.status == "draft"
        assert obj.version == "1.0.0"
        assert obj.sprint_id is None

    def test_task(self):
        obj = Task(id="t1", project_id="p1", title="Implement feature")
        assert obj.status == "pending"
        assert obj.priority == "medium"
        assert obj.prd_id is None

    def test_design(self):
        obj = Design(id="d1", prd_id="prd1", project_id="p1")
        assert obj.file_path is None

    def test_sync_mapping(self):
        obj = SyncMapping(
            entity_type="task",
            local_id="t1",
            external_system="linear",
            external_id="ext-1",
        )
        assert obj.sync_status == "synced"

    def test_external_config(self):
        obj = ExternalConfig(
            project_id="p1", system="linear", config='{"token": "abc"}'
        )
        assert obj.id is None  # autoincrement

    def test_worktree(self):
        obj = Worktree(
            id="w1",
            project_id="p1",
            prd_id="prd1",
            branch_name="feature/x",
            path="/tmp/wt",
        )
        assert obj.status == "active"
        assert obj.pr_url is None

    def test_review(self):
        obj = Review(
            task_id="t1",
            project_id="p1",
            reviewer_type="self",
            verdict="pass",
        )
        assert obj.round == 1
        assert obj.findings is None

    def test_audit_log(self):
        obj = AuditLog(
            project_id="p1",
            action_type="create_task",
            outcome="success",
        )
        assert obj.agent_id is None

    def test_requirement(self):
        obj = Requirement(
            id="req1",
            prd_id="prd1",
            req_type="functional",
            req_number="FR-001",
            summary="System shall...",
        )
        assert obj.depth == "structural"

    def test_requirement_link(self):
        obj = RequirementLink(requirement_id="req1", task_id="t1")
        assert obj.requirement_id == "req1"

    def test_ac_verification(self):
        obj = AcVerification(requirement_id="req1", task_id="t1")
        assert obj.verified_by is None
        assert obj.evidence is None

    def test_challenge_record(self):
        obj = ChallengeRecord(
            artifact_type="prd",
            artifact_id="prd1",
            round_number=1,
        )
        assert obj.status == "open"


# -----------------------------------------------------------------------
# Pydantic validation -- type enforcement and required fields
# -----------------------------------------------------------------------


class TestValidation:
    """Pydantic validation catches invalid data via model_validate().

    Note: SQLModel ``table=True`` models are lenient on direct construction
    (missing fields default to None for deferred DB validation).  Strict
    Pydantic validation is triggered through ``model_validate()``.
    """

    def test_project_requires_id(self):
        with pytest.raises(ValidationError):
            Project.model_validate({"shortname": "X", "name": "N", "path": "/p"})

    def test_project_requires_shortname(self):
        with pytest.raises(ValidationError):
            Project.model_validate({"id": "p1", "name": "N", "path": "/p"})

    def test_project_requires_name(self):
        with pytest.raises(ValidationError):
            Project.model_validate({"id": "p1", "shortname": "X", "path": "/p"})

    def test_project_requires_path(self):
        with pytest.raises(ValidationError):
            Project.model_validate({"id": "p1", "shortname": "X", "name": "N"})

    def test_task_requires_title(self):
        with pytest.raises(ValidationError):
            Task.model_validate({"id": "t1", "project_id": "p1"})

    def test_prd_requires_title(self):
        with pytest.raises(ValidationError):
            Prd.model_validate({"id": "prd1", "project_id": "p1"})

    def test_sprint_requires_title(self):
        with pytest.raises(ValidationError):
            Sprint.model_validate({"id": "s1", "project_id": "p1"})

    def test_review_requires_verdict(self):
        with pytest.raises(ValidationError):
            Review.model_validate(
                {"task_id": "t1", "project_id": "p1", "reviewer_type": "self"}
            )

    def test_requirement_requires_summary(self):
        with pytest.raises(ValidationError):
            Requirement.model_validate(
                {"id": "req1", "prd_id": "prd1", "req_type": "functional", "req_number": "FR-001"}
            )

    def test_challenge_record_requires_round_number(self):
        with pytest.raises(ValidationError):
            ChallengeRecord.model_validate(
                {"artifact_type": "prd", "artifact_id": "prd1"}
            )


# -----------------------------------------------------------------------
# Default values
# -----------------------------------------------------------------------


class TestDefaults:
    """Default values on models match the DDL DEFAULT clauses."""

    def test_prd_defaults(self):
        obj = Prd(id="x", project_id="p", title="T")
        assert obj.status == "draft"
        assert obj.version == "1.0.0"

    def test_task_defaults(self):
        obj = Task(id="x", project_id="p", title="T")
        assert obj.status == "pending"
        assert obj.priority == "medium"

    def test_sprint_defaults(self):
        obj = Sprint(id="x", project_id="p", title="T")
        assert obj.status == "planned"

    def test_sync_mapping_defaults(self):
        obj = SyncMapping(
            entity_type="task", local_id="t", external_system="linear", external_id="e"
        )
        assert obj.sync_status == "synced"

    def test_worktree_defaults(self):
        obj = Worktree(id="w", project_id="p", prd_id="prd", branch_name="b", path="/x")
        assert obj.status == "active"

    def test_challenge_record_defaults(self):
        obj = ChallengeRecord(artifact_type="prd", artifact_id="p1", round_number=1)
        assert obj.status == "open"

    def test_review_defaults(self):
        obj = Review(task_id="t", project_id="p", reviewer_type="self", verdict="pass")
        assert obj.round == 1

    def test_requirement_defaults(self):
        obj = Requirement(
            id="r", prd_id="p", req_type="functional", req_number="FR-1", summary="S"
        )
        assert obj.depth == "structural"


# -----------------------------------------------------------------------
# Nullable field coverage
# -----------------------------------------------------------------------


class TestNullableFields:
    """Optional fields accept None; required fields reject it."""

    def test_prd_optional_fields_accept_none(self):
        obj = Prd(id="x", project_id="p", title="T")
        assert obj.sprint_id is None
        assert obj.file_path is None
        assert obj.source is None
        assert obj.ready_at is None
        assert obj.split_at is None
        assert obj.completed_at is None

    def test_task_optional_fields_accept_none(self):
        obj = Task(id="x", project_id="p", title="T")
        assert obj.prd_id is None
        assert obj.file_path is None
        assert obj.component is None
        assert obj.started_at is None
        assert obj.completed_at is None

    def test_sprint_optional_fields_accept_none(self):
        obj = Sprint(id="x", project_id="p", title="T")
        assert obj.goal is None
        assert obj.external_id is None
        assert obj.external_url is None
        assert obj.started_at is None
        assert obj.completed_at is None

    def test_worktree_optional_sprint_id(self):
        obj = Worktree(id="w", project_id="p", prd_id="pr", branch_name="b", path="/x")
        assert obj.sprint_id is None


# -----------------------------------------------------------------------
# Table name verification (via __tablename__)
# -----------------------------------------------------------------------


class TestTableNames:
    """Each model's __tablename__ matches the DDL table name."""

    @pytest.mark.parametrize(
        "model_cls,expected_table",
        [
            (SchemaVersion, "schema_version"),
            (Project, "projects"),
            (Sprint, "sprints"),
            (Prd, "prds"),
            (Task, "tasks"),
            (Design, "designs"),
            (SyncMapping, "sync_mappings"),
            (ExternalConfig, "external_config"),
            (Worktree, "worktrees"),
            (Review, "reviews"),
            (AuditLog, "audit_log"),
            (Requirement, "requirements"),
            (RequirementLink, "requirement_links"),
            (AcVerification, "ac_verifications"),
            (ChallengeRecord, "challenge_records"),
        ],
    )
    def test_tablename(self, model_cls, expected_table):
        assert model_cls.__tablename__ == expected_table


# -----------------------------------------------------------------------
# Datetime field assignment
# -----------------------------------------------------------------------


class TestDatetimeFields:
    """Datetime fields accept both None and actual datetime values."""

    def test_project_accepts_datetime(self):
        now = datetime(2025, 1, 1, 12, 0, 0)
        obj = Project(
            id="p", shortname="X", name="N", path="/p",
            created_at=now, last_accessed=now,
        )
        assert obj.created_at == now
        assert obj.last_accessed == now

    def test_task_accepts_timestamps(self):
        now = datetime(2025, 6, 15, 8, 30)
        obj = Task(
            id="t", project_id="p", title="T",
            started_at=now, completed_at=now,
        )
        assert obj.started_at == now
        assert obj.completed_at == now

    def test_prd_accepts_lifecycle_timestamps(self):
        now = datetime(2025, 3, 1)
        obj = Prd(
            id="prd", project_id="p", title="T",
            ready_at=now, split_at=now, completed_at=now,
        )
        assert obj.ready_at == now
        assert obj.split_at == now
        assert obj.completed_at == now

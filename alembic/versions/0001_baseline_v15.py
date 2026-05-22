"""Baseline v15 schema -- all 15 tables.

Replaces the manual 15-step migration chain in core/database.py with a
single Alembic revision that creates the complete v15 schema from scratch.

Revision ID: 0001
Revises: None
Create Date: 2025-05-20
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create all 15 tables of the v15 schema."""

    # 1. schema_version
    op.create_table(
        "schema_version",
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("version"),
    )
    op.execute("INSERT INTO schema_version (version) VALUES (15)")

    # 2. projects
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("shortname", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "last_accessed",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("path"),
    )
    op.create_index("idx_projects_path", "projects", ["path"])
    op.create_index("idx_projects_shortname", "projects", ["shortname"], unique=True)

    # 3. sprints (before prds due to FK)
    op.create_table(
        "sprints",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="planned", nullable=True),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_sprints_project", "sprints", ["project_id"])
    op.create_index("idx_sprints_status", "sprints", ["status"])

    # 4. prds
    op.create_table(
        "prds",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("sprint_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="draft", nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("version", sa.Text(), server_default="1.0.0", nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("ready_at", sa.DateTime(), nullable=True),
        sa.Column("split_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sprint_id"], ["sprints.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_prds_project", "prds", ["project_id"])
    op.create_index("idx_prds_status", "prds", ["status"])
    op.create_index("idx_prds_sprint", "prds", ["sprint_id"])

    # 5. tasks
    op.create_table(
        "tasks",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("prd_id", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="pending", nullable=True),
        sa.Column("priority", sa.Text(), server_default="medium", nullable=True),
        sa.Column("component", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prd_id"], ["prds.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tasks_project", "tasks", ["project_id"])
    op.create_index("idx_tasks_status", "tasks", ["status"])
    op.create_index("idx_tasks_prd", "tasks", ["prd_id"])

    # 6. designs
    op.create_table(
        "designs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("prd_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["prd_id"], ["prds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prd_id"),
    )
    op.create_index("idx_designs_prd", "designs", ["prd_id"])
    op.create_index("idx_designs_project", "designs", ["project_id"])

    # 7. sync_mappings
    op.create_table(
        "sync_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("local_id", sa.Text(), nullable=False),
        sa.Column("external_system", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("sync_status", sa.Text(), server_default="synced", nullable=True),
        sa.Column(
            "last_synced",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "local_id", "external_system"),
    )
    op.create_index("idx_sync_entity", "sync_mappings", ["entity_type", "local_id"])
    op.create_index(
        "idx_sync_external", "sync_mappings", ["external_system", "external_id"]
    )

    # 8. external_config
    op.create_table(
        "external_config",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("system", sa.Text(), nullable=False),
        sa.Column("config", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "system"),
    )
    op.create_index("idx_external_config_project", "external_config", ["project_id"])

    # 9. worktrees
    op.create_table(
        "worktrees",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("prd_id", sa.Text(), nullable=False),
        sa.Column("sprint_id", sa.Text(), nullable=True),
        sa.Column("branch_name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=True),
        sa.Column("pr_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.Column("cleaned_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["prd_id"], ["prds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["sprint_id"], ["sprints.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_worktrees_project", "worktrees", ["project_id"])
    op.create_index("idx_worktrees_prd", "worktrees", ["prd_id"])
    op.create_index("idx_worktrees_sprint", "worktrees", ["sprint_id"])
    op.create_index("idx_worktrees_status", "worktrees", ["status"])

    # 10. reviews
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("round", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reviewer_type", sa.Text(), nullable=False),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("findings", sa.Text(), nullable=True),
        sa.Column("test_output", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_reviews_task", "reviews", ["task_id"])
    op.create_index("idx_reviews_project", "reviews", ["project_id"])

    # 11. audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("run_id", sa.Text(), nullable=True),
        sa.Column("action_type", sa.Text(), nullable=False),
        sa.Column("target_entity", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_audit_log_project", "audit_log", ["project_id"])
    op.create_index("idx_audit_log_agent", "audit_log", ["agent_id"])
    op.create_index("idx_audit_log_run", "audit_log", ["run_id"])
    op.create_index("idx_audit_log_action", "audit_log", ["action_type"])

    # 12. requirements
    op.create_table(
        "requirements",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("prd_id", sa.Text(), nullable=False),
        sa.Column("req_type", sa.Text(), nullable=False),
        sa.Column("req_number", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("depth", sa.Text(), server_default="structural", nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["prd_id"], ["prds.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prd_id", "req_number"),
    )
    op.create_index("idx_requirements_prd", "requirements", ["prd_id"])
    op.create_index("idx_requirements_type", "requirements", ["req_type"])

    # 13. requirement_links
    op.create_table(
        "requirement_links",
        sa.Column("requirement_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("requirement_id", "task_id"),
    )

    # 14. ac_verifications
    op.create_table(
        "ac_verifications",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("requirement_id", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Text(), nullable=False),
        sa.Column("verified_by", sa.Text(), nullable=True),
        sa.Column("evidence_type", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column(
            "verified_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["requirement_id"], ["requirements.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_id", "task_id"),
    )
    op.create_index("idx_ac_verifications_task", "ac_verifications", ["task_id"])

    # 15. challenge_records
    op.create_table(
        "challenge_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_type", sa.Text(), nullable=False),
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("objections", sa.Text(), nullable=True),
        sa.Column("responses", sa.Text(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("challenger_context", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default="open", nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_type", "artifact_id", "round_number"),
    )
    op.create_index(
        "idx_challenge_artifact",
        "challenge_records",
        ["artifact_type", "artifact_id"],
    )


def downgrade() -> None:
    """Drop all 15 tables in reverse order of creation."""
    # Drop tables in reverse dependency order
    op.drop_table("challenge_records")
    op.drop_table("ac_verifications")
    op.drop_table("requirement_links")
    op.drop_table("requirements")
    op.drop_table("audit_log")
    op.drop_table("reviews")
    op.drop_table("worktrees")
    op.drop_table("external_config")
    op.drop_table("sync_mappings")
    op.drop_table("designs")
    op.drop_table("tasks")
    op.drop_table("prds")
    op.drop_table("sprints")
    op.drop_table("projects")
    op.drop_table("schema_version")

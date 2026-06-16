"""Make projects.path nullable.

Centralized/remote deployments create projects through ``create_project()``
without a server-side path. The column becomes nullable so multiple
path-less projects can coexist; the UNIQUE constraint still applies to
non-NULL paths (NULLs are distinct in SQLite and PostgreSQL).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Allow NULL values in projects.path."""
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "path",
            existing_type=sa.Text(),
            nullable=True,
        )


def downgrade() -> None:
    """Restore NOT NULL on projects.path.

    Projects created without a path (centralized/remote deployments) would
    violate the restored NOT NULL constraint, so backfill those rows before
    re-applying it. ``path`` is UNIQUE, so each placeholder must be distinct;
    deriving it from the primary key guarantees uniqueness. ``||`` is the SQL
    string-concatenation operator in both SQLite and PostgreSQL.
    """
    op.execute(
        "UPDATE projects SET path = '__null_path__/' || id WHERE path IS NULL"
    )
    with op.batch_alter_table("projects") as batch_op:
        batch_op.alter_column(
            "path",
            existing_type=sa.Text(),
            nullable=False,
        )

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


def _projects_table(path_nullable: bool) -> sa.Table:
    """The ``projects`` table definition for batch ``copy_from``.

    SQLite cannot ALTER a column's nullability in place, so Alembic uses the
    "move and copy" batch strategy (recreate the table). In offline (``--sql``)
    mode there is no live connection to reflect the existing table from, so we
    pass an explicit definition via ``copy_from``. Indexes and constraints must
    be included here or the recreated table would lose them.

    ``path_nullable`` describes the column state *before* the operation: False
    for ``upgrade`` (path is NOT NULL), True for ``downgrade``.
    """
    return sa.Table(
        "projects",
        sa.MetaData(),
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("shortname", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=path_nullable),
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
        sa.Index("idx_projects_path", "path"),
        sa.Index("idx_projects_shortname", "shortname", unique=True),
    )


def upgrade() -> None:
    """Allow NULL values in projects.path."""
    with op.batch_alter_table(
        "projects", copy_from=_projects_table(path_nullable=False)
    ) as batch_op:
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
    with op.batch_alter_table(
        "projects", copy_from=_projects_table(path_nullable=True)
    ) as batch_op:
        batch_op.alter_column(
            "path",
            existing_type=sa.Text(),
            nullable=False,
        )

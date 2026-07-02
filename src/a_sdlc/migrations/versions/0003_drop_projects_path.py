"""Drop projects.path.

The server no longer stores a filesystem path for projects. Identity is the
project id/shortname, and a repository links to its project locally through
``.sdlc/project.json`` (see ``a_sdlc.core.project_marker``). Removing the column
keeps the shared database free of device-specific paths, so the same project can
be worked on from multiple machines/containers without UNIQUE-path collisions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def _projects_table(with_path: bool) -> sa.Table:
    """The ``projects`` table definition for batch ``copy_from``.

    SQLite cannot DROP a column in place, so Alembic uses the "move and copy"
    batch strategy (recreate the table). In offline (``--sql``) mode there is no
    live connection to reflect from, so we pass an explicit definition.

    The path-specific ``UNIQUE(path)`` constraint and ``idx_projects_path``
    index are intentionally omitted here: on upgrade they disappear when the old
    table is dropped, and on downgrade they are re-created explicitly. Only the
    shortname index is carried across, matching the surviving schema.

    ``with_path`` describes whether the column is present in the model handed to
    ``copy_from``: True for ``upgrade`` (path still exists), False for
    ``downgrade`` (path already gone).
    """
    columns = [
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("shortname", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
    ]
    if with_path:
        columns.append(sa.Column("path", sa.Text(), nullable=True))
    columns.extend(
        [
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
        ]
    )
    return sa.Table(
        "projects",
        sa.MetaData(),
        *columns,
        sa.PrimaryKeyConstraint("id"),
        sa.Index("idx_projects_shortname", "shortname", unique=True),
    )


def upgrade() -> None:
    """Remove the projects.path column (and, with it, its unique index)."""
    with op.batch_alter_table(
        "projects", copy_from=_projects_table(with_path=True)
    ) as batch_op:
        batch_op.drop_column("path")


def downgrade() -> None:
    """Restore projects.path as a nullable, unique, indexed column."""
    with op.batch_alter_table(
        "projects", copy_from=_projects_table(with_path=False)
    ) as batch_op:
        batch_op.add_column(sa.Column("path", sa.Text(), nullable=True))
        batch_op.create_unique_constraint("uq_projects_path", ["path"])
        batch_op.create_index("idx_projects_path", ["path"])

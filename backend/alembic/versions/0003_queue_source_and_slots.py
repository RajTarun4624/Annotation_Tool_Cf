"""queue import source + annotation slots

SPEC3: paste-a-spreadsheet-link import stores the import source on the queue
(``queues.source_name`` = uploaded file name or pasted URL). The per-task
annotator slots (``task_annotations.status = "assigned"``) reuse the existing
free-text status column, so no other DDL is needed.

Revision ID: 0003_queue_source
Revises: 0002_consensus
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0003_queue_source"
down_revision: Union[str, None] = "0002_consensus"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("queues", sa.Column("source_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("queues", "source_name")

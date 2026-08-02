"""add pushed_event_ids_json to weekly_plans

Revision ID: 5639dfbdf36a
Revises: 97b6ef7dddad
Create Date: 2026-08-01 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5639dfbdf36a'
down_revision: Union[str, Sequence[str], None] = '97b6ef7dddad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """F19.6 (#121): weekly_plans gets a column tracking each pushed
    session's intervals.icu event id, keyed by day (PRD #111,
    docs/adr/0027). Plain nullable Text column, no CHECK constraint —
    still uses batch mode for consistency with SQLite's ALTER TABLE
    limitations (same pattern as 00edfdac9559/97b6ef7dddad)."""
    with op.batch_alter_table("weekly_plans", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pushed_event_ids_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("weekly_plans", schema=None) as batch_op:
        batch_op.drop_column("pushed_event_ids_json")

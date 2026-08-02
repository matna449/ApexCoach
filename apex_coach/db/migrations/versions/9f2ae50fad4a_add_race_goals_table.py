"""add race_goals table

Revision ID: 9f2ae50fad4a
Revises: 5639dfbdf36a
Create Date: 2026-08-02 12:56:07.033515

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f2ae50fad4a'
down_revision: Union[str, Sequence[str], None] = '5639dfbdf36a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """PRD #138 (F20.1): race_goals table -- one row per training-block
    goal, one level up monthly_targets in the Three-Horizon Model
    (ADR-0002). The partial unique index enforces at most one ACTIVE row at
    a time (docs/adr/0023, single-athlete system); SQLite has no native
    partial-index DDL in op.create_index's portable form, so it's raw SQL
    here, mirroring schema.py's sqlite_where= Index definition."""
    op.create_table(
        'race_goals',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('goal_distance', sa.String(), nullable=False),
        sa.Column('target_race_date', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=True),
        sa.CheckConstraint(
            "goal_distance IN ('5K', '10K', 'HALF_MARATHON', 'MARATHON')",
            name='goal_distance',
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'COMPLETED', 'ABANDONED')",
            name='race_goal_status',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_race_goals_one_active "
        "ON race_goals (status) WHERE status = 'ACTIVE'"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('race_goals')

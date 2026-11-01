"""add WHOOP sync columns to daily_metrics and whoop_webhook_events

Revision ID: e5b17c3d9a42
Revises: d2e8f4a1c7b3
Create Date: 2026-11-01 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5b17c3d9a42'
down_revision: Union[str, Sequence[str], None] = 'd2e8f4a1c7b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_COLUMNS = (
    ("whoop_sleep_performance_pct", sa.Float()),
    ("whoop_recovery_score_state", sa.String()),
    ("whoop_sleep_id", sa.String()),
    ("whoop_cycle_id", sa.String()),
    ("whoop_synced_at", sa.String()),
)


def upgrade() -> None:
    """F21.4 (#154): webhook events land in daily_metrics."""
    with op.batch_alter_table("daily_metrics", schema=None) as batch_op:
        for name, type_ in _NEW_COLUMNS:
            batch_op.add_column(sa.Column(name, type_, nullable=True))
    op.create_table(
        "whoop_webhook_events",
        sa.Column("trace_id", sa.String(), primary_key=True),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("record_id", sa.String(), nullable=False),
        sa.Column("received_at", sa.String(), nullable=False),
        sa.Column("processed_at", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("whoop_webhook_events")
    with op.batch_alter_table("daily_metrics", schema=None) as batch_op:
        for name, _ in reversed(_NEW_COLUMNS):
            batch_op.drop_column(name)

"""add subjective answer columns to daily_metrics

Revision ID: f8a2c6d4e1b7
Revises: e5b17c3d9a42
Create Date: 2026-11-01 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f8a2c6d4e1b7'
down_revision: Union[str, Sequence[str], None] = 'e5b17c3d9a42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """F21.7 (#156): the AI health agent's answers that have no existing column."""
    with op.batch_alter_table("daily_metrics", schema=None) as batch_op:
        batch_op.add_column(sa.Column("rpe_yesterday", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("soreness_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("subjective_stress", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("pain_note", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ck_daily_metrics_rpe_yesterday", "rpe_yesterday BETWEEN 1 AND 10"
        )
        batch_op.create_check_constraint(
            "ck_daily_metrics_subjective_stress", "subjective_stress BETWEEN 1 AND 5"
        )


def downgrade() -> None:
    with op.batch_alter_table("daily_metrics", schema=None) as batch_op:
        batch_op.drop_constraint("ck_daily_metrics_subjective_stress", type_="check")
        batch_op.drop_constraint("ck_daily_metrics_rpe_yesterday", type_="check")
        batch_op.drop_column("pain_note")
        batch_op.drop_column("subjective_stress")
        batch_op.drop_column("soreness_note")
        batch_op.drop_column("rpe_yesterday")

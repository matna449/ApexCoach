"""add source to monthly_targets

Revision ID: cab1d2863746
Revises: 9f2ae50fad4a
Create Date: 2026-08-02 14:02:04.401097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cab1d2863746'
down_revision: Union[str, Sequence[str], None] = '9f2ae50fad4a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """PRD #138 (F20.4): tracks who last wrote a month's
    periodisation_phase/load_target_total -- 'ATHLETE' vs 'MACRO_PLAN' --
    so accept_macro_plan()/regenerate_macro_plan()'s already-customized
    guardrail can tell "the macro plan itself wrote this, safe to
    regenerate" apart from "the athlete deliberately set this, don't
    touch." SQLite can't ALTER a CHECK constraint directly -- batch mode
    recreates the table (same pattern as 00edfdac9559)."""
    with op.batch_alter_table("monthly_targets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("source", sa.String(), nullable=True))
        batch_op.create_check_constraint(
            "monthly_target_source",
            "source IN ('ATHLETE', 'MACRO_PLAN')",
        )


def downgrade() -> None:
    with op.batch_alter_table("monthly_targets", schema=None) as batch_op:
        batch_op.drop_constraint("monthly_target_source", type_="check")
        batch_op.drop_column("source")

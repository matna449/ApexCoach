"""add OVERREACHED to week_status

Revision ID: d3fe52edeef7
Revises: 30c0f364a948
Create Date: 2026-07-31 10:20:54.897861

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3fe52edeef7'
down_revision: Union[str, Sequence[str], None] = '30c0f364a948'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic's autogenerate doesn't diff CHECK constraints, so this is
    # hand-written. SQLite can't ALTER a CHECK constraint directly — batch
    # mode recreates the table. alter_column's type_= alone does not
    # regenerate the table-level CHECK constraint; drop + recreate it
    # explicitly (Logic Spec §4.1 added OVERREACHED as a 5th week_status
    # state; docs/adr/0016).
    with op.batch_alter_table("weekly_plans", schema=None) as batch_op:
        batch_op.drop_constraint("week_status", type_="check")
        batch_op.create_check_constraint(
            "week_status",
            "week_status IN ('ON_TRACK', 'LOAD_DEFICIT', 'OVERREACHED', 'RECOVERY_WEEK', 'COMPLETE')",
        )


def downgrade() -> None:
    with op.batch_alter_table("weekly_plans", schema=None) as batch_op:
        batch_op.drop_constraint("week_status", type_="check")
        batch_op.create_check_constraint(
            "week_status",
            "week_status IN ('ON_TRACK', 'LOAD_DEFICIT', 'RECOVERY_WEEK', 'COMPLETE')",
        )

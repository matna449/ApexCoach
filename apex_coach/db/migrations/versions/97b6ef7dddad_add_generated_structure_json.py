"""add generated_structure_json to weekly_plans

Revision ID: 97b6ef7dddad
Revises: 00edfdac9559
Create Date: 2026-08-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '97b6ef7dddad'
down_revision: Union[str, Sequence[str], None] = '00edfdac9559'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """F19.2 (#118): weekly_plans gets a column for the pure-engine-generated
    structured HR-zone breakdown (PRD #111). Plain nullable Text column, no
    CHECK constraint needed — still uses batch mode for consistency with
    SQLite's ALTER TABLE limitations (same pattern as 00edfdac9559)."""
    with op.batch_alter_table("weekly_plans", schema=None) as batch_op:
        batch_op.add_column(sa.Column("generated_structure_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("weekly_plans", schema=None) as batch_op:
        batch_op.drop_column("generated_structure_json")

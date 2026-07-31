"""add athlete_profile table

Revision ID: aa5ca4244050
Revises: d3fe52edeef7
Create Date: 2026-07-31 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa5ca4244050'
down_revision: Union[str, Sequence[str], None] = 'd3fe52edeef7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'athlete_profile',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('max_hr', sa.Integer(), nullable=True),
        sa.Column('baseline_resting_hr', sa.Integer(), nullable=True),
        sa.Column('sex', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=True),
        sa.CheckConstraint("sex IN ('MALE', 'FEMALE')", name='athlete_sex'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('athlete_profile')

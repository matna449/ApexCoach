"""add activity_sync_provider to athlete_profile, INTERVALS_ICU to oauth_provider

Revision ID: 00edfdac9559
Revises: aa5ca4244050
Create Date: 2026-08-01 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00edfdac9559'
down_revision: Union[str, Sequence[str], None] = 'aa5ca4244050'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """F18.4 (#93): athlete_profile gets a provider-selection column;
    oauth_tokens.provider's CHECK constraint grows to allow storing an
    intervals.icu API key alongside WHOOP/Strava OAuth tokens (docs/adr/0025).
    SQLite can't ALTER a CHECK constraint directly — batch mode recreates
    the table (same pattern as d3fe52edeef7)."""
    with op.batch_alter_table("athlete_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("activity_sync_provider", sa.String(), nullable=True))
        batch_op.create_check_constraint(
            "activity_sync_provider",
            "activity_sync_provider IN ('STRAVA', 'INTERVALS_ICU')",
        )

    with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
        batch_op.drop_constraint("oauth_provider", type_="check")
        batch_op.create_check_constraint(
            "oauth_provider",
            "provider IN ('WHOOP', 'STRAVA', 'INTERVALS_ICU')",
        )


def downgrade() -> None:
    with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
        batch_op.drop_constraint("oauth_provider", type_="check")
        batch_op.create_check_constraint(
            "oauth_provider",
            "provider IN ('WHOOP', 'STRAVA')",
        )

    with op.batch_alter_table("athlete_profile", schema=None) as batch_op:
        batch_op.drop_constraint("activity_sync_provider", type_="check")
        batch_op.drop_column("activity_sync_provider")

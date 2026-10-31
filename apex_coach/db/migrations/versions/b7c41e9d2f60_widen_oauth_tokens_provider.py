"""widen oauth_tokens.provider for INTERVALS_ICU

Revision ID: b7c41e9d2f60
Revises: cab1d2863746
Create Date: 2026-10-31 17:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c41e9d2f60'
down_revision: Union[str, Sequence[str], None] = 'cab1d2863746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _alter_provider_length_on_postgres(old: int, new: int) -> None:
    """The initial schema sized the column for 'WHOOP'/'STRAVA'. 00edfdac9559
    allowed 'INTERVALS_ICU' without widening it, which Postgres enforces and
    SQLite ignores, so SQLite needs no change."""
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column(
            "oauth_tokens",
            "provider",
            existing_type=sa.String(length=old),
            type_=sa.String(length=new),
            existing_nullable=False,
        )


def upgrade() -> None:
    """Upgrade schema."""
    _alter_provider_length_on_postgres(6, 13)


def downgrade() -> None:
    """Downgrade schema."""
    _alter_provider_length_on_postgres(13, 6)

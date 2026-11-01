"""add oauth_pending_states and oauth_tokens.sync_status

Revision ID: d2e8f4a1c7b3
Revises: b7c41e9d2f60
Create Date: 2026-11-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2e8f4a1c7b3'
down_revision: Union[str, Sequence[str], None] = 'b7c41e9d2f60'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """F21.3 (#153): the hosted OAuth flow stores state and verifier between
    the two requests, and a rejected refresh token is remembered."""
    op.create_table(
        "oauth_pending_states",
        sa.Column("state", sa.String(), primary_key=True),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sync_status", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("oauth_tokens", schema=None) as batch_op:
        batch_op.drop_column("sync_status")
    op.drop_table("oauth_pending_states")

"""add decision_context_json to decisions

Revision ID: 9ec145485c43
Revises: cab1d2863746
Create Date: 2026-08-02 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ec145485c43'
down_revision: Union[str, Sequence[str], None] = 'cab1d2863746'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """#132: the full decision_context dict, stored verbatim alongside
    llm_explanation once Ollama succeeds, so GET /api/morning/context can
    rehydrate today's Decision Output (and answer further follow-ups)
    without reconstructing it from other tables."""
    with op.batch_alter_table("decisions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("decision_context_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("decisions", schema=None) as batch_op:
        batch_op.drop_column("decision_context_json")

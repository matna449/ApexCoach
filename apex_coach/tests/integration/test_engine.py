import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa

from apex_coach.db.engine import create_engine
from apex_coach.db.schema import metadata


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


def test_foreign_keys_are_enforced_by_default(db_path):
    engine = create_engine(db_path)
    metadata.create_all(engine)

    hr_zones = metadata.tables["hr_zones"]
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(hr_zones.insert().values(date="2026-07-30"))

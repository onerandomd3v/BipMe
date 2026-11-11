"""Quiet readiness: reachable database AND exactly the image's migration heads."""

import os
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

try:
    engine = create_engine(
        os.environ["BIPME_DATABASE_URL"],
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=3000"},
    )
    expected = set(ScriptDirectory.from_config(Config("/app/alembic.ini")).get_heads())
    with engine.connect() as connection:
        actual = set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())
    engine.dispose()
    sys.exit(0 if actual == expected else 1)
except Exception:
    # Probe output can become an event; never emit connection details.
    sys.exit(1)

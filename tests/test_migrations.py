"""Migrations must describe the same schema the models do.

Every other test builds its schema with `Base.metadata.create_all`, which reads
the models directly. That makes model/migration drift invisible: add a column,
forget the migration, and the whole suite still passes — the failure surfaces on
deploy, against real data, which is the worst place to find it.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        # `migrations/env.py` reads the URL from app settings, so pointing this
        # at a scratch file keeps the check away from any real database.
        env={**os.environ, "DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("command", ["upgrade"])
def test_migrations_apply_to_an_empty_database(tmp_path, command):
    result = _alembic(
        command, "head", database_url=f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_models_and_migrations_agree(tmp_path):
    """`alembic check` autogenerates against a migrated database and fails if
    it finds anything — i.e. if a model has drifted from the migrations."""
    url = f"sqlite+aiosqlite:///{tmp_path / 'check.db'}"

    upgraded = _alembic("upgrade", "head", database_url=url)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

    checked = _alembic("check", database_url=url)
    assert checked.returncode == 0, (
        "Models have drifted from migrations. Run:\n"
        "  alembic revision --autogenerate -m '<what changed>'\n\n"
        + checked.stdout
        + checked.stderr
    )

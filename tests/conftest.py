import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_cabmora.db"
# The test transport speaks plain http, and a Secure cookie would never be
# stored or sent back over it. Production keeps Secure on.
os.environ["COOKIE_SECURE"] = "false"

# Nothing in this suite may reach a real provider. Discovered the hard way on
# 2026-09-28: with MEETING_BACKEND=google in a developer's .env, `pytest`
# authenticated against Google and booked actual consultations in Cabmora's
# calendar — a test run with side effects in the real world, which is the one
# thing a test run must never have.
#
# Set here rather than in a fixture because settings are read at import time
# and cached; by the time a fixture runs, the adapter has already been chosen.
os.environ["MEETING_BACKEND"] = "manual"
os.environ["EMAIL_BACKEND"] = "logging"
os.environ["MEDIA_BACKEND"] = "local"
os.environ["SENTRY_DSN"] = ""

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.infrastructure import models  # noqa: E402,F401  (registers tables)
from app.infrastructure.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_throttle():
    """Throttling state is process-wide, so it would leak between tests.

    Without this, a test that signs in wrongly a few times would spend the
    budget for every later test using the same address — and the failure
    would land somewhere unrelated, which is the worst kind to debug.
    """
    from app.api import throttle

    throttle.reset()
    yield


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def real_notifier(session):
    """The real `Notifier` over a test session.

    Not a fake. These tests construct a use case by hand to assert on what it
    sends, and the notifier sits on the same call path in production — a stub
    here would let a change that breaks the notification pass green.
    """
    from app.application.use_cases.notifications.notifier import Notifier
    from app.infrastructure.repositories.notification_repository_impl import (
        SqlAlchemyNotificationRepository,
    )
    from app.infrastructure.repositories.user_repository_impl import (
        SqlAlchemyUserRepository,
    )

    return Notifier(
        SqlAlchemyNotificationRepository(session), SqlAlchemyUserRepository(session)
    )

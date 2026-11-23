"""The homepage figures, which used to be invented.

The rules worth pinning: a count of nothing is **null**, not zero, because the
page omits a tile it cannot fill and printing "0 Events Covered" on a marketing
homepage is worse than printing nothing; and "clients served" counts people
whose work was actually delivered, not everybody who ever made an account.
"""

from datetime import date

import pytest

from app.application.use_cases.marketing.public_stats import GetPublicStats
from app.core.security import hash_password
from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio


async def _customer(email: str) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=email,
                first_name="Pat",
                last_name="Client",
                hashed_password=hash_password("password123"),
                role=UserRole.CUSTOMER,
            )
        )
        await session.commit()
        return user


async def _project(title: str, *, customer: User | None, stage: ProjectStage) -> None:
    async with SessionFactory() as session:
        project = Project(
            title=title,
            event_type="Wedding",
            customer_id=customer.id if customer else None,
            stage=stage,
        )
        await SqlAlchemyProjectRepository(session).add(
            project,
            ProjectEvent(project_id=project.id, kind=ProjectEventKind.CREATED),
        )
        await session.commit()


def _use_case(session, founded: int | None = None) -> GetPublicStats:
    return GetPublicStats(SqlAlchemyProjectRepository(session), founded)


async def test_nothing_delivered_reports_null_not_zero(client):
    """Null so the homepage omits the tile. Zero would render as a figure."""
    async with SessionFactory() as session:
        figures = await _use_case(session).execute()
    assert figures.clients_served is None
    assert figures.events_covered is None


async def test_only_completed_work_counts(client):
    pat = await _customer("pat@example.com")
    await _project("Delivered", customer=pat, stage=ProjectStage.DELIVERED)
    await _project("Closed", customer=pat, stage=ProjectStage.CLOSED)
    # Not yet shot, and not yet delivered — neither is an event covered.
    await _project("Booked", customer=pat, stage=ProjectStage.BOOKED)
    await _project("Editing", customer=pat, stage=ProjectStage.EDITING)

    async with SessionFactory() as session:
        figures = await _use_case(session).execute()

    assert figures.events_covered == 2
    # One person, four projects. The figure is people, not jobs.
    assert figures.clients_served == 1


async def test_an_account_that_never_booked_is_not_a_client_served(client):
    """Otherwise the public figure grows every time a stranger signs up."""
    await _customer("browser@example.com")
    async with SessionFactory() as session:
        figures = await _use_case(session).execute()
    assert figures.clients_served is None


async def test_a_project_with_no_customer_is_not_counted_as_one(client):
    """A job set up before the client had an account carries a null
    customer_id, and COUNT(DISTINCT null) must not become a client."""
    await _project("No customer yet", customer=None, stage=ProjectStage.DELIVERED)
    async with SessionFactory() as session:
        figures = await _use_case(session).execute()
    assert figures.events_covered == 1
    assert figures.clients_served is None


async def test_years_active_is_omitted_until_configured(client):
    async with SessionFactory() as session:
        assert (await _use_case(session).execute()).years_active is None


async def test_years_active_counts_from_the_founding_year(client):
    async with SessionFactory() as session:
        figures = await _use_case(session, founded=2018).execute(today=date(2026, 6, 1))
    assert figures.years_active == 8


async def test_the_first_year_shows_nothing_rather_than_zero(client):
    """"0 Years of Excellence" reads as a bug, not as a new business."""
    async with SessionFactory() as session:
        figures = await _use_case(session, founded=2026).execute(today=date(2026, 6, 1))
    assert figures.years_active is None


async def test_the_endpoint_is_public(client):
    """It is the homepage. No session, no 401."""
    resp = await client.get("/api/v1/stats")
    assert resp.status_code == 200
    assert set(resp.json()) == {"clients_served", "events_covered", "years_active"}

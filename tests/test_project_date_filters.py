"""Finding projects by when they happen, and what is nearly due.

Two different questions. "Shot between these dates" is a lookup — a client
rings about a job in June. "Close to deadline" is a work queue, which is why
it behaves differently: it includes work that is already late, and leaves out
work that is finished.
"""

from datetime import date, timedelta

import pytest

from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)

pytestmark = pytest.mark.asyncio
TODAY = date.today()


async def _project(title: str, *, event=None, deadline=None, stage=ProjectStage.BOOKED):
    async with SessionFactory() as session:
        p = Project(
            title=title, event_type="Wedding",
            event_date=event, deadline=deadline, stage=stage,
        )
        await SqlAlchemyProjectRepository(session).add(
            p, ProjectEvent(project_id=p.id, kind=ProjectEventKind.CREATED)
        )
        await session.commit()


async def _titles(**kw) -> list[str]:
    async with SessionFactory() as session:
        rows = await SqlAlchemyProjectRepository(session).list_all(limit=50, **kw)
        return sorted(p.title for p in rows)


async def test_an_event_range_includes_both_ends(client):
    """An admin typing the 14th to the 16th means those three days."""
    await _project("On the from date", event=TODAY)
    await _project("In between", event=TODAY + timedelta(days=1))
    await _project("On the to date", event=TODAY + timedelta(days=2))
    await _project("Just outside", event=TODAY + timedelta(days=3))

    assert await _titles(
        event_from=TODAY, event_to=TODAY + timedelta(days=2)
    ) == ["In between", "On the from date", "On the to date"]


async def test_a_half_open_range_still_works(client):
    """One end is a perfectly good question: "anything from today onwards"."""
    await _project("Past", event=TODAY - timedelta(days=5))
    await _project("Future", event=TODAY + timedelta(days=5))
    assert await _titles(event_from=TODAY) == ["Future"]
    assert await _titles(event_to=TODAY) == ["Past"]


async def test_a_project_with_no_event_date_is_not_in_a_range(client):
    """Unknown is not a date. It must not appear in a window it was never
    placed in."""
    await _project("No date at all")
    assert await _titles(event_from=TODAY - timedelta(days=365)) == []


async def test_due_soon_includes_work_that_is_already_late(client):
    """Overdue is the most urgent thing this can return, so it is not filtered
    out by a lower bound."""
    await _project("Overdue", deadline=TODAY - timedelta(days=3))
    await _project("Due tomorrow", deadline=TODAY + timedelta(days=1))
    await _project("Due next month", deadline=TODAY + timedelta(days=30))

    assert await _titles(due_within_days=7) == ["Due tomorrow", "Overdue"]


async def test_finished_work_is_not_due(client):
    """A delivered job has no deadline pressure, and a queue padded with work
    that is done stops being read."""
    await _project("Still going", deadline=TODAY + timedelta(days=2))
    await _project("Delivered", deadline=TODAY + timedelta(days=2),
                   stage=ProjectStage.DELIVERED)
    await _project("Closed", deadline=TODAY + timedelta(days=2),
                   stage=ProjectStage.CLOSED)

    assert await _titles(due_within_days=7) == ["Still going"]


async def test_no_deadline_is_not_due_now(client):
    """NULL means there is no deadline, not that it has arrived."""
    await _project("No deadline set")
    assert await _titles(due_within_days=365) == []


async def test_the_count_agrees_with_the_page(client):
    """`list_all` and `count_all` share the filter — a total that disagreed
    with the rows would make paging lie."""
    await _project("Due", deadline=TODAY + timedelta(days=1))
    await _project("Not due", deadline=TODAY + timedelta(days=90))
    async with SessionFactory() as session:
        repo = SqlAlchemyProjectRepository(session)
        rows = await repo.list_all(due_within_days=7, limit=50)
        assert await repo.count_all(due_within_days=7) == len(rows) == 1


async def test_filters_combine_rather_than_replace(client):
    """Due soon *and* a search term, not either."""
    await _project("Hartley Wedding", deadline=TODAY + timedelta(days=1))
    await _project("Other job", deadline=TODAY + timedelta(days=1))
    assert await _titles(due_within_days=7, search="Hartley") == ["Hartley Wedding"]

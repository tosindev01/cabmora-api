"""Finding a project.

An admin hunting for a job is as likely to have the client's email or phone in
front of them as the project's title — a client writes in, and the reply has to
be matched to a project. Before this, search covered the title and the location
and nothing else.
"""

import pytest

from app.core.security import hash_password
from app.domain.entities.project import Project
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio


async def _seed() -> None:
    async with SessionFactory() as session:
        customer = await SqlAlchemyUserRepository(session).add(
            User(
                email="amara.okafor@example.com",
                first_name="Amara",
                last_name="Okafor",
                hashed_password=hash_password("password123"),
                phone="+44 7700 900123",
                whatsapp="+44 7700 900999",
                role=UserRole.CUSTOMER,
            )
        )
        projects = SqlAlchemyProjectRepository(session)
        hers = Project(
            title="Hartley Wedding", event_type="Wedding",
            location="Leeds", customer_id=customer.id,
        )
        await projects.add(
            hers, ProjectEvent(project_id=hers.id, kind=ProjectEventKind.CREATED)
        )
        other = Project(title="Unrelated Shoot", event_type="Portrait", location="Hull")
        await projects.add(
            other, ProjectEvent(project_id=other.id, kind=ProjectEventKind.CREATED)
        )
        await session.commit()


async def _found(term: str) -> list[str]:
    async with SessionFactory() as session:
        rows = await SqlAlchemyProjectRepository(session).list_all(search=term)
        return [p.title for p in rows]


async def _count(term: str) -> int:
    async with SessionFactory() as session:
        return await SqlAlchemyProjectRepository(session).count_all(search=term)


@pytest.mark.parametrize(
    "term",
    [
        "Hartley",            # the title, as before
        "Leeds",              # the location, as before
        "amara.okafor",       # the client's email
        "900123",             # their phone
        "900999",             # their WhatsApp, which is often the one they answer
        "Amara Okafor",       # their name, across two columns
        "wedding",            # the event type
    ],
)
async def test_each_of_these_finds_the_project(term, client):
    await _seed()
    assert await _found(term) == ["Hartley Wedding"]


async def test_the_count_agrees_with_the_page(client):
    """`list_all` and `count_all` share the filter. A join would have
    multiplied rows in one and inflated the total in the other; EXISTS cannot
    change the cardinality of the outer query."""
    await _seed()
    assert await _count("amara.okafor") == 1


async def test_a_client_with_no_account_does_not_break_the_search(client):
    """A project booked from an enquiry has no customer_id, and the subquery
    has to simply not match rather than error."""
    await _seed()
    assert await _found("Unrelated") == ["Unrelated Shoot"]


async def test_search_is_case_insensitive(client):
    await _seed()
    assert await _found("AMARA.OKAFOR@EXAMPLE.COM") == ["Hartley Wedding"]


# ── categories ───────────────────────────────────────────────────────────
async def test_categories_are_the_ones_already_in_use(client):
    """Derived from the projects rather than kept in a table. A category
    exists while something uses it and stops being offered when nothing does —
    so there is no list to manage and nothing to get out of step."""
    await _seed()
    async with SessionFactory() as session:
        types = await SqlAlchemyProjectRepository(session).event_types()
    assert types == ["Portrait", "Wedding"]


async def test_the_category_list_has_no_duplicates(client):
    """Two weddings are one category."""
    await _seed()
    async with SessionFactory() as session:
        projects = SqlAlchemyProjectRepository(session)
        another = Project(title="Second Wedding", event_type="Wedding")
        await projects.add(
            another,
            ProjectEvent(project_id=another.id, kind=ProjectEventKind.CREATED),
        )
        await session.commit()
        assert (await projects.event_types()).count("Wedding") == 1


async def test_the_endpoint_is_above_the_id_route(client):
    """`/event-types` has to be declared before `/{project_id}` or FastAPI
    reads the literal path as a project id and 422s on a bad UUID."""
    from app.core.security import hash_password
    from app.infrastructure.repositories.user_repository_impl import (
        SqlAlchemyUserRepository,
    )

    async with SessionFactory() as session:
        await SqlAlchemyUserRepository(session).add(
            User(
                email="cat@example.com",
                first_name="Cat",
                last_name="Admin",
                hashed_password=hash_password("password123"),
                role=UserRole.ADMIN,
            )
        )
        await session.commit()
    await client.post(
        "/api/v1/auth/login",
        json={"email": "cat@example.com", "password": "password123"},
    )
    resp = await client.get("/api/v1/admin/projects/event-types")
    assert resp.status_code == 200, resp.text
    assert isinstance(resp.json(), list)

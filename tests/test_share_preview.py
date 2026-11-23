"""Open Graph tags for a pasted share link.

Cabmora chose a real photograph over a branded card, knowing that WhatsApp,
Slack and the rest cache whatever `og:image` points at. These pin the limits
that choice is made within: the preview is always the watermarked rendition,
never the original; a link that is dead or revoked says nothing about the
gallery behind it; and reading a preview is not a visit.
"""

import pytest

from app.core.security import hash_password
from app.domain.entities.gallery_share import GalleryShare
from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.gallery_share_repository_impl import (
    SqlAlchemyGalleryShareRepository,
)
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio


async def _share(stage: ProjectStage = ProjectStage.DELIVERED) -> str:
    async with SessionFactory() as session:
        staff = await SqlAlchemyUserRepository(session).add(
            User(
                email="shareowner@example.com",
                first_name="Sam",
                last_name="Staff",
                hashed_password=hash_password("password123"),
                role=UserRole.ADMIN,
            )
        )
        project = Project(title="Okonkwo Wedding", event_type="Wedding", stage=stage)
        await SqlAlchemyProjectRepository(session).add(
            project,
            ProjectEvent(project_id=project.id, kind=ProjectEventKind.CREATED),
        )
        share, token = GalleryShare.issue(project_id=project.id, created_by=staff.id)
        await SqlAlchemyGalleryShareRepository(session).add(share)
        await session.commit()
        return token


async def test_the_landing_page_names_the_gallery(client):
    token = await _share()
    body = (await client.get(f"/s/{token}")).text
    assert "Okonkwo Wedding" in body
    assert 'property="og:title"' in body


async def test_a_private_gallery_is_never_indexable(client):
    """It carries Open Graph tags so a chat app can unfurl it, and `noindex`
    so a search engine cannot keep it. The two are not in conflict: messaging
    previews read Open Graph and ignore robots directives."""
    token = await _share()
    body = (await client.get(f"/s/{token}")).text
    assert 'name="robots" content="noindex, nofollow"' in body


async def test_a_person_is_forwarded_to_the_app(client):
    token = await _share()
    body = (await client.get(f"/s/{token}")).text
    # Not back to /s/, which nginx routes here — that would loop.
    assert f"/gallery/{token}" in body
    assert "/s/{}/".format(token) not in body.split("http-equiv")[1][:200]


async def test_a_dead_link_says_nothing_about_the_gallery(client):
    """A revoked share must not keep leaking the client's name into every
    thread it was ever pasted into."""
    token = await _share()
    async with SessionFactory() as session:
        repo = SqlAlchemyGalleryShareRepository(session)
        share = await repo.get_by_token_hash(GalleryShare.hash_of(token))
        share.revoke()
        await repo.update(share)
        await session.commit()

    body = (await client.get(f"/s/{token}")).text
    assert "Okonkwo Wedding" not in body
    assert 'property="og:image"' not in body


async def test_a_gallery_with_nothing_released_offers_no_cover(client):
    """404 rather than a placeholder, so the unfurl falls back to the site's
    own image instead of showing an empty frame."""
    token = await _share()
    assert (await client.get(f"/s/{token}/cover")).status_code == 404


async def test_an_unknown_token_is_not_confirmed_or_denied(client):
    """Same answer as a revoked one: a 404 on the cover and a page that names
    no project. Telling them apart would confirm a token once existed."""
    assert (await client.get("/s/not-a-real-token/cover")).status_code == 404
    body = (await client.get("/s/not-a-real-token")).text
    assert 'property="og:image"' not in body


async def test_a_title_cannot_inject_markup(client):
    """Project titles are typed by staff, not the public — but they reach this
    document straight from the database, and "our own people type it" is not a
    security model."""
    async with SessionFactory() as session:
        staff = await SqlAlchemyUserRepository(session).add(
            User(
                email="xss@example.com",
                first_name="Sam",
                last_name="Staff",
                hashed_password=hash_password("password123"),
                role=UserRole.ADMIN,
            )
        )
        project = Project(
            title='<script>alert(1)</script>', event_type="Wedding",
            stage=ProjectStage.DELIVERED,
        )
        await SqlAlchemyProjectRepository(session).add(
            project,
            ProjectEvent(project_id=project.id, kind=ProjectEventKind.CREATED),
        )
        share, token = GalleryShare.issue(project_id=project.id, created_by=staff.id)
        await SqlAlchemyGalleryShareRepository(session).add(share)
        await session.commit()

    body = (await client.get(f"/s/{token}")).text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body

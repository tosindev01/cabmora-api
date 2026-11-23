"""A client's own library, across every project they have.

What matters here is not that it lists things — it is what it refuses to
list. A library is a page of files somebody has been handed, so anything they
have not been handed must not appear on it, and the watermark rule has to
hold exactly as it does inside a gallery.
"""

from datetime import datetime, timezone

import pytest

from app.application.use_cases.media.list_my_media import ListMyMedia
from app.core.security import hash_password
from app.domain.entities.asset import (
    Asset,
    AssetKind,
    StorageEvent,
    StorageEventKind,
    StoredObject,
)
from app.domain.entities.project import Project
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.invoice_repository_impl import (
    SqlAlchemyInvoiceRepository,
)
from app.infrastructure.repositories.media_repository_impl import (
    SqlAlchemyMediaRepository,
)
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio


class _Storage:
    """Signs anything, so the test is about the rules and not about S3."""

    async def presign_download(
        self, *, key: str, expires_in: int, as_filename: str | None = None
    ) -> str:
        # The name is echoed back so a test can assert the link is a download
        # and not something to look at.
        suffix = f"?save={as_filename}" if as_filename else ""
        return f"https://example.test/{key}{suffix}"


async def _user(email: str, role: UserRole) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=email, first_name="Sam", last_name="Client",
                hashed_password=hash_password("password123"), role=role,
            )
        )
        await session.commit()
        return user


async def _project(owner: User, customer: User, title: str) -> Project:
    async with SessionFactory() as session:
        p = Project(
            title=title, event_type="Wedding",
            creator_id=owner.id, customer_id=customer.id,
        )
        await SqlAlchemyProjectRepository(session).add(
            p, ProjectEvent(project_id=p.id, kind=ProjectEventKind.CREATED)
        )
        await session.commit()
        return p


async def _asset(project: Project, owner: User, content_hash: str, *, released: bool,
                 kind: AssetKind = AssetKind.ORIGINAL, derived_from=None) -> Asset:
    async with SessionFactory() as session:
        asset = Asset(
            project_id=project.id, content_hash=content_hash, kind=kind,
            filename=f"{content_hash[:4]}.jpg", uploaded_by=owner.id,
            derived_from=derived_from,
            released_at=datetime.now(timezone.utc) if released else None,
            # Without this the asset is still awaiting renditions, and
            # `client_may_see` refuses it — correctly, since the only file
            # that exists then is the unwatermarked original.
            renditions_ready_at=datetime.now(timezone.utc),
        )
        await SqlAlchemyMediaRepository(session).record_asset(
            StoredObject(
                content_hash=content_hash, byte_size=1000, content_type="image/jpeg"
            ),
            asset,
            StorageEvent(
                account_id=owner.id, asset_id=asset.id,
                kind=StorageEventKind.ADDED, byte_size=1000,
            ),
        )
        await session.commit()
        return asset


def _use_case(session) -> ListMyMedia:
    return ListMyMedia(
        SqlAlchemyProjectRepository(session),
        SqlAlchemyMediaRepository(session),
        _Storage(),  # type: ignore[arg-type]
        SqlAlchemyInvoiceRepository(session),
    )


async def _library(actor: User):
    async with SessionFactory() as session:
        return await _use_case(session).execute(actor=actor)


async def test_work_not_yet_released_never_appears(client):
    """The one thing this page must not do. A gallery shows an unreleased row
    so a client can see the shoot progressing; a library is what they have
    been handed, and a tile they cannot open is the opposite of that."""
    owner = await _user("owner@example.com", UserRole.ADMIN)
    viewer = await _user("client@example.com", UserRole.CUSTOMER)
    project = await _project(owner, viewer, "Okonkwo Wedding")

    shown = await _asset(project, owner, "a" * 64, released=True)
    await _asset(project, owner, "b" * 64, released=False)
    # Previews exist for both, so the only thing separating them is release.
    await _asset(project, owner, "c" * 64, released=True,
                 kind=AssetKind.PREVIEW, derived_from=shown.id)

    library = await _library(viewer)
    assert [item.asset.id for item in library] == [shown.id]


async def test_another_clients_work_is_not_in_my_library(client):
    owner = await _user("owner@example.com", UserRole.ADMIN)
    mine = await _user("mine@example.com", UserRole.CUSTOMER)
    theirs = await _user("theirs@example.com", UserRole.CUSTOMER)

    my_project = await _project(owner, mine, "Mine")
    their_project = await _project(owner, theirs, "Theirs")
    ours = await _asset(my_project, owner, "d" * 64, released=True)
    await _asset(my_project, owner, "e" * 64, released=True,
                 kind=AssetKind.PREVIEW, derived_from=ours.id)
    stranger = await _asset(their_project, owner, "f" * 64, released=True)
    await _asset(their_project, owner, "1" * 64, released=True,
                 kind=AssetKind.PREVIEW, derived_from=stranger.id)

    assert [item.asset.id for item in await _library(mine)] == [ours.id]
    assert [item.asset.id for item in await _library(theirs)] == [stranger.id]


async def test_the_library_spans_projects_and_names_each_one(client):
    """The whole point: one surface instead of hunting through four shoots."""
    owner = await _user("owner@example.com", UserRole.ADMIN)
    viewer = await _user("client@example.com", UserRole.CUSTOMER)

    for name, digest in (("Spring Gala", "2"), ("Autumn Wedding", "3")):
        project = await _project(owner, viewer, name)
        original = await _asset(project, owner, digest * 64, released=True)
        await _asset(project, owner, chr(ord(digest) + 40) * 64, released=True,
                     kind=AssetKind.PREVIEW, derived_from=original.id)

    library = await _library(viewer)
    assert len(library) == 2
    assert {item.project.title for item in library} == {"Spring Gala", "Autumn Wedding"}
    # A watermarked copy, not the file itself — the job is not paid for.
    assert all(item.is_original is False for item in library)

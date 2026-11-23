"""Organising a shoot into named parts.

The properties worth pinning are the ones whose failure would be quiet and
expensive: filing must never publish anything, deleting a folder must never
delete a photograph, and one project's folder must never be able to reach
another project's work.
"""

import pytest

from app.application.use_cases.media.manage_folders import MAX_FOLDERS, ManageFolders
from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
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
from app.infrastructure.repositories.folder_repository_impl import (
    SqlAlchemyFolderRepository,
)
from app.infrastructure.repositories.media_repository_impl import (
    SqlAlchemyMediaRepository,
)
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio


async def _staff(email: str, role: UserRole = UserRole.ADMIN) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=email, first_name="Sam", last_name="Staff",
                hashed_password=hash_password("password123"), role=role,
            )
        )
        await session.commit()
        return user


async def _project(
    owner: User, title: str = "Okonkwo Wedding", customer: User | None = None
) -> Project:
    async with SessionFactory() as session:
        # A customer sees a project because it is theirs — `is_visible_to`
        # keys off customer_id, not membership, which is for Cabmora's own
        # people on the shoot.
        p = Project(
            title=title, event_type="Wedding", creator_id=owner.id,
            customer_id=customer.id if customer else None,
        )
        await SqlAlchemyProjectRepository(session).add(
            p, ProjectEvent(project_id=p.id, kind=ProjectEventKind.CREATED)
        )
        await session.commit()
        return p


async def _store(project: Project, owner: User, content_hash: str,
                 kind: AssetKind = AssetKind.ORIGINAL, supersedes=None) -> Asset:
    # `supersedes` is set at record time, not by `update_asset` — that method
    # deliberately writes only the fields that change over an asset's life.
    async with SessionFactory() as session:
        asset = Asset(
            project_id=project.id, content_hash=content_hash, kind=kind,
            filename=f"{content_hash[:4]}.jpg", uploaded_by=owner.id,
            supersedes=supersedes,
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


def _use_case(session) -> ManageFolders:
    return ManageFolders(
        SqlAlchemyFolderRepository(session),
        SqlAlchemyMediaRepository(session),
        SqlAlchemyProjectRepository(session),
    )


async def test_filing_a_photograph_never_releases_it(client):
    """The whole point of keeping folders away from visibility.

    A shoot contains frames nobody should show. If tidying up released them,
    a photographer sorting on a Sunday evening would publish the blinks and
    the test exposures without ever being asked.
    """
    owner = await _staff("owner@example.com")
    project = await _project(owner)
    asset = await _store(project, owner, "a" * 64)

    async with SessionFactory() as session:
        folders = _use_case(session)
        folder = await folders.create(actor=owner, project_id=project.id, name="Ceremony")
        await folders.file_assets(
            actor=owner, project_id=project.id,
            asset_ids=[asset.id], folder_id=folder.id,
        )
        stored = await SqlAlchemyMediaRepository(session).get_asset(asset.id)

    assert stored.folder_id == folder.id
    assert stored.released_at is None, "filing must not publish anything"


async def test_deleting_a_folder_unfiles_but_keeps_every_photograph(client):
    owner = await _staff("owner@example.com")
    project = await _project(owner)
    asset = await _store(project, owner, "b" * 64)

    async with SessionFactory() as session:
        folders = _use_case(session)
        folder = await folders.create(actor=owner, project_id=project.id, name="Reception")
        await folders.file_assets(
            actor=owner, project_id=project.id,
            asset_ids=[asset.id], folder_id=folder.id,
        )
        unfiled = await folders.delete(
            actor=owner, project_id=project.id, folder_id=folder.id
        )
        survivor = await SqlAlchemyMediaRepository(session).get_asset(asset.id)
        left = await folders.list_folders(actor=owner, project_id=project.id)

    assert unfiled == 1
    assert left == []
    assert survivor is not None, "a tidy-up must never destroy work"
    assert survivor.folder_id is None


async def test_a_folder_cannot_capture_another_projects_photographs(client):
    """The project is the boundary. Without this a client opens their gallery
    and finds somebody else's wedding in it."""
    owner = await _staff("owner@example.com")
    mine = await _project(owner, "Mine")
    theirs = await _project(owner, "Theirs")
    stranger = await _store(theirs, owner, "c" * 64)

    async with SessionFactory() as session:
        folders = _use_case(session)
        folder = await folders.create(actor=owner, project_id=mine.id, name="Portraits")
        moved = await folders.file_assets(
            actor=owner, project_id=mine.id,
            asset_ids=[stranger.id], folder_id=folder.id,
        )
        untouched = await SqlAlchemyMediaRepository(session).get_asset(stranger.id)

    assert moved == 0
    assert untouched.folder_id is None


async def test_counts_ignore_superseded_frames(client):
    """A folder saying twelve beside a grid of eleven is how people stop
    trusting the number."""
    owner = await _staff("owner@example.com")
    project = await _project(owner)
    original = await _store(project, owner, "d" * 64)
    correction = await _store(project, owner, "e" * 64, supersedes=original.id)

    async with SessionFactory() as session:
        folders = _use_case(session)
        folder = await folders.create(actor=owner, project_id=project.id, name="Speeches")
        await folders.file_assets(
            actor=owner, project_id=project.id,
            asset_ids=[original.id, correction.id], folder_id=folder.id,
        )
        listed = await folders.list_folders(actor=owner, project_id=project.id)

    assert [f.asset_count for f in listed] == [1]


async def test_a_client_cannot_rearrange_the_shoot(client):
    owner = await _staff("owner@example.com")
    outsider = await _staff("client@example.com", UserRole.CUSTOMER)
    project = await _project(owner)

    async with SessionFactory() as session:
        with pytest.raises(PermissionDeniedError):
            await _use_case(session).create(
                actor=outsider, project_id=project.id, name="Mine now"
            )


async def test_duplicate_names_are_refused_ignoring_case_and_padding(client):
    owner = await _staff("owner@example.com")
    project = await _project(owner)

    async with SessionFactory() as session:
        folders = _use_case(session)
        await folders.create(actor=owner, project_id=project.id, name="Ceremony")
        with pytest.raises(ValidationError):
            await folders.create(actor=owner, project_id=project.id, name="  ceremony ")


async def test_new_folders_go_to_the_end_and_reorder_takes_the_whole_list(client):
    owner = await _staff("owner@example.com")
    project = await _project(owner)

    async with SessionFactory() as session:
        folders = _use_case(session)
        first = await folders.create(actor=owner, project_id=project.id, name="Ceremony")
        second = await folders.create(actor=owner, project_id=project.id, name="Reception")
        assert [f.name for f in await folders.list_folders(
            actor=owner, project_id=project.id
        )] == ["Ceremony", "Reception"]

        reordered = await folders.reorder(
            actor=owner, project_id=project.id, folder_ids=[second.id, first.id]
        )
        assert [f.name for f in reordered] == ["Reception", "Ceremony"]

        # A partial list is refused: it would silently drop whatever it omits.
        with pytest.raises(ValidationError):
            await folders.reorder(
                actor=owner, project_id=project.id, folder_ids=[first.id]
            )


async def test_a_folder_from_another_project_is_not_found(client):
    owner = await _staff("owner@example.com")
    mine = await _project(owner, "Mine")
    theirs = await _project(owner, "Theirs")

    async with SessionFactory() as session:
        folders = _use_case(session)
        elsewhere = await folders.create(
            actor=owner, project_id=theirs.id, name="Ceremony"
        )
        with pytest.raises(EntityNotFoundError):
            await folders.rename(
                actor=owner, project_id=mine.id,
                folder_id=elsewhere.id, name="Renamed",
            )


async def _released(project: Project, owner: User, content_hash: str) -> Asset:
    """A photograph the client has actually been shown."""
    from datetime import datetime, timezone

    asset = await _store(project, owner, content_hash)
    async with SessionFactory() as session:
        media = SqlAlchemyMediaRepository(session)
        asset.released_at = datetime.now(timezone.utc)
        await media.update_asset(asset)
    return asset


async def test_a_clients_folder_count_never_describes_withheld_work(client):
    """Counting everything would announce how much is being kept back.

    "Ceremony 40" over four released frames tells a client exactly how many
    they are not being shown, and the withholding is deliberate — a shoot
    contains the blinks and the test exposures.
    """
    owner = await _staff("owner@example.com")
    viewer = await _staff("client@example.com", UserRole.CUSTOMER)
    project = await _project(owner, customer=viewer)

    shown = await _released(project, owner, "1" * 64)
    withheld = await _store(project, owner, "2" * 64)

    async with SessionFactory() as session:
        folders = _use_case(session)
        folder = await folders.create(actor=owner, project_id=project.id, name="Ceremony")
        await folders.file_assets(
            actor=owner, project_id=project.id,
            asset_ids=[shown.id, withheld.id], folder_id=folder.id,
        )
        for_staff = await folders.list_folders(actor=owner, project_id=project.id)
        for_client = await folders.list_folders(actor=viewer, project_id=project.id)

    assert [f.asset_count for f in for_staff] == [2]
    assert [f.asset_count for f in for_client] == [1]


async def test_a_folder_with_nothing_released_is_hidden_from_the_client(client):
    """An empty "Reception" tells a client the reception exists and is being
    kept from them, which is worse than saying nothing."""
    owner = await _staff("owner@example.com")
    viewer = await _staff("client@example.com", UserRole.CUSTOMER)
    project = await _project(owner, customer=viewer)

    hidden = await _store(project, owner, "3" * 64)

    async with SessionFactory() as session:
        folders = _use_case(session)
        folder = await folders.create(actor=owner, project_id=project.id, name="Reception")
        await folders.file_assets(
            actor=owner, project_id=project.id,
            asset_ids=[hidden.id], folder_id=folder.id,
        )
        assert await folders.list_folders(actor=viewer, project_id=project.id) == []
        # Still the studio's own folder, whatever the client can see.
        assert len(await folders.list_folders(actor=owner, project_id=project.id)) == 1


async def test_a_client_still_cannot_change_a_folder(client):
    """Reading opened up. Writing did not."""
    owner = await _staff("owner@example.com")
    viewer = await _staff("client@example.com", UserRole.CUSTOMER)
    project = await _project(owner, customer=viewer)

    async with SessionFactory() as session:
        folders = _use_case(session)
        made = await folders.create(actor=owner, project_id=project.id, name="Ceremony")
        for attempt in (
            folders.create(actor=viewer, project_id=project.id, name="Mine"),
            folders.rename(
                actor=viewer, project_id=project.id, folder_id=made.id, name="Mine"
            ),
            folders.delete(actor=viewer, project_id=project.id, folder_id=made.id),
        ):
            with pytest.raises(PermissionDeniedError):
                await attempt

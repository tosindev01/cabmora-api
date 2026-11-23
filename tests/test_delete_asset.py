"""Deleting a photograph, and actually getting the space back.

Storage is the running cost of this product, so the things worth pinning are
the ones that would quietly keep charging: bytes shared between projects must
not be deleted out from under the other one, renditions must go with their
original, and the usage log has to show the release against the same account
the upload was charged to — or that account's usage never comes down.
"""

import pytest

from app.core.exceptions import PermissionDeniedError
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
from app.infrastructure.repositories.media_repository_impl import (
    SqlAlchemyMediaRepository,
)
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

pytestmark = pytest.mark.asyncio

HASH_A = "a" * 64
HASH_B = "b" * 64


class _Bucket:
    """Records what was asked to be deleted, so a test can assert on it."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def delete(self, *, key: str) -> None:
        self.deleted.append(key)


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


async def _project(owner: User) -> Project:
    async with SessionFactory() as session:
        p = Project(title="Okonkwo Wedding", event_type="Wedding", creator_id=owner.id)
        await SqlAlchemyProjectRepository(session).add(
            p, ProjectEvent(project_id=p.id, kind=ProjectEventKind.CREATED)
        )
        await session.commit()
        return p


async def _store(project: Project, *, content_hash: str, size: int,
                 kind: AssetKind = AssetKind.ORIGINAL, derived_from=None,
                 owner: User) -> Asset:
    async with SessionFactory() as session:
        media = SqlAlchemyMediaRepository(session)
        asset = Asset(
            project_id=project.id, content_hash=content_hash, kind=kind,
            filename=f"{content_hash[:4]}.jpg", uploaded_by=owner.id,
            derived_from=derived_from,
        )
        stored = await media.record_asset(
            StoredObject(
                content_hash=content_hash, byte_size=size, content_type="image/jpeg"
            ),
            asset,
            StorageEvent(
                account_id=owner.id, asset_id=asset.id,
                kind=StorageEventKind.ADDED, byte_size=size,
            ),
        )
        await session.commit()
        return stored if isinstance(stored, Asset) else asset


def _use_case(session, bucket):
    from app.application.use_cases.media.delete_asset import DeleteAsset

    return DeleteAsset(
        SqlAlchemyProjectRepository(session),
        SqlAlchemyMediaRepository(session),
        bucket,
    )


async def test_shared_bytes_are_not_deleted_from_the_bucket(client):
    """Two projects uploading the same file share one object. Deleting one
    copy must decrement, or the other project's gallery goes blank."""
    owner = await _staff("owner@example.com")
    one, two = await _project(owner), await _project(owner)
    a = await _store(one, content_hash=HASH_A, size=1000, owner=owner)
    await _store(two, content_hash=HASH_A, size=1000, owner=owner)

    bucket = _Bucket()
    async with SessionFactory() as session:
        await _use_case(session, bucket).execute(asset_id=a.id, actor=owner)

    assert bucket.deleted == []
    async with SessionFactory() as session:
        blob = await SqlAlchemyMediaRepository(session).get_object(HASH_A)
        assert blob is not None and blob.reference_count == 1


async def test_the_last_reference_takes_the_bytes_with_it(client):
    owner = await _staff("last@example.com")
    project = await _project(owner)
    a = await _store(project, content_hash=HASH_A, size=1000, owner=owner)

    bucket = _Bucket()
    async with SessionFactory() as session:
        await _use_case(session, bucket).execute(asset_id=a.id, actor=owner)

    assert len(bucket.deleted) == 1


async def test_a_rendition_goes_with_its_original(client):
    """Otherwise the watermarked copy stays in the bucket for ever, reachable
    by nothing and billed for monthly."""
    owner = await _staff("rend@example.com")
    project = await _project(owner)
    original = await _store(project, content_hash=HASH_A, size=1000, owner=owner)
    await _store(
        project, content_hash=HASH_B, size=200,
        kind=AssetKind.PREVIEW, derived_from=original.id, owner=owner,
    )

    bucket = _Bucket()
    async with SessionFactory() as session:
        removed = await _use_case(session, bucket).execute(
            asset_id=original.id, actor=owner
        )

    assert removed == 2
    assert len(bucket.deleted) == 2


async def test_the_release_is_charged_to_whoever_was_charged_for_the_upload(client):
    """`usage_bytes` sums ADDED minus REMOVED per account. Releasing against
    anybody else leaves the owner's usage permanently inflated."""
    owner = await _staff("usage@example.com")
    project = await _project(owner)
    a = await _store(project, content_hash=HASH_A, size=4096, owner=owner)

    async with SessionFactory() as session:
        before = await SqlAlchemyMediaRepository(session).usage_bytes(owner.id)
    assert before == 4096

    async with SessionFactory() as session:
        await _use_case(session, _Bucket()).execute(asset_id=a.id, actor=owner)

    async with SessionFactory() as session:
        after = await SqlAlchemyMediaRepository(session).usage_bytes(owner.id)
    assert after == 0, "the released bytes never came off the account"


async def test_a_client_cannot_delete_the_work_they_are_reviewing(client):
    owner = await _staff("mgr@example.com")
    outsider = await _staff("client@example.com", role=UserRole.CUSTOMER)
    project = await _project(owner)
    a = await _store(project, content_hash=HASH_A, size=1000, owner=owner)

    async with SessionFactory() as session:
        with pytest.raises(PermissionDeniedError):
            await _use_case(session, _Bucket()).execute(
                asset_id=a.id, actor=outsider
            )


# ── a preview that is never coming ───────────────────────────────────────
def test_an_abandoned_asset_is_still_awaiting_renditions():
    """Deliberate, and load-bearing.

    `awaiting_renditions` is what stops the gallery handing over an original's
    own bytes when no watermarked preview exists. If giving up also cleared
    that flag, a file the worker could not read would start being served
    unwatermarked — a failed preview would become a watermark leak.
    """
    from app.domain.entities.asset import MAX_RENDITION_ATTEMPTS, Asset, AssetKind
    from uuid import uuid4

    asset = Asset(
        project_id=uuid4(), content_hash="c" * 64, kind=AssetKind.ORIGINAL,
        filename="not-really.jpg", uploaded_by=uuid4(),
        rendition_attempts=MAX_RENDITION_ATTEMPTS,
    )
    assert asset.renditions_abandoned is True
    assert asset.awaiting_renditions is True


def test_a_fresh_upload_is_pending_but_not_abandoned():
    """The two must not be confused: one resolves itself, the other never
    will, and the console says different things about them."""
    from app.domain.entities.asset import Asset, AssetKind
    from uuid import uuid4

    asset = Asset(
        project_id=uuid4(), content_hash="d" * 64, kind=AssetKind.ORIGINAL,
        filename="real.jpg", uploaded_by=uuid4(),
    )
    assert asset.awaiting_renditions is True
    assert asset.renditions_abandoned is False

"""The two decisions that cannot be retrofitted once real bytes exist.

Deduplication by content hash, and usage as an append-only log rather than a
counter. Both are cheap to get right now and a migration across every stored
byte to get right later, so they are pinned by tests from the start.
"""

from uuid import uuid4

import pytest

from app.domain.entities.asset import (
    Asset,
    AssetKind,
    StorageEvent,
    StorageEventKind,
    StoredObject,
)
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.media_repository_impl import (
    SqlAlchemyMediaRepository,
)

HASH = "a3f1" + "b" * 60
CREATOR = uuid4()


def _blob(size: int = 1024) -> StoredObject:
    return StoredObject(content_hash=HASH, byte_size=size, content_type="image/jpeg")


def _asset(project_id, size: int = 1024):
    asset = Asset(
        project_id=project_id,
        content_hash=HASH,
        kind=AssetKind.ORIGINAL,
        filename="IMG_2856.jpg",
        uploaded_by=CREATOR,
    )
    event = StorageEvent(
        account_id=CREATOR,
        asset_id=asset.id,
        kind=StorageEventKind.ADDED,
        byte_size=size,
    )
    return asset, event


@pytest.mark.anyio
async def test_the_same_file_is_stored_once(client):
    """Two projects, identical bytes, one blob — with both accounted for."""
    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        await repo.record_asset(_blob(), *_asset(uuid4()))
        await repo.record_asset(_blob(), *_asset(uuid4()))
        blob = await repo.get_object(HASH)

    assert blob is not None
    assert blob.reference_count == 2, "the second upload must claim, not re-create"
    assert blob.key.endswith(HASH), "the key is the content hash, sharded"


@pytest.mark.anyio
async def test_usage_is_summed_from_the_log_not_stored(client):
    project = uuid4()
    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        asset, event = _asset(project)
        await repo.record_asset(_blob(), asset, event)

    async with SessionFactory() as session:
        assert await SqlAlchemyMediaRepository(session).usage_bytes(CREATOR) == 1024


@pytest.mark.anyio
async def test_deleting_an_asset_keeps_its_history(client):
    """The log outlives what it describes — that is the whole point of it."""
    project = uuid4()
    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        asset, event = _asset(project)
        await repo.record_asset(_blob(), asset, event)

    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        blob = await repo.remove_asset(
            asset,
            StorageEvent(
                account_id=CREATOR,
                asset_id=asset.id,
                kind=StorageEventKind.REMOVED,
                byte_size=1024,
            ),
        )

    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        assert await repo.get_asset(asset.id) is None, "the asset is gone"
        assert await repo.usage_bytes(CREATOR) == 0, "and its bytes were returned"

    assert blob is not None and blob.is_orphaned, "nothing points at the blob now"


@pytest.mark.anyio
async def test_one_project_deleting_does_not_orphan_the_other(client):
    """The reference count exists for exactly this: shared bytes."""
    a_project, b_project = uuid4(), uuid4()
    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        a_asset, a_event = _asset(a_project)
        b_asset, b_event = _asset(b_project)
        await repo.record_asset(_blob(), a_asset, a_event)
        await repo.record_asset(_blob(), b_asset, b_event)

    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        blob = await repo.remove_asset(
            a_asset,
            StorageEvent(
                account_id=CREATOR,
                asset_id=a_asset.id,
                kind=StorageEventKind.REMOVED,
                byte_size=1024,
            ),
        )

    assert blob is not None
    assert not blob.is_orphaned, "the other project still needs these bytes"
    assert blob.reference_count == 1


@pytest.mark.anyio
async def test_an_original_without_renditions_is_not_viewable(client):
    """Serving the original because no watermarked preview exists yet would
    hand over exactly the file the watermark protects."""
    asset, _ = _asset(uuid4())
    assert asset.awaiting_renditions is True


# ── the storage adapter ──────────────────────────────────────────────────
@pytest.mark.anyio
async def test_a_file_survives_being_sent_in_pieces(tmp_path):
    """Chunked upload, reassembled byte for byte.

    The property that matters is not that it works — it is that the file is
    *identical*. These are photographs; a reassembly that is off by one byte is
    a corrupt RAW the client cannot open, and nothing would report an error.
    """
    from app.infrastructure.storage.local_media_storage import LocalMediaStorage

    storage = LocalMediaStorage(
        root=tmp_path, secret="dev", base_url="http://localhost:8000/api/v1"
    )
    original = bytes(range(256)) * 100_000          # ~25 MB, non-repeating
    key = "assets/ab/cd/" + "ab" * 32

    ticket = await storage.start_upload(
        key=key, content_type="image/jpeg", byte_size=len(original)
    )
    assert len(ticket.part_urls) == 3, "25 MB at 10 MiB chunks"

    etags = [
        storage.write_part(
            upload_id=ticket.upload_id,
            part=n,
            data=original[(n - 1) * ticket.part_size : n * ticket.part_size],
        )
        for n in range(1, len(ticket.part_urls) + 1)
    ]

    assert await storage.exists(key=key) is None, "nothing exists until completion"
    await storage.complete_upload(key=key, upload_id=ticket.upload_id, etags=etags)
    assert storage.read_bytes(key=key) == original, "reassembled byte for byte"


@pytest.mark.anyio
async def test_a_missing_part_refuses_rather_than_truncates(tmp_path):
    """Half a photograph is worse than an error — it looks like a file."""
    from app.infrastructure.storage.local_media_storage import LocalMediaStorage

    storage = LocalMediaStorage(
        root=tmp_path, secret="dev", base_url="http://localhost:8000/api/v1"
    )
    key = "assets/ef/01/" + "ef" * 32
    ticket = await storage.start_upload(
        key=key, content_type="image/jpeg", byte_size=25 * 1024 * 1024
    )
    storage.write_part(upload_id=ticket.upload_id, part=1, data=b"x" * 1024)

    with pytest.raises(ValueError, match="never uploaded"):
        await storage.complete_upload(
            key=key, upload_id=ticket.upload_id, etags=["a", "b", "c"]
        )
    assert await storage.exists(key=key) is None


@pytest.mark.anyio
async def test_a_key_cannot_escape_the_media_root(tmp_path):
    from app.infrastructure.storage.local_media_storage import LocalMediaStorage

    storage = LocalMediaStorage(
        root=tmp_path, secret="dev", base_url="http://localhost:8000/api/v1"
    )
    with pytest.raises(ValueError, match="escapes the media root"):
        await storage.exists(key="../../etc/passwd")

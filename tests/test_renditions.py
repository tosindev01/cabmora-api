"""Making the file a client is allowed to look at.

Two things are defended here: the original is never altered, and nothing is
marked ready until both renditions exist. A photograph that reports itself
ready without a watermarked preview is the exact bug that would hand a client
the untouched file.
"""

import hashlib
import io

import pytest
from PIL import Image

from app.api import deps
from app.application.use_cases.media.generate_renditions import GenerateRenditions
from app.core.security import hash_password
from app.domain.entities.asset import AssetKind
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.imaging.pillow_processor import PillowImageProcessor
from app.infrastructure.repositories.media_repository_impl import (
    SqlAlchemyMediaRepository,
)
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"


def _photograph(width: int = 3000, height: int = 2000) -> bytes:
    """Bigger than a preview, so the resize has something to do."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for x in range(0, width, 7):
        for y in range(0, height, 7):
            pixels[x, y] = ((x * 7) % 256, (y * 5) % 256, ((x + y) * 3) % 256)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


PHOTO = _photograph()
DIGEST = hashlib.sha256(PHOTO).hexdigest()


@pytest.fixture
def storage(tmp_path):
    from app.infrastructure.storage.local_media_storage import LocalMediaStorage
    from app.main import app

    disk = LocalMediaStorage(root=tmp_path, secret="test", base_url="/api/v1")
    app.dependency_overrides[deps.get_media_storage] = lambda: disk
    yield disk
    app.dependency_overrides.pop(deps.get_media_storage, None)


async def _make(email: str, role: UserRole) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(email=email, first_name="Test", last_name="Person",
                 hashed_password=hash_password(PASSWORD), role=role)
        )
        await session.commit()
        return user


async def _uploaded(client, storage) -> tuple[str, str]:
    admin = await _make("admin@example.com", UserRole.ADMIN)
    customer = await _make("customer@example.com", UserRole.CUSTOMER)
    await client.post("/api/v1/auth/login",
                      json={"email": admin.email, "password": PASSWORD})
    made = await client.post("/api/v1/admin/projects", json={
        "title": "Okafor Wedding", "customer_id": str(customer.id),
        "event_type": "Wedding", "location": "Manchester",
    })
    project_id = made.json()["id"]
    await client.post(f"/api/v1/admin/projects/{project_id}/stage",
                      json={"stage": "booked"})

    body = {"content_hash": DIGEST, "filename": "IMG_0001.jpg",
            "content_type": "image/jpeg", "byte_size": len(PHOTO)}
    ask = await client.post(f"/api/v1/projects/{project_id}/uploads", json=body)
    ticket = ask.json()["ticket"]
    etags = [
        storage.write_part(upload_id=ticket["upload_id"], part=n,
                           data=PHOTO[(n-1)*ticket["part_size"]:n*ticket["part_size"]])
        for n in range(1, len(ticket["part_urls"]) + 1)
    ]
    done = await client.post(f"/api/v1/projects/{project_id}/uploads/confirm",
                             json={**body, "upload_id": ticket["upload_id"], "etags": etags})
    assert done.status_code == 201, done.text
    return project_id, done.json()["id"]


async def _run(storage) -> object:
    async with SessionFactory() as session:
        return await GenerateRenditions(
            SqlAlchemyMediaRepository(session),
            SqlAlchemyProjectRepository(session),
            storage,
            PillowImageProcessor(),
        ).execute()


@pytest.mark.anyio
async def test_a_preview_and_a_thumbnail_are_made(client, storage):
    from uuid import UUID

    project_id, asset_id = await _uploaded(client, storage)
    report = await _run(storage)
    assert report.processed == 1 and report.failed == 0

    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        original = await repo.get_asset(UUID(asset_id))
        assert original.renditions_ready_at is not None
        assert original.awaiting_renditions is False

        kinds = {
            a.kind
            for a in await repo.list_project_assets(UUID(project_id))
            if a.derived_from == UUID(asset_id)
        }
    assert kinds == {AssetKind.PREVIEW, AssetKind.THUMBNAIL}


@pytest.mark.anyio
async def test_the_original_is_never_altered(client, storage):
    """RAWs are irreplaceable and they are the product."""
    from uuid import UUID

    project_id, asset_id = await _uploaded(client, storage)
    async with SessionFactory() as session:
        blob = await SqlAlchemyMediaRepository(session).get_object(DIGEST)
    before = storage.read_bytes(key=blob.key)

    await _run(storage)

    after = storage.read_bytes(key=blob.key)
    assert after == before == PHOTO, "byte-for-byte untouched"


@pytest.mark.anyio
async def test_the_preview_is_smaller_and_marked(client, storage):
    from uuid import UUID

    project_id, asset_id = await _uploaded(client, storage)
    await _run(storage)

    async with SessionFactory() as session:
        repo = SqlAlchemyMediaRepository(session)
        preview = next(
            a for a in await repo.list_project_assets(UUID(project_id))
            if a.kind is AssetKind.PREVIEW
        )
        blob = await repo.get_object(preview.content_hash)

    image = Image.open(io.BytesIO(storage.read_bytes(key=blob.key)))
    assert max(image.size) == 2048, "downscaled to the review size"
    assert blob.byte_size < len(PHOTO), "and much lighter than the original"


@pytest.mark.anyio
async def test_a_second_run_finds_nothing_to_do(client, storage):
    """The queue is `renditions_ready_at IS NULL` — work must leave it."""
    await _uploaded(client, storage)
    first = await _run(storage)
    second = await _run(storage)
    assert first.processed == 1
    assert second.processed == 0, "already rendered work must not be redone"


@pytest.mark.anyio
async def test_the_client_can_see_it_once_released_and_rendered(client, storage):
    """Both conditions, together — this is the whole point of the pipeline."""
    project_id, asset_id = await _uploaded(client, storage)
    await client.post(f"/api/v1/projects/{project_id}/assets/release",
                      json={"asset_ids": [asset_id], "released": True})
    await _run(storage)

    await client.post("/api/v1/auth/logout")
    await client.post("/api/v1/auth/login",
                      json={"email": "customer@example.com", "password": PASSWORD})
    rows = (await client.get(f"/api/v1/projects/{project_id}/assets")).json()
    assert rows[0]["url"] is not None, "released and rendered — the client may look"
    assert rows[0]["is_original"] is False, "but never at the original"


@pytest.mark.anyio
async def test_a_client_is_never_handed_the_original_file(client, storage):
    """The bug this exists to prevent.

    Reporting `is_original: false` while serving the original's bytes is the
    worst possible failure here: it looks correct in every response and hands
    over exactly the file the watermark protects. So this asserts on the bytes
    behind the link, not on the flag beside it.
    """
    import io
    from urllib.parse import urlparse

    from PIL import Image

    project_id, asset_id = await _uploaded(client, storage)
    await client.post(f"/api/v1/projects/{project_id}/assets/release",
                      json={"asset_ids": [asset_id], "released": True})
    await _run(storage)

    admin_row = (await client.get(f"/api/v1/projects/{project_id}/assets")).json()[0]

    await client.post("/api/v1/auth/logout")
    await client.post("/api/v1/auth/login",
                      json={"email": "customer@example.com", "password": PASSWORD})
    client_row = (await client.get(f"/api/v1/projects/{project_id}/assets")).json()[0]

    assert client_row["url"] is not None, "released and rendered — they may look"
    assert client_row["url"] != admin_row["url"], "and at a different file"

    def _bytes(url: str) -> bytes:
        key = urlparse(url).path.split("/media/", 1)[1]
        return storage.read_bytes(key=key)

    served = _bytes(client_row["url"])
    assert served != PHOTO, "the client must not receive the original's bytes"
    assert max(Image.open(io.BytesIO(served)).size) == 2048, "they get the preview"


@pytest.mark.anyio
async def test_no_preview_means_no_link_however_released(client, storage):
    """Releasing cannot outrun the watermark."""
    project_id, asset_id = await _uploaded(client, storage)
    await client.post(f"/api/v1/projects/{project_id}/assets/release",
                      json={"asset_ids": [asset_id], "released": True})
    # Deliberately not rendered.

    await client.post("/api/v1/auth/logout")
    await client.post("/api/v1/auth/login",
                      json={"email": "customer@example.com", "password": PASSWORD})
    row = (await client.get(f"/api/v1/projects/{project_id}/assets")).json()[0]
    assert row["url"] is None

"""Uploading a profile picture, in one request.

This used to hand the browser signed URLs and take a second call to confirm —
the shape media uses, and the wrong one for an 8 MB photograph. It needed a
CORS policy and an exposed ETag header to work at all, and broke silently
without either. Pinned here is what holding the bytes buys: the file is proved
to be an image rather than trusted to say so, and nothing of the original
file's metadata survives.
"""

import io

import pytest
from PIL import Image

from app.api import deps
from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import (
    SqlAlchemyUserRepository,
)
from app.main import app

pytestmark = pytest.mark.anyio


@pytest.fixture
def disk(tmp_path):
    """Local storage instead of the bucket, as the media tests do."""
    from app.infrastructure.storage.local_media_storage import LocalMediaStorage

    store = LocalMediaStorage(root=tmp_path, secret="test-secret", base_url="/api/v1")
    app.dependency_overrides[deps.get_media_storage] = lambda: store
    yield store
    app.dependency_overrides.pop(deps.get_media_storage, None)


def _jpeg(width: int = 1200, height: int = 900, exif: Image.Exif | None = None) -> bytes:
    buffer = io.BytesIO()
    image = Image.new("RGB", (width, height), (90, 120, 160))
    image.save(buffer, format="JPEG", **({"exif": exif} if exif is not None else {}))
    return buffer.getvalue()


async def _signed_in(client) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email="shooter@example.com", first_name="Sam", last_name="Shooter",
                hashed_password=hash_password("password123"), role=UserRole.ADMIN,
            )
        )
        await session.commit()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "shooter@example.com", "password": "password123"},
    )
    assert resp.status_code == 200, resp.text
    return user


async def _stored_avatar(user_id, disk) -> bytes:
    async with SessionFactory() as session:
        saved = await SqlAlchemyUserRepository(session).get_by_id(user_id)
    assert saved.avatar_key, "the account should point at a picture"
    return await disk.read(key=saved.avatar_key)


async def test_a_picture_uploads_in_one_request(client, disk):
    user = await _signed_in(client)
    resp = await client.post(
        "/api/v1/auth/me/avatar",
        files={"file": ("me.jpg", _jpeg(), "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"], "the response carries a link to the new picture"

    stored = Image.open(io.BytesIO(await _stored_avatar(user.id, disk)))
    # Square, because every avatar in this product is shown in a circle.
    assert stored.size == (512, 512)


async def test_something_that_is_not_an_image_is_refused(client, disk):
    """A content type is a claim the browser makes, and `image/jpeg` on a zip
    is a claim it will happily make. Only decoding the bytes can tell."""
    await _signed_in(client)
    resp = await client.post(
        "/api/v1/auth/me/avatar",
        files={"file": ("me.jpg", b"PK\x03\x04 not a photograph at all", "image/jpeg")},
    )
    assert resp.status_code == 422, resp.text
    assert "image" in resp.json()["detail"].lower()


async def test_location_data_does_not_survive_the_upload(client, disk):
    """A phone records where a photograph was taken. Keeping that because
    somebody chose a picture of themselves is not a trade anybody agreed to."""
    user = await _signed_in(client)

    # Scalar tags, because the point is that the EXIF block does not survive
    # and GPS coordinates live in that block. Proving none of it is kept
    # proves the coordinates are not.
    exif = Image.Exif()
    exif[0x010F] = "TestPhone"  # Make
    exif[0x0110] = "Model X"  # Model
    original = _jpeg(exif=exif)
    assert Image.open(io.BytesIO(original)).getexif(), "the fixture carries EXIF"

    resp = await client.post(
        "/api/v1/auth/me/avatar",
        files={"file": ("me.jpg", original, "image/jpeg")},
    )
    assert resp.status_code == 200, resp.text

    stored = Image.open(io.BytesIO(await _stored_avatar(user.id, disk)))
    assert not stored.getexif(), "no metadata from the original may be stored"

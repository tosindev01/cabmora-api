"""Saving a delivered photograph to the device.

The bug behind this file: the gallery offered a link, and following it opened
the photograph in a tab instead of saving it. Two causes, both server-side.
A `download` attribute on an anchor is **ignored for cross-origin URLs**, and
a presigned link always is one; and fetching the bytes to save a blob needs a
CORS grant on the bucket and holds the whole file in the tab's memory, so it
could never have worked for video.

So what is asserted here is the thing the browser actually obeys — the
`Content-Disposition` on the response the link leads to — and not merely that
an endpoint returned a URL.
"""

import hashlib
import io

import pytest
from PIL import Image

from app.api import deps
from app.application.use_cases.media.generate_renditions import GenerateRenditions
from app.core.security import hash_password
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
FILENAME = "Okafor Wedding, Ayọ̀ & Sam.jpg"


def _photograph(width: int = 3000, height: int = 2000) -> bytes:
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


async def _login(client, email: str) -> None:
    await client.post("/api/v1/auth/logout")
    resp = await client.post("/api/v1/auth/login",
                             json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _run(storage) -> object:
    async with SessionFactory() as session:
        return await GenerateRenditions(
            SqlAlchemyMediaRepository(session),
            SqlAlchemyProjectRepository(session),
            storage,
            PillowImageProcessor(),
        ).execute()


async def _delivered(client, storage, *, allow_downloads: bool) -> tuple[str, str, User]:
    """A released, rendered photograph on a project the customer owns."""
    admin = await _make("admin@example.com", UserRole.ADMIN)
    customer = await _make("customer@example.com", UserRole.CUSTOMER)
    await _login(client, admin.email)

    made = await client.post("/api/v1/admin/projects", json={
        "title": "Okafor Wedding", "customer_id": str(customer.id),
        "event_type": "Wedding", "location": "Manchester",
    })
    project_id = made.json()["id"]
    await client.post(f"/api/v1/admin/projects/{project_id}/stage",
                      json={"stage": "booked"})
    if allow_downloads:
        turned_on = await client.patch(f"/api/v1/admin/projects/{project_id}",
                                       json={"allow_downloads": True})
        assert turned_on.status_code == 200, turned_on.text

    body = {"content_hash": DIGEST, "filename": FILENAME,
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
    asset_id = done.json()["id"]

    await client.post(f"/api/v1/projects/{project_id}/assets/release",
                      json={"asset_ids": [asset_id], "released": True})
    await _run(storage)
    return project_id, asset_id, customer


@pytest.mark.anyio
async def test_the_link_tells_the_browser_to_save_rather_than_open(client, storage):
    """The assertion that matters: what the response actually instructs.

    Returning a URL proves nothing — the old behaviour returned one too, and
    the browser displayed it.
    """
    _, asset_id, customer = await _delivered(client, storage, allow_downloads=True)
    await _login(client, customer.email)

    handed = await client.get(f"/api/v1/me/media/{asset_id}/download")
    assert handed.status_code == 200, handed.text

    served = await client.get(handed.json()["url"])
    assert served.status_code == 200, served.text
    disposition = served.headers["content-disposition"]
    assert disposition.startswith("attachment;"), disposition
    # Both encodings, so the name survives a browser of any age. The ASCII
    # half cannot carry the diacritics, which is exactly why there are two.
    assert "filename*=UTF-8''" in disposition
    assert "Okafor" in disposition


@pytest.mark.anyio
async def test_a_project_with_downloads_off_refuses(client, storage):
    """Off is the default, because the PRD asks for galleries that are not
    downloadable. The client may still look — they just may not keep."""
    _, asset_id, customer = await _delivered(client, storage, allow_downloads=False)
    await _login(client, customer.email)

    refused = await client.get(f"/api/v1/me/media/{asset_id}/download")
    assert refused.status_code == 403, refused.text


@pytest.mark.anyio
async def test_downloading_hands_over_the_watermarked_copy_while_unpaid(client, storage):
    """Downloads on is not a bypass of the watermark.

    The two settings answer different questions — whether a save button
    exists at all, and which file is behind it — and conflating them is how
    an unpaid client ends up holding an original.
    """
    _, asset_id, customer = await _delivered(client, storage, allow_downloads=True)
    await _login(client, customer.email)

    url = (await client.get(f"/api/v1/me/media/{asset_id}/download")).json()["url"]
    saved = (await client.get(url)).content
    assert saved != PHOTO, "that is the untouched original"


@pytest.mark.anyio
async def test_a_stranger_is_not_told_the_file_exists(client, storage):
    """Not found, not forbidden: whether an id exists is not something
    somebody with no claim on it should be able to learn."""
    _, asset_id, _ = await _delivered(client, storage, allow_downloads=True)
    outsider = await _make("someone@example.com", UserRole.CUSTOMER)
    await _login(client, outsider.email)

    denied = await client.get(f"/api/v1/me/media/{asset_id}/download")
    assert denied.status_code == 404, denied.text


@pytest.mark.anyio
async def test_a_view_link_cannot_be_edited_into_a_download(client, storage):
    """The disposition is signed, not appended.

    R2 folds `response-content-disposition` into the signature; the local
    stand-in signs the filename into its payload for the same reason. If
    either stopped doing so, a gallery's view link could be turned into a
    download of the same file by hand — which would make the project's
    downloads switch decorative.
    """
    project_id, asset_id, customer = await _delivered(client, storage, allow_downloads=False)
    await _login(client, customer.email)

    viewing = (await client.get(f"/api/v1/projects/{project_id}/assets")).json()[0]["url"]
    assert viewing is not None
    forged = f"{viewing}&filename=stolen.jpg"

    refused = await client.get(forged)
    assert refused.status_code == 403, refused.text

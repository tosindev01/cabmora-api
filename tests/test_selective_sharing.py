"""Sharing a few photographs rather than the whole gallery.

The bug: picking one picture shared the lot. Nothing stored which frames a
link was for, so every link meant "this project", and a client sending one
photograph to a relative sent the whole wedding.

What these pin is the part that cannot be seen from the outside — that the
selection is enforced where the photographs are handed over, not merely
offered in the picker. The ids arrive over HTTP, so a selection the server
does not check is a suggestion.
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


def _photograph(seed: int) -> bytes:
    """Distinct bytes per seed, so content-addressed storage keeps them apart."""
    image = Image.new("RGB", (1400, 900))
    pixels = image.load()
    for x in range(0, 1400, 11):
        for y in range(0, 900, 11):
            pixels[x, y] = ((x * seed) % 256, (y * seed) % 256, (seed * 37) % 256)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


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


async def _render(storage) -> None:
    async with SessionFactory() as session:
        await GenerateRenditions(
            SqlAlchemyMediaRepository(session),
            SqlAlchemyProjectRepository(session),
            storage,
            PillowImageProcessor(),
        ).execute()


async def _upload(client, storage, project_id: str, seed: int) -> str:
    photo = _photograph(seed)
    body = {"content_hash": hashlib.sha256(photo).hexdigest(),
            "filename": f"IMG_{seed:04d}.jpg",
            "content_type": "image/jpeg", "byte_size": len(photo)}
    ask = await client.post(f"/api/v1/projects/{project_id}/uploads", json=body)
    ticket = ask.json()["ticket"]
    etags = [
        storage.write_part(upload_id=ticket["upload_id"], part=n,
                           data=photo[(n-1)*ticket["part_size"]:n*ticket["part_size"]])
        for n in range(1, len(ticket["part_urls"]) + 1)
    ]
    done = await client.post(f"/api/v1/projects/{project_id}/uploads/confirm",
                             json={**body, "upload_id": ticket["upload_id"], "etags": etags})
    assert done.status_code == 201, done.text
    return done.json()["id"]


async def _gallery_of_three(client, storage) -> tuple[str, list[str], User]:
    """A project with three released, rendered photographs."""
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

    asset_ids = [await _upload(client, storage, project_id, seed) for seed in (3, 5, 7)]
    await client.post(f"/api/v1/projects/{project_id}/assets/release",
                      json={"asset_ids": asset_ids, "released": True})
    await _render(storage)
    return project_id, asset_ids, customer


@pytest.mark.anyio
async def test_sharing_one_photograph_shares_one_photograph(client, storage):
    """The bug, stated as a test."""
    project_id, asset_ids, _ = await _gallery_of_three(client, storage)

    made = await client.post(f"/api/v1/projects/{project_id}/shares",
                             json={"label": "Mum", "asset_ids": [asset_ids[1]]})
    assert made.status_code == 201, made.text
    assert made.json()["photograph_count"] == 1
    token = made.json()["url"].rsplit("/", 1)[-1]

    seen = await client.get(f"/api/v1/shared/{token}")
    assert seen.status_code == 200, seen.text
    shown = seen.json()["photographs"]
    assert [p["id"] for p in shown] == [asset_ids[1]], "only the chosen frame"


@pytest.mark.anyio
async def test_omitting_the_selection_still_shares_everything(client, storage):
    """What every link meant before there was a choice, and what the existing
    rows in the database mean. A new field must not change them."""
    project_id, asset_ids, _ = await _gallery_of_three(client, storage)

    made = await client.post(f"/api/v1/projects/{project_id}/shares", json={"label": "All"})
    assert made.status_code == 201, made.text
    assert made.json()["photograph_count"] is None, "null means the whole gallery"
    token = made.json()["url"].rsplit("/", 1)[-1]

    shown = (await client.get(f"/api/v1/shared/{token}")).json()["photographs"]
    assert len(shown) == 3


@pytest.mark.anyio
async def test_an_empty_selection_is_refused_rather_than_guessed_at(client, storage):
    """"None" and "all" differ by the entire gallery. Guessing either way is
    how somebody sends a wedding to a group chat believing they sent one
    photograph."""
    project_id, _, _ = await _gallery_of_three(client, storage)

    refused = await client.post(f"/api/v1/projects/{project_id}/shares",
                                json={"label": "Oops", "asset_ids": []})
    assert refused.status_code == 422, refused.text


@pytest.mark.anyio
async def test_an_unreleased_frame_cannot_be_named_in_a_link(client, storage):
    """The check that matters, because the picker is not where it can live.

    A blink, a test shot or a photograph being deliberately withheld is not
    something a public link may be minted for just because its id was typed
    into the request.
    """
    project_id, asset_ids, _ = await _gallery_of_three(client, storage)
    withheld = await _upload(client, storage, project_id, 11)
    await _render(storage)

    refused = await client.post(f"/api/v1/projects/{project_id}/shares",
                                json={"asset_ids": [asset_ids[0], withheld]})
    assert refused.status_code == 422, refused.text
    # Not echoed back: an id is not something the person chose or can read,
    # and repeating it confirms which ones exist.
    assert withheld not in refused.text


@pytest.mark.anyio
async def test_a_frame_from_another_project_cannot_be_smuggled_in(client, storage):
    project_id, asset_ids, customer = await _gallery_of_three(client, storage)

    other = await client.post("/api/v1/admin/projects", json={
        "title": "Someone Else", "customer_id": str(customer.id),
        "event_type": "Birthday", "location": "Leeds",
    })
    other_id = other.json()["id"]
    await client.post(f"/api/v1/admin/projects/{other_id}/stage", json={"stage": "booked"})
    stranger = await _upload(client, storage, other_id, 13)

    refused = await client.post(f"/api/v1/projects/{project_id}/shares",
                                json={"asset_ids": [stranger]})
    assert refused.status_code == 422, refused.text


@pytest.mark.anyio
async def test_the_unfurl_cover_comes_from_inside_the_link(client, storage):
    """A selective share must not advertise a photograph it does not contain.

    An unfurl puts the image into the chat thread and into the messaging
    app's own cache, so a cover taken from the gallery around the link would
    hand over a picture the link was never meant to carry.
    """
    project_id, asset_ids, _ = await _gallery_of_three(client, storage)
    made = await client.post(f"/api/v1/projects/{project_id}/shares",
                             json={"asset_ids": [asset_ids[2]]})
    token = made.json()["url"].rsplit("/", 1)[-1]

    cover = await client.get(f"/s/{token}/cover", follow_redirects=False)
    assert cover.status_code == 302, cover.text

    # The cover is the chosen frame's preview. Compared by the bytes behind
    # it, because the point is which photograph was handed over.
    shown = (await client.get(f"/api/v1/shared/{token}")).json()["photographs"]
    assert len(shown) == 1
    chosen_bytes = (await client.get(shown[0]["url"])).content
    cover_bytes = (await client.get(cover.headers["location"])).content
    assert cover_bytes == chosen_bytes

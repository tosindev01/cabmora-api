"""Choosing which photographs a client sees.

Withheld is the default, and that is the point: a shoot contains blinks, test
frames and shots the couple would hate. A system where everything is visible
until somebody remembers to hide it fails on the one occasion it matters.
"""

import hashlib

import pytest

from app.api import deps
from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"
PHOTO = bytes(range(256)) * 4_000
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
    resp = await client.post("/api/v1/auth/login",
                             json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _project_with_photo(client, storage) -> tuple[str, str, User, User]:
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
    return project_id, done.json()["id"], admin, customer


@pytest.mark.anyio
async def test_nothing_is_visible_to_a_client_until_it_is_released(client, storage):
    project_id, asset_id, admin, customer = await _project_with_photo(client, storage)

    seen = await client.get(f"/api/v1/projects/{project_id}/assets")
    assert seen.json()[0]["released"] is False, "withheld is the default"

    await _login(client, customer.email)
    theirs = await client.get(f"/api/v1/projects/{project_id}/assets")
    assert theirs.status_code == 200, theirs.text
    row = theirs.json()[0]
    assert row["url"] is None, "the client must not be handed a link"
    assert row["is_original"] is False


@pytest.mark.anyio
async def test_the_admin_always_sees_their_own_work(client, storage):
    """The watermark protects work from the client, not from whoever shot it."""
    project_id, asset_id, admin, customer = await _project_with_photo(client, storage)

    seen = await client.get(f"/api/v1/projects/{project_id}/assets")
    row = seen.json()[0]
    assert row["url"] is not None
    assert row["is_original"] is True


@pytest.mark.anyio
async def test_a_released_photo_still_waits_for_its_watermark(client, storage):
    """Releasing before renditions exist must not hand over the original."""
    project_id, asset_id, admin, customer = await _project_with_photo(client, storage)

    released = await client.post(f"/api/v1/projects/{project_id}/assets/release",
                                 json={"asset_ids": [asset_id], "released": True})
    assert released.status_code == 200, released.text
    assert released.json()[0]["released"] is True

    await _login(client, customer.email)
    row = (await client.get(f"/api/v1/projects/{project_id}/assets")).json()[0]
    assert row["url"] is None, (
        "renditions are pending — the only file is the unwatermarked original"
    )


@pytest.mark.anyio
async def test_a_photograph_can_be_taken_back(client, storage):
    """A shot shown by mistake has to be retractable, not permanent."""
    project_id, asset_id, admin, customer = await _project_with_photo(client, storage)

    await client.post(f"/api/v1/projects/{project_id}/assets/release",
                      json={"asset_ids": [asset_id], "released": True})
    undo = await client.post(f"/api/v1/projects/{project_id}/assets/release",
                             json={"asset_ids": [asset_id], "released": False})
    assert undo.status_code == 200, undo.text
    assert undo.json()[0]["released"] is False


@pytest.mark.anyio
async def test_a_client_cannot_release_their_own_photographs(client, storage):
    project_id, asset_id, admin, customer = await _project_with_photo(client, storage)
    await _login(client, customer.email)

    denied = await client.post(f"/api/v1/projects/{project_id}/assets/release",
                               json={"asset_ids": [asset_id], "released": True})
    assert denied.status_code == 403, denied.text


@pytest.mark.anyio
async def test_releasing_nothing_reports_it_rather_than_pretending(client, storage):
    """A console that thinks it released a photo it never touched is worse
    than an error, because nobody checks again."""
    from uuid import uuid4

    project_id, asset_id, admin, customer = await _project_with_photo(client, storage)
    resp = await client.post(f"/api/v1/projects/{project_id}/assets/release",
                             json={"asset_ids": [str(uuid4())], "released": True})
    assert resp.status_code == 404, resp.text

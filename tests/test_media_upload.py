"""Uploading a photograph, from asking permission to the file being recorded.

The two properties worth defending: a file already held is never sent twice,
and a file that did not arrive intact is never recorded as though it had.
"""

import hashlib

import pytest

from app.api import deps
from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"
PHOTO = bytes(range(256)) * 8_000          # ~2 MB, non-repeating
DIGEST = hashlib.sha256(PHOTO).hexdigest()


async def _make(email: str, role: UserRole) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(email=email, first_name="Test", last_name="Account",
                 hashed_password=hash_password(PASSWORD), role=role)
        )
        await session.commit()
        return user


async def _signed_in_admin(client) -> User:
    admin = await _make("uploader@example.com", UserRole.ADMIN)
    resp = await client.post(
        "/api/v1/auth/login", json={"email": admin.email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return admin


async def _project(client, customer_email: str = "client@example.com") -> str:
    customer = await _make(customer_email, UserRole.CUSTOMER)
    resp = await client.post("/api/v1/admin/projects", json={
        "title": "Okafor Wedding", "customer_id": str(customer.id),
        "event_type": "Wedding", "location": "Manchester",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _body(**overrides) -> dict:
    return {
        "content_hash": DIGEST, "filename": "IMG_2856.jpg",
        "content_type": "image/jpeg", "byte_size": len(PHOTO), **overrides,
    }


async def _upload(client, project_id: str, storage, **overrides) -> dict:
    """The whole dance: ask, push the parts, confirm.

    `overrides` go to `_body`, so a test can send a video without repeating
    the three-step upload. The bytes are the same either way — nothing in the
    pipeline decodes them except the rendition step, which a video skips.
    """
    ask = await client.post(
        f"/api/v1/projects/{project_id}/uploads", json=_body(**overrides)
    )
    assert ask.status_code == 200, ask.text
    ticket = ask.json()["ticket"]
    assert ticket is not None, "new bytes must produce a ticket"

    etags = [
        storage.write_part(
            upload_id=ticket["upload_id"], part=n,
            data=PHOTO[(n - 1) * ticket["part_size"] : n * ticket["part_size"]],
        )
        for n in range(1, len(ticket["part_urls"]) + 1)
    ]
    done = await client.post(
        f"/api/v1/projects/{project_id}/uploads/confirm",
        json=_body(upload_id=ticket["upload_id"], etags=etags, **overrides),
    )
    assert done.status_code == 201, done.text
    return done.json()


@pytest.fixture
def storage(tmp_path):
    """Point the API at a throwaway directory instead of the real bucket.

    Through `dependency_overrides`, not monkeypatch: FastAPI resolves
    `Depends(get_media_storage)` when the route is defined, so replacing the
    module attribute afterwards changes nothing — the app would quietly keep
    using the real one, and the test would be writing parts somewhere the API
    never looks.
    """
    from app.infrastructure.storage.local_media_storage import LocalMediaStorage
    from app.main import app

    # The same relative base the composition root uses, so the URLs these
    # tests exercise are the ones a browser is really handed.
    disk = LocalMediaStorage(
        root=tmp_path, secret="test-secret", base_url="/api/v1"
    )
    app.dependency_overrides[deps.get_media_storage] = lambda: disk
    yield disk
    app.dependency_overrides.pop(deps.get_media_storage, None)


@pytest.mark.anyio
async def test_a_photograph_is_recorded_once_it_really_exists(client, storage):
    await _signed_in_admin(client)
    project_id = await _project(client)

    asset = await _upload(client, project_id, storage)
    assert asset["content_hash"] == DIGEST
    assert asset["filename"] == "IMG_2856.jpg"
    assert asset["renditions_ready"] is False, (
        "an original is not viewable until its watermarked preview exists"
    )


@pytest.mark.anyio
async def test_the_same_photograph_is_never_uploaded_twice(client, storage):
    """The payoff of hashing before sending: the second one is instant."""
    await _signed_in_admin(client)
    first = await _project(client)
    await _upload(client, first, storage)

    second = await _project(client, "second-client@example.com")
    again = await client.post(f"/api/v1/projects/{second}/uploads", json=_body())
    assert again.status_code == 200, again.text
    body = again.json()
    assert body["ticket"] is None, "nothing to upload — we already hold these bytes"
    assert body["asset"] is not None, "but the new project has its own asset"
    assert body["asset"]["project_id"] == second


@pytest.mark.anyio
async def test_a_file_that_did_not_arrive_is_not_recorded(client, storage):
    """Confirming an upload that never happened must not create an asset."""
    await _signed_in_admin(client)
    project_id = await _project(client)

    ask = await client.post(f"/api/v1/projects/{project_id}/uploads", json=_body())
    ticket = ask.json()["ticket"]
    storage.write_part(upload_id=ticket["upload_id"], part=1, data=b"truncated")

    done = await client.post(
        f"/api/v1/projects/{project_id}/uploads/confirm",
        json=_body(upload_id=ticket["upload_id"], etags=["only-one"]),
    )
    assert done.status_code == 422, done.text
    assert "did not arrive intact" in done.text


@pytest.mark.anyio
async def test_a_customer_cannot_upload_to_their_own_project(client, storage):
    """Reviewing work is the customer's role here; delivering it is not."""
    await _signed_in_admin(client)
    project_id = await _project(client)

    await client.post("/api/v1/auth/logout")
    await client.post("/api/v1/auth/login", json={
        "email": "client@example.com", "password": PASSWORD,
    })
    denied = await client.post(f"/api/v1/projects/{project_id}/uploads", json=_body())
    assert denied.status_code == 403, denied.text


@pytest.mark.anyio
async def test_video_is_accepted(client, storage):
    """Video was refused outright because nothing could play it back.

    That is true of a camera-native master and false of the delivered film,
    which is usually already H.264. Refusing both to be safe about one meant a
    videography studio could not upload its own work.
    """
    await _signed_in_admin(client)
    project_id = await _project(client)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/uploads",
        json=_body(content_type="video/mp4"),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["ticket"] is not None


@pytest.mark.anyio
async def test_something_that_is_neither_a_photograph_nor_a_video_is_refused(
    client, storage
):
    await _signed_in_admin(client)
    project_id = await _project(client)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/uploads",
        json=_body(content_type="application/pdf"),
    )
    assert resp.status_code == 422
    assert "nothing we could show a client" in resp.text


@pytest.mark.anyio
async def test_a_video_gets_no_renditions_and_is_still_viewable(client, storage):
    """A video has no watermarked copy to make, and must not wait for one.

    The image library cannot decode it, so every attempt would fail until the
    asset was abandoned — and `storage.read` would pull the whole film into
    the process to find that out. It is marked ready without either.
    """
    await _signed_in_admin(client)
    project_id = await _project(client)

    asset = await _upload(
        client, project_id, storage,
        content_type="video/mp4", filename="wedding-film.mp4",
    )

    assert asset["kind"] == "original"

    # Read from the listing, not from the confirm response: renditions run as
    # a background task after that response is built, so it says False for a
    # photograph too.
    listed = (await client.get(f"/api/v1/projects/{project_id}/assets")).json()
    row = next(a for a in listed if a["id"] == asset["id"])
    assert row["renditions_ready"] is True, (
        "a video has no rendition to wait for — left pending it would sit in a "
        "queue that can never produce anything"
    )
    assert row["preview_pending"] is False
    # Told what it is, so the gallery draws a player rather than a broken image.
    assert row["content_type"] == "video/mp4"


@pytest.mark.anyio
async def test_the_browser_can_actually_reach_the_upload_url(client, storage):
    """The signed URL must lead somewhere.

    Every other test here writes parts through the storage object directly,
    which is why a missing route went unnoticed until a real browser tried it
    and got "Failed to fetch". This one uses the URL exactly as handed out.
    """
    await _signed_in_admin(client)
    project_id = await _project(client)

    ask = await client.post(f"/api/v1/projects/{project_id}/uploads", json=_body())
    ticket = ask.json()["ticket"]

    etags = []
    for n, url in enumerate(ticket["part_urls"], start=1):
        assert url.startswith("/api/v1/media/"), (
            "the URL must be relative, or it points at one console and breaks the other"
        )
        chunk = PHOTO[(n - 1) * ticket["part_size"] : n * ticket["part_size"]]
        put = await client.put(url, content=chunk)
        assert put.status_code == 200, put.text
        assert "ETag" in put.headers, "without this the upload can never be assembled"
        etags.append(put.headers["ETag"])

    done = await client.post(
        f"/api/v1/projects/{project_id}/uploads/confirm",
        json=_body(upload_id=ticket["upload_id"], etags=etags),
    )
    assert done.status_code == 201, done.text


@pytest.mark.anyio
async def test_a_tampered_upload_url_is_refused(client, storage):
    """The signature is the authorisation — editing the part number must fail."""
    await _signed_in_admin(client)
    project_id = await _project(client)

    ask = await client.post(f"/api/v1/projects/{project_id}/uploads", json=_body())
    url = ask.json()["ticket"]["part_urls"][0]

    tampered = url.replace("/1?", "/2?", 1)
    resp = await client.put(tampered, content=b"not mine")
    assert resp.status_code == 403, resp.text


@pytest.mark.anyio
async def test_a_bucket_failure_is_named_rather_than_swallowed(client, storage):
    """An upload the store will not finish must say so.

    Unguarded, this reached the catch-all handler and came back as "Something
    went wrong. Please try again." — a sentence that is true of every failure
    in the system, so it sent people to check their file when the bucket was
    the problem. It is the same misdirection as a download error that only
    ever said the link had expired.
    """
    await _signed_in_admin(client)
    project_id = await _project(client)
    ask = await client.post(f"/api/v1/projects/{project_id}/uploads", json=_body())
    ticket = ask.json()["ticket"]
    etags = [
        storage.write_part(
            upload_id=ticket["upload_id"], part=n,
            data=PHOTO[(n - 1) * ticket["part_size"] : n * ticket["part_size"]],
        )
        for n in range(1, len(ticket["part_urls"]) + 1)
    ]

    async def _refuse(**_: object) -> None:
        raise RuntimeError("the bucket said no")

    storage.complete_upload = _refuse  # type: ignore[method-assign]

    refused = await client.post(
        f"/api/v1/projects/{project_id}/uploads/confirm",
        json=_body(upload_id=ticket["upload_id"], etags=etags),
    )

    assert refused.status_code == 502, refused.text
    detail = refused.json()["detail"]
    assert "Something went wrong" not in detail
    assert "Storage would not finish" in detail

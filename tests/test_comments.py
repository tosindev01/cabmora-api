"""Feedback, and who is allowed to close it.

The rule worth defending: a client may ask for a change, but only the team may
mark it done. Otherwise the outstanding count — which an admin uses to decide
whether work can move on — means nothing.
"""

import pytest

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"


async def _make(email: str, role: UserRole) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(email=email, first_name="Test", last_name="Person",
                 hashed_password=hash_password(PASSWORD), role=role)
        )
        await session.commit()
        return user


async def _login(client, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


async def _setup(client) -> tuple[str, User, User]:
    admin = await _make("admin@example.com", UserRole.ADMIN)
    customer = await _make("customer@example.com", UserRole.CUSTOMER)
    await _login(client, admin.email)
    made = await client.post("/api/v1/admin/projects", json={
        "title": "Okafor Wedding", "customer_id": str(customer.id),
        "event_type": "Wedding", "location": "Manchester",
    })
    assert made.status_code == 201, made.text
    project_id = made.json()["id"]
    # Moved off draft because the rest of this fixture is about a project
    # under way, not because the client could not otherwise see it — they can.
    # `booked` is the only legal next stage.
    moved = await client.post(
        f"/api/v1/admin/projects/{project_id}/stage", json={"stage": "booked"}
    )
    assert moved.status_code == 200, moved.text
    return project_id, admin, customer


@pytest.mark.anyio
async def test_a_client_can_ask_for_a_change(client):
    project_id, admin, customer = await _setup(client)
    await _login(client, customer.email)

    resp = await client.post(f"/api/v1/projects/{project_id}/comments", json={
        "body": "Could we brighten the ceremony shots?", "kind": "amendment",
    })
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["needs_action"] is True, "an amendment is owed an answer"
    assert body["author_name"] == "Test Person"


@pytest.mark.anyio
async def test_a_remark_is_not_outstanding_work(client):
    """Marking a compliment as owed would make the count meaningless."""
    project_id, admin, customer = await _setup(client)
    await _login(client, customer.email)

    resp = await client.post(f"/api/v1/projects/{project_id}/comments", json={
        "body": "These are beautiful, thank you.",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["needs_action"] is False


@pytest.mark.anyio
async def test_a_client_cannot_close_their_own_request(client):
    """Otherwise work moves on without anybody having done it."""
    project_id, admin, customer = await _setup(client)
    await _login(client, customer.email)
    made = await client.post(f"/api/v1/projects/{project_id}/comments", json={
        "body": "Please remove the exit sign.", "kind": "amendment",
    })
    comment_id = made.json()["id"]

    denied = await client.post(f"/api/v1/comments/{comment_id}/resolve")
    assert denied.status_code == 403, denied.text

    await _login(client, admin.email)
    allowed = await client.post(f"/api/v1/comments/{comment_id}/resolve")
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["resolved"] is True
    assert allowed.json()["needs_action"] is False


@pytest.mark.anyio
async def test_a_stranger_cannot_read_the_conversation(client):
    project_id, admin, customer = await _setup(client)
    outsider = await _make("outsider@example.com", UserRole.CUSTOMER)
    await _login(client, outsider.email)

    resp = await client.get(f"/api/v1/projects/{project_id}/comments")
    assert resp.status_code == 403, resp.text


@pytest.mark.anyio
async def test_feedback_cannot_be_pinned_to_another_project_photo(client):
    """Without this check a comment could surface in somebody else's thread."""
    project_id, admin, customer = await _setup(client)
    await _login(client, admin.email)

    from uuid import uuid4

    resp = await client.post(f"/api/v1/projects/{project_id}/comments", json={
        "body": "About this one.", "asset_id": str(uuid4()),
    })
    assert resp.status_code == 404, resp.text

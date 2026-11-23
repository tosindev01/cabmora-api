"""Lead management: the pipeline, notes, consultations and conversion."""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"
ENQUIRY = {
    "first_name": "Mary Jane", "last_name": "Watson",
    "email": "mj@example.com",
    "event_type": "Wedding",
    "message": "Looking for a photographer for October.",
    "phone": "07000 000000",
}


async def _make(email: str, role: UserRole) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=email, first_name=role.value.title(), last_name="Account",
                hashed_password=hash_password(PASSWORD), role=role,
            )
        )
        await session.commit()
        return user


async def _login(client, email: str) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _submit(client) -> str:
    resp = await client.post("/api/v1/enquiries", json=ENQUIRY)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# --- intake ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_public_enquiry_starts_new_with_a_received_event(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    detail = (await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")).json()
    assert detail["status"] == "new"
    assert [e["kind"] for e in detail["events"]] == ["received"]
    # Nobody on staff submitted it.
    assert detail["events"][0]["actor_id"] is None


@pytest.mark.asyncio
async def test_the_pipeline_is_admin_only(client):
    enquiry_id = await _submit(client)
    assert (await client.get("/api/v1/admin/enquiries")).status_code == 401

    customer = await _make("cust@x.com", UserRole.CUSTOMER)
    await _login(client, customer.email)
    assert (await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")).status_code == 403


# --- pipeline -------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_moves_are_recorded_and_bounded(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    ok = await client.patch(
        f"/api/v1/admin/enquiries/{enquiry_id}", json={"status": "contacted"}
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "contacted"

    # new -> quoted skips the middle of the pipeline.
    bad = await client.patch(
        f"/api/v1/admin/enquiries/{enquiry_id}", json={"status": "new"}
    )
    assert bad.status_code == 422
    assert isinstance(bad.json()["detail"], str)


@pytest.mark.asyncio
async def test_won_cannot_be_set_by_patch(client):
    """Winning creates a project; a status flip would mark it won with nothing
    behind it."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    resp = await client.patch(
        f"/api/v1/admin/enquiries/{enquiry_id}", json={"status": "won"}
    )
    assert resp.status_code == 422
    assert "convert" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_a_lead_can_be_lost_from_any_live_stage(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    resp = await client.patch(
        f"/api/v1/admin/enquiries/{enquiry_id}", json={"status": "lost"}
    )
    assert resp.status_code == 200
    # Leads come back.
    assert "contacted" in resp.json()["allowed_next_statuses"]


@pytest.mark.asyncio
async def test_assignment_is_recorded(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    other = await _make("other@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    resp = await client.patch(
        f"/api/v1/admin/enquiries/{enquiry_id}", json={"assigned_to": str(other.id)}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["assigned_to_name"] == "Admin Account"

    detail = (await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")).json()
    assert "assigned" in [e["kind"] for e in detail["events"]]


@pytest.mark.asyncio
async def test_a_reversed_budget_range_is_refused(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    resp = await client.patch(
        f"/api/v1/admin/enquiries/{enquiry_id}",
        json={"budget_min_minor": 900000, "budget_max_minor": 500000},
    )
    assert resp.status_code == 422


# --- notes and consultations ----------------------------------------------


@pytest.mark.asyncio
async def test_notes_accumulate_rather_than_overwrite(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    for body in ("Called, no answer.", "Wants the Saturday slot."):
        resp = await client.post(
            f"/api/v1/admin/enquiries/{enquiry_id}/notes", json={"body": body}
        )
        assert resp.status_code == 201, resp.text

    detail = (await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")).json()
    notes = [e for e in detail["events"] if e["kind"] == "note_added"]
    assert [n["payload"]["body"] for n in notes] == [
        "Called, no answer.",
        "Wants the Saturday slot.",
    ]


@pytest.mark.asyncio
async def test_booking_a_consultation_advances_the_lead(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)
    await client.patch(f"/api/v1/admin/enquiries/{enquiry_id}", json={"status": "contacted"})

    when = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    resp = await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/consultations",
        json={"scheduled_at": when, "meeting_url": "https://meet.google.com/abc-defg-hij"},
    )
    assert resp.status_code == 201, resp.text
    # The manual scheduler passes the link through rather than inventing one.
    assert resp.json()["provider"] == "manual"
    assert resp.json()["meeting_url"].endswith("abc-defg-hij")

    detail = (await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")).json()
    assert detail["status"] == "consultation_booked"
    assert len(detail["consultations"]) == 1


@pytest.mark.asyncio
async def test_a_consultation_without_a_link_is_still_booked(client):
    """The manual backend does not fabricate a URL."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    resp = await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/consultations", json={"scheduled_at": when}
    )
    assert resp.status_code == 201
    assert resp.json()["meeting_url"] is None


# --- conversion -----------------------------------------------------------


@pytest.mark.asyncio
async def test_converting_creates_the_project_the_account_and_the_links(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    resp = await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/convert",
        json={
            "first_name": "Mary Jane", "last_name": "Watson",
            "title": "Watson Wedding",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["invite_url"] and "token=" in body["invite_url"]

    detail = (await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")).json()
    assert detail["status"] == "won"
    assert detail["converted_project_id"] == body["project_id"]
    assert detail["customer_id"] == body["customer_id"]
    # Terminal: a project exists downstream.
    assert detail["allowed_next_statuses"] == []

    project = (await client.get(f"/api/v1/admin/projects/{body['project_id']}")).json()
    assert project["title"] == "Watson Wedding"
    assert project["customer_name"] == "Mary Jane Watson"

    # Booked, not draft. The enquiry was won — somebody has agreed to the
    # work — so the project starts where the work starts, and the progress
    # bar reads as something begun rather than 0%. A draft is for a project
    # being set up, which this is not.
    assert project["stage"] == "booked"
    assert project["progress"] > 0, "a won enquiry must not read as nothing done"


@pytest.mark.asyncio
async def test_converting_reuses_an_existing_account(client):
    """A returning client must not become a duplicate person."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    existing = await _make(ENQUIRY["email"], UserRole.CUSTOMER)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    resp = await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/convert",
        json={"first_name": "Mary Jane", "last_name": "Watson", "title": "Second Shoot"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["customer_id"] == str(existing.id)
    # No new account, so no invite.
    assert resp.json()["invite_url"] is None


@pytest.mark.asyncio
async def test_an_enquiry_cannot_be_converted_twice(client):
    admin = await _make("admin@x.com", UserRole.ADMIN)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)
    payload = {"first_name": "Mary Jane", "last_name": "Watson", "title": "Wedding"}

    assert (
        await client.post(f"/api/v1/admin/enquiries/{enquiry_id}/convert", json=payload)
    ).status_code == 201
    second = await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/convert", json=payload
    )
    assert second.status_code == 422
    assert "already been converted" in second.json()["detail"]


@pytest.mark.asyncio
async def test_converting_a_staff_email_still_creates_the_project(client):
    """An email collision with a creator must not block real work — but the
    project must not land in a staff portal either."""
    admin = await _make("admin@x.com", UserRole.ADMIN)
    await _make(ENQUIRY["email"], UserRole.CREATOR)
    enquiry_id = await _submit(client)
    await _login(client, admin.email)

    resp = await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/convert",
        json={"first_name": "Mary Jane", "last_name": "Watson", "title": "Wedding"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["customer_id"] is None
    assert "creator account" in body["warning"]

    project = (await client.get(f"/api/v1/admin/projects/{body['project_id']}")).json()
    assert project["customer_id"] is None
    # And the reason is in the trail, not just in one HTTP response.
    detail = (await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")).json()
    won = [e for e in detail["events"] if e["kind"] == "won"][0]
    assert "warning" in won["payload"]

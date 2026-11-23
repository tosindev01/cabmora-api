"""Availability and clash detection.

The rule that matters: two consultations must never share a minute, and it has
to hold at the API, not only in the grid an admin is looking at.
"""

from datetime import datetime, timedelta, timezone

from app.core.display import DISPLAY_TZ

import pytest

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"
SLOT = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)


async def _admin() -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(email="admin@x.com", first_name="A", last_name="B",
                 hashed_password=hash_password(PASSWORD), role=UserRole.ADMIN)
        )
        await session.commit()
        return user


async def _login(client, email: str) -> None:
    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text


async def _enquiry(client, email="c@x.com", first="Jane", last="Doe") -> str:
    resp = await client.post("/api/v1/enquiries", json={
        "first_name": first, "last_name": last, "email": email, "event_type": "Wedding",
        "message": "Interested in a full day.",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _book(client, enquiry_id: str, at: datetime, minutes: int = 30):
    return await client.post(
        f"/api/v1/admin/enquiries/{enquiry_id}/consultations",
        json={"scheduled_at": at.isoformat(), "duration_minutes": minutes},
    )


# --- clash detection -------------------------------------------------------
@pytest.mark.anyio
async def test_an_overlapping_booking_is_refused(client):
    admin = await _admin()
    await _login(client, admin.email)
    first, second = await _enquiry(client), await _enquiry(client, "d@x.com", "John", "Roe")

    assert (await _book(client, first, SLOT)).status_code == 201

    clash = await _book(client, second, SLOT + timedelta(minutes=10))
    assert clash.status_code == 422, clash.text
    detail = clash.json()["detail"]
    assert isinstance(detail, str)
    # Derived, not hardcoded: the admin books in local time, so the refusal has
    # to name the slot in local time too. Writing "10:00" here once hid a bug
    # where a 12:00 booking was refused for clashing with "11:00 UTC", and a
    # hardcoded hour would start lying again the day the clocks go back.
    expected = SLOT.astimezone(DISPLAY_TZ).strftime("%H:%M")
    assert expected in detail, "the admin must be told which slot it clashes with"
    assert "UTC" not in detail, "the refusal must not mix clocks with the grid"


@pytest.mark.anyio
async def test_back_to_back_bookings_are_allowed(client):
    """A day of consecutive slots is the normal way to book, not a clash."""
    admin = await _admin()
    await _login(client, admin.email)
    first, second = await _enquiry(client), await _enquiry(client, "d@x.com")

    assert (await _book(client, first, SLOT, 30)).status_code == 201
    assert (await _book(client, second, SLOT + timedelta(minutes=30), 30)).status_code == 201


@pytest.mark.anyio
async def test_a_longer_call_still_blocks_a_later_start(client):
    """The clash window must reach back past `scheduled_at`."""
    admin = await _admin()
    await _login(client, admin.email)
    first, second = await _enquiry(client), await _enquiry(client, "d@x.com")

    assert (await _book(client, first, SLOT, 120)).status_code == 201
    late = await _book(client, second, SLOT + timedelta(minutes=90), 30)
    assert late.status_code == 422, "a two-hour call occupies 10:00-12:00"


@pytest.mark.anyio
async def test_a_zero_length_consultation_is_refused(client):
    admin = await _admin()
    await _login(client, admin.email)
    enquiry = await _enquiry(client)
    assert (await _book(client, enquiry, SLOT, 0)).status_code == 422


# --- availability ----------------------------------------------------------
@pytest.mark.anyio
async def test_availability_reports_who_each_slot_is_with(client):
    admin = await _admin()
    await _login(client, admin.email)
    enquiry = await _enquiry(client, "jane@x.com")
    await _book(client, enquiry, SLOT, 45)

    day = SLOT.replace(hour=0)
    resp = await client.get("/api/v1/admin/enquiries/availability", params={
        "start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat(),
    })
    assert resp.status_code == 200, resp.text
    booked = resp.json()["booked"]
    assert len(booked) == 1
    slot = booked[0]
    assert slot["client_name"] == "Jane Doe"
    assert slot["event_type"] == "Wedding"
    assert slot["duration_minutes"] == 45
    # ends_at is computed server-side so the grid cannot disagree with the rule.
    assert slot["ends_at"] > slot["starts_at"]


@pytest.mark.anyio
async def test_a_call_starting_before_the_window_still_shows(client):
    """Filtering on scheduled_at alone would hide it and offer a taken slot."""
    admin = await _admin()
    await _login(client, admin.email)
    enquiry = await _enquiry(client)
    # 23:30 the night before, running 60 minutes into the day being viewed.
    await _book(client, enquiry, SLOT.replace(hour=23, minute=30) - timedelta(days=1), 60)

    day = SLOT.replace(hour=0)
    resp = await client.get("/api/v1/admin/enquiries/availability", params={
        "start": day.isoformat(), "end": (day + timedelta(days=1)).isoformat(),
    })
    assert len(resp.json()["booked"]) == 1, "a call spanning midnight occupies both days"


@pytest.mark.anyio
async def test_an_absurd_window_is_refused(client):
    admin = await _admin()
    await _login(client, admin.email)
    resp = await client.get("/api/v1/admin/enquiries/availability", params={
        "start": SLOT.isoformat(), "end": (SLOT + timedelta(days=400)).isoformat(),
    })
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_a_customer_cannot_read_the_calendar(client):
    admin = await _admin()
    await _login(client, admin.email)
    async with SessionFactory() as session:
        await SqlAlchemyUserRepository(session).add(
            User(email="cust@x.com", first_name="C", last_name="D",
                 hashed_password=hash_password(PASSWORD), role=UserRole.CUSTOMER)
        )
        await session.commit()

    await _login(client, "cust@x.com")
    resp = await client.get("/api/v1/admin/enquiries/availability", params={
        "start": SLOT.isoformat(), "end": (SLOT + timedelta(days=1)).isoformat(),
    })
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_a_calendar_failure_is_named_rather_than_swallowed(client, monkeypatch):
    """An admin told "something went wrong" clicks the same button again.

    The scheduler raises rather than falling back, deliberately — a confirmed
    call with no diary entry is worse. But unguarded that reached the catch-all
    handler, so an expired token and a disabled Meet looked identical to a
    transient blip.
    """
    from app.api import deps
    from app.domain.services.meeting_scheduler import MeetingScheduler
    from app.main import app

    class _Broken(MeetingScheduler):
        async def schedule(self, **_: object):
            raise RuntimeError("Meet is not enabled for this Google account")

    admin = await _admin()
    await _login(client, admin.email)
    # A slot the *client* asked for on the website, so it is REQUESTED and
    # there is something to confirm. An admin booking one directly is already
    # confirmed, which is a different path.
    asked = await client.post("/api/v1/enquiries", json={
        "first_name": "Jane", "last_name": "Doe", "email": "booking@x.com",
        "event_type": "Wedding", "message": "Could we talk?",
        "preferred_slot": SLOT.isoformat(),
    })
    assert asked.status_code == 201, asked.text
    enquiry_id = asked.json()["id"]

    detail = await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")
    consultation_id = detail.json()["consultations"][0]["id"]

    app.dependency_overrides[deps.get_meeting_scheduler] = lambda: _Broken()
    try:
        refused = await client.post(
            f"/api/v1/admin/enquiries/{enquiry_id}"
            f"/consultations/{consultation_id}/confirm",
            json={},
        )
    finally:
        app.dependency_overrides.pop(deps.get_meeting_scheduler, None)

    assert refused.status_code == 502, refused.text
    detail = refused.json()["detail"]
    assert "Something went wrong" not in detail
    assert "nothing has been confirmed" in detail


@pytest.mark.anyio
async def test_confirm_succeeds_when_the_calendar_is_not_google(client):
    """Everything except Google: the request, the state change, the record.

    Pinned because the whole flow was being judged by one 500. With the
    manual scheduler — which is what MEETING_BACKEND=manual selects — a
    client's requested slot confirms normally, which places the fault
    squarely on the calendar integration rather than on bookings.
    """
    from app.domain.services.meeting_scheduler import ManualScheduler

    admin = await _admin()
    await _login(client, admin.email)

    asked = await client.post("/api/v1/enquiries", json={
        "first_name": "Jane", "last_name": "Doe", "email": "booker@x.com",
        "event_type": "Wedding", "message": "Could we talk?",
        "preferred_slot": SLOT.isoformat(),
    })
    assert asked.status_code == 201, asked.text
    enquiry_id = asked.json()["id"]
    detail = await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")
    consultation_id = detail.json()["consultations"][0]["id"]

    from app.api import deps
    from app.main import app

    app.dependency_overrides[deps.get_meeting_scheduler] = lambda: ManualScheduler()
    try:
        done = await client.post(
            f"/api/v1/admin/enquiries/{enquiry_id}"
            f"/consultations/{consultation_id}/confirm",
            json={"meeting_url": "https://meet.example/abc"},
        )
    finally:
        app.dependency_overrides.pop(deps.get_meeting_scheduler, None)

    assert done.status_code == 200, done.text
    assert done.json()["status"] == "confirmed"


@pytest.mark.anyio
async def test_a_month_spanning_a_clock_change_is_still_offered(client):
    """October in London is 31 days and an hour.

    The picker asks for local midnight to local midnight, so in a timezone
    that puts its clocks back mid-month that span exceeds a flat 31-day
    limit by one hour. Every UK visitor was refused the whole month and
    shown an empty calendar, while a visitor an hour east saw it normally.
    """
    from zoneinfo import ZoneInfo

    london = ZoneInfo("Europe/London")
    utc = ZoneInfo("UTC")
    start = datetime(2026, 10, 1, tzinfo=london)
    end = datetime(2026, 11, 1, tzinfo=london)
    # Converted first: subtracting two datetimes in the same zone gives the
    # wall-clock difference and hides the very hour this is about.
    assert end.astimezone(utc) - start.astimezone(utc) == timedelta(days=31, hours=1)

    resp = await client.get(
        "/api/v1/enquiries/availability",
        params={"start": start.isoformat(), "end": end.isoformat()},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
async def test_a_dead_calendar_does_not_block_a_booking_when_a_link_is_given(client):
    """The admin's own link gets the call confirmed anyway.

    Falling back silently would be wrong — somebody would believe in a diary
    entry nobody made. Falling back to a link the administrator typed is not
    silent: they know there is no calendar entry, because they made the link.
    """
    from app.api import deps
    from app.domain.services.meeting_scheduler import (
        MeetingScheduler,
        SchedulerAuthExpired,
    )
    from app.main import app

    class _Lapsed(MeetingScheduler):
        async def schedule(self, **_: object):
            raise SchedulerAuthExpired("the saved sign-in is no longer accepted")

    admin = await _admin()
    await _login(client, admin.email)
    asked = await client.post("/api/v1/enquiries", json={
        "first_name": "Jane", "last_name": "Doe", "email": "fallback@x.com",
        "event_type": "Wedding", "message": "Could we talk?",
        "preferred_slot": SLOT.isoformat(),
    })
    enquiry_id = asked.json()["id"]
    detail = await client.get(f"/api/v1/admin/enquiries/{enquiry_id}")
    consultation_id = detail.json()["consultations"][0]["id"]

    app.dependency_overrides[deps.get_meeting_scheduler] = lambda: _Lapsed()
    try:
        url = f"/api/v1/admin/enquiries/{enquiry_id}/consultations/{consultation_id}/confirm"

        # Without a link there is nothing to fall back to, and the refusal
        # has to say that pasting one is the way past it.
        refused = await client.post(url, json={})
        assert refused.status_code == 502, refused.text
        assert "meeting link" in refused.json()["detail"]

        done = await client.post(url, json={"meeting_url": "https://meet.example/abc"})
    finally:
        app.dependency_overrides.pop(deps.get_meeting_scheduler, None)

    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "confirmed"
    assert body["meeting_url"] == "https://meet.example/abc"

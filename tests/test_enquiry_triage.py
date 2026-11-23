"""Triage: open leads, soonest event first, banded by how close the event is.

Two things here are easy to get wrong and silent when they are:

· **Where undated leads sort.** `event_date` is nullable, Postgres sorts NULLs
  last on ASC and SQLite sorts them first. Left to the default, every enquiry
  with no date would head the urgency table on a developer's machine and tail it
  in production — the same code reading as two different features.
· **What counts as open.** A queue padded with won and lost leads stops being
  read, and the whole point of the table is that somebody reads it.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.application.use_cases.enquiries.triage_enquiries import (
    NEEDS_CHASING_WITHIN,
    UNANSWERED_FOR,
    UrgencyBand,
    band_for,
)
from app.core.security import hash_password
from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.enquiry_repository_impl import (
    SqlAlchemyEnquiryRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"
NOW = datetime.now(timezone.utc)


async def _staff(email: str) -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=email,
                first_name="Triage",
                last_name="Admin",
                hashed_password=hash_password(PASSWORD),
                role=UserRole.ADMIN,
            )
        )
        await session.commit()
        return user


async def _lead(
    name: str,
    *,
    days: int | None,
    status: EnquiryStatus = EnquiryStatus.NEW,
    arrived_days_ago: int = 0,
) -> Enquiry:
    async with SessionFactory() as session:
        enquiry = Enquiry(
            first_name=name,
            last_name="Lead",
            email=f"{name.lower()}@example.com",
            event_type="Wedding",
            message="Please quote.",
            event_date=None if days is None else NOW + timedelta(days=days),
            status=status,
            created_at=NOW - timedelta(days=arrived_days_ago),
        )
        # The RECEIVED event goes in with it — `add` takes both in one commit,
        # because an enquiry with no received event is a hole in the audit trail.
        saved = await SqlAlchemyEnquiryRepository(session).add(
            enquiry,
            EnquiryEvent(enquiry_id=enquiry.id, kind=EnquiryEventKind.RECEIVED),
        )
        await session.commit()
        return saved


async def _login(client, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


# ── the banding, as a pure function ──────────────────────────────────────
@pytest.mark.parametrize(
    "offset,expected",
    [
        (-30, UrgencyBand.PASSED),
        (-1, UrgencyBand.PASSED),
        (0, UrgencyBand.THIS_WEEK),
        (7, UrgencyBand.THIS_WEEK),
        (8, UrgencyBand.THIS_MONTH),
        (30, UrgencyBand.THIS_MONTH),
        (31, UrgencyBand.THIS_QUARTER),
        (90, UrgencyBand.THIS_QUARTER),
        (91, UrgencyBand.LATER),
    ],
)
def test_every_band_boundary(offset: int, expected: UrgencyBand):
    today = date(2026, 6, 15)
    band, days = band_for(today + timedelta(days=offset), today=today)
    assert band is expected
    assert days == offset


def test_no_date_is_undated_and_not_later():
    """`UNDATED` is its own band. Folding it into `LATER` would assert that an
    enquiry we know nothing about is far away, which we do not know."""
    band, days = band_for(None, today=date(2026, 6, 15))
    assert band is UrgencyBand.UNDATED
    assert days is None


# ── the ordering ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_soonest_event_first_and_undated_last(client):
    await _staff("triage1@example.com")
    await _lead("Faraway", days=200)
    await _lead("Nodate", days=None)
    await _lead("Soon", days=3)
    await _lead("Gone", days=-5)

    await _login(client, "triage1@example.com")
    body = (await client.get("/api/v1/admin/enquiries/triage")).json()

    assert [row["full_name"] for row in body["items"]] == [
        "Gone Lead",      # already happened — a miss, and first
        "Soon Lead",
        "Faraway Lead",
        "Nodate Lead",    # last, never first
    ]
    assert [row["band"] for row in body["items"]] == [
        "passed",
        "this_week",
        "later",
        "undated",
    ]


@pytest.mark.asyncio
async def test_won_and_lost_are_not_in_the_queue(client):
    await _staff("triage2@example.com")
    await _lead("Openone", days=10)
    await _lead("Wonone", days=5, status=EnquiryStatus.WON)
    await _lead("Lostone", days=2, status=EnquiryStatus.LOST)

    await _login(client, "triage2@example.com")
    body = (await client.get("/api/v1/admin/enquiries/triage")).json()

    assert [row["full_name"] for row in body["items"]] == ["Openone Lead"]
    # The count has to agree with the filter, or the footer tells a reader
    # there are rows the table is refusing to show.
    assert body["open_total"] == 1


@pytest.mark.asyncio
async def test_every_open_status_is_included(client):
    await _staff("triage3@example.com")
    for index, status in enumerate(
        [
            EnquiryStatus.NEW,
            EnquiryStatus.CONTACTED,
            EnquiryStatus.CONSULTATION_BOOKED,
            EnquiryStatus.QUOTED,
        ]
    ):
        await _lead(f"Open{index}", days=index + 1, status=status)

    await _login(client, "triage3@example.com")
    body = (await client.get("/api/v1/admin/enquiries/triage")).json()
    assert body["open_total"] == 4
    assert len(body["items"]) == 4


# ── the flag the table exists for ────────────────────────────────────────
@pytest.mark.asyncio
async def test_untouched_with_a_close_event_needs_chasing(client):
    await _staff("triage4@example.com")
    await _lead("Urgent", days=NEEDS_CHASING_WITHIN - 1, status=EnquiryStatus.NEW)
    # Same closeness, but somebody has picked it up.
    await _lead("Handled", days=NEEDS_CHASING_WITHIN - 1, status=EnquiryStatus.CONTACTED)
    # Untouched, but months away — real work, no alarm.
    await _lead("Patient", days=120, status=EnquiryStatus.NEW)

    await _login(client, "triage4@example.com")
    body = (await client.get("/api/v1/admin/enquiries/triage")).json()
    flagged = {row["full_name"]: row["needs_chasing"] for row in body["items"]}

    assert flagged["Urgent Lead"] is True
    assert flagged["Handled Lead"] is False
    assert flagged["Patient Lead"] is False


@pytest.mark.asyncio
async def test_an_undated_lead_is_chased_once_it_has_waited(client):
    """Waiting is the second source of urgency, and the one that works today.

    This used to assert the opposite — "no date means no deadline to have
    missed" — which read well and was wrong in practice. Almost every lead has
    no event date, so that rule meant the queue could never flag anything: the
    console showed eleven untouched enquiries and called none of them urgent.
    A wedding enquiry ignored for nine days has gone to another studio whether
    or not we know when the wedding is.
    """
    await _staff("triage5@example.com")
    await _lead("Fresh", days=None, arrived_days_ago=0)
    await _lead("Stale", days=None, arrived_days_ago=UNANSWERED_FOR + 5)
    # Waited just as long, but somebody has replied.
    await _lead(
        "Answered",
        days=None,
        arrived_days_ago=UNANSWERED_FOR + 5,
        status=EnquiryStatus.CONTACTED,
    )

    await _login(client, "triage5@example.com")
    body = (await client.get("/api/v1/admin/enquiries/triage")).json()
    flagged = {row["full_name"]: row["needs_chasing"] for row in body["items"]}

    assert flagged["Fresh Lead"] is False
    assert flagged["Stale Lead"] is True
    assert flagged["Answered Lead"] is False


@pytest.mark.asyncio
async def test_undated_leads_are_ordered_longest_waiting_first(client):
    """Within the undated band the only knowable signal is age, so the one that
    has been ignored longest has to be the one at the top."""
    await _staff("triage7@example.com")
    await _lead("Newest", days=None, arrived_days_ago=1)
    await _lead("Oldest", days=None, arrived_days_ago=40)
    await _lead("Middle", days=None, arrived_days_ago=10)

    await _login(client, "triage7@example.com")
    body = (await client.get("/api/v1/admin/enquiries/triage")).json()
    assert [row["full_name"] for row in body["items"]] == [
        "Oldest Lead",
        "Middle Lead",
        "Newest Lead",
    ]


@pytest.mark.asyncio
async def test_every_row_carries_a_waiting_count(client):
    """The column that stopped the table being eleven rows of em-dashes."""
    await _staff("triage8@example.com")
    await _lead("Dated", days=20, arrived_days_ago=3)
    await _lead("Undated", days=None, arrived_days_ago=3)

    await _login(client, "triage8@example.com")
    body = (await client.get("/api/v1/admin/enquiries/triage")).json()
    assert all(row["days_waiting"] == 3 for row in body["items"])


# ── access ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_customer_cannot_read_the_queue(client):
    async with SessionFactory() as session:
        await SqlAlchemyUserRepository(session).add(
            User(
                email="outsider@example.com",
                first_name="Out",
                last_name="Sider",
                hashed_password=hash_password(PASSWORD),
                role=UserRole.CUSTOMER,
            )
        )
        await session.commit()

    await _login(client, "outsider@example.com")
    assert (await client.get("/api/v1/admin/enquiries/triage")).status_code == 403


@pytest.mark.asyncio
async def test_triage_is_not_read_as_an_enquiry_id(client):
    """`/triage` has to be declared above `/{enquiry_id}`. Below it, FastAPI
    reads the literal path as a UUID and 422s — a failure that looks like a
    client bug and is not."""
    await _staff("triage6@example.com")
    await _login(client, "triage6@example.com")
    resp = await client.get("/api/v1/admin/enquiries/triage")
    assert resp.status_code == 200, resp.text
    assert "items" in resp.json()

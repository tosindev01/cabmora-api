"""The bell: who is told, who can read it, and what clears it.

Cabmora's UAT asked for "notification for all on admin & client portal
(messages, enquiry, bookings etc)". The two things worth testing are therefore
the two that are easy to get wrong: the **audience** — a staff-wide fan-out
reaches every member of staff, not the one address in `ENQUIRY_NOTIFICATION_EMAIL`
— and the **scope**, since a feed that can be read by id is a feed one client
can read for another.
"""

from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.core.security import hash_password
from app.domain.entities.notification import MAX_BODY, Notification, NotificationTopic
from app.domain.entities.preferences import NotificationKind, UserPreferences
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.preferences_repository_impl import (
    SqlAlchemyPreferencesRepository,
)
from app.infrastructure.repositories.user_repository_impl import SqlAlchemyUserRepository

PASSWORD = "password123"


async def _make(email: str, role: UserRole, first: str = "Test") -> User:
    async with SessionFactory() as session:
        user = await SqlAlchemyUserRepository(session).add(
            User(
                email=email,
                first_name=first,
                last_name="Account",
                hashed_password=hash_password(PASSWORD),
                role=role,
            )
        )
        await session.commit()
        return user


async def _login(client, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


async def _enquire(client, name: str = "Amara") -> None:
    resp = await client.post(
        "/api/v1/enquiries",
        json={
            "first_name": name,
            "last_name": "Okafor",
            "email": f"{name.lower()}@example.com",
            "event_type": "Wedding",
            "message": "We are getting married in June and need a photographer.",
        },
    )
    assert resp.status_code in (200, 201), resp.text


# ── the entity ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "url", ["https://cabmoramedia.com/admin/projects/1", "admin/projects/1", "//evil.test"]
)
def test_a_notification_link_has_to_be_a_path(url):
    """An absolute URL here is how a coordinator's bell starts sending them to
    the customer portal — the API does not know which origin served them. A
    protocol-relative `//host` is the same problem wearing a path's clothes."""
    with pytest.raises(ValidationError):
        Notification(
            user_id=uuid4(),
            topic=NotificationTopic.PROJECT,
            title="Something happened",
            url=url,
        )


def test_a_long_body_is_truncated_rather_than_refused():
    """The body is somebody else's prose arriving through a quoted message. A
    client writing an essay must not be the reason the notice is lost."""
    notification = Notification(
        user_id=uuid4(),
        topic=NotificationTopic.MESSAGE,
        title="Amara wrote on Okonkwo Wedding",
        body="x" * (MAX_BODY + 500),
    )
    assert len(notification.body) <= MAX_BODY
    assert notification.body.endswith("…")


def test_marking_read_twice_does_not_move_the_stamp():
    notification = Notification(
        user_id=uuid4(),
        topic=NotificationTopic.PROJECT,
        title="Moved to editing",
    )
    notification.mark_read()
    first = notification.read_at
    notification.mark_read()
    assert notification.read_at == first


# ── the audience ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_an_enquiry_reaches_every_member_of_staff(client):
    """The point of not building this on top of the enquiry email: that email
    goes to one configured inbox, so "tell every admin" cannot be expressed
    through it at all."""
    await _make("admin1@example.com", UserRole.ADMIN)
    await _make("admin2@example.com", UserRole.ADMIN)
    await _make("coord@example.com", UserRole.COORDINATOR)
    await _make("client@example.com", UserRole.CUSTOMER)

    await _enquire(client)

    for who in ("admin1@example.com", "admin2@example.com", "coord@example.com"):
        await _login(client, who)
        feed = (await client.get("/api/v1/notifications")).json()
        assert feed["unread"] == 1, who
        assert feed["items"][0]["topic"] == "enquiry"
        assert "Amara Okafor" in feed["items"][0]["title"]
        # The link has to land on the enquiry itself, not a list to hunt in.
        assert feed["items"][0]["url"].startswith("/admin/enquiries/")

    # A customer is not staff. This is the check that would fail if the fan-out
    # were ever widened to "every active account".
    await _login(client, "client@example.com")
    assert (await client.get("/api/v1/notifications")).json()["unread"] == 0


@pytest.mark.asyncio
async def test_a_coordinator_is_staff_for_notifications(client):
    """A coordinator triaging the pipeline is exactly who a new lead is for.
    Telling only admins would make the feature useless to whoever does the
    work."""
    await _make("onlycoord@example.com", UserRole.COORDINATOR)
    await _enquire(client, "Bisi")
    await _login(client, "onlycoord@example.com")
    assert (await client.get("/api/v1/notifications")).json()["unread"] == 1


# ── the scope ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_one_account_cannot_read_anothers_feed(client):
    """There is no `user_id` parameter to try, which is the point — the scope
    comes from the session. This asserts the absence."""
    await _make("mine@example.com", UserRole.ADMIN)
    other = await _make("theirs@example.com", UserRole.ADMIN)
    await _enquire(client, "Chidi")

    await _login(client, "mine@example.com")
    sneaky = await client.get(f"/api/v1/notifications?user_id={other.id}")
    assert sneaky.status_code == 200
    feed = sneaky.json()
    # One each: the parameter was ignored, not honoured.
    assert feed["unread"] == 1


@pytest.mark.asyncio
async def test_signing_out_closes_the_feed(client):
    await _make("gone@example.com", UserRole.ADMIN)
    await _login(client, "gone@example.com")
    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/notifications")).status_code == 401


# ── reading and clearing ─────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_the_badge_counts_unread_and_marking_clears_it(client):
    await _make("badge@example.com", UserRole.ADMIN)
    await _enquire(client, "Dayo")
    await _enquire(client, "Efe")
    await _login(client, "badge@example.com")

    assert (await client.get("/api/v1/notifications/unread-count")).json() == 2

    feed = (await client.get("/api/v1/notifications")).json()
    one = feed["items"][0]["id"]
    marked = (await client.post("/api/v1/notifications/read", json={"notification_ids": [one]})).json()
    assert marked == {"marked": 1, "unread": 1}

    # Again, and nothing changes. A second click must not claim to have done
    # something, or "mark all read" can never be trusted.
    again = (await client.post("/api/v1/notifications/read", json={"notification_ids": [one]})).json()
    assert again["marked"] == 0

    cleared = (await client.post("/api/v1/notifications/read", json={})).json()
    assert cleared == {"marked": 1, "unread": 0}


@pytest.mark.asyncio
async def test_an_empty_list_clears_nothing(client):
    """`{}` means "all of them" and `{"notification_ids": []}` means "these
    none". Collapsing the two would let a client that sends an accidentally
    empty selection wipe the whole feed."""
    await _make("careful@example.com", UserRole.ADMIN)
    await _enquire(client, "Femi")
    await _login(client, "careful@example.com")

    resp = (await client.post("/api/v1/notifications/read", json={"notification_ids": []})).json()
    assert resp == {"marked": 0, "unread": 1}


@pytest.mark.asyncio
async def test_marking_somebody_elses_notification_changes_nothing(client):
    await _make("a@example.com", UserRole.ADMIN)
    await _make("b@example.com", UserRole.ADMIN)
    await _enquire(client, "Gbemi")

    await _login(client, "b@example.com")
    theirs = (await client.get("/api/v1/notifications")).json()["items"][0]["id"]

    await _login(client, "a@example.com")
    await client.post("/api/v1/notifications/read", json={"notification_ids": [theirs]})

    # B's own copy is a different row and is untouched.
    await _login(client, "b@example.com")
    assert (await client.get("/api/v1/notifications/unread-count")).json() == 1


@pytest.mark.asyncio
async def test_the_feed_can_be_filtered_by_topic(client):
    await _make("filter@example.com", UserRole.ADMIN)
    await _enquire(client, "Hauwa")
    await _login(client, "filter@example.com")

    assert len((await client.get("/api/v1/notifications?topic=enquiry")).json()["items"]) == 1
    assert len((await client.get("/api/v1/notifications?topic=invoice")).json()["items"]) == 0
    # The badge still reports the whole feed, not the filtered slice — a filter
    # that changed the count would make the number mean nothing.
    assert (await client.get("/api/v1/notifications?topic=invoice")).json()["unread"] == 1


# ── the thing that is easiest to get wrong ───────────────────────────────
@pytest.mark.asyncio
async def test_muting_an_email_does_not_silence_the_bell(client):
    """Email and the bell are different channels.

    `NotificationKind` gates **mail** at the send boundary. Somebody who turns
    off invoice email is saying "stop filling my inbox", not "stop showing me
    this in the product" — and if the bell were built as a side effect of
    sending that email, the one switch would have silenced both.
    """
    admin = await _make("muted@example.com", UserRole.ADMIN)
    async with SessionFactory() as session:
        preferences = SqlAlchemyPreferencesRepository(session)
        await preferences.save(
            admin.id,
            UserPreferences(muted={NotificationKind.BOOKINGS, NotificationKind.MESSAGES}),
        )
        await session.commit()

    await _enquire(client, "Ifeoma")
    await _login(client, "muted@example.com")
    assert (await client.get("/api/v1/notifications/unread-count")).json() == 1

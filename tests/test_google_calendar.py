"""The scheduler that books the call rather than recording one.

What matters here is not that an HTTP call happens — it is what we refuse to
return. A booking confirmed without a link, or one that quietly duplicates
Google's own invitation, are both worse than an error the admin can see.
"""

from datetime import datetime, timezone

import httpx
import pytest

from app.domain.entities.consultation import MeetingProvider
from app.infrastructure.scheduling.google_calendar_scheduler import (
    GoogleCalendarScheduler,
)

WHEN = datetime(2026, 10, 14, 13, 30, tzinfo=timezone.utc)


def _scheduler(event: dict, seen: list | None = None) -> GoogleCalendarScheduler:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3600})
        if seen is not None:
            seen.append(request)
        return httpx.Response(200, json=event)

    return GoogleCalendarScheduler(
        client_id="cid", client_secret="secret", refresh_token="rt",
        calendar_id="bookings@cabmoramedia.com",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def _book(scheduler, **kwargs):
    return await scheduler.schedule(
        summary="Cabmora consultation — Wedding", starts_at=WHEN,
        minutes=30, attendees=["client@example.com"], **kwargs,
    )


@pytest.mark.anyio
async def test_it_returns_the_meet_link_google_created():
    seen: list[httpx.Request] = []
    meeting = await _book(_scheduler({"id": "ev1", "hangoutLink": "https://meet.google.com/abc"}, seen))

    assert meeting.url == "https://meet.google.com/abc"
    assert meeting.provider is MeetingProvider.GOOGLE_MEET
    assert "bookings%40cabmoramedia.com" in str(seen[0].url), "calendar id must be escaped"


@pytest.mark.anyio
async def test_google_does_not_email_the_attendee():
    """We send our own confirmation; two invitations for one call is a bug."""
    seen: list[httpx.Request] = []
    await _book(_scheduler({"id": "ev1", "hangoutLink": "https://meet.google.com/abc"}, seen))
    assert "sendUpdates=none" in str(seen[0].url)
    assert "conferenceDataVersion=1" in str(seen[0].url)


@pytest.mark.anyio
async def test_an_event_without_a_link_is_an_error():
    """Returning None here would confirm a call with no way to join it."""
    with pytest.raises(RuntimeError, match="without a Meet link"):
        await _book(_scheduler({"id": "ev1"}))


@pytest.mark.anyio
async def test_a_pasted_link_overrides_and_creates_nothing():
    seen: list[httpx.Request] = []
    meeting = await _book(
        _scheduler({"id": "ev1", "hangoutLink": "https://meet.google.com/abc"}, seen),
        meeting_url="https://zoom.us/j/123",
    )
    assert meeting.url == "https://zoom.us/j/123"
    assert meeting.provider is MeetingProvider.MANUAL
    assert seen == [], "an override must not litter the diary with an unused Meet"

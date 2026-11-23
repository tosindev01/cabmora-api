"""Books the call in Cabmora's own Google Calendar and returns its Meet link.

The point is what the admin *doesn't* do. Picking a date is the whole
interaction: no opening meet.google.com, no creating a call by hand, no pasting
a link back into a second form. That manual path was three chances to paste the
wrong link, and it left every booking invisible to anyone looking at the
calendar — the call existed only in our database.

Deliberately built on `httpx`, which is already a dependency, rather than
`google-api-python-client`. Two HTTP calls do not justify that dependency tree,
and the same reasoning produced `MailtrapEmailSender`.

**Failures raise.** Unlike the email adapters, which log and continue because
their side effects have already happened, this runs *before* the consultation is
saved. A booking tool that reports success for a call it never put in the diary
is worse than one that occasionally says "try again" — the admin can see the
error and retry, where a silent fallback would have them believing in a meeting
nobody scheduled.
"""

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import httpx

from app.domain.entities.consultation import MeetingProvider
from app.domain.services.meeting_scheduler import (
    MeetingScheduler,
    ScheduledMeeting,
    SchedulerAuthExpired,
)

logger = logging.getLogger(__name__)




TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"

#: Enough for an API having a slow moment, short enough that an admin is not
#: left watching a spinner because Google is.
TIMEOUT_SECONDS = 15.0

#: Refresh a little before the hour Google actually grants, so a token cannot
#: expire between our check and Google reading it.
_EXPIRY_MARGIN = timedelta(seconds=60)

#: Namespace for conference request ids. Fixed, so the same booking derives
#: the same id on this machine, the next deploy and every replica.
_CONFERENCE_NS = uuid5(NAMESPACE_URL, "https://cabmoramedia.com/consultation")


class GoogleCalendarScheduler(MeetingScheduler):
    """Creates a Calendar event with a Meet conference attached."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        calendar_id: str = "primary",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        #: The long-lived credential. It does not expire on its own; anyone
        #: holding it can write to Cabmora's calendar until it is revoked.
        self._refresh_token = refresh_token
        self._calendar_id = calendar_id
        self._client = client
        self._access_token: str | None = None
        self._expires_at = datetime.min.replace(tzinfo=timezone.utc)

    # ── transport ────────────────────────────────────────────────────────
    async def _request(self, method: str, url: str, **kwargs) -> dict:
        if self._client is not None:
            response = await self._client.request(method, url, **kwargs)
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
                response = await client.request(method, url, **kwargs)
        response.raise_for_status()
        return response.json()

    async def _token(self) -> str:
        """A valid access token, refreshed only when the cached one is stale."""
        now = datetime.now(timezone.utc)
        if self._access_token and now < self._expires_at:
            return self._access_token

        try:
            payload = await self._request(
                "POST",
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPStatusError as exc:
            if "invalid_grant" not in exc.response.text:
                raise
            # Named apart from every other calendar failure because the
            # remedy is completely different and nobody can guess it from
            # "the calendar refused". Google expires a refresh token after
            # seven days while the OAuth app's publishing status is
            # "Testing", so this comes back on a weekly cycle until the
            # consent screen is published or set to Internal. Re-authorising
            # alone buys another seven days.
            raise SchedulerAuthExpired(
                "Google has rejected the saved sign-in (invalid_grant). "
                "Re-authorise with scripts.google_authorize, and publish the "
                "OAuth consent screen or set it to Internal — otherwise it "
                "expires again in seven days."
            ) from exc
        self._access_token = payload["access_token"]
        self._expires_at = now + timedelta(seconds=payload.get("expires_in", 3600)) - _EXPIRY_MARGIN
        return self._access_token

    def _seed(self, summary: str, moment: datetime, attendees: list[str]) -> str:
        """What makes this booking *this* booking. Attendees sorted, so
        argument order cannot change the identity."""
        return "|".join(
            [self._calendar_id, moment.isoformat(), summary, *sorted(attendees)]
        )

    def _conference_id(self, seed: str) -> str:
        """Google's idempotency key for the conference *within one event*.

        Worth being precise about, because it is easy to over-read: this
        stops one event ending up with two conferences. It does nothing about
        two events — a second POST creates a second event with a second Meet
        link, whatever this says. Verified against the live API on
        2026-09-28, which is what `_event_id` exists to handle.
        """
        return str(uuid5(_CONFERENCE_NS, seed))

    def _event_id(self, seed: str) -> str:
        """A deterministic id for the event itself.

        This is the part that actually makes a retry safe. Supplying the id
        means Google refuses a second insert with 409 rather than quietly
        booking the same consultation twice — so a timeout that hid a
        successful response cannot leave the client holding one link while
        the diary holds another.

        A hex digest happens to be valid for Google's id charset, which
        allows 0-9 and a-v.
        """
        return hashlib.sha256(seed.encode()).hexdigest()

    # ── the port ─────────────────────────────────────────────────────────
    async def schedule(
        self,
        *,
        summary: str,
        starts_at: datetime,
        minutes: int,
        attendees: list[str],
        meeting_url: str | None = None,
    ) -> ScheduledMeeting:
        # An admin-supplied link wins. Not a fallback path — an override, for
        # the case where the client insists on Zoom or their own boardroom
        # bridge. Creating a Meet nobody will join would just litter the diary.
        if meeting_url:
            return ScheduledMeeting(url=meeting_url, provider=MeetingProvider.MANUAL)

        moment = starts_at if starts_at.tzinfo else starts_at.replace(tzinfo=timezone.utc)
        token = await self._token()

        seed = self._seed(summary, moment, attendees)
        event_id = self._event_id(seed)
        events_url = f"{CALENDAR_API}/calendars/{quote(self._calendar_id, safe='')}/events"

        try:
            event = await self._request(
                "POST",
                events_url,
                params={
                    "conferenceDataVersion": 1,
                    # We send our own branded confirmation the moment this
                    # returns. Letting Google invite the attendee as well
                    # means the client gets two emails for one booking, one
                    # of them not ours.
                    "sendUpdates": "none",
                },
                headers={"Authorization": f"Bearer {token}"},
                json={
                    # Ours, not Google's. This is what makes a retry return
                    # the same call rather than book a second one.
                    "id": event_id,
                    "summary": summary,
                    "start": {"dateTime": moment.isoformat()},
                    "end": {"dateTime": (moment + timedelta(minutes=minutes)).isoformat()},
                    "attendees": [{"email": email} for email in attendees],
                    "conferenceData": {
                        "createRequest": {
                            "requestId": self._conference_id(seed),
                            "conferenceSolutionKey": {"type": "hangoutsMeet"},
                        }
                    },
                },
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 409:
                raise
            # Already booked. Google is telling us this exact consultation
            # exists, which is success, not failure — fetch it and hand back
            # the link it already has.
            logger.info("[calendar] %s already existed — reusing it", event_id)
            event = await self._request(
                "GET",
                f"{events_url}/{event_id}",
                headers={"Authorization": f"Bearer {token}"},
            )

        url = event.get("hangoutLink")
        if not url:
            # The event exists but has no conference. Surfacing this rather than
            # returning None keeps the caller from confirming a link-less call
            # that the admin believes Google created.
            raise RuntimeError(
                f"Calendar event {event.get('id')} was created without a Meet "
                "link. Check that Meet is enabled for this Google account."
            )

        logger.info("[calendar] booked %s at %s", event.get("id"), moment.isoformat())
        return ScheduledMeeting(url=url, provider=MeetingProvider.GOOGLE_MEET)

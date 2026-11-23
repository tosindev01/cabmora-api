from datetime import datetime
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.domain.entities.user import User
from app.domain.repositories.enquiry_repository import EnquiryRepository


class UpdateEnquiry:
    """What staff change about a lead.

    Everything is editable, which this use case once refused. The reasoning
    for refusing was that a submitted enquiry is evidence and a record that
    can be tidied is not one — and that reasoning is sound, so it was not
    deleted, it was paid for: **every change writes a DETAILS_CHANGED event
    carrying the old value**. The history still shows what the client sent,
    who changed it and when. Remove that and this is back to being a form
    staff can quietly rewrite.

    Opened up on 2026-10-01 because the alternative was worse: an event date
    given through a form at midnight is usually a guess, a mistyped phone
    number is one nobody can ring, and a lead nobody can correct is a lead
    somebody re-enters by hand into a spreadsheet.

    **Except the email address.** That is the lead's identity — every message
    already sent went to it, and conversion matches an account on it — so
    changing it here would quietly point the record at a different person.
    A wrong address is a reason to ask the client, not to edit the record.
    """

    def __init__(self, enquiries: EnquiryRepository) -> None:
        self._enquiries = enquiries

    async def execute(
        self,
        enquiry_id: UUID,
        actor: User,
        status: EnquiryStatus | None = None,
        assigned_to: UUID | None = None,
        budget_min_minor: int | None = None,
        budget_max_minor: int | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        whatsapp: str | None = None,
        event_type: str | None = None,
        message: str | None = None,
        event_date: datetime | None = None,
        deadline: datetime | None = None,
    ) -> Enquiry:
        enquiry = await self._enquiries.get_by_id(enquiry_id)
        if enquiry is None:
            raise EntityNotFoundError("Enquiry not found")

        events: list[EnquiryEvent] = []

        # The submitted details, first, so that a correction and a status move
        # in one request both land on the timeline rather than one overwriting
        # the other.
        #
        # An empty string clears a field that may be empty, and is refused for
        # one that may not — "" is how a form says "I deleted this", and
        # treating it as "unchanged" would make a phone number impossible to
        # remove once added.
        submitted: dict[str, str | datetime | None] = {
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "whatsapp": whatsapp,
            "event_type": event_type,
            "message": message,
            "event_date": event_date,
            "deadline": deadline,
        }
        clearable = {"phone", "whatsapp", "event_date", "deadline"}

        for field, value in submitted.items():
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    if field not in clearable:
                        raise ValidationError(f"{field.replace('_', ' ').capitalize()} cannot be empty.")
                    value = None
            if value == getattr(enquiry, field):
                continue
            was = getattr(enquiry, field)
            events.append(
                EnquiryEvent(
                    enquiry_id=enquiry.id,
                    kind=EnquiryEventKind.DETAILS_CHANGED,
                    actor_id=actor.id,
                    payload={
                        "field": field,
                        "from": _readable(was),
                        "to": _readable(value),
                    },
                )
            )
            setattr(enquiry, field, value)

        event: EnquiryEvent | None = None

        if status is not None and status is not enquiry.status:
            if status is EnquiryStatus.WON:
                # Winning creates a project and an account. Allowing it here
                # would mark the lead won with nothing behind it.
                raise ValidationError(
                    "Use the convert endpoint to win an enquiry — it creates "
                    "the project."
                )
            if not enquiry.can_move_to(status):
                raise ValidationError(
                    f"An enquiry cannot move from {enquiry.status.value} to "
                    f"{status.value}."
                )
            event = EnquiryEvent(
                enquiry_id=enquiry.id,
                kind=EnquiryEventKind.LOST
                if status is EnquiryStatus.LOST
                else EnquiryEventKind.STATUS_CHANGED,
                actor_id=actor.id,
                payload={"from": enquiry.status.value, "to": status.value},
            )
            enquiry.status = status

        if assigned_to is not None and assigned_to != enquiry.assigned_to:
            enquiry.assigned_to = assigned_to
            event = event or EnquiryEvent(
                enquiry_id=enquiry.id,
                kind=EnquiryEventKind.ASSIGNED,
                actor_id=actor.id,
                payload={"assigned_to": str(assigned_to)},
            )

        if budget_min_minor is not None:
            enquiry.budget_min_minor = budget_min_minor
        if budget_max_minor is not None:
            enquiry.budget_max_minor = budget_max_minor
        if (
            enquiry.budget_min_minor is not None
            and enquiry.budget_max_minor is not None
            and enquiry.budget_min_minor > enquiry.budget_max_minor
        ):
            raise ValidationError("Budget minimum cannot exceed the maximum.")

        # `update` takes one event; the date corrections are added separately
        # so a request that changes a date *and* the status records both.
        saved = await self._enquiries.update(enquiry, event)
        for extra in events:
            await self._enquiries.add_event(extra)
        return saved


def _readable(value: object) -> str | None:
    """A payload value the timeline can print without knowing the type."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)

from uuid import UUID

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.enquiry_event import EnquiryEvent, EnquiryEventKind
from app.domain.entities.user import User
from app.domain.repositories.enquiry_repository import EnquiryRepository


class AddEnquiryNote:
    """A note is an event, not a column.

    Notes accumulate — "called, no answer", "wants the Saturday slot" — and a
    single `notes` field would either be overwritten or become an unstructured
    blob with no author and no time.
    """

    def __init__(self, enquiries: EnquiryRepository) -> None:
        self._enquiries = enquiries

    async def execute(self, enquiry_id: UUID, actor: User, body: str) -> EnquiryEvent:
        if await self._enquiries.get_by_id(enquiry_id) is None:
            raise EntityNotFoundError("Enquiry not found")
        return await self._enquiries.add_event(
            EnquiryEvent(
                enquiry_id=enquiry_id,
                kind=EnquiryEventKind.NOTE_ADDED,
                actor_id=actor.id,
                payload={"body": body.strip()},
            )
        )

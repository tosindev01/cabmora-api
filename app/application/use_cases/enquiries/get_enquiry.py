from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.consultation import Consultation
from app.domain.entities.enquiry import Enquiry
from app.domain.entities.enquiry_event import EnquiryEvent
from app.domain.entities.user import User
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.repositories.user_repository import UserRepository


@dataclass
class EnquiryDetail:
    enquiry: Enquiry
    events: list[EnquiryEvent]
    consultations: list[Consultation]
    #: The account this lead's address already belongs to, if any. Answered
    #: here rather than left to the console because converting asks the admin
    #: for a name that is only used when an account is *created* — so they
    #: need to know which case they are in before they type it.
    existing_account: User | None = None


class GetEnquiry:
    def __init__(self, enquiries: EnquiryRepository, users: UserRepository) -> None:
        self._enquiries = enquiries
        self._users = users

    async def execute(self, enquiry_id: UUID) -> EnquiryDetail:
        enquiry = await self._enquiries.get_by_id(enquiry_id)
        if enquiry is None:
            raise EntityNotFoundError("Enquiry not found")
        return EnquiryDetail(
            enquiry=enquiry,
            events=await self._enquiries.list_events(enquiry_id),
            consultations=await self._enquiries.list_consultations(enquiry_id),
            # Deliberately the same normalised lookup `ConvertEnquiry` performs.
            # If these two ever diverge the console promises one outcome and the
            # conversion delivers another.
            existing_account=await self._users.get_by_email(enquiry.email.lower()),
        )

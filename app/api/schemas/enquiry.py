from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.entities.enquiry import EnquiryStatus


class EnquiryCreateRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    #: Both carry their dialling code, because a number without one cannot be
    #: rung from another country and this studio says it works worldwide.
    phone: str | None = Field(default=None, max_length=50)
    whatsapp: str | None = Field(default=None, max_length=50)
    event_type: str = Field(min_length=1, max_length=100)
    event_date: datetime | None = None
    message: str = Field(min_length=1, max_length=5000)
    #: The slot the visitor picked, if they picked one. A request, not a
    #: booking — Cabmora confirms it before anything is in a diary.
    preferred_slot: datetime | None = None


class OpenSlotsResponse(BaseModel):
    """Only the times somebody may ask for.

    No busy slots, no names, no ids. A caller cannot tell a booked hour from a
    closed one, which is the point.
    """

    slots: list[datetime]
    duration_minutes: int


class EnquiryResponse(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    #: Derived on the entity, and named as `UserResponse` names it. Sent as
    #: well as the parts so a list does not join two fields in every row and
    #: get the spacing subtly different each time.
    full_name: str
    email: str
    phone: str | None
    whatsapp: str | None
    event_type: str
    event_date: datetime | None
    message: str
    status: EnquiryStatus
    created_at: datetime

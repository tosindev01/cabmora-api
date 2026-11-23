from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from datetime import datetime, timedelta, timezone

from app.api.deps import (
    CurrentAdminDep,
    OptionalUserDep,
    get_list_enquiries,
    get_list_open_slots,
    get_submit_enquiry,
)
from app.api.schemas.enquiry import (
    EnquiryCreateRequest,
    EnquiryResponse,
    OpenSlotsResponse,
)
from app.application.use_cases.enquiries.list_enquiries import ListEnquiries
from app.application.use_cases.enquiries.list_open_slots import (
    MAX_HORIZON_DAYS,
    SLOT_MINUTES,
    ListOpenSlots,
)
from app.application.use_cases.enquiries.submit_enquiry import SubmitEnquiry
from app.domain.entities.user import UserRole

router = APIRouter(prefix="/enquiries", tags=["enquiries"])


@router.post("", response_model=EnquiryResponse, status_code=status.HTTP_201_CREATED)
async def submit_enquiry(
    body: EnquiryCreateRequest,
    use_case: Annotated[SubmitEnquiry, Depends(get_submit_enquiry)],
    caller: OptionalUserDep = None,
) -> EnquiryResponse:
    """Public endpoint — website 'Make Enquiry' form.

    Open to anybody, but it recognises a signed-in client: an existing
    customer booking a second shoot arrives attached to their account
    instead of as a stranger who happens to know their own email address.
    Authentication is optional, so a lapsed session still submits the form.

    Only a customer is stamped. Staff use this endpoint while testing, and
    recording an admin as the customer of their own enquiry would convert
    into a project owned by the office.
    """
    enquiry = await use_case.execute(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        event_type=body.event_type,
        message=body.message,
        phone=body.phone,
        whatsapp=body.whatsapp,
        event_date=body.event_date,
        preferred_slot=body.preferred_slot,
        customer_id=(
            caller.id if caller is not None and caller.role is UserRole.CUSTOMER else None
        ),
    )
    return EnquiryResponse.model_validate(enquiry, from_attributes=True)

@router.get("/availability", response_model=OpenSlotsResponse)
async def open_slots(
    use_case: Annotated[ListOpenSlots, Depends(get_list_open_slots)],
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
) -> OpenSlotsResponse:
    """When a visitor may ask to talk — public, and deliberately thin.

    Unauthenticated because the people who need it have not signed up yet: it
    sits on the enquiry form. Safe to leave open because it says only what is
    free. Nothing here identifies a client, and a booked hour is indis-
    tinguishable from a closed one.
    """
    now = datetime.now(timezone.utc)
    window_start = start or now
    window_end = end or min(
        window_start + timedelta(days=21), now + timedelta(days=MAX_HORIZON_DAYS)
    )
    return OpenSlotsResponse(
        slots=await use_case.execute(start=window_start, end=window_end),
        duration_minutes=SLOT_MINUTES,
    )


# NOTE: the admin listing moved to `enquiries_admin.py` when leads gained a
# pipeline. It lives behind /admin/enquiries with paging, filters and the
# event trail; leaving a second, unpaginated listing here would be a way to
# read the whole table and would drift from it.

"""Lead management.

The public `POST /enquiries` stays in `enquiries.py`; everything here is behind
`CurrentAdminDep`. The split is deliberate — one file mixing the internet-facing
write with the staff pipeline is how an admin route ends up unguarded.
"""

from typing import Annotated
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentAdminDep,
    CurrentTeamDep,
    get_add_enquiry_note,
    get_confirm_consultation,
    get_convert_enquiry,
    get_get_enquiry,
    get_list_enquiries,
    get_schedule_consultation,
    get_triage_enquiries,
    get_update_enquiry,
    ListAvailabilityDep,
    PaginationDep,
    UserRepoDep,
)
from app.api.schemas.enquiry_admin import (
    EnquiryTriageResponse,
    TriagedEnquiryResponse,
    AvailabilityResponse,
    BookedSlotResponse,
    AdminEnquiryDetailResponse,
    ExistingAccountResponse,
    AdminEnquiryResponse,
    ConfirmConsultationRequest,
    ConsultationRequest,
    ConsultationResponse,
    ConversionResponse,
    ConvertRequest,
    EnquiryEventResponse,
    EnquiryUpdateRequest,
    NoteRequest,
)
from app.api.schemas.page import Page
from app.application.use_cases.enquiries.add_note import AddEnquiryNote
from app.application.use_cases.enquiries.confirm_consultation import (
    ConfirmConsultation,
)
from app.application.use_cases.enquiries.convert_enquiry import ConvertEnquiry
from app.application.use_cases.enquiries.get_enquiry import GetEnquiry
from app.application.use_cases.enquiries.list_enquiries import ListEnquiries
from app.application.use_cases.enquiries.schedule_consultation import (
    ScheduleConsultation,
)
from app.application.use_cases.enquiries.triage_enquiries import TriageEnquiries
from app.application.use_cases.enquiries.update_enquiry import UpdateEnquiry
from app.core.config import get_settings
from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.entities.user import User, UserRole

router = APIRouter(prefix="/admin/enquiries", tags=["admin: enquiries"])

_DERIVED = {"allowed_next_statuses", "assigned_to_name"}


def _to_response(enquiry: Enquiry, names: dict[UUID, User]) -> AdminEnquiryResponse:
    owner = names.get(enquiry.assigned_to) if enquiry.assigned_to else None
    return AdminEnquiryResponse(
        **{
            field: getattr(enquiry, field)
            for field in AdminEnquiryResponse.model_fields
            if field not in _DERIVED
        },
        allowed_next_statuses=enquiry.allowed_next_statuses,
        assigned_to_name=owner.full_name if owner else None,
    )


async def _names_for(users: UserRepoDep, *enquiries: Enquiry) -> dict[UUID, User]:
    """One lookup covering every assignee on the page, not one per row."""
    return await users.get_many({e.assigned_to for e in enquiries if e.assigned_to})


@router.get("/availability", response_model=AvailabilityResponse)
async def availability(
    _team: CurrentTeamDep,
    listing: ListAvailabilityDep,
    start: datetime,
    end: datetime,
) -> AvailabilityResponse:
    """Consultations already booked in a window, across every enquiry.

    Declared before `/{enquiry_id}` so "availability" is not parsed as a UUID —
    FastAPI matches in definition order.

    Returns what is taken, not what is free: "free" depends on working hours,
    holidays and call length, which belong to whoever is reading the grid.
    """
    slots = await listing.execute(start=start, end=end)
    return AvailabilityResponse(
        start=start,
        end=end,
        booked=[
            BookedSlotResponse(
                consultation_id=slot.consultation.id,
                enquiry_id=slot.enquiry_id,
                client_name=slot.client_name,
                event_type=slot.event_type,
                starts_at=slot.consultation.starts_at,
                ends_at=slot.consultation.ends_at,
                duration_minutes=slot.consultation.duration_minutes,
                meeting_url=slot.consultation.meeting_url,
            )
            for slot in slots
        ],
    )


@router.get("", response_model=Page[AdminEnquiryResponse])
async def list_enquiries(
    _team: CurrentTeamDep,
    page: PaginationDep,
    use_case: Annotated[ListEnquiries, Depends(get_list_enquiries)],
    users: UserRepoDep,
    status_filter: EnquiryStatus | None = Query(default=None, alias="status"),
    assigned_to: UUID | None = Query(default=None),
    q: str | None = Query(default=None, max_length=255),
) -> Page[AdminEnquiryResponse]:
    result = await use_case.execute(
        limit=page.limit, offset=page.offset, status=status_filter,
        assigned_to=assigned_to, search=q,
    )
    names = await _names_for(users, *result.items)
    return Page[AdminEnquiryResponse](
        items=[_to_response(e, names) for e in result.items],
        total=result.total, limit=result.limit, offset=result.offset,
    )


@router.get("/triage", response_model=EnquiryTriageResponse)
async def triage(
    actor: CurrentTeamDep,
    use_case: Annotated[TriageEnquiries, Depends(get_triage_enquiries)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> EnquiryTriageResponse:
    """Open leads, soonest event first, banded by urgency.

    **Declared above `/{enquiry_id}`, and it has to stay there.** FastAPI matches
    routes in definition order, so with this below it the path "triage" is read
    as an enquiry id and the request 422s on a malformed UUID — a failure that
    looks like a client bug and is not.
    """
    result = await use_case.execute(actor=actor, limit=limit, offset=offset)
    return EnquiryTriageResponse(
        items=[
            TriagedEnquiryResponse(
                id=row.enquiry.id,
                full_name=row.enquiry.full_name,
                event_type=row.enquiry.event_type,
                event_date=row.enquiry.event_date,
                status=row.enquiry.status,
                band=row.band,
                days_until=row.days_until,
                days_waiting=row.days_waiting,
                assigned_to_name=row.owner_name,
                needs_chasing=row.needs_chasing,
                created_at=row.enquiry.created_at,
            )
            for row in result.items
        ],
        open_total=result.open_total,
    )


@router.get("/{enquiry_id}", response_model=AdminEnquiryDetailResponse)
async def get_enquiry(
    enquiry_id: UUID,
    _team: CurrentTeamDep,
    use_case: Annotated[GetEnquiry, Depends(get_get_enquiry)],
    users: UserRepoDep,
) -> AdminEnquiryDetailResponse:
    detail = await use_case.execute(enquiry_id)
    names = await _names_for(users, detail.enquiry)
    return AdminEnquiryDetailResponse(
        **_to_response(detail.enquiry, names).model_dump(),
        events=[
            EnquiryEventResponse.model_validate(e, from_attributes=True)
            for e in detail.events
        ],
        consultations=[
            ConsultationResponse.model_validate(c, from_attributes=True)
            for c in detail.consultations
        ],
        existing_account=(
            ExistingAccountResponse(
                id=detail.existing_account.id,
                first_name=detail.existing_account.first_name,
                last_name=detail.existing_account.last_name,
                role=detail.existing_account.role.value,
                is_customer=detail.existing_account.role is UserRole.CUSTOMER,
            )
            if detail.existing_account
            else None
        ),
    )


@router.patch("/{enquiry_id}", response_model=AdminEnquiryResponse)
async def update_enquiry(
    enquiry_id: UUID,
    body: EnquiryUpdateRequest,
    actor: CurrentTeamDep,
    use_case: Annotated[UpdateEnquiry, Depends(get_update_enquiry)],
    users: UserRepoDep,
) -> AdminEnquiryResponse:
    enquiry = await use_case.execute(
        enquiry_id, actor, **body.model_dump(exclude_unset=True)
    )
    return _to_response(enquiry, await _names_for(users, enquiry))


@router.post(
    "/{enquiry_id}/notes",
    response_model=EnquiryEventResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_note(
    enquiry_id: UUID,
    body: NoteRequest,
    actor: CurrentTeamDep,
    use_case: Annotated[AddEnquiryNote, Depends(get_add_enquiry_note)],
) -> EnquiryEventResponse:
    event = await use_case.execute(enquiry_id, actor, body.body)
    return EnquiryEventResponse.model_validate(event, from_attributes=True)


@router.post(
    "/{enquiry_id}/consultations",
    response_model=ConsultationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def schedule_consultation(
    enquiry_id: UUID,
    body: ConsultationRequest,
    actor: CurrentTeamDep,
    use_case: Annotated[ScheduleConsultation, Depends(get_schedule_consultation)],
) -> ConsultationResponse:
    """Book a call. While the scheduler is manual the admin supplies the link;
    a Google Meet backend would generate it without changing this route."""
    consultation = await use_case.execute(
        enquiry_id, actor, body.scheduled_at, body.duration_minutes, body.meeting_url
    )
    return ConsultationResponse.model_validate(consultation, from_attributes=True)


@router.post(
    "/{enquiry_id}/consultations/{consultation_id}/confirm",
    response_model=ConsultationResponse,
)
async def confirm_consultation(
    enquiry_id: UUID,
    consultation_id: UUID,
    body: ConfirmConsultationRequest,
    actor: CurrentTeamDep,
    use_case: Annotated[ConfirmConsultation, Depends(get_confirm_consultation)],
) -> ConsultationResponse:
    """Agree a call the client asked for, at their time or another.

    Everything that makes the call real happens here rather than when the
    client picked the slot: the calendar entry, the meeting link, the email
    and the move to CONSULTATION_BOOKED.
    """
    consultation = await use_case.execute(
        enquiry_id,
        consultation_id,
        actor,
        scheduled_at=body.scheduled_at,
        duration_minutes=body.duration_minutes,
        meeting_url=body.meeting_url,
    )
    return ConsultationResponse.model_validate(consultation, from_attributes=True)


@router.post(
    "/{enquiry_id}/convert",
    response_model=ConversionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def convert_enquiry(
    enquiry_id: UUID,
    body: ConvertRequest,
    actor: CurrentAdminDep,
    use_case: Annotated[ConvertEnquiry, Depends(get_convert_enquiry)],
) -> ConversionResponse:
    """Win the lead: create the project, provision the client, link all three."""
    result = await use_case.execute(enquiry_id, actor, **body.model_dump())
    return ConversionResponse(
        project_id=result.project.id,
        customer_id=result.customer.id if result.customer else None,
        warning=result.warning,
        # An invite link is a credential; outside local the client's inbox is
        # the only place it appears.
        invite_url=result.invite_url
        if get_settings().environment == "local"
        else None,
    )

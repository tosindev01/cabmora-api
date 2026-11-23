from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    CurrentActiveUserDep,
    OptionalStorageDep,
    get_get_my_creator_studio,
    get_get_public_creator_studio,
    get_list_creator_bookings,
    get_submit_creator_booking,
    get_update_creator_booking_status,
    get_update_my_creator_studio,
)
from app.api.schemas.creator_studio import (
    CreatorBookingCreateRequest,
    CreatorBookingResponse,
    CreatorBookingStatusUpdateRequest,
    CreatorStudioPayload,
    CreatorStudioResponse,
    PortfolioItemResponse,
)
from app.application.use_cases.creators.studio_profile import (
    GetMyCreatorStudio,
    GetPublicCreatorStudio,
    ListCreatorBookings,
    StudioUpdateData,
    StudioWithPortfolio,
    SubmitCreatorBooking,
    UpdateCreatorBookingStatus,
    UpdateMyCreatorStudio,
)
from app.domain.entities.creator_studio import BookingRequest
from app.domain.services.media_storage import MediaStorage

router = APIRouter(prefix="/creators", tags=["creator-studios"])


async def _presign_avatar(
    avatar_key: str | None, storage: MediaStorage | None
) -> str | None:
    if not avatar_key or storage is None:
        return None
    try:
        return await storage.presign_download(key=avatar_key, expires_in=900)
    except Exception:
        return None


def _to_studio_response(
    bundle: StudioWithPortfolio, avatar_url: str | None
) -> CreatorStudioResponse:
    s = bundle.studio
    return CreatorStudioResponse(
        user_id=s.user_id,
        slug=s.slug,
        is_published=s.is_published,
        studio_name=s.studio_name,
        legal_name=s.legal_name,
        specialization=s.specialization,
        categories=s.categories,
        bio=s.bio,
        experience_years=s.experience_years,
        team_size=s.team_size,
        currency=s.currency,
        day_rate=s.day_rate,
        tax_id=s.tax_id,
        cover_url=s.cover_url,
        avatar_url=avatar_url,
        primary_email=s.primary_email,
        secondary_email=s.secondary_email,
        phone=s.phone,
        allow_sms_alerts=s.allow_sms_alerts,
        address=s.address,
        city=s.city,
        country=s.country,
        timezone=s.timezone,
        socials=s.socials,
        landing_config=s.landing_config,
        portfolio_items=[
            PortfolioItemResponse(
                id=item.id,
                creator_id=item.creator_id,
                title=item.title,
                subtitle=item.subtitle,
                category=item.category,
                media_type=item.media_type,
                media_url=item.media_url,
                video_url=item.video_url,
                description=item.description,
                client_name=item.client_name,
                location=item.location,
                shoot_year=item.shoot_year,
                aspect_ratio=item.aspect_ratio,
                featured=item.featured,
                sort_order=item.sort_order,
                gallery_images=item.gallery_images,
                created_at=item.created_at,
            )
            for item in bundle.portfolio_items
        ],
        updated_at=s.updated_at,
    )


def _to_booking_response(b: BookingRequest) -> CreatorBookingResponse:
    return CreatorBookingResponse(
        id=b.id,
        creator_slug=b.creator_slug,
        client_name=b.client_name,
        client_email=b.client_email,
        client_phone=b.client_phone,
        company_or_brand=b.company_or_brand,
        service_title=b.service_title,
        event_type=b.event_type,
        preferred_date=b.preferred_date,
        location=b.location,
        budget_range=b.budget_range,
        project_brief=b.project_brief,
        status=b.status,
        created_at=b.created_at,
    )


@router.get("/me/profile", response_model=CreatorStudioResponse)
async def get_my_profile(
    actor: CurrentActiveUserDep,
    storage: OptionalStorageDep,
    use_case: Annotated[GetMyCreatorStudio, Depends(get_get_my_creator_studio)],
) -> CreatorStudioResponse:
    bundle = await use_case.execute(actor)
    return _to_studio_response(bundle, await _presign_avatar(bundle.avatar_key, storage))


@router.put("/me/profile", response_model=CreatorStudioResponse)
async def update_my_profile(
    body: CreatorStudioPayload,
    actor: CurrentActiveUserDep,
    storage: OptionalStorageDep,
    use_case: Annotated[UpdateMyCreatorStudio, Depends(get_update_my_creator_studio)],
) -> CreatorStudioResponse:
    bundle = await use_case.execute(
        actor,
        StudioUpdateData(
            slug=body.slug,
            is_published=body.is_published,
            studio_name=body.studio_name,
            legal_name=body.legal_name,
            specialization=body.specialization,
            categories=body.categories,
            bio=body.bio,
            experience_years=body.experience_years,
            team_size=body.team_size,
            currency=body.currency,
            day_rate=body.day_rate,
            tax_id=body.tax_id,
            cover_url=body.cover_url,
            primary_email=body.primary_email,
            secondary_email=body.secondary_email,
            phone=body.phone,
            allow_sms_alerts=body.allow_sms_alerts,
            address=body.address,
            city=body.city,
            country=body.country,
            timezone=body.timezone,
            socials=body.socials,
            landing_config=body.landing_config,
            portfolio_items=[item.model_dump() for item in body.portfolio_items],
        ),
    )
    return _to_studio_response(bundle, await _presign_avatar(bundle.avatar_key, storage))


@router.get("/public/{slug}", response_model=CreatorStudioResponse)
async def get_public_profile(
    slug: str,
    storage: OptionalStorageDep,
    use_case: Annotated[GetPublicCreatorStudio, Depends(get_get_public_creator_studio)],
) -> CreatorStudioResponse:
    bundle = await use_case.execute(slug)
    return _to_studio_response(bundle, await _presign_avatar(bundle.avatar_key, storage))


@router.post(
    "/public/{slug}/bookings",
    response_model=CreatorBookingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_booking(
    slug: str,
    body: CreatorBookingCreateRequest,
    use_case: Annotated[SubmitCreatorBooking, Depends(get_submit_creator_booking)],
) -> CreatorBookingResponse:
    booking = await use_case.execute(
        slug,
        client_name=body.client_name,
        client_email=body.client_email,
        client_phone=body.client_phone,
        company_or_brand=body.company_or_brand,
        service_title=body.service_title,
        event_type=body.event_type,
        preferred_date=body.preferred_date,
        location=body.location,
        budget_range=body.budget_range,
        project_brief=body.project_brief,
    )
    return _to_booking_response(booking)


@router.get("/me/bookings", response_model=list[CreatorBookingResponse])
async def list_my_bookings(
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListCreatorBookings, Depends(get_list_creator_bookings)],
) -> list[CreatorBookingResponse]:
    rows = await use_case.execute(actor)
    return [_to_booking_response(row) for row in rows]


@router.patch("/me/bookings/{booking_id}", response_model=CreatorBookingResponse)
async def update_my_booking_status(
    booking_id: UUID,
    body: CreatorBookingStatusUpdateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[
        UpdateCreatorBookingStatus, Depends(get_update_creator_booking_status)
    ],
) -> CreatorBookingResponse:
    updated = await use_case.execute(actor, booking_id, body.status)
    return _to_booking_response(updated)


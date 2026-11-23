from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.core.exceptions import (
    EntityAlreadyExistsError,
    EntityNotFoundError,
    PermissionDeniedError,
)
from app.domain.entities.creator_studio import (
    BookingRequest,
    BookingStatus,
    CreatorStudio,
    PortfolioItem,
    normalise_slug,
)
from app.domain.entities.user import User, UserRole
from app.domain.repositories.creator_studio_repository import CreatorStudioRepository
from app.domain.repositories.user_repository import UserRepository


@dataclass
class StudioWithPortfolio:
    studio: CreatorStudio
    portfolio_items: list[PortfolioItem]
    avatar_key: str | None = None


def _default_slug_for(user: User) -> str:
    base = f"{user.first_name}-{user.last_name}".strip("-") or "creator"
    try:
        return normalise_slug(base)
    except Exception:
        return f"creator-{str(user.id)[:8]}"


class GetMyCreatorStudio:
    def __init__(self, studios: CreatorStudioRepository) -> None:
        self._studios = studios

    async def execute(self, actor: User) -> StudioWithPortfolio:
        if actor.role not in (UserRole.CREATOR, UserRole.ADMIN):
            raise PermissionDeniedError("Creator access required.")
        studio = await self._studios.get_by_user(actor.id)
        if studio is None:
            studio = CreatorStudio(
                user_id=actor.id,
                slug=_default_slug_for(actor),
                studio_name=actor.full_name or "Cabmora Studio",
                primary_email=actor.email,
                phone=actor.phone or "",
            )
            return StudioWithPortfolio(
                studio=studio,
                portfolio_items=[],
                avatar_key=actor.avatar_key,
            )
        items = await self._studios.list_portfolio(actor.id)
        return StudioWithPortfolio(
            studio=studio,
            portfolio_items=items,
            avatar_key=actor.avatar_key,
        )


@dataclass
class StudioUpdateData:
    slug: str
    is_published: bool
    studio_name: str
    legal_name: str
    specialization: str
    categories: list[str]
    bio: str
    experience_years: int
    team_size: str
    currency: str
    day_rate: int
    tax_id: str
    cover_url: str
    primary_email: str
    secondary_email: str
    phone: str
    allow_sms_alerts: bool
    address: str
    city: str
    country: str
    timezone: str
    socials: dict[str, str]
    landing_config: dict[str, Any]
    portfolio_items: list[dict[str, Any]]


class UpdateMyCreatorStudio:
    def __init__(self, studios: CreatorStudioRepository) -> None:
        self._studios = studios

    async def execute(self, actor: User, data: StudioUpdateData) -> StudioWithPortfolio:
        if actor.role not in (UserRole.CREATOR, UserRole.ADMIN):
            raise PermissionDeniedError("Creator access required.")

        slug = normalise_slug(data.slug)
        existing_with_slug = await self._studios.get_by_slug(slug)
        if existing_with_slug is not None and existing_with_slug.user_id != actor.id:
            raise EntityAlreadyExistsError(
                "That custom profile link is already claimed by another creator."
            )

        studio = CreatorStudio(
            user_id=actor.id,
            slug=slug,
            is_published=data.is_published,
            studio_name=data.studio_name.strip(),
            legal_name=data.legal_name.strip(),
            specialization=data.specialization.strip(),
            categories=list(data.categories),
            bio=data.bio.strip(),
            experience_years=max(0, data.experience_years),
            team_size=data.team_size.strip(),
            currency=data.currency.strip(),
            day_rate=max(0, data.day_rate),
            tax_id=data.tax_id.strip(),
            cover_url=data.cover_url.strip(),
            primary_email=data.primary_email.strip(),
            secondary_email=data.secondary_email.strip(),
            phone=data.phone.strip(),
            allow_sms_alerts=data.allow_sms_alerts,
            address=data.address.strip(),
            city=data.city.strip(),
            country=data.country.strip(),
            timezone=data.timezone.strip(),
            socials=dict(data.socials),
            landing_config=dict(data.landing_config),
            updated_at=datetime.now(timezone.utc),
        )
        saved_studio = await self._studios.save(studio)

        portfolio_entities: list[PortfolioItem] = []
        for idx, raw in enumerate(data.portfolio_items):
            raw_id = raw.get("id")
            try:
                item_id = UUID(str(raw_id)) if raw_id else uuid4()
            except ValueError:
                item_id = uuid4()
            portfolio_entities.append(
                PortfolioItem(
                    id=item_id,
                    creator_id=actor.id,
                    title=str(raw.get("title") or "Untitled Work"),
                    subtitle=str(raw.get("subtitle") or ""),
                    category=str(raw.get("category") or "Editorial"),
                    media_type="video" if raw.get("media_type") == "video" else "photo",
                    media_url=str(raw.get("media_url") or ""),
                    video_url=raw.get("video_url") or None,
                    description=str(raw.get("description") or ""),
                    client_name=str(raw.get("client_name") or ""),
                    location=str(raw.get("location") or ""),
                    shoot_year=str(raw.get("shoot_year") or ""),
                    aspect_ratio=str(raw.get("aspect_ratio") or "portrait"),
                    featured=bool(raw.get("featured", False)),
                    sort_order=int(raw.get("sort_order", idx)),
                    gallery_images=[str(u) for u in (raw.get("gallery_images") or []) if u],
                )
            )
        saved_items = await self._studios.replace_portfolio(actor.id, portfolio_entities)
        return StudioWithPortfolio(
            studio=saved_studio,
            portfolio_items=saved_items,
            avatar_key=actor.avatar_key,
        )


class GetPublicCreatorStudio:
    def __init__(
        self, studios: CreatorStudioRepository, users: UserRepository
    ) -> None:
        self._studios = studios
        self._users = users

    async def execute(self, slug: str) -> StudioWithPortfolio:
        clean_slug = normalise_slug(slug)
        studio = await self._studios.get_by_slug(clean_slug)
        if studio is None or not studio.is_published:
            raise EntityNotFoundError("Creator landing page not found.")
        owner = await self._users.get_by_id(studio.user_id)
        items = await self._studios.list_portfolio(studio.user_id)
        return StudioWithPortfolio(
            studio=studio,
            portfolio_items=items,
            avatar_key=owner.avatar_key if owner else None,
        )


class SubmitCreatorBooking:
    def __init__(self, studios: CreatorStudioRepository) -> None:
        self._studios = studios

    async def execute(
        self,
        slug: str,
        *,
        client_name: str,
        client_email: str,
        client_phone: str = "",
        company_or_brand: str = "",
        service_title: str = "",
        event_type: str = "",
        preferred_date: str = "",
        location: str = "",
        budget_range: str = "",
        project_brief: str = "",
    ) -> BookingRequest:
        clean_slug = normalise_slug(slug)
        studio = await self._studios.get_by_slug(clean_slug)
        if studio is None or not studio.is_published:
            raise EntityNotFoundError("Creator landing page not found.")

        booking = BookingRequest(
            creator_id=studio.user_id,
            creator_slug=studio.slug,
            client_name=client_name.strip(),
            client_email=client_email.strip().lower(),
            client_phone=client_phone.strip(),
            company_or_brand=company_or_brand.strip(),
            service_title=service_title.strip(),
            event_type=event_type.strip(),
            preferred_date=preferred_date.strip(),
            location=location.strip(),
            budget_range=budget_range.strip(),
            project_brief=project_brief.strip(),
        )
        return await self._studios.add_booking(booking)


class ListCreatorBookings:
    def __init__(self, studios: CreatorStudioRepository) -> None:
        self._studios = studios

    async def execute(self, actor: User) -> list[BookingRequest]:
        if actor.role not in (UserRole.CREATOR, UserRole.ADMIN):
            raise PermissionDeniedError("Creator access required.")
        return await self._studios.list_bookings(actor.id)


class UpdateCreatorBookingStatus:
    def __init__(self, studios: CreatorStudioRepository) -> None:
        self._studios = studios

    async def execute(
        self, actor: User, booking_id: UUID, status: BookingStatus
    ) -> BookingRequest:
        if actor.role not in (UserRole.CREATOR, UserRole.ADMIN):
            raise PermissionDeniedError("Creator access required.")
        booking = await self._studios.get_booking(booking_id)
        if booking is None or booking.creator_id != actor.id:
            raise EntityNotFoundError("Booking request not found.")
        booking.status = status
        return await self._studios.save_booking(booking)


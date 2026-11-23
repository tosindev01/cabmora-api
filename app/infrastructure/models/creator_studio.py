from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.creator_studio import (
    BookingRequest,
    BookingStatus,
    CreatorStudio,
    PortfolioItem,
)
from app.infrastructure.database import Base


class CreatorStudioModel(Base):
    """One row per creator. `slug` is the public address, so it is unique."""

    __tablename__ = "creator_studios"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    studio_name: Mapped[str] = mapped_column(String(200), default="")
    legal_name: Mapped[str] = mapped_column(String(200), default="")
    specialization: Mapped[str] = mapped_column(String(200), default="")
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    bio: Mapped[str] = mapped_column(Text, default="")
    experience_years: Mapped[int] = mapped_column(Integer, default=0)
    team_size: Mapped[str] = mapped_column(String(80), default="")
    currency: Mapped[str] = mapped_column(String(20), default="USD ($)")
    day_rate: Mapped[int] = mapped_column(Integer, default=0)
    tax_id: Mapped[str] = mapped_column(String(80), default="")
    cover_url: Mapped[str] = mapped_column(String(1000), default="")
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    primary_email: Mapped[str] = mapped_column(String(255), default="")
    secondary_email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    allow_sms_alerts: Mapped[bool] = mapped_column(Boolean, default=False)
    address: Mapped[str] = mapped_column(String(300), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    country: Mapped[str] = mapped_column(String(120), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="")
    socials: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    landing_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> CreatorStudio:
        return CreatorStudio(
            user_id=UUID(self.user_id),
            slug=self.slug,
            studio_name=self.studio_name,
            legal_name=self.legal_name,
            specialization=self.specialization,
            categories=list(self.categories or []),
            bio=self.bio,
            experience_years=self.experience_years,
            team_size=self.team_size,
            currency=self.currency,
            day_rate=self.day_rate,
            tax_id=self.tax_id,
            cover_url=self.cover_url,
            is_published=self.is_published,
            primary_email=self.primary_email,
            secondary_email=self.secondary_email,
            phone=self.phone,
            allow_sms_alerts=self.allow_sms_alerts,
            address=self.address,
            city=self.city,
            country=self.country,
            timezone=self.timezone,
            socials=dict(self.socials or {}),
            landing_config=dict(self.landing_config or {}),
            updated_at=self.updated_at,
        )

    def apply(self, s: CreatorStudio) -> None:
        self.slug = s.slug
        self.studio_name = s.studio_name
        self.legal_name = s.legal_name
        self.specialization = s.specialization
        self.categories = s.categories
        self.bio = s.bio
        self.experience_years = s.experience_years
        self.team_size = s.team_size
        self.currency = s.currency
        self.day_rate = s.day_rate
        self.tax_id = s.tax_id
        self.cover_url = s.cover_url
        self.is_published = s.is_published
        self.primary_email = s.primary_email
        self.secondary_email = s.secondary_email
        self.phone = s.phone
        self.allow_sms_alerts = s.allow_sms_alerts
        self.address = s.address
        self.city = s.city
        self.country = s.country
        self.timezone = s.timezone
        self.socials = s.socials
        self.landing_config = s.landing_config
        self.updated_at = s.updated_at


class PortfolioItemModel(Base):
    __tablename__ = "creator_portfolio_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    creator_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(300), default="")
    category: Mapped[str] = mapped_column(String(80), default="")
    media_type: Mapped[str] = mapped_column(String(10), default="photo")
    media_url: Mapped[str] = mapped_column(String(1000), default="")
    video_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    client_name: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    shoot_year: Mapped[str] = mapped_column(String(10), default="")
    aspect_ratio: Mapped[str] = mapped_column(String(12), default="portrait")
    featured: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    gallery_images: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> PortfolioItem:
        return PortfolioItem(
            id=UUID(self.id),
            creator_id=UUID(self.creator_id),
            title=self.title,
            subtitle=self.subtitle,
            category=self.category,
            media_type=self.media_type,
            media_url=self.media_url,
            video_url=self.video_url,
            description=self.description,
            client_name=self.client_name,
            location=self.location,
            shoot_year=self.shoot_year,
            aspect_ratio=self.aspect_ratio,
            featured=self.featured,
            sort_order=self.sort_order,
            gallery_images=list(self.gallery_images or []),
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, i: PortfolioItem) -> "PortfolioItemModel":
        return cls(
            id=str(i.id),
            creator_id=str(i.creator_id),
            title=i.title,
            subtitle=i.subtitle,
            category=i.category,
            media_type=i.media_type,
            media_url=i.media_url,
            video_url=i.video_url,
            description=i.description,
            client_name=i.client_name,
            location=i.location,
            shoot_year=i.shoot_year,
            aspect_ratio=i.aspect_ratio,
            featured=i.featured,
            sort_order=i.sort_order,
            gallery_images=i.gallery_images,
            created_at=i.created_at,
        )


class BookingRequestModel(Base):
    __tablename__ = "creator_booking_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    creator_id: Mapped[str] = mapped_column(String(36), index=True)
    creator_slug: Mapped[str] = mapped_column(String(60))
    client_name: Mapped[str] = mapped_column(String(200))
    client_email: Mapped[str] = mapped_column(String(255))
    client_phone: Mapped[str] = mapped_column(String(50), default="")
    company_or_brand: Mapped[str] = mapped_column(String(200), default="")
    service_title: Mapped[str] = mapped_column(String(200), default="")
    event_type: Mapped[str] = mapped_column(String(100), default="")
    preferred_date: Mapped[str] = mapped_column(String(20), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    budget_range: Mapped[str] = mapped_column(String(60), default="")
    project_brief: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), default=BookingStatus.NEW.value, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> BookingRequest:
        return BookingRequest(
            id=UUID(self.id),
            creator_id=UUID(self.creator_id),
            creator_slug=self.creator_slug,
            client_name=self.client_name,
            client_email=self.client_email,
            client_phone=self.client_phone,
            company_or_brand=self.company_or_brand,
            service_title=self.service_title,
            event_type=self.event_type,
            preferred_date=self.preferred_date,
            location=self.location,
            budget_range=self.budget_range,
            project_brief=self.project_brief,
            status=BookingStatus(self.status),
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, b: BookingRequest) -> "BookingRequestModel":
        return cls(
            id=str(b.id),
            creator_id=str(b.creator_id),
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
            status=b.status.value,
            created_at=b.created_at,
        )


from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.domain.entities.creator_studio import BookingStatus


class PortfolioItemPayload(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    subtitle: str = Field(default="", max_length=300)
    category: str = Field(default="Editorial", max_length=80)
    media_type: Literal["photo", "video"] = "photo"
    media_url: str = Field(default="", max_length=1000)
    video_url: str | None = Field(default=None, max_length=1000)
    description: str = Field(default="", max_length=2000)
    client_name: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    shoot_year: str = Field(default="", max_length=10)
    aspect_ratio: Literal["portrait", "landscape", "square", "cinema"] = "portrait"
    featured: bool = False
    sort_order: int = 0
    gallery_images: list[str] = Field(default_factory=list)


class PortfolioItemResponse(BaseModel):
    id: UUID
    creator_id: UUID
    title: str
    subtitle: str
    category: str
    media_type: str
    media_url: str
    video_url: str | None
    description: str
    client_name: str
    location: str
    shoot_year: str
    aspect_ratio: str
    featured: bool
    sort_order: int
    gallery_images: list[str]
    created_at: datetime


class CreatorStudioPayload(BaseModel):
    slug: str = Field(min_length=3, max_length=60)
    is_published: bool = True
    studio_name: str = Field(default="", max_length=200)
    legal_name: str = Field(default="", max_length=200)
    specialization: str = Field(default="", max_length=200)
    categories: list[str] = Field(default_factory=list)
    bio: str = Field(default="", max_length=2000)
    experience_years: int = Field(default=0, ge=0, le=80)
    team_size: str = Field(default="", max_length=80)
    currency: str = Field(default="USD ($)", max_length=20)
    day_rate: int = Field(default=0, ge=0)
    tax_id: str = Field(default="", max_length=80)
    cover_url: str = Field(default="", max_length=1000)
    primary_email: str = Field(default="", max_length=255)
    secondary_email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=50)
    allow_sms_alerts: bool = False
    address: str = Field(default="", max_length=300)
    city: str = Field(default="", max_length=120)
    country: str = Field(default="", max_length=120)
    timezone: str = Field(default="", max_length=64)
    socials: dict[str, str] = Field(default_factory=dict)
    landing_config: dict[str, Any] = Field(default_factory=dict)
    portfolio_items: list[PortfolioItemPayload] = Field(default_factory=list)


class CreatorStudioResponse(BaseModel):
    user_id: UUID
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
    avatar_url: str | None = None
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
    portfolio_items: list[PortfolioItemResponse]
    updated_at: datetime


class CreatorBookingCreateRequest(BaseModel):
    client_name: str = Field(min_length=2, max_length=200)
    client_email: EmailStr
    client_phone: str = Field(default="", max_length=50)
    company_or_brand: str = Field(default="", max_length=200)
    service_title: str = Field(default="", max_length=200)
    event_type: str = Field(default="Editorial / Commercial", max_length=100)
    preferred_date: str = Field(default="", max_length=20)
    location: str = Field(default="", max_length=200)
    budget_range: str = Field(default="", max_length=60)
    project_brief: str = Field(min_length=5, max_length=4000)


class CreatorBookingStatusUpdateRequest(BaseModel):
    status: BookingStatus


class CreatorBookingResponse(BaseModel):
    id: UUID
    creator_slug: str
    client_name: str
    client_email: str
    client_phone: str
    company_or_brand: str
    service_title: str
    event_type: str
    preferred_date: str
    location: str
    budget_range: str
    project_brief: str
    status: BookingStatus
    created_at: datetime


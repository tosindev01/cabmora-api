"""A creator's public studio: profile, landing-page configuration, portfolio
and the booking requests that arrive through it."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError

#: What a slug may look like. Lowercase so `/creators/Sarah` and `/creators/sarah`
#: are one address, and no leading/trailing hyphen so it reads as a name.
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_SLUGS = frozenset({"me", "public", "apply", "admin", "new", "api"})


def normalise_slug(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (raw or "").strip().lower()).strip("-")
    if len(slug) < 3 or len(slug) > 60 or not SLUG_PATTERN.match(slug):
        raise ValidationError("The page address must be 3–60 letters, numbers or hyphens.")
    if slug in RESERVED_SLUGS:
        raise ValidationError("That page address is reserved. Please choose another.")
    return slug


class BookingStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    BOOKED = "booked"
    ARCHIVED = "archived"


@dataclass
class CreatorStudio:
    user_id: UUID
    slug: str
    studio_name: str = ""
    legal_name: str = ""
    specialization: str = ""
    categories: list[str] = field(default_factory=list)
    bio: str = ""
    experience_years: int = 0
    team_size: str = ""
    currency: str = "USD ($)"
    day_rate: int = 0
    tax_id: str = ""
    cover_url: str = ""
    is_published: bool = True
    primary_email: str = ""
    secondary_email: str = ""
    phone: str = ""
    allow_sms_alerts: bool = False
    address: str = ""
    city: str = ""
    country: str = ""
    timezone: str = ""
    socials: dict[str, str] = field(default_factory=dict)
    #: Theme, hero, rich text, packages, FAQs, section toggles. JSON because the
    #: shape is the designer's to evolve and nothing queries inside it.
    landing_config: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class PortfolioItem:
    creator_id: UUID
    title: str
    subtitle: str = ""
    category: str = ""
    media_type: str = "photo"  # photo | video
    media_url: str = ""
    video_url: str | None = None
    description: str = ""
    client_name: str = ""
    location: str = ""
    shoot_year: str = ""
    aspect_ratio: str = "portrait"
    featured: bool = False
    sort_order: int = 0
    gallery_images: list[str] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BookingRequest:
    creator_id: UUID
    creator_slug: str
    client_name: str
    client_email: str
    project_brief: str
    client_phone: str = ""
    company_or_brand: str = ""
    service_title: str = ""
    event_type: str = ""
    preferred_date: str = ""
    location: str = ""
    budget_range: str = ""
    status: BookingStatus = BookingStatus.NEW
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


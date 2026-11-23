from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.creator_studio import (
    BookingRequest,
    CreatorStudio,
    PortfolioItem,
)


class CreatorStudioRepository(ABC):
    @abstractmethod
    async def get_by_user(self, user_id: UUID) -> CreatorStudio | None: ...

    @abstractmethod
    async def get_by_slug(self, slug: str) -> CreatorStudio | None: ...

    @abstractmethod
    async def save(self, studio: CreatorStudio) -> CreatorStudio: ...

    @abstractmethod
    async def list_portfolio(self, creator_id: UUID) -> list[PortfolioItem]: ...

    @abstractmethod
    async def replace_portfolio(
        self, creator_id: UUID, items: list[PortfolioItem]
    ) -> list[PortfolioItem]: ...

    @abstractmethod
    async def add_booking(self, booking: BookingRequest) -> BookingRequest: ...

    @abstractmethod
    async def list_bookings(self, creator_id: UUID) -> list[BookingRequest]: ...

    @abstractmethod
    async def get_booking(self, booking_id: UUID) -> BookingRequest | None: ...

    @abstractmethod
    async def save_booking(self, booking: BookingRequest) -> BookingRequest: ...


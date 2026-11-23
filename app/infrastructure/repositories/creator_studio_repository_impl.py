from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.creator_studio import (
    BookingRequest,
    CreatorStudio,
    PortfolioItem,
)
from app.domain.repositories.creator_studio_repository import CreatorStudioRepository
from app.infrastructure.models.creator_studio import (
    BookingRequestModel,
    CreatorStudioModel,
    PortfolioItemModel,
)


class SqlAlchemyCreatorStudioRepository(CreatorStudioRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_user(self, user_id: UUID) -> CreatorStudio | None:
        model = await self._session.get(CreatorStudioModel, str(user_id))
        return model.to_entity() if model else None

    async def get_by_slug(self, slug: str) -> CreatorStudio | None:
        query = select(CreatorStudioModel).where(CreatorStudioModel.slug == slug)
        model = (await self._session.execute(query)).scalar_one_or_none()
        return model.to_entity() if model else None

    async def save(self, studio: CreatorStudio) -> CreatorStudio:
        model = await self._session.get(CreatorStudioModel, str(studio.user_id))
        if model is None:
            model = CreatorStudioModel(user_id=str(studio.user_id), slug=studio.slug)
            self._session.add(model)
        model.apply(studio)
        await self._session.commit()
        return model.to_entity()

    async def list_portfolio(self, creator_id: UUID) -> list[PortfolioItem]:
        query = (
            select(PortfolioItemModel)
            .where(PortfolioItemModel.creator_id == str(creator_id))
            .order_by(PortfolioItemModel.sort_order.asc(), PortfolioItemModel.created_at.desc())
        )
        rows = (await self._session.execute(query)).scalars().all()
        return [row.to_entity() for row in rows]

    async def replace_portfolio(
        self, creator_id: UUID, items: list[PortfolioItem]
    ) -> list[PortfolioItem]:
        await self._session.execute(
            delete(PortfolioItemModel).where(
                PortfolioItemModel.creator_id == str(creator_id)
            )
        )
        models = [PortfolioItemModel.from_entity(item) for item in items]
        for m in models:
            self._session.add(m)
        await self._session.commit()
        return [m.to_entity() for m in models]

    async def add_booking(self, booking: BookingRequest) -> BookingRequest:
        model = BookingRequestModel.from_entity(booking)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def list_bookings(self, creator_id: UUID) -> list[BookingRequest]:
        query = (
            select(BookingRequestModel)
            .where(BookingRequestModel.creator_id == str(creator_id))
            .order_by(BookingRequestModel.created_at.desc())
        )
        rows = (await self._session.execute(query)).scalars().all()
        return [row.to_entity() for row in rows]

    async def get_booking(self, booking_id: UUID) -> BookingRequest | None:
        model = await self._session.get(BookingRequestModel, str(booking_id))
        return model.to_entity() if model else None

    async def save_booking(self, booking: BookingRequest) -> BookingRequest:
        model = await self._session.get(BookingRequestModel, str(booking.id))
        if model is None:
            model = BookingRequestModel.from_entity(booking)
            self._session.add(model)
        else:
            model.status = booking.status.value
        await self._session.commit()
        return model.to_entity()


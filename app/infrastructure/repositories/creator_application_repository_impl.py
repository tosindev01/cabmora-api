from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.creator_application import (
    ApplicationStatus,
    CreatorApplication,
)
from app.domain.repositories.creator_application_repository import (
    CreatorApplicationRepository,
)
from app.infrastructure.models.creator_application import CreatorApplicationModel


class SqlAlchemyCreatorApplicationRepository(CreatorApplicationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, application: CreatorApplication) -> CreatorApplication:
        model = CreatorApplicationModel.from_entity(application)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def get_by_id(self, application_id: UUID) -> CreatorApplication | None:
        model = await self._session.get(CreatorApplicationModel, str(application_id))
        return model.to_entity() if model else None

    async def get_pending_by_email(self, email: str) -> CreatorApplication | None:
        result = await self._session.execute(
            select(CreatorApplicationModel).where(
                CreatorApplicationModel.email == email.lower(),
                CreatorApplicationModel.status == ApplicationStatus.PENDING.value,
            )
        )
        model = result.scalars().first()
        return model.to_entity() if model else None

    async def list_all(
        self,
        *,
        status: ApplicationStatus | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[CreatorApplication]:
        query = select(CreatorApplicationModel)
        if status is not None:
            query = query.where(CreatorApplicationModel.status == status.value)
        # Newest first: a review queue is worked from the top.
        query = query.order_by(CreatorApplicationModel.created_at.desc())
        result = await self._session.execute(query.limit(limit).offset(offset))
        return [m.to_entity() for m in result.scalars().all()]

    async def count_all(self, *, status: ApplicationStatus | None = None) -> int:
        query = select(func.count()).select_from(CreatorApplicationModel)
        if status is not None:
            query = query.where(CreatorApplicationModel.status == status.value)
        return int((await self._session.execute(query)).scalar_one())

    async def update(self, application: CreatorApplication) -> CreatorApplication:
        model = await self._session.get(CreatorApplicationModel, str(application.id))
        if model is None:
            raise EntityNotFoundError("Application not found")
        # Only the decision changes after submission — what the studio told us
        # is a record of what they said, not a field to edit later.
        model.status = application.status.value
        model.decision_note = application.decision_note
        model.reviewed_by = (
            str(application.reviewed_by) if application.reviewed_by else None
        )
        model.reviewed_at = application.reviewed_at
        model.created_user_id = (
            str(application.created_user_id) if application.created_user_id else None
        )
        await self._session.commit()
        return model.to_entity()

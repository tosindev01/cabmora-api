from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.preferences import UserPreferences
from app.domain.repositories.preferences_repository import PreferencesRepository
from app.infrastructure.models.preferences import UserPreferencesModel
from app.infrastructure.models.user import UserModel


class SqlAlchemyPreferencesRepository(PreferencesRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> UserPreferences:
        model = await self._session.get(UserPreferencesModel, str(user_id))
        # The defaults are the absence of a row, so nothing is written merely
        # because somebody opened the settings page.
        return model.to_entity() if model else UserPreferences()

    async def save(self, user_id: UUID, preferences: UserPreferences) -> UserPreferences:
        model = await self._session.get(UserPreferencesModel, str(user_id))
        if model is None:
            model = UserPreferencesModel(user_id=str(user_id))
            self._session.add(model)
        model.apply(preferences)
        await self._session.commit()
        return model.to_entity()

    async def get_by_email(self, email: str) -> UserPreferences:
        query = (
            select(UserPreferencesModel)
            .join(UserModel, UserModel.id == UserPreferencesModel.user_id)
            .where(UserModel.email == email.strip().lower())
        )
        model = (await self._session.execute(query)).scalar_one_or_none()
        return model.to_entity() if model else UserPreferences()

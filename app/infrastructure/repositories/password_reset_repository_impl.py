from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.password_reset import PasswordResetToken
from app.domain.repositories.password_reset_repository import PasswordResetRepository
from app.infrastructure.models.password_reset import PasswordResetTokenModel


class SqlAlchemyPasswordResetRepository(PasswordResetRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, token: PasswordResetToken) -> PasswordResetToken:
        model = PasswordResetTokenModel.from_entity(token)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def get_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        result = await self._session.execute(
            select(PasswordResetTokenModel).where(
                PasswordResetTokenModel.token_hash == token_hash
            )
        )
        model = result.scalar_one_or_none()
        return model.to_entity() if model else None

    async def mark_used(self, token: PasswordResetToken) -> None:
        model = await self._session.get(PasswordResetTokenModel, str(token.id))
        if model is None:
            return
        model.used_at = datetime.now(timezone.utc)
        await self._session.commit()

    async def invalidate_outstanding(self, user_id: UUID) -> None:
        # One statement rather than a read-then-write loop: this runs on every
        # request for a link, and the set it is retiring is the set that was
        # live a moment ago either way.
        await self._session.execute(
            update(PasswordResetTokenModel)
            .where(
                PasswordResetTokenModel.user_id == str(user_id),
                PasswordResetTokenModel.used_at.is_(None),
            )
            .values(used_at=datetime.now(timezone.utc))
        )
        await self._session.commit()

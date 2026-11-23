from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.invite import InviteToken
from app.domain.repositories.invite_repository import InviteRepository
from app.infrastructure.models.invite import InviteTokenModel


class SqlAlchemyInviteRepository(InviteRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, invite: InviteToken) -> InviteToken:
        model = InviteTokenModel.from_entity(invite)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def get_by_hash(self, token_hash: str) -> InviteToken | None:
        result = await self._session.execute(
            select(InviteTokenModel).where(InviteTokenModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return model.to_entity() if model else None

    async def mark_used(self, invite: InviteToken) -> None:
        model = await self._session.get(InviteTokenModel, str(invite.id))
        if model is None:
            return
        model.used_at = datetime.now(timezone.utc)
        await self._session.commit()

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.unmatched_funds import UnmatchedFunds
from app.domain.repositories.unmatched_funds_repository import (
    UnmatchedFundsRepository,
)
from app.infrastructure.models.unmatched_funds import UnmatchedFundsModel


def _aware(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything is stored UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _entity(row: UnmatchedFundsModel) -> UnmatchedFunds:
    funds = row.to_entity()
    funds.received_at = _aware(funds.received_at)  # type: ignore[assignment]
    funds.handled_at = _aware(funds.handled_at)
    return funds


class SqlAlchemyUnmatchedFundsRepository(UnmatchedFundsRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, funds: UnmatchedFunds) -> UnmatchedFunds:
        existing = await self._session.scalar(
            select(UnmatchedFundsModel).where(
                UnmatchedFundsModel.reference == funds.reference
            )
        )
        # Checked rather than caught. A unique violation would poison the
        # session, and this path runs inside a webhook that must still return
        # 2xx — Stripe retries anything else until it gives up.
        if existing is not None:
            return _entity(existing)
        self._session.add(UnmatchedFundsModel.from_entity(funds))
        await self._session.commit()
        return funds

    async def get_by_id(self, funds_id: UUID) -> UnmatchedFunds | None:
        row = await self._session.get(UnmatchedFundsModel, str(funds_id))
        return _entity(row) if row else None

    async def update(self, funds: UnmatchedFunds) -> UnmatchedFunds:
        row = await self._session.get(UnmatchedFundsModel, str(funds.id))
        if row is None:
            raise EntityNotFoundError("Those funds are no longer on record.")
        # Only what handling writes. The amount, the currency and who it came
        # from are the gateway's account of what happened and are not ours to
        # edit — a row that could be rewritten is not an audit trail.
        row.handled_at = funds.handled_at
        row.handled_by_id = (
            str(funds.handled_by_id) if funds.handled_by_id else None
        )
        row.note = funds.note
        await self._session.commit()
        return funds

    async def list_all(
        self, *, handled: bool | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[UnmatchedFunds], int]:
        where = []
        if handled is True:
            where.append(UnmatchedFundsModel.handled_at.is_not(None))
        elif handled is False:
            where.append(UnmatchedFundsModel.handled_at.is_(None))

        total = await self._session.scalar(
            select(func.count()).select_from(UnmatchedFundsModel).where(*where)
        )
        rows = await self._session.scalars(
            select(UnmatchedFundsModel)
            .where(*where)
            .order_by(UnmatchedFundsModel.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_entity(row) for row in rows], int(total or 0)

    async def count_outstanding(self) -> int:
        total = await self._session.scalar(
            select(func.count())
            .select_from(UnmatchedFundsModel)
            .where(UnmatchedFundsModel.handled_at.is_(None))
        )
        return int(total or 0)

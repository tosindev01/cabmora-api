"""Looking at, and dealing with, money the gateway could not place.

Read-and-annotate only. Nothing here moves money: applying a credit to an
invoice is the gateway's own job the moment a matching payment is opened, and
a button in this console that claimed to do it would be describing a transfer
that never happened.
"""

from uuid import UUID

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.unmatched_funds import UnmatchedFunds
from app.domain.entities.user import User
from app.domain.repositories.unmatched_funds_repository import (
    UnmatchedFundsRepository,
)
from app.domain.repositories.user_repository import UserRepository


class ListUnmatchedFunds:
    def __init__(
        self, funds: UnmatchedFundsRepository, users: UserRepository
    ) -> None:
        self._funds = funds
        self._users = users

    async def execute(
        self, *, handled: bool | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[tuple[UnmatchedFunds, User | None]], int]:
        """Each arrival with whoever it came from, where we can tell.

        Resolved here rather than per row by the router, for the same reason
        the payments list is: a page of thirty would otherwise be thirty extra
        queries to put a name beside an amount.
        """
        rows, total = await self._funds.list_all(
            handled=handled, limit=limit, offset=offset
        )
        people = await self._users.get_many(
            [row.customer_id for row in rows if row.customer_id is not None]
        )
        return [(row, people.get(row.customer_id)) for row in rows], total  # type: ignore[arg-type]


class MarkFundsHandled:
    def __init__(self, funds: UnmatchedFundsRepository) -> None:
        self._funds = funds

    async def execute(
        self, *, funds_id: UUID, actor: User, note: str
    ) -> UnmatchedFunds:
        row = await self._funds.get_by_id(funds_id)
        if row is None:
            raise EntityNotFoundError("Those funds are no longer on record.")
        try:
            row.mark_handled(by=actor.id, note=note)
        except ValueError as exc:
            # The entity owns both rules — an empty note, and handling twice.
            # Translated rather than allowed to escape as a 500.
            raise ValidationError(str(exc)) from exc
        return await self._funds.update(row)

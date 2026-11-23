from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.unmatched_funds import UnmatchedFunds


class UnmatchedFundsRepository(ABC):
    """Arrivals the gateway could not place against an invoice."""

    @abstractmethod
    async def record(self, funds: UnmatchedFunds) -> UnmatchedFunds:
        """Store one arrival, or return the one already stored for it.

        Idempotent on `reference`, and that has to live here rather than in the
        caller: the webhook is redelivered until acknowledged, and two rows for
        one arrival would read as twice the money.
        """

    @abstractmethod
    async def get_by_id(self, funds_id: UUID) -> UnmatchedFunds | None: ...

    @abstractmethod
    async def update(self, funds: UnmatchedFunds) -> UnmatchedFunds: ...

    @abstractmethod
    async def list_all(
        self, *, handled: bool | None = None, limit: int = 50, offset: int = 0
    ) -> tuple[list[UnmatchedFunds], int]:
        """Newest first, with the total for paging.

        `handled=None` means both. The console defaults to the unhandled ones
        — that is the working list — but the handled rows are the audit trail
        and must stay reachable rather than being deleted once dealt with.
        """

    @abstractmethod
    async def count_outstanding(self) -> int:
        """How many nobody has looked at. For the badge on the payments screen."""

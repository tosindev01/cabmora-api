from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.entities.invoice import PaymentStatus
from app.domain.entities.user import UserRole
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.user_repository import UserRepository

#: Ten years of monthly points is not a report, it is a scan. Capped so nobody
#: can ask for one by editing a query string.
MAX_MONTHS = 24


@dataclass
class MonthlyPoint:
    month: str  #: "2026-06"
    customers: int
    creators: int
    #: Confirmed payments net of confirmed refunds, matching Invoice.paid_minor.
    #: The fixture summed gross, which overstates the moment anything is
    #: refunded — and a refund is exactly when someone checks the number.
    revenue_minor: int


class MonthlyReport:
    """User growth and revenue, bucketed by calendar month.

    Bucketed in Python from `created_at` rather than with SQL date functions.
    That is deliberate: SQLite wants `strftime('%Y-%m')` and Postgres wants
    `date_trunc`, so a dialect-specific expression here passes the SQLite test
    suite and fails in production, or the reverse. One definition, both
    databases, and at current volumes the cost is nil.

    When this stops being cheap the answer is a materialised monthly rollup
    table written as payments settle — not a cleverer query.
    """

    def __init__(self, users: UserRepository, invoices: InvoiceRepository) -> None:
        self._users = users
        self._invoices = invoices

    @staticmethod
    def _bucket(value: datetime) -> str:
        # SQLite hands back naive datetimes; treating them as UTC keeps a
        # payment made at 23:30 on the 31st in the month it belongs to.
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return f"{moment.year:04d}-{moment.month:02d}"

    @staticmethod
    def _recent_months(count: int) -> list[str]:
        now = datetime.now(timezone.utc)
        months: list[str] = []
        year, month = now.year, now.month
        for _ in range(count):
            months.append(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                year, month = year - 1, 12
        return list(reversed(months))

    async def execute(self, *, months: int = 6) -> list[MonthlyPoint]:
        span = max(1, min(months, MAX_MONTHS))
        wanted = self._recent_months(span)
        index = {month: i for i, month in enumerate(wanted)}

        customers = [0] * span
        creators = [0] * span
        revenue = [0] * span

        # A month with no activity must still appear, or the chart silently
        # closes the gap and a quiet month reads as a missing one.
        for user in await self._users.list_all(limit=10_000, offset=0):
            slot = index.get(self._bucket(user.created_at))
            if slot is None:
                continue
            if user.role is UserRole.CUSTOMER:
                customers[slot] += 1
            elif user.role is UserRole.CREATOR:
                creators[slot] += 1

        for payment in await self._invoices.list_payments(limit=10_000, offset=0):
            if payment.status is not PaymentStatus.CONFIRMED:
                continue
            slot = index.get(self._bucket(payment.created_at))
            if slot is not None:
                revenue[slot] += payment.net_minor

        return [
            MonthlyPoint(
                month=month,
                customers=customers[i],
                creators=creators[i],
                revenue_minor=revenue[i],
            )
            for i, month in enumerate(wanted)
        ]

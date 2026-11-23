from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.invoice import Invoice, Payment
from app.domain.entities.user import User, UserRole
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class PaymentRow:
    """A payment with the context the payments screen shows beside it.

    Assembled here rather than joined in SQL, matching how projects resolve
    `customer_name`: the repository returns entities, and the names are filled
    in per page with batch lookups. Two extra queries for a page of thirty, not
    sixty more.
    """

    payment: Payment
    invoice: Invoice
    customer_name: str | None
    creator_name: str | None
    project_title: str | None


class ListPayments:
    """Every payment received, newest first.

    A creator sees only payments against invoices they raised; an admin sees
    everything. Customers never reach this — the router keeps them out.
    """

    def __init__(
        self,
        invoices: InvoiceRepository,
        projects: ProjectRepository,
        users: UserRepository,
    ) -> None:
        self._invoices = invoices
        self._projects = projects
        self._users = users

    async def execute(
        self,
        *,
        actor: User,
        limit: int = 30,
        offset: int = 0,
        status: str | None = None,
        project_id: UUID | None = None,
    ) -> tuple[list[PaymentRow], int]:
        issued_by_id = actor.id if actor.role is UserRole.CREATOR else None

        payments = await self._invoices.list_payments(
            limit=limit,
            offset=offset,
            status=status,
            issued_by_id=issued_by_id,
            project_id=project_id,
        )
        total = await self._invoices.count_payments(
            status=status, issued_by_id=issued_by_id, project_id=project_id
        )
        if not payments:
            return [], total

        invoices: dict[UUID, Invoice] = {}
        for payment in payments:
            if payment.invoice_id not in invoices:
                invoice = await self._invoices.get_by_id(payment.invoice_id)
                if invoice is not None:
                    invoices[invoice.id] = invoice

        projects = {
            invoice.project_id: await self._projects.get_by_id(invoice.project_id)
            for invoice in invoices.values()
        }

        # One batch lookup for every name on the page.
        user_ids = {i.customer_id for i in invoices.values()}
        user_ids |= {p.creator_id for p in projects.values() if p and p.creator_id}
        people = await self._users.get_many(user_ids)

        rows: list[PaymentRow] = []
        for payment in payments:
            invoice = invoices.get(payment.invoice_id)
            if invoice is None:
                continue
            project = projects.get(invoice.project_id)
            customer = people.get(invoice.customer_id)
            creator = people.get(project.creator_id) if project and project.creator_id else None
            rows.append(
                PaymentRow(
                    payment=payment,
                    invoice=invoice,
                    customer_name=customer.full_name if customer else None,
                    creator_name=creator.full_name if creator else None,
                    project_title=project.title if project else None,
                )
            )
        return rows, total

"""One invoice as a file somebody can keep, forward or file.

Access is delegated to `GetInvoice` rather than re-derived. The rules there
are subtle — a customer gets "not found" for a draft so that its existence is
not confirmed — and a second copy of them would be a second thing to keep
right.
"""

from uuid import UUID

from app.application.use_cases.billing.list_invoices import GetInvoice
from app.domain.entities.user import User
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.invoice_renderer import (
    BankTransferDetails,
    InvoiceRenderer,
    IssuerIdentity,
    RenderedDocument,
)


class RenderInvoice:
    def __init__(
        self,
        get_invoice: GetInvoice,
        projects: ProjectRepository,
        users: UserRepository,
        renderer: InvoiceRenderer,
        issuer: IssuerIdentity,
        bank: BankTransferDetails | None = None,
    ) -> None:
        self._get_invoice = get_invoice
        self._projects = projects
        self._users = users
        self._renderer = renderer
        self._issuer = issuer
        self._bank = bank

    async def execute(self, *, actor: User, invoice_id: UUID) -> RenderedDocument:
        invoice = await self._get_invoice.execute(actor=actor, invoice_id=invoice_id)

        project = await self._projects.get_by_id(invoice.project_id)
        customer = await self._users.get_by_id(invoice.customer_id)

        return self._renderer.render(
            invoice,
            bank=self._bank,
            issuer=self._issuer,
            # Falls back rather than failing: a deleted customer row must not
            # make an issued invoice unprintable, because the invoice is the
            # record of what was owed regardless.
            bill_to=customer.full_name if customer else "Customer",
            project_title=project.title if project else "Photography services",
        )

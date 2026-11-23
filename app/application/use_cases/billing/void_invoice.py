from uuid import UUID

from app.application.use_cases.billing._access import assert_may_manage
from app.core.exceptions import EntityNotFoundError
from app.domain.entities.invoice import Invoice
from app.domain.entities.user import User
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.project_repository import ProjectRepository


class VoidInvoice:
    def __init__(self, invoices: InvoiceRepository, projects: ProjectRepository) -> None:
        self._invoices = invoices
        self._projects = projects

    async def execute(self, *, actor: User, invoice_id: UUID) -> Invoice:
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")
        assert_may_manage(actor, invoice, await self._projects.get_by_id(invoice.project_id))
        invoice.void()
        return await self._invoices.update(invoice)

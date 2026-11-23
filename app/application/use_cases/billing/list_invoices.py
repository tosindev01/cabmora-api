from uuid import UUID

from app.domain.entities.invoice import Invoice, InvoiceStatus, Settlement
from app.domain.entities.user import User, UserRole
from app.domain.repositories.invoice_repository import InvoiceRepository


class ListInvoices:
    """Scoped by who is asking.

    An admin sees everything; a creator only what they raised; a customer only
    their own, and never a draft — a half-written invoice appearing in someone's
    portal generates a phone call.
    """

    def __init__(self, invoices: InvoiceRepository) -> None:
        self._invoices = invoices

    async def execute(
        self,
        *,
        actor: User,
        limit: int = 30,
        offset: int = 0,
        status: InvoiceStatus | None = None,
        settlement: Settlement | None = None,
        project_id: UUID | None = None,
        customer_id: UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[Invoice], int]:
        issued_by_id = actor.id if actor.role is UserRole.CREATOR else None
        if actor.role is UserRole.CUSTOMER:
            customer_id = actor.id
            if status is None:
                status = InvoiceStatus.ISSUED

        scope = dict(
            status=status,
            settlement=settlement,
            project_id=project_id,
            customer_id=customer_id,
            issued_by_id=issued_by_id,
            search=search,
        )
        items = await self._invoices.list_all(limit=limit, offset=offset, **scope)
        total = await self._invoices.count_all(**scope)
        return items, total


class GetInvoice:
    def __init__(self, invoices: InvoiceRepository) -> None:
        self._invoices = invoices

    async def execute(self, *, actor: User, invoice_id: UUID) -> Invoice:
        from app.core.exceptions import EntityNotFoundError, PermissionDeniedError

        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")

        if actor.role is UserRole.CUSTOMER:
            # Not found rather than forbidden: confirming an invoice exists is
            # itself a leak when the asker has no business knowing.
            if invoice.customer_id != actor.id or invoice.status is InvoiceStatus.DRAFT:
                raise EntityNotFoundError("Invoice not found")
        elif actor.role is UserRole.CREATOR and invoice.issued_by_id != actor.id:
            raise PermissionDeniedError("You cannot view this invoice.")
        return invoice

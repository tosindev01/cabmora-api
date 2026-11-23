from datetime import datetime
from uuid import UUID

from app.application.use_cases.billing._access import assert_may_bill_project
from app.core.exceptions import EntityNotFoundError, ValidationError
from app.domain.entities.invoice import Invoice, InvoiceLineItem
from app.domain.entities.user import User, UserRole
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository


class CreateInvoice:
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
        project_id: UUID,
        due_at: datetime,
        line_items: list[dict],
        customer_id: UUID | None = None,
        #: None means "whatever this project is priced in", which is almost
        #: always what is wanted. A hardcoded GBP default billed a job in
        #: sterling however it had been quoted, and nothing on the invoice
        #: said the two disagreed.
        currency: str | None = None,
        notes: str | None = None,
    ) -> Invoice:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        assert_may_bill_project(actor, project)

        # Default to the project's customer. Billing someone who is not on the
        # project is almost always a mistake, so it has to be stated explicitly.
        target = customer_id or project.customer_id
        if target is None:
            raise ValidationError(
                "This project has no customer yet. Assign one, or name the "
                "customer to invoice."
            )
        customer = await self._users.get_by_id(target)
        if customer is None or customer.role is not UserRole.CUSTOMER:
            raise ValidationError("An invoice must be addressed to a customer account.")

        if not line_items:
            raise ValidationError("An invoice needs at least one line.")

        invoice = Invoice(
            project_id=project.id,
            customer_id=customer.id,
            issued_by_id=actor.id,
            due_at=due_at,
            currency=currency or project.currency,
            notes=notes,
            line_items=[
                InvoiceLineItem(
                    description=item["description"],
                    quantity=item["quantity"],
                    unit_amount_minor=item["unit_amount_minor"],
                )
                for item in line_items
            ],
        )
        return await self._invoices.add(invoice)

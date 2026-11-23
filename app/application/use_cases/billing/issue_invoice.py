import logging
from datetime import datetime, timezone
from uuid import UUID

from app.application.use_cases.billing._access import assert_may_manage
from app.core.exceptions import EntityNotFoundError
from app.domain.entities.invoice import Invoice
from app.domain.entities.user import User
from app.application.use_cases.billing._money import money as _money
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.email_sender import EmailSender
from app.domain.services.invoice_renderer import (
    BankTransferDetails,
    InvoiceRenderer,
    IssuerIdentity,
)

logger = logging.getLogger(__name__)


class IssueInvoice:
    """Turn a draft into a document the customer can see and pay."""

    def __init__(
        self,
        invoices: InvoiceRepository,
        projects: ProjectRepository,
        users: UserRepository,
        email: EmailSender,
        notifier: Notifier,
        public_base_url: str,
        renderer: InvoiceRenderer,
        issuer: IssuerIdentity,
        bank: BankTransferDetails | None = None,
    ) -> None:
        self._invoices = invoices
        self._projects = projects
        self._users = users
        self._email = email
        self._notifier = notifier
        self._base_url = public_base_url.rstrip("/")
        self._renderer = renderer
        self._issuer = issuer
        self._bank = bank

    async def execute(self, *, actor: User, invoice_id: UUID) -> Invoice:
        invoice = await self._invoices.get_by_id(invoice_id)
        if invoice is None:
            raise EntityNotFoundError("Invoice not found")
        project = await self._projects.get_by_id(invoice.project_id)
        assert_may_manage(actor, invoice, project)

        # The number is taken here, not at creation: an abandoned draft must not
        # leave a gap in the sequence.
        number = await self._invoices.next_number(year=datetime.now(timezone.utc).year)
        invoice.issue(number=number)
        issued = await self._invoices.update(invoice)

        # Issuing is the moment the client is asked for money, so it is the
        # moment they are told. Before this, an invoice existed and nobody
        # outside the console had any way to know.
        await self._announce(issued, project)
        return issued

    async def _announce(self, invoice: Invoice, project) -> None:
        customer = await self._users.get_by_id(invoice.customer_id)
        if customer is None:
            return

        # Attached so it can be filed or forwarded without signing in, which
        # is what an accountant actually asks for. Rendered defensively: a
        # layout failure must not stop somebody being told they owe money.
        document = None
        try:
            rendered = self._renderer.render(
                invoice,
                bank=self._bank,
                issuer=self._issuer,
                bill_to=customer.full_name,
                project_title=project.title if project else "Photography services",
            )
            document = (rendered.filename, rendered.data, rendered.content_type)
        except Exception:  # noqa: BLE001
            logger.exception(
                "[billing] could not render a PDF for %s — sending without it",
                invoice.number,
            )

        await self._notifier.invoice_issued(
            customer_id=customer.id,
            invoice_id=invoice.id,
            number=invoice.number or "",
            amount=_money(invoice.due_minor, invoice.currency),
            project_title=project.title if project else "your project",
        )
        try:
            await self._email.send_invoice_issued(
                to=customer.email,
                first_name=customer.first_name,
                project_title=project.title if project else "your project",
                number=invoice.number or "",
                amount=_money(invoice.due_minor, invoice.currency),
                due_at=invoice.due_at,
                invoice_url=f"{self._base_url}/client/projects/{invoice.project_id}",
                document=document,
                bank=self._bank,
            )
        except Exception:  # noqa: BLE001
            # The invoice is issued and numbered. A failed email is chased by
            # a person; rolling the number back would leave a hole in the
            # sequence, which an accountant will ask about.
            logger.exception(
                "[billing] issued %s but could not tell %s", invoice.number, customer.email
            )



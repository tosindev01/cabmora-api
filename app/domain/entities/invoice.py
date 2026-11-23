from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError

#: Everything is integer minor units — pence, cents. Never a float.
#:
#: `Enquiry.budget_min_minor` set this precedent for the stated reason that
#: free text "cannot be reported on"; money owed has the stronger version of
#: that argument. 0.1 + 0.2 != 0.3 in binary floating point, and an invoicing
#: system that is out by a penny is out by a penny in front of an accountant.
DEFAULT_CURRENCY = "GBP"


def is_settled(*, billed_minor: int, paid_minor: int) -> bool:
    """Whether a project has been paid for in full.

    One definition, because several things now turn on it — whether the
    watermark comes off, whether a gallery opens at all, what a share link
    hands out — and three slightly different answers to "are they paid up"
    is how a client ends up holding originals on one screen and proofs on
    another.

    **Nothing billed is not paid.** A project nobody has invoiced reads as
    unsettled, so the finished files cannot be handed over by forgetting to
    send the invoice. An overpayment still settles it; a part payment does
    not.
    """
    return billed_minor > 0 and paid_minor >= billed_minor


class InvoiceStatus(str, Enum):
    """Where the *document* is in its life. Not whether it has been paid.

    Splitting these two axes is deliberate. The designer's fixture used one
    field with `Paid | Outstanding | Overdue`, which cannot express a paid
    invoice that is still a valid issued document, and has no way at all to say
    "cancelled". A voided invoice is not "unpaid", it does not exist as a claim;
    an invoice paid in full is still ISSUED. Settlement is derived separately.
    """

    DRAFT = "draft"    # editable, not a legal document, no number burned
    ISSUED = "issued"  # sent to the customer; immutable from here
    VOID = "void"      # cancelled. You void an invoice, you never delete one


class Settlement(str, Enum):
    """How much of an issued invoice has actually been paid. Always derived."""

    UNPAID = "unpaid"
    PART_PAID = "part_paid"
    PAID = "paid"
    OVERDUE = "overdue"  # unpaid or part-paid, and past due_at


class PaymentMethod(str, Enum):
    STRIPE_CARD = "stripe_card"
    #: A transfer to an account Stripe issued for this customer. Separate from
    #: BANK_TRANSFER because the two settle differently: this one confirms
    #: itself from a webhook, that one waits for an administrator. Merging them
    #: would make "has anybody checked this?" unanswerable for the half that
    #: still needs checking.
    STRIPE_BANK_TRANSFER = "stripe_bank_transfer"
    #: A transfer to Cabmora's own account, reconciled by hand.
    BANK_TRANSFER = "bank_transfer"
    CASH = "cash"
    OTHER = "other"


class PaymentStatus(str, Enum):
    """A payment is only money once someone or something has confirmed it.

    Stripe confirms itself, via webhook. A bank transfer is confirmed by an
    administrator who has seen it land. Both arrive here as PENDING first, so
    "the customer says they have paid" and "the money is in the account" are
    never the same record.

    There is deliberately no REFUNDED member. A refund is not a state a payment
    is in — it is a second movement of money, with its own date, amount, reason
    and author, and there can be several against one payment. Collapsing that
    into a status makes a partial refund inexpressible and throws away the audit
    trail exactly where an auditor will look for it.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"


class RefundStatus(str, Enum):
    PENDING = "pending"      # requested; not yet back with the customer
    CONFIRMED = "confirmed"  # gateway settled it, or an admin sent the transfer
    FAILED = "failed"


class RefundState(str, Enum):
    """How much of a payment has been given back. Always derived."""

    NONE = "none"
    PARTIAL = "partial"
    FULL = "full"


@dataclass
class Refund:
    payment_id: UUID
    amount_minor: int
    #: Why. Shown to the customer and to whoever reconciles the account, so it
    #: is required rather than an optional note nobody fills in.
    reason: str
    issued_by_id: UUID
    status: RefundStatus = RefundStatus.PENDING
    #: Gateway refund id, or the bank reference for a manual return.
    reference: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_settled(self) -> bool:
        return self.status is RefundStatus.CONFIRMED


@dataclass
class InvoiceLineItem:
    description: str
    quantity: int
    unit_amount_minor: int
    id: UUID = field(default_factory=uuid4)

    @property
    def amount_minor(self) -> int:
        return self.quantity * self.unit_amount_minor


@dataclass
class Payment:
    invoice_id: UUID
    amount_minor: int
    method: PaymentMethod
    status: PaymentStatus = PaymentStatus.PENDING
    #: Bank reference, cheque number, or the gateway's own id — a Checkout
    #: Session (`cs_...`) for a card, a PaymentIntent (`pi_...`) for a Stripe
    #: bank transfer. Whichever it is, it has to be the id the webhook will
    #: arrive quoting, or the money cannot be matched to this row.
    reference: str | None = None
    #: Who keyed it in. None when Stripe created it from a webhook.
    recorded_by_id: UUID | None = None
    #: The administrator who verified the money arrived. Required before a
    #: manually recorded payment counts towards settlement.
    confirmed_by_id: UUID | None = None
    confirmed_at: datetime | None = None
    #: Loaded by the repository, like Invoice.payments.
    refunds: list["Refund"] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def counts_towards_settlement(self) -> bool:
        return self.status is PaymentStatus.CONFIRMED

    @property
    def refunded_minor(self) -> int:
        return sum(r.amount_minor for r in self.refunds if r.is_settled)

    @property
    def net_minor(self) -> int:
        """What the customer has actually parted with, after refunds.

        This is what settlement must count. A payment that has been refunded and
        still counts in full leaves an invoice reading PAID with the money back
        in the customer's account.
        """
        if not self.counts_towards_settlement:
            return 0
        return self.amount_minor - self.refunded_minor

    @property
    def refund_state(self) -> "RefundState":
        if self.refunded_minor <= 0:
            return RefundState.NONE
        if self.refunded_minor >= self.amount_minor:
            return RefundState.FULL
        return RefundState.PARTIAL

    @property
    def refundable_minor(self) -> int:
        return max(self.net_minor, 0)

    def refund(self, *, amount_minor: int, reason: str, issued_by_id: UUID) -> "Refund":
        if not self.counts_towards_settlement:
            raise ValidationError("Only a confirmed payment can be refunded.")
        if amount_minor <= 0:
            raise ValidationError("A refund must be for a positive amount.")
        if amount_minor > self.refundable_minor:
            raise ValidationError(
                "That is more than remains on this payment. "
                f"At most {self.refundable_minor} may still be refunded."
            )
        refund = Refund(
            payment_id=self.id,
            amount_minor=amount_minor,
            reason=reason.strip(),
            issued_by_id=issued_by_id,
        )
        self.refunds.append(refund)
        return refund


@dataclass
class Invoice:
    project_id: UUID
    customer_id: UUID
    #: Admin or creator. Creators invoice their own clients, so ownership is a
    #: row-level check in the use case, per CLAUDE.md §4's recommendation for
    #: the four-principal tenancy question while volumes are small.
    issued_by_id: UUID
    due_at: datetime
    line_items: list[InvoiceLineItem] = field(default_factory=list)
    currency: str = DEFAULT_CURRENCY
    status: InvoiceStatus = InvoiceStatus.DRAFT
    #: Burned from a per-year sequence at issue time, never before: a draft that
    #: is discarded must not leave a hole in the numbering.
    number: str | None = None
    issued_at: datetime | None = None
    voided_at: datetime | None = None
    notes: str | None = None
    #: Loaded by the repository. Settlement is computed from these rather than
    #: stored, so a paid total and its payments can never disagree.
    payments: list[Payment] = field(default_factory=list)
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── amounts ──────────────────────────────────────────────
    @property
    def total_minor(self) -> int:
        return sum(item.amount_minor for item in self.line_items)

    @property
    def paid_minor(self) -> int:
        """Net of refunds — see `Payment.net_minor`."""
        return sum(p.net_minor for p in self.payments)

    @property
    def refunded_minor(self) -> int:
        return sum(p.refunded_minor for p in self.payments)

    @property
    def due_minor(self) -> int:
        """Never negative — an overpayment is a refund to handle, not a credit."""
        return max(self.total_minor - self.paid_minor, 0)

    # ── derived state ────────────────────────────────────────
    @property
    def settlement(self) -> Settlement:
        if self.paid_minor >= self.total_minor and self.total_minor > 0:
            return Settlement.PAID
        overdue = self._now() > self._aware(self.due_at)
        if overdue:
            return Settlement.OVERDUE
        return Settlement.PART_PAID if self.paid_minor > 0 else Settlement.UNPAID

    @property
    def is_editable(self) -> bool:
        return self.status is InvoiceStatus.DRAFT

    # ── transitions ──────────────────────────────────────────
    def issue(self, *, number: str, at: datetime | None = None) -> None:
        if self.status is not InvoiceStatus.DRAFT:
            raise ValidationError("Only a draft invoice can be issued.")
        if not self.line_items:
            raise ValidationError("An invoice needs at least one line before it is issued.")
        if self.total_minor <= 0:
            raise ValidationError("An invoice must be for a positive amount.")
        self.number = number
        self.issued_at = at or self._now()
        self.status = InvoiceStatus.ISSUED

    def void(self, *, at: datetime | None = None) -> None:
        """Cancel an issued invoice. Corrections are a void plus a new invoice.

        Editing an issued invoice is what makes numbering untrustworthy — the
        copy the customer holds would no longer match the copy you hold.
        """
        if self.status is InvoiceStatus.VOID:
            raise ValidationError("This invoice is already void.")
        if self.paid_minor > 0:
            raise ValidationError(
                "This invoice has payments against it. Refund them before voiding."
            )
        self.voided_at = at or self._now()
        self.status = InvoiceStatus.VOID

    # ── helpers ──────────────────────────────────────────────
    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        """SQLite hands back naive datetimes; comparing them raises."""
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domain.entities.invoice import (
    InvoiceStatus,
    PaymentMethod,
    PaymentStatus,
    RefundState,
    RefundStatus,
    Settlement,
)


# ── requests ─────────────────────────────────────────────────
class InvoiceLineItemRequest(BaseModel):
    description: str = Field(min_length=1, max_length=500)
    quantity: int = Field(default=1, ge=1, le=10_000)
    #: Minor units. An integer in the contract too — a JSON float would
    #: reintroduce the rounding the schema exists to avoid.
    unit_amount_minor: int = Field(ge=0)


class InvoiceCreateRequest(BaseModel):
    project_id: UUID
    due_at: datetime
    line_items: list[InvoiceLineItemRequest] = Field(min_length=1)
    #: Defaults to the project's customer.
    customer_id: UUID | None = None
    #: Omit to bill in whatever the project is priced in.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    notes: str | None = Field(default=None, max_length=2000)


class InvoiceUpdateRequest(BaseModel):
    due_at: datetime | None = None
    line_items: list[InvoiceLineItemRequest] | None = None
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _reject_an_empty_patch(self) -> "InvoiceUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to change.")
        return self


class RecordPaymentRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=255)


class PaymentInstructionsResponse(BaseModel):
    """Where to send a transfer, or nothing when it is not configured.

    Every field or none: a half-set account is unpayable, so the API returns
    `bank: null` rather than a partial one and the screen says to get in
    touch. Nothing here is ever a placeholder — somebody will pay whatever
    they are shown.
    """

    account_name: str
    bank_name: str
    sort_code: str
    account_number: str
    iban: str | None = None


class RefundRequest(BaseModel):
    amount_minor: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class CheckoutRequest(BaseModel):
    #: Omit to pay the whole outstanding balance.
    amount_minor: int | None = Field(default=None, gt=0)


# ── responses ────────────────────────────────────────────────
class InvoiceLineItemResponse(BaseModel):
    id: UUID
    description: str
    quantity: int
    unit_amount_minor: int
    amount_minor: int


class RefundResponse(BaseModel):
    id: UUID
    payment_id: UUID
    amount_minor: int
    reason: str
    status: RefundStatus
    issued_by_id: UUID
    reference: str | None
    created_at: datetime


class PaymentResponse(BaseModel):
    id: UUID
    invoice_id: UUID
    amount_minor: int
    #: After confirmed refunds. This is what settlement counts.
    net_minor: int
    method: PaymentMethod
    status: PaymentStatus
    refund_state: RefundState
    refundable_minor: int
    reference: str | None
    recorded_by_id: UUID | None
    confirmed_by_id: UUID | None
    confirmed_at: datetime | None
    created_at: datetime
    refunds: list[RefundResponse]


class InvoiceResponse(BaseModel):
    id: UUID
    number: str | None
    project_id: UUID
    customer_id: UUID
    issued_by_id: UUID
    currency: str

    #: Where the document is. Stored.
    status: InvoiceStatus
    #: How much has been paid. Derived, never stored — see the entity module.
    settlement: Settlement

    total_minor: int
    paid_minor: int
    due_minor: int
    refunded_minor: int

    due_at: datetime
    issued_at: datetime | None
    created_at: datetime

    #: Published for the same reason as ProjectResponse.allowed_next_stages: the
    #: UI offers only legal actions rather than discovering them via a 422.
    allowed_actions: list[str]


class InvoiceDetailResponse(InvoiceResponse):
    line_items: list[InvoiceLineItemResponse]
    payments: list[PaymentResponse]
    notes: str | None


class CheckoutResponse(BaseModel):
    checkout_url: str
    reference: str
    amount_minor: int


class BankTransferFundingResponse(BaseModel):
    """An account issued to this customer, for this invoice.

    Not interchangeable with `PaymentInstructionsResponse`, despite looking
    alike. That one is Cabmora's own account and is the same for everybody;
    this one is issued per customer by the gateway, settles itself, and must
    never be cached or shown to anybody else.
    """

    reference: str
    account_holder_name: str
    sort_code: str
    account_number: str
    #: Quote this on the transfer. The gateway matches on it first and falls
    #: back to the exact amount, so leaving it off is how one client's money
    #: settles another client's invoice.
    payment_reference: str
    amount_minor: int
    hosted_instructions_url: str | None = None


class UnmatchedFundsResponse(BaseModel):
    """Money the gateway holds against a customer and against no invoice.

    Carries no invoice id because there is none — that is the whole condition
    being reported. `customer_name` is null when the gateway customer matches
    no account here, which is a real case rather than a lookup that failed.
    """

    id: UUID
    amount_minor: int
    currency: str
    received_at: datetime
    gateway_customer_reference: str
    customer_id: UUID | None
    customer_name: str | None
    customer_email: str | None
    handled_at: datetime | None
    note: str | None


class MarkFundsHandledRequest(BaseModel):
    #: Required, and not merely non-empty: this is the only record of what
    #: happened to somebody's money.
    note: str = Field(min_length=1, max_length=500)


class PaymentRowResponse(PaymentResponse):
    """A payment plus the invoice and people it belongs to.

    Denormalised for display only, resolved per page — the payments screen shows
    a client and a creator beside every amount, and fetching those per row would
    be sixty extra requests for a page of thirty.
    """

    invoice_number: str | None
    invoice_total_minor: int
    customer_name: str | None
    creator_name: str | None
    project_title: str | None
    currency: str


class BillingStatsResponse(BaseModel):
    currency: str
    outstanding_minor: int
    paid_minor: int
    pending_minor: int
    refunded_minor: int
    overdue_count: int

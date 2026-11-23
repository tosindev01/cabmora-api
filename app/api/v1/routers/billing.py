"""Invoices, payments and refunds.

Three routers in one module because they are one aggregate:

- `admin_router`  — admins and creators: raise, issue, void, record, refund
- `router`        — the customer's own invoices, and paying one
- `webhook_router`— the gateway callback. No auth dependency by design; the
                    signature *is* the authentication.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response, status

from app.api.deps import (
    RenderInvoiceDep,
    ConfirmPaymentDep,
    ConfirmRefundDep,
    CreateInvoiceDep,
    CurrentActiveUserDep,
    PaymentsDep,
    GetInvoiceDep,
    HandleGatewayEventDep,
    InvoiceRepoDep,
    IssueInvoiceDep,
    ListInvoicesDep,
    ListPaymentsDep,
    ListUnmatchedFundsDep,
    MarkFundsHandledDep,
    PaginationDep,
    RecordPaymentDep,
    get_bank_details,
    RefundPaymentDep,
    StartBankTransferDep,
    StartCheckoutDep,
    VoidInvoiceDep,
)
from app.api.schemas.billing import (
    BankTransferFundingResponse,
    MarkFundsHandledRequest,
    UnmatchedFundsResponse,
    BillingStatsResponse,
    CheckoutRequest,
    CheckoutResponse,
    InvoiceCreateRequest,
    InvoiceDetailResponse,
    InvoiceLineItemResponse,
    InvoiceResponse,
    PaymentResponse,
    PaymentRowResponse,
    PaymentInstructionsResponse,
    RecordPaymentRequest,
    RefundRequest,
    RefundResponse,
)
from app.api.schemas.page import Page
from app.core.content_disposition import attachment
from app.domain.entities.invoice import (
    Invoice,
    InvoiceStatus,
    Payment,
    PaymentStatus,
    Refund,
    Settlement,
)
from app.domain.entities.user import User, UserRole

admin_router = APIRouter(prefix="/admin", tags=["billing-admin"])
router = APIRouter(tags=["billing"])
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── serialisation ────────────────────────────────────────────
def _allowed_actions(invoice: Invoice, actor: User) -> list[str]:
    """What this actor may legally do next, so the UI need not re-derive it."""
    if invoice.status is InvoiceStatus.DRAFT:
        return ["edit", "issue", "delete"] if actor.role is not UserRole.CUSTOMER else []
    if invoice.status is InvoiceStatus.VOID:
        return []
    if actor.role is UserRole.CUSTOMER:
        return ["pay"] if invoice.due_minor > 0 else []
    actions = ["record_payment"] if invoice.due_minor > 0 else []
    if invoice.paid_minor == 0:
        actions.append("void")
    if invoice.paid_minor > 0:
        actions.append("refund")
    return actions


def _refund_out(refund: Refund) -> RefundResponse:
    return RefundResponse(**vars(refund))


def _payment_out(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        invoice_id=payment.invoice_id,
        amount_minor=payment.amount_minor,
        net_minor=payment.net_minor,
        method=payment.method,
        status=payment.status,
        refund_state=payment.refund_state,
        refundable_minor=payment.refundable_minor,
        reference=payment.reference,
        recorded_by_id=payment.recorded_by_id,
        confirmed_by_id=payment.confirmed_by_id,
        confirmed_at=payment.confirmed_at,
        created_at=payment.created_at,
        refunds=[_refund_out(r) for r in payment.refunds],
    )


def _invoice_out(invoice: Invoice, actor: User) -> InvoiceResponse:
    return InvoiceResponse(
        id=invoice.id,
        number=invoice.number,
        project_id=invoice.project_id,
        customer_id=invoice.customer_id,
        issued_by_id=invoice.issued_by_id,
        currency=invoice.currency,
        status=invoice.status,
        settlement=invoice.settlement,
        total_minor=invoice.total_minor,
        paid_minor=invoice.paid_minor,
        due_minor=invoice.due_minor,
        refunded_minor=invoice.refunded_minor,
        due_at=invoice.due_at,
        issued_at=invoice.issued_at,
        created_at=invoice.created_at,
        allowed_actions=_allowed_actions(invoice, actor),
    )


def _invoice_detail(invoice: Invoice, actor: User) -> InvoiceDetailResponse:
    return InvoiceDetailResponse(
        **_invoice_out(invoice, actor).model_dump(),
        notes=invoice.notes,
        line_items=[
            InvoiceLineItemResponse(
                id=i.id,
                description=i.description,
                quantity=i.quantity,
                unit_amount_minor=i.unit_amount_minor,
                amount_minor=i.amount_minor,
            )
            for i in invoice.line_items
        ],
        payments=[_payment_out(p) for p in invoice.payments],
    )


# ── admin + creator ──────────────────────────────────────────
@admin_router.post(
    "/invoices", response_model=InvoiceDetailResponse, status_code=status.HTTP_201_CREATED
)
async def create_invoice(
    body: InvoiceCreateRequest, actor: PaymentsDep, create: CreateInvoiceDep
) -> InvoiceDetailResponse:
    invoice = await create.execute(
        actor=actor,
        project_id=body.project_id,
        due_at=body.due_at,
        line_items=[i.model_dump() for i in body.line_items],
        customer_id=body.customer_id,
        currency=body.currency,
        notes=body.notes,
    )
    return _invoice_detail(invoice, actor)


@admin_router.get("/invoices", response_model=Page[InvoiceResponse])
async def list_invoices_admin(
    actor: PaymentsDep,
    page: PaginationDep,
    listing: ListInvoicesDep,
    status_filter: InvoiceStatus | None = None,
    settlement: Settlement | None = None,
    project_id: UUID | None = None,
    customer_id: UUID | None = None,
    q: str | None = None,
) -> Page[InvoiceResponse]:
    items, total = await listing.execute(
        actor=actor,
        limit=page.limit,
        offset=page.offset,
        status=status_filter,
        settlement=settlement,
        project_id=project_id,
        customer_id=customer_id,
        search=q,
    )
    return Page(
        items=[_invoice_out(i, actor) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@admin_router.get("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_invoice_admin(
    invoice_id: UUID, actor: PaymentsDep, get: GetInvoiceDep
) -> InvoiceDetailResponse:
    return _invoice_detail(await get.execute(actor=actor, invoice_id=invoice_id), actor)


@admin_router.post("/invoices/{invoice_id}/issue", response_model=InvoiceDetailResponse)
async def issue_invoice(
    invoice_id: UUID, actor: PaymentsDep, issue: IssueInvoiceDep
) -> InvoiceDetailResponse:
    return _invoice_detail(await issue.execute(actor=actor, invoice_id=invoice_id), actor)


@admin_router.post("/invoices/{invoice_id}/void", response_model=InvoiceDetailResponse)
async def void_invoice(
    invoice_id: UUID, actor: PaymentsDep, void: VoidInvoiceDep
) -> InvoiceDetailResponse:
    return _invoice_detail(await void.execute(actor=actor, invoice_id=invoice_id), actor)


@admin_router.post(
    "/invoices/{invoice_id}/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def record_payment(
    invoice_id: UUID,
    body: RecordPaymentRequest,
    actor: PaymentsDep,
    record: RecordPaymentDep,
) -> PaymentResponse:
    payment = await record.execute(
        actor=actor,
        invoice_id=invoice_id,
        amount_minor=body.amount_minor,
        method=body.method,
        reference=body.reference,
    )
    return _payment_out(payment)


@admin_router.post("/payments/{payment_id}/confirm", response_model=PaymentResponse)
async def confirm_payment(
    payment_id: UUID, actor: PaymentsDep, confirm: ConfirmPaymentDep
) -> PaymentResponse:
    return _payment_out(await confirm.execute(actor=actor, payment_id=payment_id))


@admin_router.post(
    "/payments/{payment_id}/refunds",
    response_model=RefundResponse,
    status_code=status.HTTP_201_CREATED,
)
async def refund_payment(
    payment_id: UUID, body: RefundRequest, actor: PaymentsDep, refund: RefundPaymentDep
) -> RefundResponse:
    return _refund_out(
        await refund.execute(
            actor=actor,
            payment_id=payment_id,
            amount_minor=body.amount_minor,
            reason=body.reason,
        )
    )


@admin_router.post("/refunds/{refund_id}/confirm", response_model=RefundResponse)
async def confirm_refund(
    refund_id: UUID, actor: PaymentsDep, confirm: ConfirmRefundDep
) -> RefundResponse:
    return _refund_out(await confirm.execute(actor=actor, refund_id=refund_id))


@admin_router.get("/payments", response_model=Page[PaymentRowResponse])
async def list_payments_admin(
    actor: PaymentsDep,
    page: PaginationDep,
    listing: ListPaymentsDep,
    status_filter: PaymentStatus | None = None,
    project_id: UUID | None = None,
) -> Page[PaymentRowResponse]:
    rows, total = await listing.execute(
        actor=actor,
        limit=page.limit,
        offset=page.offset,
        status=status_filter.value if status_filter else None,
        project_id=project_id,
    )
    return Page(
        items=[
            PaymentRowResponse(
                **_payment_out(row.payment).model_dump(),
                invoice_number=row.invoice.number,
                invoice_total_minor=row.invoice.total_minor,
                currency=row.invoice.currency,
                customer_name=row.customer_name,
                creator_name=row.creator_name,
                project_title=row.project_title,
            )
            for row in rows
        ],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@admin_router.get("/billing/stats", response_model=BillingStatsResponse)
async def billing_stats(
    actor: PaymentsDep,
    listing: ListInvoicesDep,
    customer_id: UUID | None = None,
) -> BillingStatsResponse:
    """Money in scope, optionally for one client.

    `customer_id` narrows it to a single account, which is what the user
    detail screen asks for — and it reuses this computation rather than
    adding a second one, so "outstanding" cannot come to mean two things.
    """
    # Over every invoice in scope. Fine at these volumes; when it stops being
    # fine the answer is aggregate SQL, not a cached counter that can drift.
    invoices, _ = await listing.execute(
        actor=actor, limit=10_000, offset=0, customer_id=customer_id
    )
    live = [i for i in invoices if i.status is InvoiceStatus.ISSUED]
    pending = sum(
        p.amount_minor
        for i in live
        for p in i.payments
        if p.status is PaymentStatus.PENDING
    )
    return BillingStatsResponse(
        currency="GBP",
        outstanding_minor=sum(i.due_minor for i in live),
        paid_minor=sum(i.paid_minor for i in live),
        pending_minor=pending,
        refunded_minor=sum(i.refunded_minor for i in invoices),
        overdue_count=sum(1 for i in live if i.settlement is Settlement.OVERDUE),
    )


# ── customer ─────────────────────────────────────────────────
@router.get("/billing/summary", response_model=BillingStatsResponse)
async def my_billing_summary(
    actor: CurrentActiveUserDep, listing: ListInvoicesDep
) -> BillingStatsResponse:
    """What this client owes, totalled here rather than in the browser.

    `ListInvoices` already scopes a customer to their own invoices, so the
    same computation the admin dashboard runs answers this one — the figures
    cannot disagree because there is one of them.

    Summed server-side on purpose. Money is added up by the API or not at
    all; a total computed in a browser from a page of invoices is one that
    silently goes wrong the day the page stops being the whole list.
    """
    invoices, _ = await listing.execute(actor=actor, limit=10_000, offset=0)
    live = [i for i in invoices if i.status is InvoiceStatus.ISSUED]
    pending = sum(
        p.amount_minor
        for i in live
        for p in i.payments
        if p.status is PaymentStatus.PENDING
    )
    return BillingStatsResponse(
        currency="GBP",
        outstanding_minor=sum(i.due_minor for i in live),
        paid_minor=sum(i.paid_minor for i in live),
        #: What they have told us about but we have not confirmed. Shown so a
        #: client who has just paid does not see an unchanged balance and
        #: assume nobody noticed.
        pending_minor=pending,
        refunded_minor=sum(i.refunded_minor for i in invoices),
        overdue_count=sum(1 for i in live if i.settlement is Settlement.OVERDUE),
    )


@router.get("/invoices", response_model=Page[InvoiceResponse])
async def list_my_invoices(
    actor: CurrentActiveUserDep, page: PaginationDep, listing: ListInvoicesDep
) -> Page[InvoiceResponse]:
    items, total = await listing.execute(
        actor=actor, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[_invoice_out(i, actor) for i in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/invoices/{invoice_id}", response_model=InvoiceDetailResponse)
async def get_my_invoice(
    invoice_id: UUID, actor: CurrentActiveUserDep, get: GetInvoiceDep
) -> InvoiceDetailResponse:
    return _invoice_detail(await get.execute(actor=actor, invoice_id=invoice_id), actor)


# ── money nobody can place ───────────────────────────────────
@admin_router.get("/unmatched-funds", response_model=Page[UnmatchedFundsResponse])
async def list_unmatched_funds(
    actor: PaymentsDep,
    page: PaginationDep,
    listing: ListUnmatchedFundsDep,
    handled: bool | None = None,
) -> Page[UnmatchedFundsResponse]:
    """Transfers the gateway holds against a customer and against no invoice.

    Behind the payments permission rather than admin-only: whoever reconciles
    the account is exactly who needs this, and it is the same door as the
    payments list it sits beside.
    """
    rows, total = await listing.execute(
        handled=handled, limit=page.limit, offset=page.offset
    )
    return Page(
        items=[_funds_out(funds, payer) for funds, payer in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@admin_router.post(
    "/unmatched-funds/{funds_id}/handled", response_model=UnmatchedFundsResponse
)
async def mark_funds_handled(
    funds_id: UUID,
    body: MarkFundsHandledRequest,
    actor: PaymentsDep,
    mark: MarkFundsHandledDep,
) -> UnmatchedFundsResponse:
    """Record that somebody looked into it — not that the money moved.

    Nothing here touches the gateway. Applying a credit to an invoice is the
    gateway's own job once a matching payment exists, and an endpoint that
    claimed otherwise would be describing a transfer that never happened.
    """
    funds = await mark.execute(funds_id=funds_id, actor=actor, note=body.note)
    return _funds_out(funds, None)


@router.get("/billing/payment-instructions", response_model=PaymentInstructionsResponse | None)
async def payment_instructions(
    _: CurrentActiveUserDep,
) -> PaymentInstructionsResponse | None:
    """Where a transfer should go. Null until the account is configured.

    Its own endpoint rather than a field on every invoice: it is one fact
    about the business, not a fact about each bill, and repeating it down a
    list of eight invoices is noise.
    """
    # Called directly rather than injected: it reads settings and takes no
    # dependencies, and wrapping a frozen dataclass in `Depends` only asks
    # pydantic to build a schema for something that is never a request body.
    bank = get_bank_details()
    if bank is None:
        return None
    return PaymentInstructionsResponse(
        account_name=bank.account_name,
        bank_name=bank.bank_name,
        sort_code=bank.sort_code,
        account_number=bank.account_number,
        iban=bank.iban,
    )


@router.post(
    "/invoices/{invoice_id}/payments",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def declare_my_payment(
    invoice_id: UUID,
    body: RecordPaymentRequest,
    actor: CurrentActiveUserDep,
    use_case: RecordPaymentDep,
) -> PaymentResponse:
    """Tell us you have sent a payment.

    Changes nothing by itself. The row lands PENDING, exactly as one entered
    by staff does, and only an administrator confirming it moves any money in
    the system — nothing is settled, no watermark lifts and no delivery gate
    opens until then.

    Worth having rather than making the client email: a transfer sent on a
    Friday is otherwise invisible until somebody reconciles the bank, and the
    client has no way to show they have done their part.
    """
    return _payment_out(
        await use_case.declare(
            actor=actor,
            invoice_id=invoice_id,
            amount_minor=body.amount_minor,
            method=body.method,
            reference=body.reference,
        )
    )


@router.post("/invoices/{invoice_id}/checkout", response_model=CheckoutResponse)
async def start_checkout(
    invoice_id: UUID,
    body: CheckoutRequest,
    actor: CurrentActiveUserDep,
    checkout: StartCheckoutDep,
) -> CheckoutResponse:
    hosted, amount = await checkout.execute(
        actor=actor, invoice_id=invoice_id, amount_minor=body.amount_minor
    )
    return CheckoutResponse(
        checkout_url=hosted.url, reference=hosted.reference, amount_minor=amount
    )


@router.post(
    "/invoices/{invoice_id}/bank-transfer",
    response_model=BankTransferFundingResponse,
)
async def start_bank_transfer(
    invoice_id: UUID,
    body: CheckoutRequest,
    actor: CurrentActiveUserDep,
    transfer: StartBankTransferDep,
) -> BankTransferFundingResponse:
    """Issue this customer an account the gateway reconciles for us.

    POST rather than GET although it mostly reads: it creates a customer at
    the gateway the first time and opens a payment every time, and a GET that
    does either is a GET somebody's prefetcher will fire.
    """
    funding, _ = await transfer.execute(
        actor=actor, invoice_id=invoice_id, amount_minor=body.amount_minor
    )
    return BankTransferFundingResponse(
        reference=funding.reference,
        account_holder_name=funding.account_holder_name,
        sort_code=funding.sort_code,
        account_number=funding.account_number,
        payment_reference=funding.payment_reference,
        amount_minor=funding.amount_minor,
        hosted_instructions_url=funding.hosted_instructions_url,
    )


def _funds_out(funds, payer) -> UnmatchedFundsResponse:
    return UnmatchedFundsResponse(
        id=funds.id,
        amount_minor=funds.amount_minor,
        currency=funds.currency,
        received_at=funds.received_at,
        gateway_customer_reference=funds.gateway_customer_reference,
        customer_id=funds.customer_id,
        customer_name=payer.full_name if payer else None,
        customer_email=payer.email if payer else None,
        handled_at=funds.handled_at,
        note=funds.note,
    )


# ── gateway ──────────────────────────────────────────────────
@webhook_router.post("/stripe")
async def stripe_webhook(request: Request, handle: HandleGatewayEventDep) -> dict:
    """Always 200 once the signature verifies.

    A non-2xx makes Stripe retry, and retrying will not fix an event we cannot
    match to a payment. The idempotency table means a retry is harmless anyway.
    """
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    await handle.execute(payload=payload, signature=signature)
    return {"received": True}


def _pdf(document, *, save: bool = False) -> Response:
    """The invoice, to look at or to keep.

    `inline` is still the default: most people want to read it before
    deciding, and every PDF viewer offers a download of its own.

    `save` exists because a control labelled "Download PDF" that opens a
    viewer is a control that lies, and the caller is the only one who knows
    which of the two it is offering. Decided server-side rather than with a
    `download` attribute on the anchor so the answer does not depend on the
    browser honouring it.
    """
    return Response(
        content=document.data,
        media_type=document.content_type,
        headers={"Content-Disposition": attachment(document.filename) if save
                 else f'inline; filename="{document.filename}"'},
    )


@admin_router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf_admin(
    invoice_id: UUID, actor: CurrentActiveUserDep, render: RenderInvoiceDep
) -> Response:
    """The invoice as a PDF, for whoever raised it."""
    return _pdf(await render.execute(actor=actor, invoice_id=invoice_id))


@router.get("/invoices/{invoice_id}/pdf")
async def my_invoice_pdf(
    invoice_id: UUID,
    actor: CurrentActiveUserDep,
    render: RenderInvoiceDep,
    save: bool = Query(False, description="Serve as a download rather than inline"),
) -> Response:
    """The invoice as a PDF, for the customer it was raised against.

    Generated per request rather than stored: the document is derived
    entirely from the invoice, and a stored copy is one that can disagree
    with the record after a payment lands.
    """
    return _pdf(await render.execute(actor=actor, invoice_id=invoice_id), save=save)

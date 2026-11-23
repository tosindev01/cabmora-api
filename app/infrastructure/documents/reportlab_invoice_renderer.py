"""An invoice as a PDF, drawn with ReportLab.

ReportLab rather than an HTML-to-PDF engine on purpose. WeasyPrint and its
relatives need cairo and pango present in the image; this is pure Python on
top of a dependency the project already carries for renditions, so the Docker
build stays a `pip install` and nothing else.

The layout is plain by intention. An invoice is read by somebody deciding
whether to pay it and later by an accountant reconciling it, and both want the
number, the amount and the date to be findable in one glance.
"""

from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdfcanvas

from app.core.display import DISPLAY_TZ
from app.domain.entities.invoice import Invoice, InvoiceStatus, Settlement
from app.domain.services.invoice_renderer import (
    BankTransferDetails,
    InvoiceRenderer,
    IssuerIdentity,
    RenderedDocument,
)

#: The studio's gold, as close as a document without the brand fonts gets.
GOLD = colors.Color(0.788, 0.659, 0.416)
INK = colors.Color(0.067, 0.055, 0.039)
FAINT = colors.Color(0.45, 0.43, 0.40)
RULE = colors.Color(0.87, 0.85, 0.81)

PAGE_W, PAGE_H = A4
MARGIN = 20 * mm

#: Nothing in the body is drawn below this. The footer lives under it, and a
#: table that runs past it does not wrap — it draws at a negative coordinate,
#: off the paper, silently. An itemised invoice losing its own total that way
#: is the worst kind of bug on a financial document.
FLOOR = MARGIN + 70

#: What the totals block needs. Checked before starting it rather than after.
TOTALS_HEIGHT = 80

_SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}

#: How a settlement state should read to a person holding the paper.
_STATE = {
    Settlement.PAID: "PAID IN FULL",
    Settlement.PART_PAID: "PART PAID",
    Settlement.OVERDUE: "OVERDUE",
    Settlement.UNPAID: "",
}


def money(minor: int, currency: str) -> str:
    symbol = _SYMBOLS.get(currency.upper())
    body = f"{minor / 100:,.2f}"
    return f"{symbol}{body}" if symbol else f"{body} {currency.upper()}"


def _date(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"{value.astimezone(DISPLAY_TZ):%-d %B %Y}"


class ReportLabInvoiceRenderer(InvoiceRenderer):
    def render(
        self,
        invoice: Invoice,
        *,
        issuer: IssuerIdentity,
        bill_to: str,
        project_title: str,
        bank: BankTransferDetails | None = None,
    ) -> RenderedDocument:
        buffer = BytesIO()
        c = pdfcanvas.Canvas(buffer, pagesize=A4)
        c.setTitle(f"Invoice {invoice.number or 'draft'}")
        c.setAuthor(issuer.name)

        y = self._header(c, invoice, issuer)
        y = self._parties(c, y, issuer, bill_to, project_title)
        y = self._lines(c, y, invoice)
        y = self._totals(c, y, invoice, issuer)
        y = self._how_to_pay(c, y, invoice, bank)
        self._footer(c, invoice, issuer)

        c.showPage()
        c.save()
        return RenderedDocument(
            data=buffer.getvalue(),
            content_type="application/pdf",
            # Named by its number so a folder of these sorts usefully.
            filename=f"Invoice-{invoice.number or 'draft'}.pdf",
        )

    # ── sections ─────────────────────────────────────────────────────────

    def _header(self, c, invoice: Invoice, issuer: IssuerIdentity) -> float:
        y = PAGE_H - MARGIN

        c.setFillColor(GOLD)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(MARGIN, y, "C A B M O R A   M E D I A")

        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 26)
        c.drawRightString(PAGE_W - MARGIN, y - 4, "INVOICE")

        c.setFillColor(FAINT)
        c.setFont("Helvetica", 10)
        c.drawRightString(PAGE_W - MARGIN, y - 20, invoice.number or "DRAFT — not issued")

        # A state worth seeing before reading anything else.
        stamp = _STATE.get(invoice.settlement, "")
        if stamp:
            c.setFillColor(GOLD if invoice.settlement is Settlement.PAID else colors.Color(0.6, 0.27, 0.15))
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(PAGE_W - MARGIN, y - 36, stamp)

        y -= 46
        c.setStrokeColor(RULE)
        c.setLineWidth(0.7)
        c.line(MARGIN, y, PAGE_W - MARGIN, y)
        return y - 18

    def _parties(self, c, y: float, issuer: IssuerIdentity, bill_to: str, project_title: str) -> float:
        right = PAGE_W / 2 + 6 * mm

        c.setFillColor(FAINT)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(MARGIN, y, "FROM")
        c.drawString(right, y, "BILL TO")

        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGIN, y - 14, issuer.name)
        c.drawString(right, y - 14, bill_to)

        c.setFont("Helvetica", 9)
        c.setFillColor(FAINT)
        line = y - 27
        for part in issuer.address.split(", "):
            c.drawString(MARGIN, line, part)
            line -= 11
        c.drawString(MARGIN, line, issuer.email)
        line -= 11
        c.drawString(MARGIN, line, issuer.phone)

        # Only what is true. Both are omitted entirely when unset.
        if issuer.company_number:
            line -= 11
            c.drawString(MARGIN, line, f"Company no. {issuer.company_number}")
        if issuer.vat_number:
            line -= 11
            c.drawString(MARGIN, line, f"VAT no. {issuer.vat_number}")

        c.drawString(right, y - 27, project_title)
        return min(line, y - 27) - 24

    def _lines(self, c, y: float, invoice: Invoice) -> float:
        qty_x = PAGE_W - MARGIN - 95 * mm
        unit_x = PAGE_W - MARGIN - 55 * mm
        amount_x = PAGE_W - MARGIN

        self._columns(c, y)
        y -= 24

        c.setFont("Helvetica", 10)
        for item in invoice.line_items:
            if y < FLOOR:
                y = self._continue(c, invoice)
            c.setFillColor(INK)
            # Truncated rather than wrapped: a description long enough to wrap
            # belongs in the notes, and a silently reflowed table is worse to
            # reconcile than a clipped one.
            c.drawString(MARGIN, y, item.description[:58])
            c.drawRightString(qty_x, y, str(item.quantity))
            c.drawRightString(unit_x, y, money(item.unit_amount_minor, invoice.currency))
            c.drawRightString(amount_x, y, money(item.amount_minor, invoice.currency))
            y -= 8
            c.setStrokeColor(RULE)
            c.line(MARGIN, y, PAGE_W - MARGIN, y)
            y -= 16

        return y - 6

    def _continue(self, c, invoice: Invoice) -> float:
        """Start a fresh page and say what it belongs to.

        A second sheet with no invoice number on it is a page that gets
        separated from the first and never reunited.
        """
        c.showPage()
        y = PAGE_H - MARGIN

        c.setFillColor(FAINT)
        c.setFont("Helvetica", 9)
        c.drawString(MARGIN, y, f"Invoice {invoice.number or 'draft'} — continued")
        y -= 16
        c.setStrokeColor(RULE)
        c.setLineWidth(0.7)
        c.line(MARGIN, y, PAGE_W - MARGIN, y)
        y -= 18

        self._columns(c, y)
        c.setFont("Helvetica", 10)
        return y - 24

    @staticmethod
    def _columns(c, y: float) -> None:
        qty_x = PAGE_W - MARGIN - 95 * mm
        unit_x = PAGE_W - MARGIN - 55 * mm

        c.setFillColor(FAINT)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(MARGIN, y, "DESCRIPTION")
        c.drawRightString(qty_x, y, "QTY")
        c.drawRightString(unit_x, y, "UNIT")
        c.drawRightString(PAGE_W - MARGIN, y, "AMOUNT")
        c.setStrokeColor(RULE)
        c.setLineWidth(0.7)
        c.line(MARGIN, y - 8, PAGE_W - MARGIN, y - 8)

    def _totals(self, c, y: float, invoice: Invoice, issuer: IssuerIdentity) -> float:
        # The one block that must never be orphaned — an invoice whose amount
        # due fell off the bottom is worse than no invoice.
        if y - TOTALS_HEIGHT < FLOOR:
            y = self._continue(c, invoice) + 24

        label_x = PAGE_W - MARGIN - 55 * mm
        value_x = PAGE_W - MARGIN

        rows: list[tuple[str, str, bool]] = [
            ("Total", money(invoice.total_minor, invoice.currency), False)
        ]
        if invoice.paid_minor:
            rows.append(("Paid", f"-{money(invoice.paid_minor, invoice.currency)}", False))
        rows.append(("Amount due", money(invoice.due_minor, invoice.currency), True))

        for label, value, emphasis in rows:
            if emphasis:
                y -= 4
                c.setStrokeColor(RULE)
                c.line(label_x - 10 * mm, y + 12, value_x, y + 12)
            c.setFillColor(INK if emphasis else FAINT)
            c.setFont("Helvetica-Bold" if emphasis else "Helvetica", 12 if emphasis else 10)
            c.drawRightString(label_x, y, label)
            c.drawRightString(value_x, y, value)
            y -= 18

        # VAT registration is a fact about the issuer, not about the invoice.
        if not issuer.vat_number:
            # Said plainly so nobody wonders whether VAT was forgotten.
            c.setFillColor(FAINT)
            c.setFont("Helvetica-Oblique", 8)
            c.drawRightString(value_x, y, "No VAT charged.")
            y -= 14

        return y

    def _how_to_pay(
        self, c, y: float, invoice: Invoice, bank: BankTransferDetails | None
    ) -> float:
        """Where to send the money, and what to write on it.

        The reference is the operationally important line, not the account
        number. A transfer arrives as an amount from a name, and without the
        invoice number on it somebody has to guess which of four outstanding
        invoices it settles — which they will eventually guess wrong.

        Nothing is printed for a draft (it is not payable), for a settled
        invoice (it is not owed), or where the account has not been
        configured. The last of those says to get in touch instead: an
        invented sort code is worse than none.
        """
        if invoice.status is not InvoiceStatus.ISSUED or invoice.due_minor <= 0:
            return y

        y -= 26
        if y < FLOOR + 60:
            y = self._continue(c, invoice) + 24

        c.setFillColor(FAINT)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(MARGIN, y, "HOW TO PAY")
        y -= 16

        if bank is None:
            c.setFillColor(INK)
            c.setFont("Helvetica", 9.5)
            c.drawString(
                MARGIN, y, "Please get in touch and we will send payment details."
            )
            return y - 14

        c.setFillColor(INK)
        c.setFont("Helvetica", 9.5)
        c.drawString(MARGIN, y, f"Bank transfer to {bank.account_name}")
        y -= 13
        c.setFillColor(FAINT)
        c.setFont("Helvetica", 9)
        c.drawString(
            MARGIN,
            y,
            f"{bank.bank_name}  ·  Sort code {bank.sort_code}  ·  "
            f"Account {bank.account_number}",
        )
        y -= 13
        if bank.iban:
            c.drawString(MARGIN, y, f"IBAN {bank.iban}")
            y -= 13

        if invoice.number:
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(MARGIN, y, f"Please quote {invoice.number} as the reference.")
            y -= 14
        return y

    def _footer(self, c, invoice: Invoice, issuer: IssuerIdentity) -> None:
        y = MARGIN + 34

        c.setStrokeColor(RULE)
        c.line(MARGIN, y + 22, PAGE_W - MARGIN, y + 22)

        c.setFillColor(FAINT)
        c.setFont("Helvetica", 9)
        issued = _date(invoice.issued_at) if invoice.issued_at else "not yet issued"
        c.drawString(MARGIN, y + 8, f"Issued {issued}    Due {_date(invoice.due_at)}")

        if invoice.notes:
            c.drawString(MARGIN, y - 6, invoice.notes[:110])

        c.setFont("Helvetica", 8)
        c.drawRightString(
            PAGE_W - MARGIN, y - 6, f"{issuer.name} · {issuer.email}"
        )

"""Turning an invoice into a document somebody can keep.

A port for the same reason email and imaging are ports: the use case that
decides *who may have* an invoice should not know how a PDF is laid out, and
swapping the generator should not reach into billing.

The document is deliberately produced on demand rather than stored. An
invoice's PDF is entirely derived from the invoice, and a stored copy is one
that can disagree with the record after a payment lands — which is the version
a client would wave at you.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class IssuerIdentity:
    """Who the invoice is from, in the legal sense.

    Carried in rather than hardcoded because these are facts about a company,
    not about this codebase — and because the two optional ones must not be
    invented. A company number appears on an invoice only once the company is
    registered, and **a VAT line appears only for a business that is actually
    VAT registered**: showing VAT you are not entitled to charge is not a
    formatting mistake.
    """

    name: str
    address: str
    email: str
    phone: str
    company_number: str | None = None
    vat_number: str | None = None


@dataclass(frozen=True)
class BankTransferDetails:
    """Where a transfer should actually go.

    All of it or none of it — see `configured`. A half-filled block puts an
    account number with no sort code on a legal document, which is unpayable
    and reads as a mistake the client has to chase.

    Never defaulted to a placeholder. Somebody will pay whatever is printed,
    and an invented sort code on an invoice is worse than no instructions at
    all: the money goes nowhere, or the invoice looks fraudulent, and both of
    those cost more than the inconvenience of an unset field.
    """

    account_name: str
    bank_name: str
    sort_code: str
    account_number: str
    iban: str | None = None

    @classmethod
    def configured(cls, settings) -> "BankTransferDetails | None":
        """The details, or None when they have not all been set."""
        parts = (
            settings.bank_account_name,
            settings.bank_name,
            settings.bank_sort_code,
            settings.bank_account_number,
        )
        if not all(parts):
            return None
        return cls(*parts, iban=settings.bank_iban)  # type: ignore[arg-type]


@dataclass(frozen=True)
class RenderedDocument:
    data: bytes
    content_type: str
    filename: str


class InvoiceRenderer(ABC):
    @abstractmethod
    def render(
        self,
        invoice,
        *,
        issuer: IssuerIdentity,
        bill_to: str,
        project_title: str,
        bank: "BankTransferDetails | None" = None,
    ) -> RenderedDocument:
        """One invoice as a file. `invoice` is a domain `Invoice`.

        `bank` is omitted where the account has not been configured, and the
        document then says to get in touch rather than printing half an
        account or a made-up one.
        """

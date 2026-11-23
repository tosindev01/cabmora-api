"""Money that arrived and belongs to nobody's invoice yet.

The gateway reconciles a transfer by matching it to an open payment. When it
cannot — the client sent too little, or sent it before the invoice existed, or
quoted no reference and the amount matched nothing — the money is real, it is
sitting in that customer's balance at the gateway, and **no screen in Cabmora
would otherwise show it**. The client believes they have paid. The invoice says
unpaid. Nobody is looking anywhere that would reconcile the two.

So this is a notice, not a payment. It is deliberately *not* a `Payment`:

* a `Payment` belongs to an invoice, and the defining property of this money
  is that it belongs to none;
* a `Payment` that counts towards settlement would release the photographs,
  and nothing here has been checked by anybody;
* and the resolution is usually not ours to make — the gateway applies the
  funds itself the moment a matching payment is opened, at which point the
  normal webhook settles the invoice and this row is only ever history.

`handled` says a person has looked, and says nothing about where the money
went. That distinction has to survive into the console copy: a button that
reads "resolve" on a row about somebody's four thousand pounds will be read as
having moved it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4


@dataclass
class UnmatchedFunds:
    """One arrival of money the gateway could not place."""

    #: The gateway's id for the customer it landed against. Always known —
    #: the account it arrived in *is* the customer — which is why this can be
    #: recorded at all.
    gateway_customer_reference: str
    amount_minor: int
    currency: str
    #: The gateway's own id for this credit. The deduplication key: webhooks
    #: are redelivered until acknowledged, and a notice that multiplies on
    #: retry is a notice people learn to disbelieve.
    reference: str
    #: Our customer, where the reference resolves to one. None is not a bug:
    #: a transfer can arrive against a customer created by hand in the
    #: gateway's dashboard, and the row is still worth showing.
    customer_id: UUID | None = None
    received_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    #: Who looked, and when. Both or neither.
    handled_at: datetime | None = None
    handled_by_id: UUID | None = None
    #: What they found. Required to mark it handled, like `Refund.reason`: the
    #: question asked three months later is "what happened to this", and an
    #: empty note answers it no better than an unhandled row.
    note: str | None = None
    id: UUID = field(default_factory=uuid4)

    @property
    def is_handled(self) -> bool:
        return self.handled_at is not None

    def mark_handled(self, *, by: UUID, note: str, at: datetime | None = None) -> None:
        """Record that somebody looked into it.

        Refuses an empty note rather than storing a blank one, and refuses to
        re-handle: the second note would overwrite the first, and the first is
        the one written while anybody still remembered.
        """
        if self.is_handled:
            raise ValueError("These funds have already been dealt with.")
        if not note.strip():
            raise ValueError("Say what happened to the money.")
        self.handled_at = at or datetime.now(timezone.utc)
        self.handled_by_id = by
        self.note = note.strip()

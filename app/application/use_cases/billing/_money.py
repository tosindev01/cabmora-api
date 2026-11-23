"""Minor units to something a person reads.

Lifted out of `issue_invoice` when a second caller appeared. Not localised —
one studio, one currency per invoice, and a wrong-looking total is worse than a
plain one. The renderer carries its own copy on purpose: a PDF is typeset and
has different constraints from a line in a notification.
"""


def money(minor: int, currency: str) -> str:
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper(), "")
    return (
        f"{symbol}{minor / 100:,.2f}"
        if symbol
        else f"{minor / 100:,.2f} {currency.upper()}"
    )

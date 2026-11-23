"""What somebody has chosen about how the platform behaves for them.

One row per account, created on first write rather than at registration: the
defaults are the absence of a row, so nothing has to be backfilled when a new
preference is added and nobody is carrying a stale copy of yesterday's default.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.core.exceptions import ValidationError


class NotificationKind(str, Enum):
    """An email somebody may decline.

    Only three, and that is the point: this enum is the complete list of what
    can be turned off. Everything absent from it is unmutable **by
    construction** rather than by a rule someone has to remember —

      · invites and password resets, because muting them locks a person out of
        their own account;
      · "your photographs are ready", because it is the one message the whole
        product exists to deliver, and a client who silenced it would simply
        never learn their work was done.

    Cabmora's list also named "payments" and "system updates". Neither sends an
    email today, and a switch that gates nothing is the same lie as a switch
    that does nothing — they go in when the emails behind them do.
    """

    INVOICES = "invoices"
    BOOKINGS = "bookings"
    MESSAGES = "messages"


#: ISO 4217. A short list rather than every code on earth: each one has to be
#: formattable and meaningful on an invoice, and "we support 180 currencies" is
#: a claim nobody can honour.
SUPPORTED_CURRENCIES = ("GBP", "USD", "EUR", "NGN", "CAD", "AUD")

SUPPORTED_LANGUAGES = ("en-GB",)

DATE_FORMATS = ("DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD")


@dataclass
class UserPreferences:
    currency: str = "GBP"
    language: str = "en-GB"
    #: An IANA name, not an offset. An offset is wrong twice a year.
    timezone: str = "Europe/London"
    date_format: str = "DD/MM/YYYY"
    #: What this person has turned **off**.
    #:
    #: Muted rather than enabled, so adding a fourth kind later switches it on
    #: for everybody without a migration that writes a row per account — and so
    #: an empty set means "send me everything", which is the right default for
    #: a row that does not exist yet.
    muted: set[NotificationKind] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.currency not in SUPPORTED_CURRENCIES:
            raise ValidationError(f"{self.currency} is not a currency we can bill in.")
        if self.language not in SUPPORTED_LANGUAGES:
            raise ValidationError(f"{self.language} is not a language we publish in yet.")
        if self.date_format not in DATE_FORMATS:
            raise ValidationError(f"{self.date_format} is not a date format we offer.")
        if not self.timezone.strip():
            raise ValidationError("A time zone is needed.")

    def wants(self, kind: NotificationKind) -> bool:
        return kind not in self.muted

from pydantic import BaseModel


class PublicStatsResponse(BaseModel):
    """Counted figures for the public homepage.

    Every field is nullable and null means "we cannot stand behind a number
    here" — the page omits that figure rather than printing a zero.
    """

    clients_served: int | None
    events_covered: int | None
    years_active: int | None

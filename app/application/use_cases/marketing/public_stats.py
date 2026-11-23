"""The figures on the public homepage, counted rather than claimed.

These were invented: "500+ Happy Clients", "8 Years of Excellence", "200+
Events Covered" and "4.9 ★ Google Rating" sat on the live site as fixtures,
with the rating asserted while no Google integration exists.

**A figure that cannot be counted is not returned.** Every field here is
nullable and the homepage omits what it has no value for, because a marketing
page showing "0 Events Covered" is worse than one showing nothing — and a
number nobody can stand behind is worse than both.

The trade this makes, which is worth stating plainly: these count the
*platform*, not the *business*. Cabmora shot weddings before any of this
existed, and those jobs are not in the database. The numbers here will
therefore read lower than the truth about the company until enough work has
run through the product. That is the price of only publishing what can be
verified.
"""

from dataclasses import dataclass
from datetime import date

from app.domain.repositories.project_repository import ProjectRepository


@dataclass
class PublicFigures:
    #: Distinct customers with at least one completed project. Null when none.
    clients_served: int | None
    #: Projects that reached delivered or closed. Null when none.
    events_covered: int | None
    #: Years since Cabmora started trading. Null when the founding year is not
    #: configured — it is a fact about the company, not something the database
    #: can know, so it is not invented here.
    years_active: int | None


class GetPublicStats:
    def __init__(
        self, projects: ProjectRepository, founded_year: int | None = None
    ) -> None:
        self._projects = projects
        self._founded_year = founded_year

    async def execute(self, *, today: date | None = None) -> PublicFigures:
        clients = await self._projects.count_clients_served()
        events = await self._projects.count_completed()

        years: int | None = None
        if self._founded_year:
            elapsed = (today or date.today()).year - self._founded_year
            # Zero would render as "0 Years of Excellence" in its first year,
            # which reads as a bug rather than as a new business.
            years = elapsed if elapsed > 0 else None

        return PublicFigures(
            clients_served=clients or None,
            events_covered=events or None,
            years_active=years,
        )

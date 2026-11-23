"""Public figures for the marketing site.

Unauthenticated by design — it is the homepage. Nothing here identifies anybody:
three aggregate counts, no names, no projects, no money.
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_public_stats
from app.api.schemas.stats import PublicStatsResponse
from app.application.use_cases.marketing.public_stats import GetPublicStats

router = APIRouter(prefix="/stats", tags=["marketing"])


@router.get("", response_model=PublicStatsResponse)
async def public_stats(
    use_case: Annotated[GetPublicStats, Depends(get_public_stats)],
) -> PublicStatsResponse:
    figures = await use_case.execute()
    return PublicStatsResponse(
        clients_served=figures.clients_served,
        events_covered=figures.events_covered,
        years_active=figures.years_active,
    )

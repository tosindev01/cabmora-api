"""Review moderation, and the one public read of it.

Two routers with nothing in common but the table: one is the queue an
administrator works through, the other is what an unauthenticated visitor to
the marketing site is allowed to see.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    ReviewsDep,
    PaginationDep,
    get_list_published_reviews,
    get_moderate_reviews,
)
from app.api.schemas.page import Page
from app.api.schemas.review import PublicReviewResponse, ReviewResponse
from app.application.use_cases.reviews.moderate_reviews import (
    ListPublishedReviews,
    ModerateReviews,
    ReviewRow,
)
from app.domain.entities.rating import Rating, ReviewStatus

admin_router = APIRouter(prefix="/admin/reviews", tags=["admin: reviews"])
public_router = APIRouter(prefix="/reviews", tags=["reviews"])


def _row(row: ReviewRow) -> ReviewResponse:
    return ReviewResponse(
        id=row.rating.id,
        project_id=row.rating.project_id,
        project_title=row.project_title,
        client_name=row.client_name,
        client_email=row.client_email,
        stars=row.rating.stars,
        words=row.rating.words,
        may_publish=row.rating.may_publish,
        status=row.rating.status,
        moderated_at=row.rating.moderated_at,
        created_at=row.rating.created_at,
        updated_at=row.rating.updated_at,
    )


def _moderated(rating: Rating) -> ReviewResponse:
    """After a publish or hide the names are already on screen, so the row is
    returned without a second round of lookups to fetch them again."""
    return ReviewResponse(
        id=rating.id,
        project_id=rating.project_id,
        project_title=None,
        client_name=None,
        client_email=None,
        stars=rating.stars,
        words=rating.words,
        may_publish=rating.may_publish,
        status=rating.status,
        moderated_at=rating.moderated_at,
        created_at=rating.created_at,
        updated_at=rating.updated_at,
    )


@admin_router.get("", response_model=Page[ReviewResponse])
async def list_reviews(
    _: ReviewsDep,
    page: PaginationDep,
    use_case: Annotated[ModerateReviews, Depends(get_moderate_reviews)],
    status: ReviewStatus | None = Query(default=None),
) -> Page[ReviewResponse]:
    """The moderation queue. Admin only: deciding what the business quotes
    publicly is not a coordinator's call."""
    rows, total = await use_case.list_reviews(
        status=status, limit=page.limit, offset=page.offset
    )
    return Page[ReviewResponse](
        items=[_row(row) for row in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@admin_router.post("/{review_id}/publish", response_model=ReviewResponse)
async def publish_review(
    review_id: UUID,
    actor: ReviewsDep,
    use_case: Annotated[ModerateReviews, Depends(get_moderate_reviews)],
) -> ReviewResponse:
    """Allow it on the public site.

    Refused where the client did not offer it. Moderation decides what we
    show, not what we are allowed to show.
    """
    return _moderated(await use_case.publish(review_id=review_id, actor=actor))


@admin_router.post("/{review_id}/hide", response_model=ReviewResponse)
async def hide_review(
    review_id: UUID,
    actor: ReviewsDep,
    use_case: Annotated[ModerateReviews, Depends(get_moderate_reviews)],
) -> ReviewResponse:
    """Take it down, or decline to put it up.

    Always allowed, including on a review the client offered: consent to be
    quoted is not an obligation to quote. The record stays either way — there
    is no delete here on purpose.
    """
    return _moderated(await use_case.hide(review_id=review_id, actor=actor))


@admin_router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: UUID,
    actor: ReviewsDep,
    use_case: Annotated[ModerateReviews, Depends(get_moderate_reviews)],
) -> None:
    """Remove a review for good.

    The heavier of the two controls. Hiding keeps what somebody wrote and
    stops showing it; this destroys it, and is for a review that should never
    have existed rather than one you disagree with.
    """
    await use_case.delete(review_id=review_id, actor=actor)


@public_router.get("", response_model=list[PublicReviewResponse])
async def list_public_reviews(
    use_case: Annotated[ListPublishedReviews, Depends(get_list_published_reviews)],
    limit: int = Query(default=12, ge=1, le=50),
) -> list[PublicReviewResponse]:
    """What real clients said, for the marketing site.

    Published *and* consented, both checked in the query rather than here.
    Returns an empty list when there is nothing — which the site shows as
    nothing, rather than falling back to invented quotes.
    """
    return [
        PublicReviewResponse(
            stars=row.rating.stars,
            words=row.rating.words,
            name=row.client_name,
            created_at=row.rating.created_at,
        )
        for row in await use_case.execute(limit=limit)
    ]

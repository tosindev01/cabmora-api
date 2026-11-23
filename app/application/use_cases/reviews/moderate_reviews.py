"""Deciding which of the things clients said may be quoted.

Moderation here is about **words, never scores**. A hidden review still counts
towards an average: the alternative is an average over the reviews we happened
to like, which is precisely the number that would then be shown to people
deciding whether to book.

Nothing is ever deleted. A removed review is somebody's words destroyed by the
business they are about, and `HIDDEN` says the same thing without discarding
the record.
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.rating import Rating, ReviewStatus
from app.domain.entities.user import User
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.rating_repository import RatingRepository
from app.domain.repositories.user_repository import UserRepository


@dataclass(frozen=True)
class ReviewRow:
    """A review with the people and work it is about, for the queue."""

    rating: Rating
    client_name: str | None
    #: Shown in the moderation queue so a reviewer can be identified and, if
    #: it comes to it, contacted. Never leaves the admin side.
    client_email: str | None
    project_title: str | None


class ModerateReviews:
    def __init__(
        self,
        ratings: RatingRepository,
        projects: ProjectRepository,
        users: UserRepository,
    ) -> None:
        self._ratings = ratings
        self._projects = projects
        self._users = users

    async def list_reviews(
        self,
        *,
        status: ReviewStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ReviewRow], int]:
        ratings = await self._ratings.list_all(status=status, limit=limit, offset=offset)
        total = await self._ratings.count_all(status=status)
        if not ratings:
            return [], total

        # One lookup each for the page rather than one per row.
        people = await self._users.get_many({r.customer_id for r in ratings})
        projects = {}
        for rating in ratings:
            if rating.project_id not in projects:
                projects[rating.project_id] = await self._projects.get_by_id(
                    rating.project_id
                )

        rows = [
            ReviewRow(
                rating=rating,
                client_name=(
                    people[rating.customer_id].full_name
                    if rating.customer_id in people
                    else None
                ),
                client_email=(
                    people[rating.customer_id].email
                    if rating.customer_id in people
                    else None
                ),
                project_title=(
                    projects[rating.project_id].title
                    if projects.get(rating.project_id)
                    else None
                ),
            )
            for rating in ratings
        ]
        return rows, total

    async def publish(self, *, review_id: UUID, actor: User) -> Rating:
        rating = await self._get(review_id)
        # Raises where the client never offered it. The check lives on the
        # entity so every caller gets it, including whatever calls this next.
        rating.publish(actor.id)
        return await self._ratings.update(rating)

    async def hide(self, *, review_id: UUID, actor: User) -> Rating:
        rating = await self._get(review_id)
        rating.hide(actor.id)
        return await self._ratings.update(rating)

    async def delete(self, *, review_id: UUID, actor: User) -> None:
        """Remove a review for good.

        Separate from `hide`, and the heavier of the two: hiding keeps what
        somebody wrote and merely stops showing it, while this destroys it.
        Worth having for a review that should never have existed — abuse, a
        test row, something posted in error — and worth reaching for second.
        """
        await self._get(review_id)
        await self._ratings.delete(review_id)

    async def _get(self, review_id: UUID) -> Rating:
        rating = await self._ratings.get_by_id(review_id)
        if rating is None:
            raise EntityNotFoundError("Review not found")
        return rating


class ListPublishedReviews:
    """What the public site may show.

    Its own use case rather than a flag on the moderation one: this is the
    only unauthenticated read of anything a client wrote, and it should be
    impossible to call it with a status that widens it.
    """

    def __init__(self, ratings: RatingRepository, users: UserRepository) -> None:
        self._ratings = ratings
        self._users = users

    async def execute(self, limit: int = 12) -> list[ReviewRow]:
        ratings = await self._ratings.list_published(limit=limit)
        if not ratings:
            return []
        people = await self._users.get_many({r.customer_id for r in ratings})
        return [
            ReviewRow(
                rating=rating,
                # First name and initial only. A testimonial does not need
                # somebody's full legal name on a public page, and they
                # consented to being quoted rather than to being indexed.
                client_name=_public_name(people.get(rating.customer_id)),
                # Never on the public side.
                client_email=None,
                project_title=None,
            )
            for rating in ratings
        ]


def _public_name(user) -> str | None:
    if user is None:
        return None
    surname = user.last_name.strip()
    initial = f" {surname[0]}." if surname else ""
    return f"{user.first_name.strip()}{initial}".strip() or None

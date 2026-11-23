"""The client scoring the finished work.

Theirs alone, like approval and for the same reason: a score entered by the
studio on the client's behalf is not feedback, it is marketing, and the moment
one of these is posted publicly the difference matters.

Deliberately not gated on approval. Somebody can be delighted with the
photographs and still be mid-amendment about one of them, and refusing a
rating until the paperwork is in order loses the rating rather than improving
it. It is gated on the work having been shown at all, which is the earliest
point at which there is anything to judge.
"""

from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.project import ProjectStage
from app.domain.entities.rating import Rating
from app.domain.entities.user import User
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.rating_repository import RatingRepository

#: Before this there is nothing to have an opinion about. DRAFT, BOOKED and
#: SHOOTING are all "we have not shown you anything yet".
RATEABLE_FROM = {
    ProjectStage.EDITING,
    ProjectStage.IN_REVIEW,
    ProjectStage.DELIVERED,
    ProjectStage.CLOSED,
}


class RateProject:
    def __init__(
        self, projects: ProjectRepository, ratings: RatingRepository
    ) -> None:
        self._projects = projects
        self._ratings = ratings

    async def execute(
        self,
        *,
        project_id: UUID,
        actor: User,
        stars: int,
        words: str = "",
        may_publish: bool = False,
    ) -> Rating:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if project.customer_id is None or project.customer_id != actor.id:
            raise PermissionDeniedError("Only the client can rate this work.")
        if project.stage not in RATEABLE_FROM:
            raise ValidationError("There is nothing to rate yet.")

        existing = await self._ratings.get_for_project(project_id)
        if existing is not None:
            # Revised rather than refused. A client who rates in the first
            # flush and then changes their mind should be able to say so, and
            # a score nobody can change is one people hesitate to leave.
            existing.revise(stars=stars, words=words)
            # Consent travels with the words. Changing what you said and
            # leaving an old permission attached would publish a sentence
            # nobody agreed to.
            existing.may_publish = may_publish
            return await self._ratings.update(existing)

        return await self._ratings.add(
            Rating(
                project_id=project_id,
                customer_id=actor.id,
                stars=stars,
                words=words,
                may_publish=may_publish,
            )
        )

    async def current(self, *, project_id: UUID, actor: User) -> Rating | None:
        """What they said last time, so the stars open where they left them."""
        project = await self._projects.get_by_id(project_id)
        if project is None or not project.is_visible_to(actor):
            raise EntityNotFoundError("Project not found")
        return await self._ratings.get_for_project(project_id)

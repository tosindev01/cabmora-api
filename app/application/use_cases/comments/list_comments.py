"""The conversation on a project, in one read.

Returned flat rather than grouped by photograph: the admin's view is
chronological ("what has the client said today"), and the gallery can filter
by `asset_id` itself without a second shape to keep in step.
"""

from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.comment import Comment
from app.domain.entities.user import User
from app.domain.repositories.comment_repository import CommentRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository

from ._author import CommentWithAuthor, author_info_of


class ListComments:
    def __init__(
        self,
        projects: ProjectRepository,
        comments: CommentRepository,
        users: UserRepository,
    ) -> None:
        self._projects = projects
        self._comments = comments
        self._users = users

    async def execute(self, project_id: UUID, actor: User) -> list[CommentWithAuthor]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")

        rows = await self._comments.list_for_project(project_id)

        # One lookup per distinct author, not per comment: a long thread is
        # usually two people talking.
        authors: dict[UUID, tuple[str, str | None, str | None]] = {}
        for comment in rows:
            if comment.author_id not in authors:
                authors[comment.author_id] = await author_info_of(
                    self._users, comment.author_id
                )
        return [
            CommentWithAuthor(
                c,
                authors[c.author_id][0],
                authors[c.author_id][1],
                authors[c.author_id][2],
            )
            for c in rows
        ]

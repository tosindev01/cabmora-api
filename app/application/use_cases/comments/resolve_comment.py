"""Close an amendment request.

Only whoever manages the project may resolve one. A client marking their own
request resolved would let the work move on without anybody having done it,
and the outstanding count is what an admin relies on before advancing a stage.
"""

import logging
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.comment import CommentKind
from app.domain.entities.user import User
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.comment_repository import CommentRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository

from app.domain.services.email_sender import EmailSender

from ._author import CommentWithAuthor, name_of

logger = logging.getLogger(__name__)


class ResolveComment:
    def __init__(
        self,
        projects: ProjectRepository,
        comments: CommentRepository,
        users: UserRepository,
        email: EmailSender,
        notifier: Notifier,
        public_base_url: str,
    ) -> None:
        self._projects = projects
        self._comments = comments
        self._users = users
        self._email = email
        self._notifier = notifier
        self._base_url = public_base_url.rstrip("/")

    async def execute(self, comment_id: UUID, actor: User) -> CommentWithAuthor:
        comment = await self._comments.get_by_id(comment_id)
        if comment is None:
            raise EntityNotFoundError("Comment not found")

        project = await self._projects.get_by_id(comment.project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("Only the team can resolve a request.")

        was_a_request = comment.kind is CommentKind.AMENDMENT
        comment.resolve(actor.id)
        saved = await self._comments.update(comment)

        if was_a_request:
            await self._tell_the_author(project, saved)

        # The author, never the person who just closed it.
        return CommentWithAuthor(saved, await name_of(self._users, saved.author_id))

    async def reopen(self, comment_id: UUID, actor: User) -> CommentWithAuthor:
        comment = await self._comments.get_by_id(comment_id)
        if comment is None:
            raise EntityNotFoundError("Comment not found")
        project = await self._projects.get_by_id(comment.project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")
        comment.reopen()
        saved = await self._comments.update(comment)
        return CommentWithAuthor(saved, await name_of(self._users, saved.author_id))

    async def _tell_the_author(self, project, comment) -> None:
        """Say that the change they asked for has been made.

        Only for change requests. Closing a plain remark is housekeeping, and
        emailing somebody because their "lovely, thank you" was ticked off a
        list would teach them to ignore the next message.

        Not sent to whoever asked if that was the team itself — an admin
        raising a request on a client's behalf should not mail the client
        about their own internal note.
        """
        author = await self._users.get_by_id(comment.author_id)
        if author is None or project.customer_id != author.id:
            return
        await self._notifier.amendment_resolved(
            customer_id=author.id,
            project_id=project.id,
            project_title=project.title,
            request=comment.body,
        )
        try:
            await self._email.send_amendment_resolved(
                to=author.email,
                first_name=author.first_name,
                project_title=project.title,
                request=comment.body,
                gallery_url=f"{self._base_url}/client/projects/{project.id}",
            )
        except Exception:  # noqa: BLE001
            # The request is genuinely resolved. Failing to say so must not
            # reopen it.
            logger.exception(
                "[comments] resolved %s but could not tell %s", comment.id, author.email
            )

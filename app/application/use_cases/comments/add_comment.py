"""Leave feedback on a project, or on one photograph in it.

Both sides of the relationship use this: the client asking for a change and
the admin answering. What differs is only what they are allowed to say about —
which is a visibility question, and therefore the project's to answer.
"""

import logging
from uuid import UUID

from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.comment import MAX_BODY, Comment, CommentKind
from app.domain.entities.user import User
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.comment_repository import CommentRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.user_repository import UserRepository
from app.domain.services.email_sender import EmailSender
from app.domain.repositories.project_repository import ProjectRepository


logger = logging.getLogger(__name__)


class AddComment:
    def __init__(
        self,
        projects: ProjectRepository,
        comments: CommentRepository,
        media: MediaRepository,
        users: UserRepository,
        email: EmailSender,
        notifier: Notifier,
        public_base_url: str,
        admin_base_url: str | None = None,
        studio_notification_email: str | None = None,
    ) -> None:
        self._projects = projects
        self._comments = comments
        self._media = media
        self._users = users
        self._email = email
        self._notifier = notifier
        self._public = public_base_url.rstrip("/")
        self._admin = (admin_base_url or public_base_url).rstrip("/")
        self._studio_email = studio_notification_email

    async def execute(
        self,
        *,
        project_id: UUID,
        actor: User,
        body: str,
        asset_id: UUID | None = None,
        parent_id: UUID | None = None,
        point_x: float | None = None,
        point_y: float | None = None,
        kind: CommentKind = CommentKind.COMMENT,
    ) -> Comment:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")

        body = body.strip()
        if not body:
            raise ValidationError("A comment needs something in it.")
        if len(body) > MAX_BODY:
            raise ValidationError(f"Keep it under {MAX_BODY} characters.")

        if asset_id is not None:
            asset = await self._media.get_asset(asset_id)
            # Checked rather than trusted: without this, a comment could be
            # attached to a photograph on somebody else's project and would
            # then appear in their conversation.
            if asset is None or asset.project_id != project_id:
                raise EntityNotFoundError("That photograph is not on this project.")

        if parent_id is not None:
            parent = await self._comments.get_by_id(parent_id)
            if parent is None or parent.project_id != project_id:
                raise EntityNotFoundError("Parent comment not found on this project.")
            if asset_id is None:
                asset_id = parent.asset_id

        saved = await self._comments.add(
            Comment(
                project_id=project_id,
                author_id=actor.id,
                body=body,
                asset_id=asset_id,
                parent_id=parent_id,
                point_x=point_x,
                point_y=point_y,
                kind=kind,
            )
        )
        await self._tell_the_other_side(project, actor, saved)
        return saved

    async def _tell_the_other_side(self, project, actor: User, comment: Comment) -> None:
        """Email whoever did not write it.

        Without this the conversation only works for whoever happens to be
        looking: a client writes and the studio finds out next time somebody
        opens the project, which for a question about a date is too late to be
        useful.

        Never to the author. A failure here must not undo the comment — it is
        saved and visible in both screens either way, and losing somebody's
        words because a mail server was briefly unreachable is far worse than
        a missed notification.
        """
        try:
            if project.customer_id is not None and actor.id == project.customer_id:
                await self._tell_the_studio(project, actor, comment)
            else:
                await self._tell_the_client(project, actor, comment)
        except Exception:  # noqa: BLE001 — see docstring
            logger.exception(
                "[comments] %s saved on project %s but nobody could be told",
                comment.id, project.id,
            )

    async def _tell_the_studio(self, project, actor: User, comment: Comment) -> None:
        # The creator running the shoot where there is one, otherwise whoever
        # watches the pipeline. Unset means nobody is told, which is a
        # configuration gap rather than something to invent an address for.
        to = self._studio_email
        creator: User | None = None
        if project.creator_id is not None:
            creator = await self._users.get_by_id(project.creator_id)
            if creator is not None:
                to = creator.email

        # The bell, before the email and independent of it. Addressed to the
        # creator running the shoot where there is one, and otherwise to the
        # whole office — which is the case the studio *email* cannot serve,
        # because `studio_notification_email` is one address and may be unset.
        await self._notifier.project_message(
            from_name=actor.full_name,
            project_id=project.id,
            project_title=project.title,
            body=comment.body,
            recipient_id=creator.id if creator else None,
            recipient_is_staff=True,
            to_all_staff=creator is None,
            author_id=actor.id,
            about_a_photograph=comment.asset_id is not None,
        )

        if not to:
            return
        await self._email.send_project_message(
            to=to,
            recipient_first_name="there",
            from_name=actor.full_name,
            project_title=project.title,
            body=comment.body,
            url=f"{self._admin}/admin/projects/{project.id}",
            about_a_photograph=comment.asset_id is not None,
        )

    async def _tell_the_client(self, project, actor: User, comment: Comment) -> None:
        if project.customer_id is None:
            return
        customer = await self._users.get_by_id(project.customer_id)
        if customer is None:
            return
        await self._notifier.project_message(
            # As the studio, not as whichever member of staff typed it — the
            # same reason the email does, below.
            from_name="Cabmora Media",
            project_id=project.id,
            project_title=project.title,
            body=comment.body,
            recipient_id=customer.id,
            about_a_photograph=comment.asset_id is not None,
        )
        await self._email.send_project_message(
            to=customer.email,
            recipient_first_name=customer.first_name,
            # The studio writes as the studio. A client does not know which
            # member of staff is which, and a name they have never heard
            # reads like the wrong email.
            from_name="Cabmora Media",
            project_title=project.title,
            body=comment.body,
            url=f"{self._public}/client/messages",
            about_a_photograph=comment.asset_id is not None,
        )

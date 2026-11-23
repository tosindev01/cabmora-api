from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError, ValidationError
from app.domain.entities.project import Project, ProjectStage
from app.domain.entities.project_event import ProjectEvent, ProjectEventKind
from app.domain.entities.user import User
from app.domain.repositories.media_repository import MediaRepository
from app.application.use_cases.notifications.notifier import Notifier
from app.domain.repositories.project_repository import ProjectRepository


#: What a client is told the stage is called.
#:
#: Only the two that do not read right from the enum. `in_review` would
#: otherwise become "in review", which is true but reads as jargon, and `draft`
#: never reaches a client at all — a drafted project has nobody to notify.
#: Everything else is its own value with the underscore taken out, which is
#: why this is a sparse map and not a complete one.
_LABELS = {
    ProjectStage.IN_REVIEW: "ready for your review",
    ProjectStage.DELIVERED: "delivered",
}


class ChangeProjectStage:
    """Move a project to any stage, recording who moved it.

    This used to refuse Client Review unless something had been released, and
    Delivered unless the client had approved — because the transition map alone
    let a project with no media at all be walked to Closed one click at a time.
    Both refusals are gone on Cabmora's instruction: the console is operated by
    people who know more about the job than the state machine does, and an
    admin backfilling a wedding that already happened was fighting it.

    The stage still moves on its own when the work happens — upload moves a
    project to Editing, release moves it to Client Review, the client accepting
    moves it to Delivered. Those live in `media/confirm_upload`,
    `media/release_assets` and `Project.approve`, and none of them come through
    here. So the stage is right by default and overridable by hand, which is a
    different thing from unguarded.

    What this *does* still enforce is who may move it, and that something
    actually changed.
    """

    def __init__(
        self, projects: ProjectRepository, media: MediaRepository, notifier: Notifier
    ) -> None:
        self._projects = projects
        self._notifier = notifier
        # Kept on the signature though no longer read: the guard that used it
        # may come back, and churning the composition root for a constructor
        # argument is noise. Remove both together if it does not.
        self._media = media

    async def execute(self, project_id: UUID, actor: User, stage: ProjectStage) -> Project:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot manage this project.")

        if stage is project.stage:
            raise ValidationError(f"Project is already {stage.value}.")
        if not project.can_move_to(stage):
            # Named explicitly rather than a generic refusal: "you cannot go
            # from shooting to delivered" is actionable; "invalid stage" is not.
            raise ValidationError(
                f"A project cannot move from {project.stage.value} to {stage.value}."
            )


        previous = project.stage
        project.stage = stage
        if stage is ProjectStage.EDITING:
            # Work going back for changes is no longer the work that was
            # signed off, so the sign-off cannot still stand over it.
            project.withdraw_approval()
        saved = await self._projects.update(
            project,
            ProjectEvent(
                project_id=project.id,
                kind=ProjectEventKind.STAGE_CHANGED,
                actor_id=actor.id,
                payload={"from": previous.value, "to": stage.value},
            ),
        )
        # After the write, not before: a client told their job moved to editing
        # by a transition that then failed to save is worse than a client told
        # nothing. No email for this one — a stage change is progress, not news
        # worth an inbox, and the bell is exactly the right weight for it.
        await self._notifier.stage_changed(
            customer_id=saved.customer_id,
            project_id=saved.id,
            project_title=saved.title,
            stage_label=_LABELS.get(stage, stage.value.replace("_", " ")),
        )
        return saved

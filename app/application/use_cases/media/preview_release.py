"""What a release is about to do, before anybody does it.

Sharing photographs is not the toggle it looks like in the console: it emails
the client, it can move the project into review, and under `ALL_AT_ONCE` it
releases work that was never selected. An admin cannot see any of that from a
button, and the email cannot be unsent.

The console could work most of it out for itself, and that is exactly the
problem — it would be a second copy of a rule `ReleaseAssets` owns, correct
until the day the rule gains a condition and silently wrong after it. So the
answer comes from here, from the same entity method the real release uses.
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import EntityNotFoundError, PermissionDeniedError
from app.domain.entities.asset import AssetKind
from app.domain.entities.project import ProjectStage
from app.domain.entities.user import User
from app.domain.entities.invoice import is_settled
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository


@dataclass(frozen=True)
class ReleasePreview:
    """Everything a confirmation step needs to tell the truth."""

    #: How many photographs were picked. Echoed so the console can say "all
    #: twelve, not the two you chose" without re-counting the selection.
    selected: int
    #: How many would actually change hands. Already allows for the release
    #: mode, and excludes anything that is where it should be: releasing
    #: something already released does nothing and must not be announced.
    affected: int
    #: Of those, how many have no watermarked copy yet. They would be
    #: released and still not viewable, which looks to a client like an empty
    #: gallery and to the admin like success.
    preview_pending: int
    #: Whether the client gets an email out of this. False when nothing
    #: changes, when work is being withheld rather than shared, or when no
    #: client is on the project yet.
    notifies_client: bool
    #: Where the project would end up, or None if it stays put.
    moves_to_stage: ProjectStage | None
    #: Whether the client would be handed the original files rather than
    #: watermarked copies. Derived here because it depends on the watermark
    #: policy *and* on whether the job has been paid for — two facts a console
    #: should not have to combine for itself.
    hands_over_originals: bool


class PreviewRelease:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        invoices: InvoiceRepository,
    ) -> None:
        self._projects = projects
        self._media = media
        self._invoices = invoices

    async def execute(
        self, *, project_id: UUID, actor: User, asset_ids: list[UUID], released: bool
    ) -> ReleasePreview:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        # The same check the release itself makes. A preview is a read, but it
        # is a read of what would happen to somebody's photographs.
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("You cannot release work on this project.")

        on_project = {
            asset.id: asset
            for asset in await self._media.list_project_assets(
                project_id, kinds=[AssetKind.ORIGINAL.value]
            )
        }
        missing = [i for i in asset_ids if i not in on_project]
        if missing:
            raise EntityNotFoundError(
                f"{len(missing)} of those photographs are not on this project."
            )

        billed, paid = (
            await self._invoices.totals_for_projects([project_id])
        ).get(project_id, (0, 0))
        settled = is_settled(billed_minor=billed, paid_minor=paid)

        targets = project.release_targets(list(on_project), asset_ids)
        changing = [
            on_project[i] for i in targets if on_project[i].is_released != released
        ]

        return ReleasePreview(
            selected=len(asset_ids),
            affected=len(changing),
            preview_pending=sum(1 for asset in changing if asset.awaiting_renditions),
            notifies_client=bool(
                released and changing and project.customer_id is not None
            ),
            moves_to_stage=(
                project.stage_after_release if released and changing else None
            ),
            hands_over_originals=project.hands_over_originals(settled=settled),
        )

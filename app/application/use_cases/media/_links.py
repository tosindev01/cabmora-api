"""Who may be handed which file, and the link that hands it over.

Shared by the gallery and by the version history behind it, because both
answer the same question about the same photographs and a second copy of this
rule would eventually hand a client an unwatermarked original. Underscored
like `comments/_author.py`: it is shared between use cases in this package
rather than a use case of its own.
"""

import logging
from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.asset import Asset, AssetKind
from app.domain.entities.invoice import is_settled
from app.domain.entities.project import Project
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.services.media_storage import MediaStorage

#: Long enough to scroll a gallery, short enough that a shared link dies
#: before it reaches anyone it was not meant for.
VIEW_TTL = 15 * 60


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Link:
    #: None when this person may not see the file yet. The row still exists,
    #: so a client can tell that work exists without being handed it.
    url: str | None
    #: True when the link is the untouched original rather than a preview.
    is_original: bool
    #: The media type of the file this link actually points at — which is not
    #: always the original's. A gallery has to know whether to draw an image
    #: or a player, and guessing from the filename is how a .mov ends up in an
    #: `<img>` tag.
    content_type: str | None = None


NOTHING = Link(url=None, is_original=False)


def client_may_see(project: Project, asset: Asset, *, settled: bool) -> bool:
    """Whether a customer may be handed a link to this photograph.

    Three conditions, and all of them must hold. Here rather than in the
    console because a second client of this API — a mobile app, a share link
    — must not be able to skip them.
    """
    # 1. Somebody chose to show it. The default is no.
    if not asset.is_released:
        return False
    # 2. Something exists that is safe to hand over. Before renditions are
    #    made the only file is the untouched original, and serving that would
    #    defeat the watermark entirely.
    if asset.awaiting_renditions:
        return False
    # 3. The money, where the project says the money comes first. Distinct
    #    from the watermark, which decides *what* they are handed: this
    #    decides whether they are handed anything at all. Both are now real;
    #    this one was a switch an admin could tick that nothing read.
    if project.require_payment_before_delivery and not settled:
        return False
    return True


class AssetLinker:
    """Turns a photograph into a link the viewer in front of you may use."""

    def __init__(
        self,
        media: MediaRepository,
        storage: MediaStorage,
        invoices: InvoiceRepository,
    ) -> None:
        self._media = media
        self._storage = storage
        self._invoices = invoices

    async def settled(self, project: Project) -> bool:
        """Whether this project has been paid for in full.

        Asked here because this is the only place the answer is used — what
        the watermark does, and whether a gallery opens at all. Billing owns
        the figures, `is_settled` owns what they mean, and this owns neither.
        """
        totals = await self._invoices.totals_for_projects([project.id])
        billed, paid = totals.get(project.id, (0, 0))
        return is_settled(billed_minor=billed, paid_minor=paid)

    @staticmethod
    def previews_by_original(assets: list[Asset]) -> dict[UUID, Asset]:
        """Previews indexed by the original they were made from.

        A client is handed one of these and never the file it came from:
        looking the blob up by the *original's* hash would serve the untouched
        photograph to everybody and quietly undo the watermark.
        """
        return {
            asset.derived_from: asset
            for asset in assets
            if asset.kind is AssetKind.PREVIEW and asset.derived_from
        }

    @staticmethod
    def ancestry(assets: list[Asset]) -> dict[UUID, tuple[UUID, ...]]:
        """Each asset's own id, followed by the ids of every frame it replaced.

        A selective share names the frames chosen at the time. When the
        photographer later uploads a correction, the gallery shows the new
        frame in place of the old one — so a link matching only the exact id
        it stored would go blank precisely because the picture was improved.
        Walking back through `supersedes` keeps it pointing at the same
        photograph.

        Here beside `previews_by_original` because it is the same sort of
        thing: a rule about how assets relate, needed by more than one use
        case, and wrong to answer twice.

        Guarded against a cycle. The chain is built by uploads and nothing
        enforces that it is acyclic; a `while` over bad data would hang a
        public request rather than fail it.
        """
        by_id = {asset.id: asset for asset in assets}
        chains: dict[UUID, tuple[UUID, ...]] = {}
        for asset in assets:
            chain = [asset.id]
            seen = {asset.id}
            current: Asset | None = asset
            while (
                current is not None
                and current.supersedes is not None
                and current.supersedes not in seen
            ):
                chain.append(current.supersedes)
                seen.add(current.supersedes)
                current = by_id.get(current.supersedes)
            chains[asset.id] = tuple(chain)
        return chains

    async def mint(
        self,
        *,
        project: Project,
        manages: bool,
        original: Asset,
        preview: Asset | None,
        settled: bool,
        as_filename: str | None = None,
    ) -> Link:
        """Sign a link to whichever file this viewer may be handed.

        `as_filename` makes it a download rather than something to look at.
        It is a parameter here rather than a second method because *which*
        file somebody gets is the rule this class exists to hold, and it is
        identical for both: a client who may only see the watermarked copy
        downloads the watermarked copy. A separate minting path would be the
        duplicate rule this module's docstring warns about, and the way an
        unwatermarked original eventually escapes.
        """
        source: Asset | None = None
        if manages:
            # Whoever shot it sees it as it was taken.
            source = original
        elif client_may_see(project, original, settled=settled):
            # Whoever commissioned it sees the watermarked copy until the job
            # is paid for; after that the project's watermark policy hands
            # them the file they actually paid for. No preview means no link,
            # however released the work is.
            source = original if project.hands_over_originals(settled=settled) else preview

        if source is None:
            return NOTHING

        blob = await self._media.get_object(source.content_hash)
        if blob is None:
            return NOTHING

        try:
            url = await self._storage.presign_download(
                key=blob.key,
                expires_in=VIEW_TTL,
                as_filename=as_filename,
            )
        except Exception:  # noqa: BLE001
            # One object the store will not sign must not take the gallery
            # with it. Unguarded this failed the whole listing, and the
            # console showed "no media yet" over a project holding two
            # photographs — the count beside it comes from the database and
            # kept saying so, which is how the two disagreed.
            #
            # Logged rather than swallowed: the frame renders as not ready,
            # and the reason is in the log instead of nowhere.
            logger.exception(
                "[media] could not sign %s (%s)",
                blob.key,
                "download" if as_filename else "viewing",
            )
            return NOTHING

        return Link(
            # Whether *this* link is the untouched file, not whether the
            # viewer happens to manage the project — a client holding an
            # approved original is handed one too.
            url=url,
            is_original=source is original,
            content_type=blob.content_type,
        )

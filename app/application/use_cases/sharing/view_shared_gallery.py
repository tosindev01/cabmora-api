"""What somebody holding a link gets to see.

The only unauthenticated read of anybody's photographs in the system, so it is
written to be boring: resolve the token, refuse it if it is spent, and hand
back exactly what the project's own rules already allow — nothing is widened
because the viewer arrived without an account.

**The watermark is not lifted by holding a link.** Whether originals are
handed over is `watermark_policy` read against whether the job has been paid
for, and that question has the same answer for the client and for whoever they
sent the link to. A paid-up project hands over the files; an unpaid one hands
over marked proofs, to everybody.
"""

from dataclasses import dataclass
from datetime import datetime

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.asset import AssetKind
from app.domain.entities.gallery_share import GalleryShare
from app.domain.repositories.gallery_share_repository import GalleryShareRepository
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage

from ..media._links import AssetLinker, client_may_see


@dataclass(frozen=True)
class SharedPhotograph:
    id: str
    filename: str
    url: str
    #: Optional, so it goes last. Travels with the url for the same reason it
    #: does on `_links.Link`: whoever draws this has to know whether to make
    #: an image or a player, and a public share page gets no second chance.
    content_type: str | None = None


@dataclass(frozen=True)
class SharedGallery:
    project_title: str
    event_type: str
    photographs: list[SharedPhotograph]
    expires_at: datetime
    #: Whether what is being handed over is the finished file. Published so
    #: the page can say which it is instead of leaving somebody to wonder why
    #: there is a watermark on it.
    hands_over_originals: bool


class ViewSharedGallery:
    def __init__(
        self,
        shares: GalleryShareRepository,
        projects: ProjectRepository,
        media: MediaRepository,
        storage: MediaStorage,
        invoices: InvoiceRepository,
    ) -> None:
        self._shares = shares
        self._projects = projects
        self._media = media
        self._links = AssetLinker(media, storage, invoices)

    async def execute(self, token: str) -> SharedGallery:
        share = await self._shares.get_by_token_hash(GalleryShare.hash_of(token))
        # One message for "no such link", "revoked" and "expired". Telling
        # the difference would confirm to somebody guessing that a token once
        # existed, and the person who actually holds a dead link needs to ask
        # whoever sent it either way.
        if share is None or not share.is_usable:
            raise EntityNotFoundError("This link is no longer available.")

        project = await self._projects.get_by_id(share.project_id)
        if project is None:
            raise EntityNotFoundError("This link is no longer available.")

        everything = await self._media.list_project_assets(share.project_id)
        originals = [a for a in everything if a.kind is AssetKind.ORIGINAL]
        previews = AssetLinker.previews_by_original(everything)
        replaced = {a.supersedes for a in everything if a.supersedes is not None}
        settled = await self._links.settled(project)
        ancestry = AssetLinker.ancestry(everything)

        photographs: list[SharedPhotograph] = []
        for original in originals:
            # A corrected frame is shown in place of the one it replaced, the
            # same as it is for the client. Somebody handed a link does not
            # need to see the version that was complained about.
            if original.id in replaced:
                continue
            if not client_may_see(project, original, settled=settled):
                continue
            # The chosen few, where the link named any. Asked with the frame's
            # ancestors as well, so a photograph that has been re-edited since
            # the link was made is still the photograph that was shared.
            if not share.covers(*ancestry[original.id]):
                continue
            link = await self._links.mint(
                project=project,
                manages=False,
                original=original,
                preview=previews.get(original.id),
                settled=settled,
            )
            if link.url:
                photographs.append(
                    SharedPhotograph(
                        id=str(original.id), filename=original.filename, url=link.url,
                        content_type=link.content_type,
                    )
                )

        share.viewed()
        await self._shares.update(share)

        return SharedGallery(
            project_title=project.title,
            event_type=project.event_type,
            photographs=photographs,
            expires_at=share.expires_at,
            hands_over_originals=project.hands_over_originals(settled=settled),
        )

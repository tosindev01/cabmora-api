"""The photograph a messaging app shows when somebody pastes a share link.

Cabmora asked for a real picture from the gallery rather than a branded card.
Worth being clear about what that means, because it cannot be undone later:
**WhatsApp, Slack, Facebook and iMessage fetch the image and cache it on their
own servers.** Once a link has been pasted, a copy of that photograph lives
outside this system, outside the signed-URL expiry, and outside the "secure,
non-downloadable links" the PRD asks for. Deleting the share afterwards does
not reach it.

So the picture handed over is the most guarded one the project allows:

· the **preview** rendition wherever one exists, which carries the watermark
  when the project's policy says it should — never the untouched original,
  even for a project that has been paid for and would show originals in the
  gallery itself;
· chosen through the same `client_may_see` rules the gallery uses, so a frame
  nobody is allowed to see yet cannot surface in a link preview;
· nothing at all for a project with no released work, which falls back to the
  site's own image rather than inventing something;
· and, for a link that names particular photographs, only one of those — the
  cover must come from inside the link rather than from the gallery around it.

Looking at a preview must also not count as a visit. `ViewSharedGallery` marks
the share viewed; this deliberately does not, or every paste into a group chat
would inflate the count with readers who have not opened anything.
"""

from dataclasses import dataclass

from app.domain.entities.asset import AssetKind
from app.domain.entities.gallery_share import GalleryShare
from app.domain.repositories.gallery_share_repository import GalleryShareRepository
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage

from ..media._links import AssetLinker, client_may_see


@dataclass(frozen=True)
class SharePreview:
    project_title: str
    event_type: str
    #: A fetchable URL for the cover photograph, or None when the gallery has
    #: nothing to show. Minted per request, so the signature is always fresh.
    cover_url: str | None
    #: What the cover actually is, so a caller can refuse a film: a messaging
    #: app wants a still, and handing it an mp4 gets no preview at all.
    cover_content_type: str | None


class GetSharePreview:
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

    async def execute(self, token: str) -> SharePreview | None:
        share = await self._shares.get_by_token_hash(GalleryShare.hash_of(token))
        if share is None or not share.is_usable:
            return None

        project = await self._projects.get_by_id(share.project_id)
        if project is None:
            return None

        everything = await self._media.list_project_assets(share.project_id)
        previews = AssetLinker.previews_by_original(everything)
        replaced = {a.supersedes for a in everything if a.supersedes is not None}
        settled = await self._links.settled(project)
        ancestry = AssetLinker.ancestry(everything)

        for original in everything:
            if original.kind is not AssetKind.ORIGINAL:
                continue
            if original.id in replaced:
                continue
            if not client_may_see(project, original, settled=settled):
                continue
            # The cover has to come from inside the link. A selective share
            # unfurling with a photograph it does not contain would put that
            # picture into a chat thread — and into the messaging app's
            # cache — on the strength of a link that was never meant to
            # carry it.
            if not share.covers(*ancestry[original.id]):
                continue

            preview = previews.get(original.id)
            # No preview rendition means the only thing available is the
            # original, and that is the one file this must never hand to a
            # third-party cache. Skip to the next frame instead.
            if preview is None:
                continue

            link = await self._links.mint(
                project=project,
                manages=False,
                original=original,
                preview=preview,
                settled=settled,
            )
            # `settled` can make the linker return the original even when a
            # preview was offered, for a project that has been paid for. That
            # is right inside the gallery and wrong here.
            if link.url is None or link.is_original:
                continue
            if not (link.content_type or "").startswith("image/"):
                continue

            return SharePreview(
                project_title=project.title,
                event_type=project.event_type,
                cover_url=link.url,
                cover_content_type=link.content_type,
            )

        return SharePreview(
            project_title=project.title,
            event_type=project.event_type,
            cover_url=None,
            cover_content_type=None,
        )

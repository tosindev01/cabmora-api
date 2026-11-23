"""Everything a client has been given, across all of their projects.

Not a second gallery. The project gallery is where work is reviewed — comment
on it, ask for a change, approve it. This is the other half: what they have
been handed and what they may take away, with the projects collapsed into one
surface so a repeat customer stops hunting through four shoots for the one
photograph they remember.

Links are minted the same way as everywhere else, through `AssetLinker`, so
the watermark rule lives in exactly one place. A client sees the watermarked
copy until the project's own policy says otherwise — holding a link to this
page does not lift it, any more than holding a share link does.
"""

from dataclasses import dataclass

from app.domain.entities.asset import Asset, AssetKind
from app.domain.entities.project import Project
from app.domain.entities.user import User
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.services.media_storage import MediaStorage

from ._links import AssetLinker, client_may_see

#: How many projects deep this looks. A client with more than this has a
#: relationship nobody has designed for yet, and silently truncating is better
#: than a page that takes a minute to build.
MAX_PROJECTS = 50


@dataclass
class LibraryItem:
    asset: Asset
    project: Project
    #: Signed, short-lived, and never the original unless the project says so.
    url: str
    is_original: bool
    content_type: str | None

    @property
    def downloadable(self) -> bool:
        """Whether a save button should appear at all.

        A separate decision from which file is behind the link: with
        downloads on and the job unpaid, what saves is the watermarked copy.
        The two settings answer different questions and conflating them is how
        an unpaid client ends up holding an original.
        """
        return self.project.allow_downloads


class ListMyMedia:
    def __init__(
        self,
        projects: ProjectRepository,
        media: MediaRepository,
        storage: MediaStorage,
        invoices: InvoiceRepository,
    ) -> None:
        self._projects = projects
        self._media = media
        self._links = AssetLinker(media, storage, invoices)

    async def execute(self, *, actor: User) -> list[LibraryItem]:
        # Scoped by who is asking, like `ListProjects` — the endpoint being
        # reachable says nothing about which rows may be read.
        projects = await self._projects.list_all(
            customer_id=actor.id, limit=MAX_PROJECTS
        )

        library: list[LibraryItem] = []
        for project in projects:
            if not project.is_visible_to(actor):
                continue

            everything = await self._media.list_project_assets(project.id)
            previews = AssetLinker.previews_by_original(everything)
            # Asked once per project rather than once per photograph.
            settled = await self._links.settled(project)
            replaced = {a.supersedes for a in everything if a.supersedes is not None}

            for original in everything:
                if original.kind is not AssetKind.ORIGINAL:
                    continue
                # The client sees the corrected frame in its place, not both.
                if original.id in replaced:
                    continue
                if not client_may_see(project, original, settled=settled):
                    continue

                link = await self._links.mint(
                    project=project,
                    manages=False,
                    original=original,
                    preview=previews.get(original.id),
                    settled=settled,
                )
                # No link means the work exists but is not theirs yet. On a
                # project gallery that row still appears, so somebody can see
                # the shoot is progressing. Here it would be a blank tile in a
                # library of things they have been given, which is the one
                # thing this page is not.
                if link.url is None:
                    continue

                library.append(
                    LibraryItem(
                        asset=original,
                        project=project,
                        url=link.url,
                        is_original=link.is_original,
                        content_type=link.content_type,
                    )
                )

        # Newest first, by when it was handed over rather than when it was
        # taken: the client's question is "what came most recently", and a
        # wedding shot in June and delivered in August belongs at August.
        library.sort(key=lambda item: item.asset.released_at or item.asset.created_at, reverse=True)
        return library

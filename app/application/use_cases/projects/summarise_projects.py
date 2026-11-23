"""What a project card needs to be acted on without opening it.

Three questions an admin asks about a project at a glance — are there
photographs, is the client waiting on me, has it been paid — answered for a
whole page at once.

**Three queries for thirty projects, not ninety.** Each repository is asked
once with every id on the page. Asking per project is the obvious way to write
this and the reason list screens get slow six months after launch, by which
point the cause is spread across three files.

Deliberately not on `Project`. None of it is a property of the project: the
photographs live in media, the comments in feedback, the money in billing, and
putting any of it on the entity would mean loading all three to answer "what
is this called".
"""

from dataclasses import dataclass
from uuid import UUID

from app.domain.repositories.comment_repository import CommentRepository
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.media_repository import MediaRepository


@dataclass(frozen=True)
class ProjectSummary:
    """Counts and totals for one project. Zeroes, never nulls — a card showing
    a blank where a number belongs reads as "not loaded", not as "none"."""

    #: Original photographs. Renditions are not work anybody did.
    photos: int
    #: How many of them the client can see.
    released: int
    #: Client remarks nobody has dealt with. The "you are holding this up"
    #: number.
    open_comments: int
    #: Issued, in minor units. Drafts are excluded — an invoice nobody has
    #: sent is not money owed.
    billed_minor: int
    #: Received, net of refunds.
    paid_minor: int

    @property
    def outstanding_minor(self) -> int:
        """Never negative. An overpayment is a credit, not a debt, and a card
        reading "-£50 outstanding" would be read as an error."""
        return max(0, self.billed_minor - self.paid_minor)


EMPTY = ProjectSummary(photos=0, released=0, open_comments=0, billed_minor=0, paid_minor=0)


class SummariseProjects:
    def __init__(
        self,
        media: MediaRepository,
        comments: CommentRepository,
        invoices: InvoiceRepository,
    ) -> None:
        self._media = media
        self._comments = comments
        self._invoices = invoices

    async def execute(self, project_ids: list[UUID]) -> dict[UUID, ProjectSummary]:
        if not project_ids:
            return {}

        photos = await self._media.counts_for_projects(project_ids)
        comments = await self._comments.open_counts_for_projects(project_ids)
        money = await self._invoices.totals_for_projects(project_ids)

        return {
            project_id: ProjectSummary(
                photos=photos.get(project_id, (0, 0))[0],
                released=photos.get(project_id, (0, 0))[1],
                open_comments=comments.get(project_id, 0),
                billed_minor=money.get(project_id, (0, 0))[0],
                paid_minor=money.get(project_id, (0, 0))[1],
            )
            for project_id in project_ids
        }

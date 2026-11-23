from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.enquiry import Enquiry, EnquiryStatus
from app.domain.repositories.enquiry_repository import EnquiryRepository

DEFAULT_PAGE_SIZE = 30


@dataclass
class EnquiryPage:
    items: list[Enquiry]
    total: int
    limit: int
    offset: int


class ListEnquiries:
    def __init__(self, enquiries: EnquiryRepository) -> None:
        self._enquiries = enquiries

    async def execute(
        self,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        status: EnquiryStatus | None = None,
        assigned_to: UUID | None = None,
        search: str | None = None,
    ) -> EnquiryPage:
        items = await self._enquiries.list_all(
            limit=limit, offset=offset, status=status,
            assigned_to=assigned_to, search=search,
        )
        total = await self._enquiries.count_all(
            status=status, assigned_to=assigned_to, search=search
        )
        return EnquiryPage(items=items, total=total, limit=limit, offset=offset)

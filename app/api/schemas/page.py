from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """The response shape for every paginated collection.

    Generic so `Page[UserResponse]` and `Page[ProjectResponse]` are the same
    contract: a client that can read one reads them all, and OpenAPI documents
    them identically instead of once per endpoint.
    """

    items: list[T]
    #: Matches the current filters, never the grand total — otherwise a filtered
    #: view renders "page 1 of 12" beside three rows.
    total: int
    limit: int
    offset: int

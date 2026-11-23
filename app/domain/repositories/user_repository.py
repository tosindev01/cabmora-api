from abc import ABC, abstractmethod
from collections.abc import Iterable
from uuid import UUID

from app.domain.entities.user import Permission, User, UserRole, UserStatus


class UserRepository(ABC):
    @abstractmethod
    async def add(self, user: User) -> User: ...

    @abstractmethod
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def get_many(self, user_ids: Iterable[UUID]) -> dict[UUID, User]:
        """Batch lookup for display names. One query per page, not per row."""

    @abstractmethod
    async def list_all(
        self,
        limit: int = 30,
        offset: int = 0,
        roles: list[UserRole] | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ) -> list[User]: ...

    @abstractmethod
    async def count_all(
        self,
        roles: list[UserRole] | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ) -> int: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def save_profile(self, user: User) -> User:
        """Write back the fields the account holder owns.

        Separate from `update`, which is administration's narrow role/status
        write. Neither touches the other's columns, so an admin changing a role
        cannot clobber a name the person edited a moment earlier, and vice
        versa.
        """
        ...

    @abstractmethod
    async def set_password(self, user: User) -> User:
        """Store a new password hash.

        Separate from `update`, which deliberately writes only role and status:
        widening it to cover credentials would let an administrative edit
        overwrite a password from a stale read.
        """

    @abstractmethod
    async def get_by_stripe_customer_id(self, customer_id: str) -> User | None:
        """Whose gateway customer this is, if it is anybody's.

        None is an ordinary answer, not an error: a customer created by hand
        in the gateway's dashboard has no account here, and money arriving
        against it is still money worth showing somebody.
        """

    @abstractmethod
    async def set_stripe_customer_id(self, user_id: UUID, customer_id: str) -> None:
        """Remember the gateway's id for this person.

        Its own method, like `set_password`, and for the same reason: `update`
        writes role and status only, and this is written from a payment flow
        rather than from administration. The two must not be able to clobber
        each other.
        """

    @abstractmethod
    async def set_permissions(
        self, user_id: UUID, permissions: set[Permission], granted_by: UUID
    ) -> None:
        """Replace what this person has been granted.

        The whole set, not a delta — for the same reason a project's members
        are sent whole: add and remove endpoints that can disagree are how
        somebody keeps access they were taken off.
        """

    @abstractmethod
    async def count_by_status(self) -> dict[UserStatus, int]: ...

    @abstractmethod
    async def count_by_role(self) -> dict[UserRole, int]: ...

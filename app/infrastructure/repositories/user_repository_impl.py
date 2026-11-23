from collections.abc import Iterable
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import EntityNotFoundError
from app.domain.entities.user import Permission, User, UserRole, UserStatus
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.models.access_group import (
    AccessGroupModel,
    AccessGroupPermissionModel,
    UserGroupModel,
)
from app.infrastructure.models.user import UserModel, UserPermissionModel


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _hydrate(self, models: list[UserModel]) -> list[User]:
        """Attach each person's granted sections.

        Every read goes through this, including the one behind the session:
        a `User` with an empty `granted` would answer `can()` wrongly, and the
        guards would refuse somebody who has been given access. One batch
        query for the page rather than one per row.
        """
        users = [m.to_entity() for m in models]
        if not users:
            return users
        rows = await self._session.execute(
            select(UserPermissionModel.user_id, UserPermissionModel.permission).where(
                UserPermissionModel.user_id.in_([str(u.id) for u in users])
            )
        )
        granted: dict[str, set[Permission]] = {}
        for user_id, permission in rows.all():
            try:
                granted.setdefault(user_id, set()).add(Permission(permission))
            except ValueError:
                # A permission removed from the enum but still in the table.
                # Ignored rather than raised: a stale row must not break
                # signing in, and it grants nothing because nothing reads it.
                continue
        for user in users:
            user.granted = granted.get(str(user.id), set())

        # And what their groups give them. Three joins' worth of work done as
        # one query for the page: membership, the group's name, and each
        # permission it carries.
        rows = await self._session.execute(
            select(
                UserGroupModel.user_id,
                AccessGroupModel.name,
                AccessGroupPermissionModel.permission,
            )
            .join(AccessGroupModel, AccessGroupModel.id == UserGroupModel.group_id)
            .outerjoin(
                AccessGroupPermissionModel,
                AccessGroupPermissionModel.group_id == UserGroupModel.group_id,
            )
            .where(UserGroupModel.user_id.in_([str(u.id) for u in users]))
        )
        from_groups: dict[str, set[Permission]] = {}
        names: dict[str, set[str]] = {}
        for user_id, name, permission in rows.all():
            names.setdefault(user_id, set()).add(name)
            if permission is None:
                continue  # a group with no permissions yet
            try:
                from_groups.setdefault(user_id, set()).add(Permission(permission))
            except ValueError:
                continue
        for user in users:
            user.from_groups = from_groups.get(str(user.id), set())
            user.group_names = sorted(names.get(str(user.id), set()))
        return users

    async def _one(self, model: UserModel | None) -> User | None:
        if model is None:
            return None
        return (await self._hydrate([model]))[0]

    async def add(self, user: User) -> User:
        model = UserModel.from_entity(user)
        self._session.add(model)
        await self._session.commit()
        return model.to_entity()

    async def get_by_id(self, user_id: UUID) -> User | None:
        return await self._one(await self._session.get(UserModel, str(user_id)))

    async def get_many(self, user_ids: Iterable[UUID]) -> dict[UUID, User]:
        ids = {str(uid) for uid in user_ids if uid is not None}
        if not ids:
            return {}
        result = await self._session.execute(
            select(UserModel).where(UserModel.id.in_(ids))
        )
        users = await self._hydrate(list(result.scalars().all()))
        return {user.id: user for user in users}

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email)
        )
        return await self._one(result.scalar_one_or_none())

    @staticmethod
    def _filters(
        roles: list[UserRole] | None,
        status: UserStatus | None,
        search: str | None,
    ) -> list:
        """Shared by list_all and count_all.

        They must not drift: a count computed from different predicates than the
        page would produce a footer that disagrees with the rows in front of it.
        """
        clauses = []
        # `role` and `status` are String(20) columns, so compare enum values.
        # A list rather than one role because the console has two lists of
        # people — clients and Cabmora's own staff — and each is a set of
        # roles. `IN ()` with an empty list matches nothing, which is the
        # right answer to "show me none of them" but the wrong one to "no
        # filter", so an empty list is treated as absent.
        if roles:
            clauses.append(UserModel.role.in_([r.value for r in roles]))
        if status is not None:
            clauses.append(UserModel.status == status.value)
        if search and search.strip():
            term = f"%{search.strip().lower()}%"
            # `full_name` is a derived property, not a column, so a full-name
            # search has to match the concatenation — otherwise "ada lovelace"
            # matches neither first_name nor last_name and search looks broken.
            # `+` on String columns emits `||` on both SQLite and Postgres.
            clauses.append(
                or_(
                    func.lower(UserModel.email).like(term),
                    func.lower(
                        UserModel.first_name + " " + UserModel.last_name
                    ).like(term),
                )
            )
        return clauses

    async def list_all(
        self,
        limit: int = 30,
        offset: int = 0,
        roles: list[UserRole] | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ) -> list[User]:
        stmt = (
            select(UserModel)
            .where(*self._filters(roles, status, search))
            # Newest first: the admin screen exists to spot new and problem
            # accounts, not to browse the back catalogue.
            .order_by(UserModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return await self._hydrate(list(result.scalars().all()))

    async def count_all(
        self,
        roles: list[UserRole] | None = None,
        status: UserStatus | None = None,
        search: str | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(UserModel)
            .where(*self._filters(roles, status, search))
        )
        return (await self._session.execute(stmt)).scalar_one()

    async def update(self, user: User) -> User:
        model = await self._session.get(UserModel, str(user.id))
        if model is None:
            raise EntityNotFoundError("User not found")
        # Deliberately narrow: only the two fields administration owns. Writing
        # the whole entity back would let a stale read silently clobber the
        # email or password, which belong to the account holder.
        model.role = user.role.value
        model.status = user.status.value
        await self._session.commit()
        return model.to_entity()

    async def get_by_stripe_customer_id(self, customer_id: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.stripe_customer_id == customer_id)
        )
        return await self._one(result.scalar_one_or_none())

    async def set_stripe_customer_id(self, user_id: UUID, customer_id: str) -> None:
        model = await self._session.get(UserModel, str(user_id))
        if model is None:
            raise EntityNotFoundError("User not found")
        model.stripe_customer_id = customer_id
        await self._session.commit()

    async def save_profile(self, user: User) -> User:
        model = await self._session.get(UserModel, str(user.id))
        if model is None:
            raise EntityNotFoundError("User not found")
        # Listed one by one on purpose, and deliberately not role, status or
        # the password hash: those belong to administration and to the
        # credential flow, and writing the whole entity back here is how a
        # profile edit would quietly restore a suspended account.
        model.first_name = user.first_name
        model.last_name = user.last_name
        model.email = user.email
        model.phone = user.phone
        model.whatsapp = user.whatsapp
        model.avatar_key = user.avatar_key
        await self._session.commit()
        return model.to_entity()

    async def set_password(self, user: User) -> User:
        model = await self._session.get(UserModel, str(user.id))
        if model is None:
            raise EntityNotFoundError("User not found")
        model.hashed_password = user.hashed_password
        await self._session.commit()
        return model.to_entity()

    async def set_permissions(
        self, user_id: UUID, permissions: set[Permission], granted_by: UUID
    ) -> None:
        # Cleared and rewritten rather than diffed. The set is small, the
        # write is one transaction, and a diff is a third place for "what do
        # they have" to be computed slightly differently.
        await self._session.execute(
            delete(UserPermissionModel).where(
                UserPermissionModel.user_id == str(user_id)
            )
        )
        now = datetime.now(timezone.utc)
        for permission in permissions:
            self._session.add(
                UserPermissionModel(
                    user_id=str(user_id),
                    permission=permission.value,
                    granted_by=str(granted_by),
                    granted_at=now,
                )
            )
        await self._session.commit()

    async def count_by_status(self) -> dict[UserStatus, int]:
        # GROUP BY in the database: counting a paginated list in Python would
        # silently cap at the page size.
        result = await self._session.execute(
            select(UserModel.status, func.count()).group_by(UserModel.status)
        )
        return {UserStatus(status): count for status, count in result.all()}

    async def count_by_role(self) -> dict[UserRole, int]:
        result = await self._session.execute(
            select(UserModel.role, func.count()).group_by(UserModel.role)
        )
        return {UserRole(role): count for role, count in result.all()}

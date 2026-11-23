from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.user import User, UserRole, UserStatus
from app.infrastructure.database import Base


class UserModel(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: Object key, not a URL — see the entity.
    avatar_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Stripe's `cus_...`, once this person has been issued one. Indexed
    #: because a webhook that cannot be matched by payment reference is traced
    #: back through the customer.
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    role: Mapped[str] = mapped_column(String(20), default=UserRole.CUSTOMER.value)
    status: Mapped[str] = mapped_column(String(20), default=UserStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> User:
        from uuid import UUID

        return User(
            id=UUID(self.id),
            email=self.email,
            first_name=self.first_name,
            last_name=self.last_name,
            phone=self.phone,
            whatsapp=self.whatsapp,
            avatar_key=self.avatar_key,
            hashed_password=self.hashed_password,
            stripe_customer_id=self.stripe_customer_id,
            role=UserRole(self.role),
            status=UserStatus(self.status),
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, user: User) -> "UserModel":
        return cls(
            id=str(user.id),
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            # `full_name` is a property on the entity, never a column.
            phone=user.phone,
            whatsapp=user.whatsapp,
            avatar_key=user.avatar_key,
            hashed_password=user.hashed_password,
            stripe_customer_id=user.stripe_customer_id,
            role=user.role.value,
            status=user.status.value,
            created_at=user.created_at,
        )


class UserPermissionModel(Base):
    """One granted section, per person.

    A table rather than a column so "who can see payments?" is a query, and
    so a grant can carry who gave it and when — which is the question asked
    after something goes wrong, and the one a JSON blob cannot answer.
    """

    __tablename__ = "user_permissions"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, index=True)
    permission: Mapped[str] = mapped_column(String(40), primary_key=True)
    granted_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

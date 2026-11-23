from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.entities.password_reset import PasswordResetToken
from app.infrastructure.database import Base


class PasswordResetTokenModel(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # Unique + indexed: this is the lookup key, and two rows hashing the same
    # would mean a token that authenticates as two people.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    def to_entity(self) -> PasswordResetToken:
        return PasswordResetToken(
            id=UUID(self.id),
            user_id=UUID(self.user_id),
            token_hash=self.token_hash,
            expires_at=self.expires_at,
            used_at=self.used_at,
            created_at=self.created_at,
        )

    @classmethod
    def from_entity(cls, token: PasswordResetToken) -> "PasswordResetTokenModel":
        return cls(
            id=str(token.id),
            user_id=str(token.user_id),
            token_hash=token.token_hash,
            expires_at=token.expires_at,
            used_at=token.used_at,
            created_at=token.created_at,
        )

"""Putting a name to a comment.

Shared by listing and resolving because both hand a comment back to a console
that has to say who wrote it, and the answer must be the *author* in each
case. Resolving used to report the person who clicked the button, which
quietly reattributed a client's change request to whoever closed it.
"""

from dataclasses import dataclass
from uuid import UUID

from app.domain.entities.comment import Comment
from app.domain.repositories.user_repository import UserRepository


@dataclass
class CommentWithAuthor:
    comment: Comment
    #: Resolved here so the console does not need a second call per row, and
    #: falls back rather than rendering a bare id at somebody.
    author_name: str
    author_role: str | None = None
    author_avatar_key: str | None = None


async def author_info_of(
    users: UserRepository, user_id: UUID
) -> tuple[str, str | None, str | None]:
    author = await users.get_by_id(user_id)
    if author is None:
        return ("Someone", None, None)
    name = f"{author.first_name} {author.last_name}".strip() or "Someone"
    return (name, author.role.value, author.avatar_key)


async def name_of(users: UserRepository, user_id: UUID) -> str:
    name, _, _ = await author_info_of(users, user_id)
    return name

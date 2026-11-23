"""A client's whole conversation with us, grouped by the work it is about.

The gallery already shows what was said about one photograph. What it cannot
answer is "when will the rest be ready?" — a question about the project, not
about any frame in it. A client with nowhere to ask that asks it by email,
which is the thing the portal exists to replace.

Nothing new is stored. A comment with no `asset_id` has always meant a remark
about the project as a whole; this is the first screen that surfaces them.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from app.domain.entities.project import ProjectStage
from app.domain.entities.user import User
from app.domain.repositories.comment_repository import CommentRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository

from ._author import CommentWithAuthor

#: A long thread is still a thread. Capped so one project cannot make the
#: screen unbounded, newest kept.
MAX_PER_PROJECT = 200

#: Stands in for "never" when ordering. Never compared as a real date.
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Conversation:
    project_id: UUID
    project_title: str
    event_type: str
    stage: ProjectStage
    messages: list[CommentWithAuthor]


class ListConversations:
    def __init__(
        self,
        projects: ProjectRepository,
        comments: CommentRepository,
        users: UserRepository,
    ) -> None:
        self._projects = projects
        self._comments = comments
        self._users = users

    async def execute(self, actor: User) -> list[Conversation]:
        """Every project of theirs, with what has been said on it.

        Loaded in one pass rather than per conversation: a client has one or
        two projects, and two round trips to show a list of two is the kind
        of thing that becomes thirty later.
        """
        # Scoped to them by `customer_id`; no stage filter, because a client
        # can now see every project that is theirs. A draft they are talking
        # to us about is a conversation they should still be able to read.
        visible = await self._projects.list_all(
            limit=50, offset=0, customer_id=actor.id
        )
        if not visible:
            return []

        threads = await self._comments.list_for_projects([p.id for p in visible])

        # One lookup per distinct author across every thread. A conversation
        # is two people, however many projects it spans.
        authors = {c.author_id for thread in threads.values() for c in thread}
        people = await self._users.get_many(authors)

        def named(comment) -> CommentWithAuthor:
            person = people.get(comment.author_id)
            return CommentWithAuthor(
                comment, person.full_name if person else "Someone"
            )

        conversations = [
            Conversation(
                project_id=project.id,
                project_title=project.title,
                event_type=project.event_type,
                stage=project.stage,
                messages=[named(c) for c in threads.get(project.id, [])][
                    -MAX_PER_PROJECT:
                ],
            )
            for project in visible
        ]
        # The one most recently spoken on first — that is the conversation
        # somebody opened this screen for. Projects with nothing said yet
        # fall to the bottom rather than being hidden: "no messages" is where
        # the first one gets written.
        # Two keys, not one: sorting a datetime against None raises, and a
        # project nobody has written on has no date to compare. The first
        # element pushes the empty ones to the bottom without inventing a
        # timestamp for them.
        conversations.sort(
            key=lambda c: (
                bool(c.messages),
                c.messages[-1].comment.created_at if c.messages else EPOCH,
            ),
            reverse=True,
        )
        return conversations

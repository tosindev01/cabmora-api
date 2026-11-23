"""A link that lets somebody see a gallery without an account.

Not a `OneTimeToken`. Those are spent on use and belong to a `user_id`; this
is used many times by people the system has never heard of, and belongs to a
project. The secret is made and stored the same way — hashed, never readable —
because a share link is a credential whatever else it is.

What it deliberately does **not** do is lift the watermark. Whether the
originals are handed over is the project's `watermark_policy` read against
whether the job has been paid for, and that is the same question for a client
and for their aunt. A link cannot answer it differently.
"""

from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app.domain.entities._one_time_token import hash_token, new_token

#: Long enough to be useful, short enough that it is not forever. A public URL
#: to somebody's wedding that never expires outlives everybody's memory of
#: having created it, and there is no later moment at which anyone decides to
#: go and revoke it.
DEFAULT_TTL = timedelta(days=30)


@dataclass
class GalleryShare:
    project_id: UUID
    token_hash: str
    #: Who handed it out. Usually the client; an admin can too.
    created_by: UUID
    expires_at: datetime
    #: Set when somebody takes the link back. Kept rather than deleted — "who
    #: shared this, and when did we stop it" is the question asked after a
    #: photograph turns up somewhere it should not have.
    revoked_at: datetime | None = None
    last_viewed_at: datetime | None = None
    views: int = 0
    #: What the client called it — "Mum", "the group chat". Optional, and the
    #: reason a list of three links is something a person can act on rather
    #: than three identical rows.
    label: str = ""
    #: Whether this link shows a chosen few rather than the whole gallery.
    #:
    #: A separate flag from `asset_ids` being empty, and not redundant with
    #: it. A selective link whose photographs have since been deleted has no
    #: rows left, and "no rows" must not quietly come to mean "everything" —
    #: that would turn a link to one frame into a link to the whole wedding
    #: by deleting a file. Every link that existed before this feature has
    #: `selective = False`, which is what it always meant.
    selective: bool = False
    #: The chosen frames, by the id of the **original**. Empty and ignored
    #: unless `selective`.
    asset_ids: frozenset[UUID] = frozenset()
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def issue(
        cls,
        *,
        project_id: UUID,
        created_by: UUID,
        label: str = "",
        ttl: timedelta = DEFAULT_TTL,
        asset_ids: Collection[UUID] | None = None,
    ) -> tuple["GalleryShare", str]:
        """Return the record to store and the secret to put in the URL.

        The plaintext is handed back exactly once, like a password. If the
        client loses the link they make another and revoke the old one, which
        is the behaviour you want anyway.

        `asset_ids` of None shares the gallery, which is what every link did
        before there was a choice. A list shares those frames and no others.
        An **empty** list is refused rather than treated as either: it is the
        one input where the two readings differ by the whole gallery, so
        guessing is how somebody sends their album to the group chat while
        believing they sent one photograph.
        """
        if asset_ids is not None and not asset_ids:
            raise ValueError("Choose at least one photograph, or share all of them.")
        token, digest = new_token()
        share = cls(
            project_id=project_id,
            created_by=created_by,
            token_hash=digest,
            label=label.strip()[:80],
            expires_at=datetime.now(timezone.utc) + ttl,
            selective=asset_ids is not None,
            asset_ids=frozenset(asset_ids or ()),
        )
        return share, token

    def covers(self, *candidates: UUID) -> bool:
        """Whether this link shows a particular photograph.

        Several ids, because a frame can be replaced after the link is made.
        The share names what was chosen; a corrected version of that frame is
        the same photograph to whoever was sent it, so the caller passes the
        asset together with the ones it supersedes. Matching only the exact
        id would make a link go blank the moment the photographer fixed the
        picture it pointed at.
        """
        if not self.selective:
            return True
        return any(candidate in self.asset_ids for candidate in candidates)

    @staticmethod
    def hash_of(token: str) -> str:
        return hash_token(token)

    @property
    def is_usable(self) -> bool:
        if self.revoked_at is not None:
            return False
        expires = self.expires_at
        # SQLite hands back naive datetimes; compare like with like rather
        # than raising inside somebody opening a link.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)

    def viewed(self) -> None:
        """Count a visit.

        Counted because it is what makes revoking a decision somebody can
        make: "nobody has opened this in a month" and "this was opened forty
        times yesterday" call for opposite actions.
        """
        self.views += 1
        self.last_viewed_at = datetime.now(timezone.utc)

    def revoke(self) -> None:
        """Idempotent — revoking twice must not rewrite when it first stopped."""
        if self.revoked_at is None:
            self.revoked_at = datetime.now(timezone.utc)

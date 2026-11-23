"""A named part of a shoot, inside one project.

The gallery already answers "what is this file" — `GalleryChips` on the web
side derives Photos, Films, Updated and Commented straight from the assets, so
nobody has to tag anything and a derived chip can never go stale. What it
cannot answer is "which part of the day", because that is not in the files.
Ceremony, Portraits, Reception is a judgement somebody makes, and a judgement
needs somewhere to be recorded.

So this is the *filed* half, standing beside the derived half rather than
replacing it. Two consequences follow and both are deliberate:

**Filing says nothing about visibility.** Moving a photograph into a folder
must never release it. `released_at` stays exactly where it was. Organising a
shoot and deciding what a client may see are different decisions taken at
different moments, and a photographer who tidies up on a Sunday evening should
not thereby publish the test exposures.

**A folder may be empty.** Derived chips vanish when nothing matches; a folder
is made before it is filled, because the structure is how somebody thinks about
the work before they have sorted it.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.core.exceptions import ValidationError

MAX_NAME = 60


@dataclass
class Folder:
    project_id: UUID
    name: str
    #: Where it sits in the running order, ascending.
    #:
    #: Explicit rather than alphabetical, because the order is the meaning: a
    #: wedding runs Ceremony then Portraits then Reception, and sorting by
    #: name puts Reception first and Ceremony last. Nobody reads a day that
    #: way.
    position: int = 0
    #: How many assets are filed here. Hydrated by the repository for display,
    #: never stored — a counter on the row is a counter that goes wrong, and
    #: assets move between folders far more often than folders are created.
    asset_count: int = 0
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        self.rename(self.name)

    def rename(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("A folder needs a name.")
        self.name = cleaned[:MAX_NAME]

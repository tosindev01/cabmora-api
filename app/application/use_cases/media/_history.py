"""The frames a photograph replaced, in the order they were replaced.

A correction does not overwrite anything: `ConfirmUpload` records a new asset
pointing back at the one it supersedes, and the old frame stays — the client
asked for a change, not for the evidence to disappear, and the comments they
left still hang off it.

That chain was being thrown away at the edge. The gallery filtered superseded
frames out for the team and skipped them entirely for the client, so "show me
what this looked like before you fixed it" could not be answered by anything,
despite every row being present.
"""

from uuid import UUID

from app.domain.entities.asset import Asset


def earlier_versions(current: Asset, by_id: dict[UUID, Asset]) -> list[Asset]:
    """Frames this one replaced, newest first.

    Walks `supersedes` back through however many corrections were made: a
    photograph fixed twice has two earlier versions, and both are of interest
    to a client asking whether the second attempt is better than the first.

    Guarded against a chain that points at itself. `supersedes` is a
    self-reference with nothing in the schema stopping a loop, and one bad row
    must not hang the gallery for everybody — a truncated history is a
    recoverable annoyance, a spinning request is not.
    """
    seen: set[UUID] = {current.id}
    chain: list[Asset] = []
    frame: Asset | None = current
    while frame is not None and frame.supersedes is not None:
        if frame.supersedes in seen:
            break
        seen.add(frame.supersedes)
        frame = by_id.get(frame.supersedes)
        if frame is not None:
            chain.append(frame)
    return chain

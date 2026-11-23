"""How a stored object asks a browser to save rather than display it.

In `core/` because three layers have to say the same thing and none of them
owns it: R2 signs the header into a presigned URL, the local stand-in returns
it from its own route, and the invoice endpoint sets it on a PDF this process
rendered itself. A storage package cannot hold something a billing router
needs — that is the dependency rule pointing the wrong way.

A header, and not a `download` attribute on an anchor, because that attribute
is **ignored for cross-origin URLs**. A presigned R2 link is always
cross-origin, so the anchor opens the photograph in a tab and the client
reports that they cannot download anything. The server-side header is the only
version of this that works, and it also gets the filename right: the presigned
URL carries a query string, so a browser left to guess names the file after
the signature.
"""

from pathlib import PurePosixPath
from urllib.parse import quote


def attachment(filename: str) -> str:
    """A Content-Disposition value that survives a real filename.

    Two encodings on purpose, per RFC 6266: `filename` for anything that
    predates it, `filename*` for everything since. A wedding gallery is full
    of names a plain ASCII header cannot carry — accents, quotes, commas and
    semicolons, any of which ends the header early and truncates the name the
    file is saved under.

    Stripped to its last path segment first. The name arrives from an upload,
    so it is somebody else's text, and a separator in it is theirs to have
    sent rather than ours to pass on to a filesystem.
    """
    safe = PurePosixPath(filename).name.replace("\\", "_").strip() or "download"
    # `replace` rather than `ignore`: a name that is entirely non-ASCII would
    # otherwise collapse to the empty string, and the legacy half of the
    # header would name the file nothing at all.
    legacy = safe.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return f"attachment; filename=\"{legacy}\"; filename*=UTF-8''{quote(safe)}"

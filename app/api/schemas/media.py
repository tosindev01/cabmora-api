from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.entities.project import ProjectStage


class UploadRequest(BaseModel):
    """What the browser knows before it sends a single byte."""

    #: Computed in the browser. It becomes the object's key, which is why the
    #: use case checks its shape rather than trusting it.
    content_hash: str = Field(min_length=64, max_length=64)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=128)
    byte_size: int = Field(gt=0)


class UploadTicketResponse(BaseModel):
    upload_id: str
    part_size: int
    part_urls: list[str]


class AssetResponse(BaseModel):
    id: UUID
    project_id: UUID
    filename: str
    kind: str
    content_hash: str
    #: False until the watermarked preview and thumbnail have been generated.
    #: The gallery must not show an original in the meantime.
    renditions_ready: bool
    #: Whether the client may see this photograph. False by default.
    released: bool = False
    #: Which folder it is filed under, or null for unfiled. Staff-side
    #: organisation: the id carries no name and the client gallery ignores it.
    folder_id: UUID | None = None


class ReleaseRequest(BaseModel):
    asset_ids: list[UUID] = Field(min_length=1)
    #: False withholds them again — a photograph shown by mistake has to be
    #: retractable, not permanent.
    released: bool = True
    #: A line from whoever is releasing them, carried into the email the
    #: client gets. Ignored when withholding: taking work back is silent, and
    #: a note attached to nothing would simply be lost.
    #:
    #: Capped at something a person would write by hand. This is the one
    #: field here whose content a client reads verbatim, so the length is a
    #: limit on the message and not on the markup — the templates escape it.
    message: str | None = Field(default=None, max_length=2000)


class ReleasePreviewResponse(BaseModel):
    """What a release would do, answered by the thing that would do it.

    Exists so the console's confirmation step does not have to re-derive the
    release rules for itself. A copy in the frontend is right until the day
    the rules change and silently wrong afterwards, which is the worst thing
    a confirmation dialog can be.
    """

    #: How many photographs were picked.
    selected: int
    #: How many would actually change hands, allowing for the release mode
    #: and ignoring anything already where it should be.
    affected: int
    #: Of those, how many have no watermarked copy yet — released, and still
    #: not viewable.
    preview_pending: int
    #: Whether this sends the client an email.
    notifies_client: bool
    #: Where the project would end up, or null if it stays put.
    moves_to_stage: ProjectStage | None = None
    #: Whether the client would get the originals rather than marked copies.
    hands_over_originals: bool


class AssetVersionResponse(BaseModel):
    """One frame in a photograph's history."""

    id: UUID
    filename: str
    #: Null when this viewer may not be handed this file. The version still
    #: appears — that a correction happened is not a secret, even where the
    #: file behind it is not theirs.
    url: str | None
    uploaded_at: datetime
    #: True for the frame currently in the gallery. Stated rather than left to
    #: list order, so a before/after cannot be drawn the wrong way round.
    is_current: bool


class VisibleAssetResponse(AssetResponse):
    """An asset plus, when this person may see it, a link that expires."""

    #: Null when the viewer may not be handed the file yet — the row still
    #: appears, so a client can tell work exists without receiving it.
    url: str | None = None
    #: True when the link is the untouched original rather than a preview.
    is_original: bool
    #: The media type behind `url`. A gallery draws a player for `video/*` and
    #: an image for anything else; without it the only clue is the filename,
    #: which is how a .mov ends up inside an `<img>` tag.
    content_type: str | None = None
    #: The frame that replaced this one. Only ever populated for whoever
    #: manages the project — a client is shown the correction in its place.
    superseded_by: UUID | None = None
    #: The watermarked copy does not exist yet, so however released this
    #: photograph is, no client can be shown it. Surfaced rather than left
    #: implicit: uploaded, released and viewable are three different states
    #: and a console that draws them identically teaches nobody the
    #: difference until something goes wrong.
    preview_pending: bool = False
    #: The worker tried and gave up — the file is not one it can read.
    #:
    #: Separate from `preview_pending` rather than folded into it. Both mean
    #: "no preview exists", but one resolves itself and the other never will,
    #: and a console badging a dead upload as "pending" tells somebody to wait
    #: for something that is not coming.
    preview_failed: bool = False
    #: How many earlier frames this one replaced. Zero for almost everything;
    #: above zero means there is a before-and-after worth looking at, which is
    #: what a gallery tile badges itself from. The frames themselves come from
    #: GET .../assets/{id}/versions.
    supersedes_count: int = 0


class UploadAuthorisationResponse(BaseModel):
    """Either something to upload, or an asset that already exists."""

    key: str
    #: Null when the file was already stored — there is nothing to send.
    ticket: UploadTicketResponse | None = None
    #: Present only when identical bytes were already held.
    asset: AssetResponse | None = None


class ConfirmUploadRequest(UploadRequest):
    upload_id: str
    #: In part order. The provider reassembles by position, so a reordered
    #: list produces a corrupt file rather than an error.
    etags: list[str] = Field(min_length=1)
    #: The photograph this upload corrects. The replacement inherits whether
    #: the client could see the old one, so a fix for something they have
    #: already complained about does not need releasing a second time.
    replaces: UUID | None = None


class DeletedAssetsResponse(BaseModel):
    """How many assets a delete actually removed.

    More than one is normal: a photograph brings its watermarked rendition and
    any version it replaced with it. Saying "1 removed" when three files went
    would misreport what the storage figure is about to do.
    """

    removed: int


class FolderResponse(BaseModel):
    id: UUID
    name: str
    position: int
    #: Photographs filed here, counted the way the gallery counts them —
    #: originals that have not been superseded.
    asset_count: int


class CreateFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class RenameFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ReorderFoldersRequest(BaseModel):
    #: The complete running order, not a move. Reconciling "this one is now
    #: third" against everyone else's positions is how two people dragging at
    #: once end up with an order that means nothing.
    folder_ids: list[UUID]


class FileAssetsRequest(BaseModel):
    asset_ids: list[UUID] = Field(min_length=1)
    #: Null unfiles them, which is how photographs leave a folder without
    #: anything being deleted.
    folder_id: UUID | None = None


class FiledResponse(BaseModel):
    moved: int


class DownloadLinkResponse(BaseModel):
    """Where to send the browser so the file lands on the device."""

    #: Signed, expires in minutes, and carries an `attachment` disposition —
    #: so following it saves the file instead of opening it.
    url: str


class LibraryItemResponse(BaseModel):
    """One photograph in a client's own library, across every project."""

    id: UUID
    filename: str
    url: str
    content_type: str | None = None
    #: Whether this link is the untouched file rather than the watermarked
    #: copy, so a save button can say which one it is handing over.
    is_original: bool
    #: Whether a save button should appear at all. Separate from the file
    #: behind the link: downloads on with the job unpaid saves the
    #: watermarked copy.
    downloadable: bool
    released_at: datetime | None = None
    project_id: UUID
    project_title: str
    project_event_type: str

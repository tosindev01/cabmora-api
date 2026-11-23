"""Dependency-injection wiring: session -> repositories -> use cases -> current user."""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query
from fastapi.security import APIKeyCookie, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.support.report_issue import (
    ListIssues,
    ListMyIssues,
    ReportIssue,
    UpdateIssue,
)
from app.infrastructure.repositories.issue_report_repository_impl import (
    SqlAlchemyIssueReportRepository,
)
from app.domain.repositories.issue_report_repository import IssueReportRepository
from app.application.use_cases.notifications.notifier import Notifier
from app.application.use_cases.notifications.read import (
    CountUnread,
    ListNotifications,
    MarkNotificationsRead,
)
from app.domain.repositories.notification_repository import NotificationRepository
from app.infrastructure.repositories.notification_repository_impl import (
    SqlAlchemyNotificationRepository,
)
from app.application.use_cases.account.change_avatar import (
    ChangeAvatar,
)
from app.application.use_cases.account.change_password import ChangePassword
from app.application.use_cases.account.preferences import (
    GetPreferences,
    UpdatePreferences,
)
from app.domain.repositories.preferences_repository import PreferencesRepository
from app.infrastructure.repositories.preferences_repository_impl import (
    SqlAlchemyPreferencesRepository,
)
from app.infrastructure.email.preference_aware_sender import PreferenceAwareEmailSender
from app.application.use_cases.account.update_profile import UpdateProfile
from app.application.use_cases.auth.login_user import LoginUser
from app.application.use_cases.auth.register_user import RegisterUser
from app.application.use_cases.enquiries.confirm_consultation import ConfirmConsultation
from app.application.use_cases.enquiries.list_enquiries import ListEnquiries
from app.application.use_cases.enquiries.list_open_slots import ListOpenSlots
from app.application.use_cases.enquiries.add_note import AddEnquiryNote
from app.application.use_cases.enquiries.convert_enquiry import ConvertEnquiry
from app.application.use_cases.enquiries.get_enquiry import GetEnquiry
from app.application.use_cases.enquiries.list_availability import ListAvailability
from app.application.use_cases.enquiries.schedule_consultation import (
    ScheduleConsultation,
)
from app.application.use_cases.enquiries.submit_enquiry import SubmitEnquiry
from app.application.use_cases.enquiries.triage_enquiries import TriageEnquiries
from app.application.use_cases.marketing.public_stats import GetPublicStats
from app.application.use_cases.media.delete_asset import DeleteAsset
from app.application.use_cases.media.download_asset import DownloadAsset
from app.application.use_cases.media.list_my_media import ListMyMedia
from app.application.use_cases.media.manage_folders import ManageFolders
from app.application.use_cases.sharing.share_preview import GetSharePreview
from app.application.use_cases.enquiries.update_enquiry import UpdateEnquiry
from app.application.use_cases.auth.request_password_reset import RequestPasswordReset
from app.application.use_cases.auth.reset_password import ResetPassword
from app.application.use_cases.invites.accept_invite import AcceptInvite
from app.application.use_cases.creators.list_applications import (
    GetCreatorApplication,
    ListCreatorApplications,
)
from app.application.use_cases.creators.review_application import (
    ReviewCreatorApplication,
)
from app.application.use_cases.creators.submit_application import (
    SubmitCreatorApplication,
)
from app.application.use_cases.creators.studio_profile import (
    GetMyCreatorStudio,
    GetPublicCreatorStudio,
    ListCreatorBookings,
    SubmitCreatorBooking,
    UpdateCreatorBookingStatus,
    UpdateMyCreatorStudio,
)
from app.domain.repositories.creator_studio_repository import CreatorStudioRepository
from app.infrastructure.repositories.creator_studio_repository_impl import (
    SqlAlchemyCreatorStudioRepository,
)
from app.application.use_cases.collaboration.workspace import (
    CreateProjectTask,
    DeleteProjectTask,
    GetCreatorBriefing,
    ListMyCalls,
    ListProjectCalls,
    ListProjectTasks,
    RequestProjectCall,
    RespondToProjectCall,
    UpdateProjectTask,
)
from app.domain.repositories.collaboration_repository import CollaborationRepository
from app.infrastructure.repositories.collaboration_repository_impl import (
    SqlAlchemyCollaborationRepository,
)
from app.application.use_cases.invites.provision_account import ProvisionAccount
from app.application.use_cases.projects.change_project_stage import ChangeProjectStage
from app.application.use_cases.projects.create_project import CreateProject
from app.application.use_cases.projects.approve_project import ApproveProject
from app.application.use_cases.projects.get_project import GetProject
from app.application.use_cases.projects.rate_project import RateProject
from app.application.use_cases.reviews.moderate_reviews import (
    ListPublishedReviews,
    ModerateReviews,
)
from app.application.use_cases.projects.set_project_members import SetProjectMembers
from app.application.use_cases.projects.list_projects import ListProjects
from app.application.use_cases.projects.summarise_projects import SummariseProjects
from app.application.use_cases.projects.update_project import UpdateProject
from app.application.use_cases.users.count_users import CountUsers
from app.application.use_cases.users.get_user import GetUser
from app.application.use_cases.users.list_users import ListUsers
from app.application.use_cases.users.update_user import UpdateUser
from app.core.config import get_settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.domain.entities.user import Permission, User, UserRole, UserStatus
from app.domain.repositories.enquiry_repository import EnquiryRepository
from app.domain.repositories.creator_application_repository import (
    CreatorApplicationRepository,
)
from app.domain.repositories.invite_repository import InviteRepository
from app.domain.services.invoice_renderer import (
    BankTransferDetails,
    InvoiceRenderer,
    IssuerIdentity,
)
from app.domain.repositories.password_reset_repository import PasswordResetRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.application.use_cases.admin.grant_permissions import GrantPermissions
from app.application.use_cases.admin.manage_access_groups import ManageAccessGroups
from app.domain.repositories.access_group_repository import AccessGroupRepository
from app.infrastructure.repositories.access_group_repository_impl import (
    SqlAlchemyAccessGroupRepository,
)
from app.application.use_cases.admin.creator_performance import CreatorPerformanceReport
from app.application.use_cases.admin.dashboard_counts import CountDashboard
from app.application.use_cases.admin.monthly_report import MonthlyReport
from app.application.use_cases.billing.create_invoice import CreateInvoice
from app.application.use_cases.billing.handle_gateway_event import HandleGatewayEvent
from app.application.use_cases.billing.issue_invoice import IssueInvoice
from app.application.use_cases.billing.render_invoice import RenderInvoice
from app.application.use_cases.billing.list_invoices import GetInvoice, ListInvoices
from app.application.use_cases.billing.list_payments import ListPayments
from app.application.use_cases.billing.record_payment import ConfirmPayment, RecordPayment
from app.application.use_cases.billing.refund_payment import ConfirmRefund, RefundPayment
from app.application.use_cases.billing.start_bank_transfer import StartBankTransfer
from app.application.use_cases.billing.unmatched_funds import (
    ListUnmatchedFunds,
    MarkFundsHandled,
)
from app.application.use_cases.billing.start_checkout import StartCheckout
from app.application.use_cases.billing.void_invoice import VoidInvoice
from app.domain.repositories.invoice_repository import InvoiceRepository
from app.domain.repositories.unmatched_funds_repository import (
    UnmatchedFundsRepository,
)
from app.domain.services.email_sender import EmailSender
from app.domain.services.payment_gateway import PaymentGateway
from app.infrastructure.payments.fake_payment_gateway import FakePaymentGateway
from app.infrastructure.payments.stripe_payment_gateway import StripePaymentGateway
from app.infrastructure.repositories.unmatched_funds_repository_impl import (
    SqlAlchemyUnmatchedFundsRepository,
)
from app.infrastructure.repositories.invoice_repository_impl import (
    SqlAlchemyInvoiceRepository,
)
from app.domain.services.meeting_scheduler import ManualScheduler, MeetingScheduler
from app.domain.repositories.user_repository import UserRepository
from app.infrastructure.database import SessionFactory, get_session
from app.infrastructure.repositories.enquiry_repository_impl import (
    SqlAlchemyEnquiryRepository,
)
from app.infrastructure.email.logging_email_sender import LoggingEmailSender
from app.infrastructure.email.mailtrap_email_sender import MailtrapEmailSender
from app.infrastructure.scheduling.google_calendar_scheduler import (
    GoogleCalendarScheduler,
)
from app.domain.services.media_storage import MediaStorage
from app.infrastructure.storage.local_media_storage import LocalMediaStorage
from app.infrastructure.storage.r2_media_storage import R2MediaStorage
from app.domain.repositories.folder_repository import FolderRepository
from app.domain.repositories.media_repository import MediaRepository
from app.infrastructure.repositories.folder_repository_impl import (
    SqlAlchemyFolderRepository,
)
from app.infrastructure.repositories.media_repository_impl import (
    SqlAlchemyMediaRepository,
)
from app.application.use_cases.media.request_upload import RequestUpload
from app.application.use_cases.media.confirm_upload import ConfirmUpload
from app.application.use_cases.sharing.manage_shares import ManageGalleryShares
from app.application.use_cases.sharing.view_shared_gallery import ViewSharedGallery
from app.application.use_cases.media.list_asset_versions import ListAssetVersions
from app.application.use_cases.media.list_project_assets import ListProjectAssets
from app.application.use_cases.media.preview_release import PreviewRelease
from app.application.use_cases.media.release_assets import ReleaseAssets
from app.application.use_cases.media.generate_renditions import GenerateRenditions
from app.domain.services.image_processor import ImageProcessor
from app.infrastructure.imaging.pillow_processor import PillowImageProcessor
from app.application.use_cases.comments.add_comment import AddComment
from app.application.use_cases.comments.list_comments import ListComments
from app.application.use_cases.comments.list_conversations import ListConversations
from app.application.use_cases.comments.resolve_comment import ResolveComment
from app.domain.repositories.comment_repository import CommentRepository
from app.domain.repositories.gallery_share_repository import GalleryShareRepository
from app.domain.repositories.rating_repository import RatingRepository
from app.infrastructure.repositories.gallery_share_repository_impl import (
    SqlAlchemyGalleryShareRepository,
)
from app.infrastructure.repositories.rating_repository_impl import (
    SqlAlchemyRatingRepository,
)
from app.infrastructure.repositories.comment_repository_impl import (
    SqlAlchemyCommentRepository,
)
from app.infrastructure.documents.reportlab_invoice_renderer import (
    ReportLabInvoiceRenderer,
)
from app.infrastructure.repositories.password_reset_repository_impl import (
    SqlAlchemyPasswordResetRepository,
)
from app.infrastructure.repositories.creator_application_repository_impl import (
    SqlAlchemyCreatorApplicationRepository,
)
from app.infrastructure.repositories.invite_repository_impl import (
    SqlAlchemyInviteRepository,
)
from app.infrastructure.repositories.project_repository_impl import (
    SqlAlchemyProjectRepository,
)
from app.infrastructure.repositories.user_repository_impl import (
    SqlAlchemyUserRepository,
)

logger = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Pagination:
    limit: int
    offset: int


def pagination(
    limit: int = Query(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    offset: int = Query(default=0, ge=0),
) -> Pagination:
    """One place for the page size and its ceiling.

    The cap is not cosmetic: without `le`, `?limit=1000000` is a trivial way to
    make the database do unbounded work on an authenticated endpoint.
    """
    return Pagination(limit=limit, offset=offset)


PaginationDep = Annotated[Pagination, Depends(pagination)]

# Two schemes, both declared so OpenAPI documents how auth actually works.
# Browsers send the HttpOnly cookie automatically; everything else — mobile,
# CI, curl — keeps using the bearer header. Neither raises on its own, because
# a request is authenticated if *either* carries a token.
cookie_scheme = APIKeyCookie(name=get_settings().session_cookie_name, auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


# --- Repositories ---
def get_user_repository(session: SessionDep) -> UserRepository:
    return SqlAlchemyUserRepository(session)


def get_enquiry_repository(session: SessionDep) -> EnquiryRepository:
    return SqlAlchemyEnquiryRepository(session)


def get_project_repository(session: SessionDep) -> ProjectRepository:
    return SqlAlchemyProjectRepository(session)


def get_password_reset_repository(session: SessionDep) -> PasswordResetRepository:
    return SqlAlchemyPasswordResetRepository(session)


def get_creator_application_repository(
    session: SessionDep,
) -> CreatorApplicationRepository:
    return SqlAlchemyCreatorApplicationRepository(session)


def get_invite_repository(session: SessionDep) -> InviteRepository:
    return SqlAlchemyInviteRepository(session)


def get_email_sender() -> EmailSender:
    """Pick the sender from config.

    `logging` prints the invite link instead of delivering it — correct locally,
    and a silent failure in production. The config guard refuses to boot with
    `mailtrap` and no token, so an unreachable branch here is not possible.
    """
    settings = get_settings()
    if settings.email_backend == "mailtrap":
        return MailtrapEmailSender(
            api_token=settings.mailtrap_api_token or "",
            sender_email=settings.mailtrap_sender,
            sender_name=settings.mailtrap_sender_name,
            support_email=settings.support_email,
            admin_base_url=settings.admin_base_url,
        )
    return LoggingEmailSender()


def get_media_storage() -> MediaStorage:
    """The one place the storage backend is chosen.

    Raises rather than returning a broken client when R2 is unconfigured: the
    API boots fine without credentials (everything else still works), but an
    upload must fail loudly here rather than hand the browser URLs that go
    nowhere.
    """
    settings = get_settings()
    if settings.media_backend == "r2":
        if not settings.media_is_configured:
            raise RuntimeError(
                "Media storage is not configured. Set R2_ACCOUNT_ID, R2_BUCKET, "
                "R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY to enable uploads."
            )
        return R2MediaStorage(
            endpoint=settings.r2_endpoint,
            bucket=settings.r2_bucket or "",
            access_key_id=settings.r2_access_key_id or "",
            secret_access_key=settings.r2_secret_access_key or "",
        )
    return LocalMediaStorage(
        root=Path(settings.media_root),
        secret=settings.jwt_secret_key,
        # Relative on purpose: an absolute host would point at one console and
        # break the other, and cross-origin PUTs fail before they start. The
        # same reasoning as `api-client`'s relative base URL.
        base_url="/api/v1",
    )


MediaStorageDep = Annotated[MediaStorage, Depends(get_media_storage)]


def get_optional_media_storage() -> MediaStorage | None:
    """Storage if it is configured, otherwise None — never an exception.

    `get_media_storage` raises on purpose: an upload that cannot work must fail
    loudly rather than hand out URLs to nowhere. But a profile picture is a
    decoration on a response, and signing one is not a reason for `GET
    /auth/me` to return 500 on an environment with no bucket. Reads that merely
    *garnish* a response take this one.
    """
    try:
        return get_media_storage()
    except RuntimeError:
        return None


OptionalStorageDep = Annotated[MediaStorage | None, Depends(get_optional_media_storage)]


def get_media_repository(session: SessionDep) -> MediaRepository:
    return SqlAlchemyMediaRepository(session)


MediaRepoDep = Annotated[MediaRepository, Depends(get_media_repository)]


def get_folder_repository(session: SessionDep) -> FolderRepository:
    return SqlAlchemyFolderRepository(session)


FolderRepoDep = Annotated[FolderRepository, Depends(get_folder_repository)]


def get_image_processor() -> ImageProcessor:
    """One implementation today. A port anyway, so the use case that decides
    *when* renditions are made never learns how a JPEG is encoded."""
    return PillowImageProcessor()


ImageProcessorDep = Annotated[ImageProcessor, Depends(get_image_processor)]
def get_comment_repository(session: SessionDep) -> CommentRepository:
    return SqlAlchemyCommentRepository(session)


CommentRepoDep = Annotated[CommentRepository, Depends(get_comment_repository)]
def get_meeting_scheduler() -> MeetingScheduler:
    """The one place the scheduling backend is chosen.

    `manual` records a link the admin pasted; `google` creates the call itself.
    `ScheduleConsultation` cannot tell the difference — it depends on the port.
    """
    settings = get_settings()
    if settings.meeting_backend == "google":
        return GoogleCalendarScheduler(
            client_id=settings.google_client_id or "",
            client_secret=settings.google_client_secret or "",
            refresh_token=settings.google_refresh_token or "",
            calendar_id=settings.google_calendar_id,
        )
    return ManualScheduler()


UserRepoDep = Annotated[UserRepository, Depends(get_user_repository)]
EnquiryRepoDep = Annotated[EnquiryRepository, Depends(get_enquiry_repository)]
ProjectRepoDep = Annotated[ProjectRepository, Depends(get_project_repository)]
InviteRepoDep = Annotated[InviteRepository, Depends(get_invite_repository)]
CreatorApplicationRepoDep = Annotated[
    CreatorApplicationRepository, Depends(get_creator_application_repository)
]
PasswordResetRepoDep = Annotated[
    PasswordResetRepository, Depends(get_password_reset_repository)
]
def get_notifying_email_sender(session: SessionDep) -> EmailSender:
    """The configured sender, wrapped so it honours what people declined.

    `get_email_sender` stays unwrapped and is what picks the backend; this is
    what everything in a request should take. The wrapper needs a session —
    preferences live in the database — which is the only reason the two are
    separate dependencies rather than one.
    """
    return PreferenceAwareEmailSender(
        get_email_sender(), SqlAlchemyPreferencesRepository(session)
    )


#: Deliberately the wrapped one. Every use case that sends mail takes this, so
#: honouring a preference is the default rather than something each new feature
#: has to remember.
EmailSenderDep = Annotated[EmailSender, Depends(get_notifying_email_sender)]
SchedulerDep = Annotated[MeetingScheduler, Depends(get_meeting_scheduler)]


# ── use cases that need the repository aliases above ─────────────────
# ── notifications ────────────────────────────────────────────────────────
def get_notification_repository(session: SessionDep) -> NotificationRepository:
    return SqlAlchemyNotificationRepository(session)


NotificationRepoDep = Annotated[
    NotificationRepository, Depends(get_notification_repository)
]


def get_notifier(
    notifications: NotificationRepoDep, users: UserRepoDep
) -> Notifier:
    """Announcing an event to the people it concerns.

    Injected into the use cases that cause those events rather than wrapped
    around the email sender, because audiences and email addresses are not the
    same thing — see the Notifier's own docstring.
    """
    return Notifier(notifications, users)


NotifierDep = Annotated[Notifier, Depends(get_notifier)]


def get_list_notifications(notifications: NotificationRepoDep) -> ListNotifications:
    return ListNotifications(notifications)


def get_count_unread_notifications(notifications: NotificationRepoDep) -> CountUnread:
    return CountUnread(notifications)


def get_mark_notifications_read(
    notifications: NotificationRepoDep,
) -> MarkNotificationsRead:
    return MarkNotificationsRead(notifications)


# ── support ──────────────────────────────────────────────────────────────
def get_issue_repository(session: SessionDep) -> IssueReportRepository:
    return SqlAlchemyIssueReportRepository(session)


IssueRepoDep = Annotated[IssueReportRepository, Depends(get_issue_repository)]


def get_report_issue(issues: IssueRepoDep, notifier: NotifierDep) -> ReportIssue:
    return ReportIssue(issues, notifier)


def get_list_my_issues(issues: IssueRepoDep) -> ListMyIssues:
    return ListMyIssues(issues)


def get_list_issues(issues: IssueRepoDep, users: UserRepoDep) -> ListIssues:
    return ListIssues(issues, users)


def get_update_issue(issues: IssueRepoDep) -> UpdateIssue:
    return UpdateIssue(issues)


def get_preferences_repository(session: SessionDep) -> PreferencesRepository:
    return SqlAlchemyPreferencesRepository(session)


PreferencesRepoDep = Annotated[PreferencesRepository, Depends(get_preferences_repository)]


def get_get_preferences(preferences: PreferencesRepoDep) -> GetPreferences:
    return GetPreferences(preferences)


def get_update_preferences(preferences: PreferencesRepoDep) -> UpdatePreferences:
    return UpdatePreferences(preferences)


# ── account ──────────────────────────────────────────────────────────────
def get_update_profile(users: UserRepoDep) -> UpdateProfile:
    return UpdateProfile(users)


def get_change_password(users: UserRepoDep) -> ChangePassword:
    return ChangePassword(users)


def get_change_avatar(
    users: UserRepoDep, storage: MediaStorageDep, images: ImageProcessorDep
) -> ChangeAvatar:
    return ChangeAvatar(users, storage, images)


def get_request_upload(
    projects: ProjectRepoDep, media: MediaRepoDep, storage: MediaStorageDep
) -> RequestUpload:
    return RequestUpload(projects, media, storage)


def get_confirm_upload(
    projects: ProjectRepoDep, media: MediaRepoDep, storage: MediaStorageDep
) -> ConfirmUpload:
    return ConfirmUpload(projects, media, storage)


def get_generate_renditions(
    media: MediaRepoDep,
    projects: ProjectRepoDep,
    storage: MediaStorageDep,
    images: ImageProcessorDep,
) -> GenerateRenditions:
    return GenerateRenditions(media, projects, storage, images)


#: What a router schedules to have one photograph rendered straight away.
RenderAsset = Callable[[UUID], Awaitable[None]]


def get_render_asset() -> RenderAsset:
    """A background renderer, with a session of its own.

    Deliberately not the request's session: this runs *after* the response has
    been sent, by which point FastAPI has closed it. Taking `SessionDep` here
    would hand the task a session that is already gone, and it would fail
    every time in a place nobody is watching.

    Nothing it does may raise. An exception in a background task has no
    request to fail and no client to tell, so it is logged and swallowed —
    and the scheduled sweep will pick the asset up regardless, which is the
    entire reason that sweep still exists.
    """

    async def render(asset_id: UUID) -> None:
        if not get_settings().media_is_configured:
            return
        try:
            async with SessionFactory() as session:
                await GenerateRenditions(
                    SqlAlchemyMediaRepository(session),
                    SqlAlchemyProjectRepository(session),
                    get_media_storage(),
                    get_image_processor(),
                ).execute_one(asset_id)
        except Exception:  # noqa: BLE001 — see docstring
            logger.exception("[renditions] background render of %s failed", asset_id)

    return render


def get_list_conversations(
    projects: ProjectRepoDep, comments: CommentRepoDep, users: UserRepoDep
) -> ListConversations:
    return ListConversations(projects, comments, users)


def get_add_comment(
    projects: ProjectRepoDep,
    comments: CommentRepoDep,
    media: MediaRepoDep,
    users: UserRepoDep,
    email: EmailSenderDep,
    notifier: NotifierDep,
) -> AddComment:
    settings = get_settings()
    return AddComment(
        projects,
        comments,
        media,
        users,
        email,
        notifier,
        settings.public_base_url,
        settings.admin_base_url,
        settings.enquiry_notification_email,
    )


def get_list_comments(
    projects: ProjectRepoDep, comments: CommentRepoDep, users: UserRepoDep
) -> ListComments:
    return ListComments(projects, comments, users)


def get_resolve_comment(
    projects: ProjectRepoDep,
    comments: CommentRepoDep,
    users: UserRepoDep,
    email: EmailSenderDep,
    notifier: NotifierDep,
) -> ResolveComment:
    return ResolveComment(
        projects, comments, users, email, notifier, get_settings().public_base_url
    )


# --- Use cases ---
def get_register_user(users: UserRepoDep) -> RegisterUser:
    return RegisterUser(users)


def get_login_user(users: UserRepoDep) -> LoginUser:
    return LoginUser(users)


def get_confirm_consultation(
    enquiries: EnquiryRepoDep,
    scheduler: SchedulerDep,
    email: EmailSenderDep,
    notifier: NotifierDep,
) -> ConfirmConsultation:
    return ConfirmConsultation(enquiries, scheduler, email, notifier)


def get_list_open_slots(enquiries: EnquiryRepoDep) -> ListOpenSlots:
    return ListOpenSlots(enquiries)


def get_submit_enquiry(
    enquiries: EnquiryRepoDep, email: EmailSenderDep, notifier: NotifierDep
) -> SubmitEnquiry:
    return SubmitEnquiry(
        enquiries, email, notifier, get_settings().enquiry_notification_email
    )


def get_triage_enquiries(
    enquiries: EnquiryRepoDep, users: UserRepoDep
) -> TriageEnquiries:
    return TriageEnquiries(enquiries, users)


def get_public_stats(projects: ProjectRepoDep) -> GetPublicStats:
    return GetPublicStats(projects, get_settings().founded_year)


def get_list_enquiries(enquiries: EnquiryRepoDep) -> ListEnquiries:
    return ListEnquiries(enquiries)


def get_list_users(users: UserRepoDep) -> ListUsers:
    return ListUsers(users)


def get_update_user(users: UserRepoDep) -> UpdateUser:
    return UpdateUser(users)


def get_get_enquiry(enquiries: EnquiryRepoDep, users: UserRepoDep) -> GetEnquiry:
    return GetEnquiry(enquiries, users)


def get_update_enquiry(enquiries: EnquiryRepoDep) -> UpdateEnquiry:
    return UpdateEnquiry(enquiries)


def get_add_enquiry_note(enquiries: EnquiryRepoDep) -> AddEnquiryNote:
    return AddEnquiryNote(enquiries)


def get_schedule_consultation(
    enquiries: EnquiryRepoDep,
    scheduler: SchedulerDep,
    email: EmailSenderDep,
    notifier: NotifierDep,
) -> ScheduleConsultation:
    return ScheduleConsultation(enquiries, scheduler, email, notifier)


def get_provision_account(
    users: UserRepoDep, invites: InviteRepoDep, email: EmailSenderDep
) -> ProvisionAccount:
    return ProvisionAccount(
        users,
        invites,
        email,
        get_settings().public_base_url,
        get_settings().admin_base_url,
    )


def get_submit_creator_application(
    applications: CreatorApplicationRepoDep,
    email: EmailSenderDep,
    notifier: NotifierDep,
) -> SubmitCreatorApplication:
    return SubmitCreatorApplication(applications, email, notifier)


def get_list_creator_applications(
    applications: CreatorApplicationRepoDep,
) -> ListCreatorApplications:
    return ListCreatorApplications(applications)


def get_get_creator_application(
    applications: CreatorApplicationRepoDep,
) -> GetCreatorApplication:
    return GetCreatorApplication(applications)


def get_review_creator_application(
    applications: CreatorApplicationRepoDep,
    users: UserRepoDep,
    invites: InviteRepoDep,
    email: EmailSenderDep,
) -> ReviewCreatorApplication:
    return ReviewCreatorApplication(
        applications,
        ProvisionAccount(
            users,
            invites,
            email,
            get_settings().public_base_url,
            get_settings().admin_base_url,
        ),
        email,
    )


def get_accept_invite(users: UserRepoDep, invites: InviteRepoDep) -> AcceptInvite:
    return AcceptInvite(users, invites)


def get_request_password_reset(
    users: UserRepoDep, tokens: PasswordResetRepoDep, email: EmailSenderDep
) -> RequestPasswordReset:
    return RequestPasswordReset(users, tokens, email, get_settings().public_base_url)


def get_reset_password(
    users: UserRepoDep, tokens: PasswordResetRepoDep
) -> ResetPassword:
    return ResetPassword(users, tokens)


def get_create_project(projects: ProjectRepoDep, users: UserRepoDep) -> CreateProject:
    return CreateProject(projects, users)


def get_convert_enquiry(
    enquiries: EnquiryRepoDep,
    users: UserRepoDep,
    invites: InviteRepoDep,
    email: EmailSenderDep,
    projects: ProjectRepoDep,
) -> ConvertEnquiry:
    return ConvertEnquiry(
        enquiries,
        users,
        ProvisionAccount(
            users,
            invites,
            email,
            get_settings().public_base_url,
            get_settings().admin_base_url,
        ),
        CreateProject(projects, users),
    )


def get_list_projects(projects: ProjectRepoDep) -> ListProjects:
    return ListProjects(projects)


def get_get_project(projects: ProjectRepoDep) -> GetProject:
    return GetProject(projects)


def get_set_project_members(
    projects: ProjectRepoDep, users: UserRepoDep
) -> SetProjectMembers:
    return SetProjectMembers(projects, users)


def get_approve_project(
    projects: ProjectRepoDep, notifier: NotifierDep
) -> ApproveProject:
    return ApproveProject(projects, notifier)


def get_update_project(projects: ProjectRepoDep, users: UserRepoDep) -> UpdateProject:
    return UpdateProject(projects, users)


def get_change_project_stage(
    projects: ProjectRepoDep, media: MediaRepoDep, notifier: NotifierDep
) -> ChangeProjectStage:
    return ChangeProjectStage(projects, media, notifier)


def get_count_users(users: UserRepoDep) -> CountUsers:
    return CountUsers(users)


def get_get_user(users: UserRepoDep) -> GetUser:
    return GetUser(users)


# --- Auth ---
async def get_current_user(
    users: UserRepoDep,
    session_token: Annotated[str | None, Depends(cookie_scheme)] = None,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> User:
    # Cookie first: a browser that has both should be treated as the browser
    # session, so signing out actually signs the tab out.
    token = session_token or (credentials.credentials if credentials else None)
    if token is None:
        raise AuthenticationError("Not authenticated")
    payload = decode_access_token(token)
    # A token can be validly signed and still identify nobody: a claim set from
    # a different token type signed with the same key, or a stale cookie from an
    # older format. Both mean "not authenticated", not "the server broke" —
    # unguarded this raised KeyError/ValueError and surfaced as a 500.
    # `UUID(None)` raises TypeError, so a missing claim lands here too.
    try:
        user_id = UUID(payload.get("sub"))
    except (TypeError, ValueError) as exc:
        raise AuthenticationError("Invalid token subject") from exc

    user = await users.get_by_id(user_id)
    if user is None or not user.can_authenticate:
        raise AuthenticationError("User not found or suspended")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    users: UserRepoDep,
    session_token: Annotated[str | None, Depends(cookie_scheme)] = None,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ] = None,
) -> User | None:
    """Who is asking, where anybody may ask.

    For endpoints the public reaches that behave better when they recognise
    the caller — the enquiry form being the case this was written for. A
    signed-in client booking a second shoot should arrive attached to their
    account rather than as a stranger who happens to share an email address.

    **Never raises.** A missing, expired or malformed token is an anonymous
    caller here, not an error: the endpoint works without one, so refusing a
    bad cookie would break the public form for somebody whose session merely
    lapsed in another tab. Anything that depends on *being* somebody still
    goes through `get_current_user`.
    """
    token = session_token or (credentials.credentials if credentials else None)
    if token is None:
        return None
    try:
        payload = decode_access_token(token)
        user = await users.get_by_id(UUID(payload.get("sub")))
    except Exception:  # noqa: BLE001 — see docstring
        return None
    return user if user is not None and user.can_authenticate else None


OptionalUserDep = Annotated[User | None, Depends(get_optional_user)]


async def get_current_active_user(user: CurrentUserDep) -> User:
    """A signed-in user whose account has actually been accepted.

    `CurrentUserDep` deliberately admits PENDING accounts — they need a session
    to load the "awaiting acceptance" screen. This is what stops them *doing*
    anything, and it is the real gate: the frontend block is a div, and a div
    does not survive curl.
    """
    if user.status is not UserStatus.ACTIVE:
        raise PermissionDeniedError("Your account is awaiting acceptance.")
    return user


CurrentActiveUserDep = Annotated[User, Depends(get_current_active_user)]


async def get_current_admin(user: CurrentUserDep) -> User:
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedError("Admin access required")
    return user


CurrentAdminDep = Annotated[User, Depends(get_current_admin)]


async def get_current_staff(user: CurrentActiveUserDep) -> User:
    """An administrator, or a creator acting on their own work.

    Billing is the first place where "not a customer" is the right gate rather
    than "is an admin": creators raise invoices against their own projects. The
    row-level check still happens in the use case — this only keeps customers
    out of the staff endpoints entirely.
    """
    if user.role not in (UserRole.ADMIN, UserRole.CREATOR):
        raise PermissionDeniedError("Staff access required")
    return user


CurrentStaffDep = Annotated[User, Depends(get_current_staff)]


async def get_current_team(user: CurrentActiveUserDep) -> User:
    """Cabmora's own people — an administrator or a coordinator.

    Distinct from `CurrentStaffDep`, which is "admin or creator" and exists
    for billing, where a partner raises invoices against their own work. This
    one is the opposite cut: the people inside the business, whether or not
    they are trusted with everyone's data.

    The gate only keeps customers and partners out of the back office. What a
    coordinator may then *see* is decided per project by
    `Project.is_managed_by`, and per list by querying their memberships —
    because a gate that admits somebody to an endpoint has said nothing about
    which rows they may read.
    """
    if user.role not in (UserRole.ADMIN, UserRole.COORDINATOR):
        raise PermissionDeniedError("Cabmora team access required")
    return user


CurrentTeamDep = Annotated[User, Depends(get_current_team)]


def requires(permission: Permission, *, also: tuple[UserRole, ...] = ()):
    """Admit whoever may use one section of the console.

    This is what actually refuses a request. The console's `canOpen` only
    decides what to draw, and the two agree because the console reads the
    same grants this does rather than inferring them from a role.

    `also` keeps the roles an endpoint already admitted for other reasons —
    billing lets a creator at their own invoices, and that is a different
    question from whether a coordinator has been granted Payments. Row-level
    checks inside the use cases are unchanged: a gate that admits somebody to
    an endpoint has said nothing about which rows they may read.
    """

    async def guard(user: CurrentActiveUserDep) -> User:
        if user.role in also or user.can(permission):
            return user
        raise PermissionDeniedError("You do not have access to this section.")

    return guard


#: The four an administrator may hand out. The others stay on
#: `CurrentAdminDep` on purpose — see `GRANTABLE` for why each one would be an
#: escalation rather than a convenience.
PaymentsDep = Annotated[
    User, Depends(requires(Permission.PAYMENTS, also=(UserRole.CREATOR,)))
]
ReviewsDep = Annotated[User, Depends(requires(Permission.REVIEWS))]
CreatorApplicationsDep = Annotated[
    User, Depends(requires(Permission.CREATOR_APPLICATIONS))
]
ReportsDep = Annotated[User, Depends(requires(Permission.REPORTS))]


# ── billing ──────────────────────────────────────────────────
def get_invoice_repository(session: SessionDep) -> InvoiceRepository:
    return SqlAlchemyInvoiceRepository(session)


InvoiceRepoDep = Annotated[InvoiceRepository, Depends(get_invoice_repository)]


def get_unmatched_funds_repository(session: SessionDep) -> UnmatchedFundsRepository:
    return SqlAlchemyUnmatchedFundsRepository(session)


UnmatchedFundsRepoDep = Annotated[
    UnmatchedFundsRepository, Depends(get_unmatched_funds_repository)
]


# Below the repository aliases on purpose. Python 3.12 — the Dockerfile's —
# evaluates an annotation when the `def` runs, so a provider placed above the
# alias it names boots fine on 3.14 here and NameErrors on import in the
# container. That cost three and a half hours in September.
def get_summarise_projects(
    media: MediaRepoDep, comments: CommentRepoDep, invoices: InvoiceRepoDep
) -> SummariseProjects:
    return SummariseProjects(media, comments, invoices)


def get_list_project_assets(
    projects: ProjectRepoDep,
    media: MediaRepoDep,
    storage: MediaStorageDep,
    invoices: InvoiceRepoDep,
) -> ListProjectAssets:
    return ListProjectAssets(projects, media, storage, invoices)


def get_list_my_media(
    projects: ProjectRepoDep,
    media: MediaRepoDep,
    storage: MediaStorageDep,
    invoices: InvoiceRepoDep,
) -> ListMyMedia:
    return ListMyMedia(projects, media, storage, invoices)


ListMyMediaDep = Annotated[ListMyMedia, Depends(get_list_my_media)]


def get_download_asset(
    projects: ProjectRepoDep,
    media: MediaRepoDep,
    storage: MediaStorageDep,
    invoices: InvoiceRepoDep,
) -> DownloadAsset:
    return DownloadAsset(projects, media, storage, invoices)


DownloadAssetDep = Annotated[DownloadAsset, Depends(get_download_asset)]


def get_manage_folders(
    folders: FolderRepoDep, media: MediaRepoDep, projects: ProjectRepoDep
) -> ManageFolders:
    return ManageFolders(folders, media, projects)


ManageFoldersDep = Annotated[ManageFolders, Depends(get_manage_folders)]


def get_delete_asset(
    projects: ProjectRepoDep, media: MediaRepoDep, storage: MediaStorageDep
) -> DeleteAsset:
    return DeleteAsset(projects, media, storage)


def get_release_assets(
    projects: ProjectRepoDep,
    media: MediaRepoDep,
    users: UserRepoDep,
    email: EmailSenderDep,
    notifier: NotifierDep,
    invoices: InvoiceRepoDep,
) -> ReleaseAssets:
    return ReleaseAssets(
        projects,
        media,
        users,
        email,
        notifier,
        invoices,
        get_settings().public_base_url,
    )


def get_preview_release(
    projects: ProjectRepoDep, media: MediaRepoDep, invoices: InvoiceRepoDep
) -> PreviewRelease:
    return PreviewRelease(projects, media, invoices)


# ── ratings ──────────────────────────────────────────────────
def get_rating_repository(session: SessionDep) -> RatingRepository:
    return SqlAlchemyRatingRepository(session)


RatingRepoDep = Annotated[RatingRepository, Depends(get_rating_repository)]


def get_rate_project(projects: ProjectRepoDep, ratings: RatingRepoDep) -> RateProject:
    return RateProject(projects, ratings)


def get_grant_permissions(users: UserRepoDep) -> GrantPermissions:
    return GrantPermissions(users)


def get_access_group_repository(session: SessionDep) -> AccessGroupRepository:
    return SqlAlchemyAccessGroupRepository(session)


AccessGroupRepoDep = Annotated[
    AccessGroupRepository, Depends(get_access_group_repository)
]


def get_manage_access_groups(
    groups: AccessGroupRepoDep, users: UserRepoDep
) -> ManageAccessGroups:
    return ManageAccessGroups(groups, users)


def get_moderate_reviews(
    ratings: RatingRepoDep, projects: ProjectRepoDep, users: UserRepoDep
) -> ModerateReviews:
    return ModerateReviews(ratings, projects, users)


def get_list_published_reviews(
    ratings: RatingRepoDep, users: UserRepoDep
) -> ListPublishedReviews:
    return ListPublishedReviews(ratings, users)


# ── sharing ──────────────────────────────────────────────────
def get_gallery_share_repository(session: SessionDep) -> GalleryShareRepository:
    return SqlAlchemyGalleryShareRepository(session)


GalleryShareRepoDep = Annotated[
    GalleryShareRepository, Depends(get_gallery_share_repository)
]


def get_share_preview(
    shares: GalleryShareRepoDep,
    projects: ProjectRepoDep,
    media: MediaRepoDep,
    storage: MediaStorageDep,
    invoices: InvoiceRepoDep,
) -> GetSharePreview:
    return GetSharePreview(shares, projects, media, storage, invoices)


def get_manage_shares(
    projects: ProjectRepoDep,
    shares: GalleryShareRepoDep,
    media: MediaRepoDep,
    invoices: InvoiceRepoDep,
) -> ManageGalleryShares:
    return ManageGalleryShares(projects, shares, media, invoices)


def get_view_shared_gallery(
    shares: GalleryShareRepoDep,
    projects: ProjectRepoDep,
    media: MediaRepoDep,
    storage: MediaStorageDep,
    invoices: InvoiceRepoDep,
) -> ViewSharedGallery:
    return ViewSharedGallery(shares, projects, media, storage, invoices)


def get_list_asset_versions(
    projects: ProjectRepoDep,
    media: MediaRepoDep,
    storage: MediaStorageDep,
    invoices: InvoiceRepoDep,
) -> ListAssetVersions:
    return ListAssetVersions(projects, media, storage, invoices)


# Media delivery now asks billing whether the job is paid for, so these four
# live below `InvoiceRepoDep` with the rest. Same 3.12 annotation rule as
# above: the alias has to exist by the time the `def` runs.


def get_payment_gateway() -> PaymentGateway:
    """Stripe when it is configured, the fake one only in local development.

    Keys decide this rather than the environment name, so staging can take
    real test-mode payments by being given keys, and local stays on the fake
    gateway by being given none.

    The fake gateway takes no money, so it must never be reachable outside
    local. An invoice marked paid by a gateway that moved nothing is worse than
    having no payments at all.
    """
    settings = get_settings()
    if settings.stripe_is_configured:
        return StripePaymentGateway(
            secret_key=settings.stripe_secret_key or "",
            webhook_secret=settings.stripe_webhook_secret or "",
        )
    if settings.environment != "local":
        raise RuntimeError(
            "No payment gateway is configured. Refusing to serve card payments "
            "with the fake gateway outside local."
        )
    return FakePaymentGateway()


PaymentGatewayDep = Annotated[PaymentGateway, Depends(get_payment_gateway)]


def get_create_invoice(
    invoices: InvoiceRepoDep, projects: ProjectRepoDep, users: UserRepoDep
) -> CreateInvoice:
    return CreateInvoice(invoices, projects, users)


def get_invoice_renderer() -> InvoiceRenderer:
    return ReportLabInvoiceRenderer()


def get_issuer_identity() -> IssuerIdentity:
    """Who invoices are from. Read from settings so a company number or VAT
    number appears only once it genuinely exists."""
    settings = get_settings()
    return IssuerIdentity(
        name=settings.company_name,
        address=settings.company_address,
        email=settings.support_email,
        phone=settings.company_phone,
        company_number=settings.company_number,
        vat_number=settings.vat_number,
    )


def get_issue_invoice(
    invoices: InvoiceRepoDep,
    projects: ProjectRepoDep,
    users: UserRepoDep,
    email: EmailSenderDep,
    notifier: NotifierDep,
) -> IssueInvoice:
    return IssueInvoice(
        invoices,
        projects,
        users,
        email,
        notifier,
        get_settings().public_base_url,
        get_invoice_renderer(),
        get_issuer_identity(),
        get_bank_details(),
    )


def get_void_invoice(invoices: InvoiceRepoDep, projects: ProjectRepoDep) -> VoidInvoice:
    return VoidInvoice(invoices, projects)


def get_list_invoices(invoices: InvoiceRepoDep) -> ListInvoices:
    return ListInvoices(invoices)


def get_bank_details() -> BankTransferDetails | None:
    """The account a transfer should go to, or None until it is configured.

    Deliberately returns None rather than a placeholder: every caller already
    handles its absence by saying "get in touch", and an invented sort code on
    an invoice is money sent nowhere.
    """
    return BankTransferDetails.configured(get_settings())


def get_render_invoice(
    invoices: InvoiceRepoDep, projects: ProjectRepoDep, users: UserRepoDep
) -> RenderInvoice:
    return RenderInvoice(
        GetInvoice(invoices),
        projects,
        users,
        get_invoice_renderer(),
        get_issuer_identity(),
        get_bank_details(),
    )


def get_get_invoice(invoices: InvoiceRepoDep) -> GetInvoice:
    return GetInvoice(invoices)


def get_list_payments(
    invoices: InvoiceRepoDep, projects: ProjectRepoDep, users: UserRepoDep
) -> ListPayments:
    return ListPayments(invoices, projects, users)


def get_record_payment(
    invoices: InvoiceRepoDep, projects: ProjectRepoDep, notifier: NotifierDep
) -> RecordPayment:
    return RecordPayment(invoices, projects, notifier)


def get_confirm_payment(invoices: InvoiceRepoDep) -> ConfirmPayment:
    return ConfirmPayment(invoices)


def get_refund_payment(invoices: InvoiceRepoDep, projects: ProjectRepoDep) -> RefundPayment:
    return RefundPayment(invoices, projects)


def get_confirm_refund(invoices: InvoiceRepoDep) -> ConfirmRefund:
    return ConfirmRefund(invoices)


def get_start_checkout(
    invoices: InvoiceRepoDep, gateway: PaymentGatewayDep
) -> StartCheckout:
    return StartCheckout(invoices, gateway, get_settings().public_base_url)


def get_start_bank_transfer(
    invoices: InvoiceRepoDep, users: UserRepoDep, gateway: PaymentGatewayDep
) -> StartBankTransfer:
    return StartBankTransfer(invoices, users, gateway)


def get_handle_gateway_event(
    invoices: InvoiceRepoDep,
    gateway: PaymentGatewayDep,
    funds: UnmatchedFundsRepoDep,
    users: UserRepoDep,
    notifier: NotifierDep,
) -> HandleGatewayEvent:
    return HandleGatewayEvent(invoices, gateway, funds, users, notifier)


def get_list_unmatched_funds(
    funds: UnmatchedFundsRepoDep, users: UserRepoDep
) -> ListUnmatchedFunds:
    return ListUnmatchedFunds(funds, users)


def get_mark_funds_handled(funds: UnmatchedFundsRepoDep) -> MarkFundsHandled:
    return MarkFundsHandled(funds)


CreateInvoiceDep = Annotated[CreateInvoice, Depends(get_create_invoice)]
IssueInvoiceDep = Annotated[IssueInvoice, Depends(get_issue_invoice)]
VoidInvoiceDep = Annotated[VoidInvoice, Depends(get_void_invoice)]
ListInvoicesDep = Annotated[ListInvoices, Depends(get_list_invoices)]
GetInvoiceDep = Annotated[GetInvoice, Depends(get_get_invoice)]
RenderInvoiceDep = Annotated[RenderInvoice, Depends(get_render_invoice)]
ListPaymentsDep = Annotated[ListPayments, Depends(get_list_payments)]
RecordPaymentDep = Annotated[RecordPayment, Depends(get_record_payment)]
ConfirmPaymentDep = Annotated[ConfirmPayment, Depends(get_confirm_payment)]
RefundPaymentDep = Annotated[RefundPayment, Depends(get_refund_payment)]
ConfirmRefundDep = Annotated[ConfirmRefund, Depends(get_confirm_refund)]
StartCheckoutDep = Annotated[StartCheckout, Depends(get_start_checkout)]
StartBankTransferDep = Annotated[
    StartBankTransfer, Depends(get_start_bank_transfer)
]
ListUnmatchedFundsDep = Annotated[
    ListUnmatchedFunds, Depends(get_list_unmatched_funds)
]
MarkFundsHandledDep = Annotated[
    MarkFundsHandled, Depends(get_mark_funds_handled)
]
HandleGatewayEventDep = Annotated[HandleGatewayEvent, Depends(get_handle_gateway_event)]


def get_count_dashboard(
    users: UserRepoDep, projects: ProjectRepoDep, enquiries: EnquiryRepoDep
) -> CountDashboard:
    return CountDashboard(users, projects, enquiries)


def get_monthly_report(users: UserRepoDep, invoices: InvoiceRepoDep) -> MonthlyReport:
    return MonthlyReport(users, invoices)


CountDashboardDep = Annotated[CountDashboard, Depends(get_count_dashboard)]
MonthlyReportDep = Annotated[MonthlyReport, Depends(get_monthly_report)]


def get_creator_performance(
    users: UserRepoDep, projects: ProjectRepoDep, invoices: InvoiceRepoDep
) -> CreatorPerformanceReport:
    return CreatorPerformanceReport(users, projects, invoices)


CreatorPerformanceDep = Annotated[
    CreatorPerformanceReport, Depends(get_creator_performance)
]


def get_list_availability(enquiries: EnquiryRepoDep) -> ListAvailability:
    return ListAvailability(enquiries)


ListAvailabilityDep = Annotated[ListAvailability, Depends(get_list_availability)]


# ── creator studios & landing pages ──────────────────────────
def get_creator_studio_repository(session: SessionDep) -> CreatorStudioRepository:
    return SqlAlchemyCreatorStudioRepository(session)


CreatorStudioRepoDep = Annotated[
    CreatorStudioRepository, Depends(get_creator_studio_repository)
]


def get_get_my_creator_studio(studios: CreatorStudioRepoDep) -> GetMyCreatorStudio:
    return GetMyCreatorStudio(studios)


def get_update_my_creator_studio(
    studios: CreatorStudioRepoDep,
) -> UpdateMyCreatorStudio:
    return UpdateMyCreatorStudio(studios)


def get_get_public_creator_studio(
    studios: CreatorStudioRepoDep, users: UserRepoDep
) -> GetPublicCreatorStudio:
    return GetPublicCreatorStudio(studios, users)


def get_submit_creator_booking(
    studios: CreatorStudioRepoDep,
) -> SubmitCreatorBooking:
    return SubmitCreatorBooking(studios)


def get_list_creator_bookings(
    studios: CreatorStudioRepoDep,
) -> ListCreatorBookings:
    return ListCreatorBookings(studios)


def get_update_creator_booking_status(
    studios: CreatorStudioRepoDep,
) -> UpdateCreatorBookingStatus:
    return UpdateCreatorBookingStatus(studios)


# ── collaboration: tasks, calls, briefing ────────────────────
def get_collaboration_repository(session: SessionDep) -> CollaborationRepository:
    return SqlAlchemyCollaborationRepository(session)


CollaborationRepoDep = Annotated[
    CollaborationRepository, Depends(get_collaboration_repository)
]


def get_list_project_tasks(
    projects: ProjectRepoDep, collab: CollaborationRepoDep
) -> ListProjectTasks:
    return ListProjectTasks(projects, collab)


def get_create_project_task(
    projects: ProjectRepoDep, collab: CollaborationRepoDep
) -> CreateProjectTask:
    return CreateProjectTask(projects, collab)


def get_update_project_task(
    projects: ProjectRepoDep, collab: CollaborationRepoDep
) -> UpdateProjectTask:
    return UpdateProjectTask(projects, collab)


def get_delete_project_task(
    projects: ProjectRepoDep, collab: CollaborationRepoDep
) -> DeleteProjectTask:
    return DeleteProjectTask(projects, collab)


def get_request_project_call(
    projects: ProjectRepoDep,
    collab: CollaborationRepoDep,
    users: UserRepoDep,
    notifier: NotifierDep,
) -> RequestProjectCall:
    return RequestProjectCall(projects, collab, users, notifier)


def get_respond_to_project_call(
    projects: ProjectRepoDep,
    collab: CollaborationRepoDep,
    users: UserRepoDep,
    notifier: NotifierDep,
) -> RespondToProjectCall:
    return RespondToProjectCall(projects, collab, users, notifier)


def get_list_project_calls(
    projects: ProjectRepoDep, collab: CollaborationRepoDep, users: UserRepoDep
) -> ListProjectCalls:
    return ListProjectCalls(projects, collab, users)


def get_list_my_calls(
    projects: ProjectRepoDep,
    collab: CollaborationRepoDep,
    users: UserRepoDep,
    notifier: NotifierDep,
) -> ListMyCalls:
    return ListMyCalls(projects, collab, users, notifier)


def get_creator_briefing(
    projects: ProjectRepoDep, comments: CommentRepoDep, collab: CollaborationRepoDep
) -> GetCreatorBriefing:
    return GetCreatorBriefing(projects, comments, collab)

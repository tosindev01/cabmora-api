from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domain.entities.collaboration import CallStatus, TaskPriority, TaskStatus


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=2000)
    priority: TaskPriority = TaskPriority.MEDIUM
    due_at: datetime | None = None
    assignee_id: UUID | None = None


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    description: str | None = Field(default=None, max_length=2000)
    status: TaskStatus | None = None
    priority: TaskPriority | None = None
    due_at: datetime | None = None


class TaskResponse(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    due_at: datetime | None
    assignee_id: UUID | None
    created_by: UUID
    created_at: datetime


class CallCreateRequest(BaseModel):
    title: str = Field(default="Project Video Sync", min_length=1, max_length=200)
    proposed_at: datetime
    duration_minutes: int = Field(default=30, ge=10, le=180)
    notes: str = Field(default="", max_length=2000)


class CallRespondRequest(BaseModel):
    action: Literal["accept", "decline", "cancel", "complete", "reschedule"]
    proposed_at: datetime | None = None


class CallResponse(BaseModel):
    id: UUID
    project_id: UUID
    project_title: str
    requester_id: UUID
    requester_name: str
    recipient_id: UUID
    recipient_name: str
    title: str
    notes: str
    proposed_at: datetime
    duration_minutes: int
    status: CallStatus
    meeting_room_id: str | None
    meeting_url: str | None
    responded_at: datetime | None
    created_at: datetime


class BriefingActionItemResponse(BaseModel):
    kind: str
    title: str
    subtitle: str
    project_id: UUID | str
    project_title: str
    url: str
    priority: str


class NewClientNotificationDto(BaseModel):
    id: str
    client_name: str
    client_email: str
    avatar: str
    project_title: str
    project_type: str
    location: str
    shoot_date: str
    package_amount: int
    status: str
    received_at: str
    notes: str


class WeatherDaySlotDto(BaseModel):
    label: str
    temp_c: int
    condition: str
    wind_kmh: int
    precip_chance: int


class NextProjectWeatherDto(BaseModel):
    project_id: str
    project_title: str
    client_name: str
    location: str
    shoot_date: str
    days_until_shoot: int
    temp_c: int
    temp_f: int
    condition: str
    humidity: int
    wind_kmh: int
    wind_direction: str
    drone_status: str
    uv_index: str
    golden_hour: str
    blue_hour: str
    ai_lighting_note: str
    location_image: str
    hourly_slots: list[WeatherDaySlotDto] = Field(default_factory=list)


class PendingClientMessageDto(BaseModel):
    id: str
    client_name: str
    client_email: str
    client_avatar: str
    project_id: str
    project_title: str
    preview: str
    received_at: str
    unread: bool
    category: str
    suggested_invoice_amount: int | None = None


class AiInvoiceLineItemDto(BaseModel):
    id: str
    description: str
    quantity: int
    unit_price: int


class AiGeneratedInvoiceDto(BaseModel):
    id: str
    client: str
    client_email: str
    project: str
    issued: str
    due: str
    amount: int
    subtotal: int
    tax_rate: int = 0
    tax_amount: int = 0
    status: Literal["Paid", "Outstanding", "Overdue"] = "Outstanding"
    notes: str
    generated_by_ai: bool = True
    line_items: list[AiInvoiceLineItemDto] = Field(default_factory=list)


class AiGenerateInvoiceRequest(BaseModel):
    client_name: str = Field(default="Clara & Julian Mercer", max_length=200)
    client_email: str = Field(default="clara.mercer@ateliermercer.com", max_length=200)
    project_title: str = Field(default="Lake Como Destination Wedding", max_length=240)
    amount: int = Field(default=6250, ge=50)
    include_drone: bool = True
    include_rehearsal: bool = False
    custom_description: str | None = None


class AiVisualAttachmentDto(BaseModel):
    url: str
    caption: str
    tag: str


class CreatorReferralEntryDto(BaseModel):
    id: str
    referred_name: str
    referred_email: str
    role: Literal["creator", "client"]
    status: Literal["Invited", "Joined Studio", "First Project Booked", "Reward Paid"]
    date: str
    reward_amount: int
    bonus_storage_gb: int


class CreatorReferralSummaryDto(BaseModel):
    referral_code: str
    referral_link: str
    tier: str
    next_tier: str
    tier_progress_percent: int
    total_earnings: int
    pending_payouts: int
    bonus_storage_gb: int
    conversion_rate: int
    referrals: list[CreatorReferralEntryDto] = Field(default_factory=list)


class CreatorReferralInviteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=200)
    role: Literal["creator", "client"] = "creator"
    personal_note: str = Field(default="", max_length=1000)


class ScreenSecurityViolationRequest(BaseModel):
    event_type: Literal["screenshot_shortcut", "focus_loss", "qr_camera_trap", "context_menu", "camera_detected"]
    route: str = Field(default="/client/dashboard", max_length=240)
    details: str = Field(default="", max_length=500)
    session_token: str = Field(default="default-client-session", max_length=120)


class ScreenSecurityStatusResponse(BaseModel):
    session_token: str
    locked: bool
    violation_count: int
    reason: str | None = None
    triggered_at: str | None = None


class ClientBriefingResponse(BaseModel):
    headline: str
    summary_text: str
    active_projects_count: int
    photos_ready_count: int
    pending_approvals_count: int
    upcoming_calls_count: int
    next_project_title: str
    next_project_venue: str
    venue_distance_km: float
    venue_travel_time: str
    deadline_iso: str
    deadline_warning: str
    action_items: list[BriefingActionItemResponse] = Field(default_factory=list)


class CommunityCommentDto(BaseModel):
    id: str
    author_name: str
    author_role: Literal["creator", "client"]
    author_avatar: str
    text: str
    created_at: str


class CommunityPostDto(BaseModel):
    id: str
    project_id: str
    project_title: str
    project_type: str
    client_name: str
    location: str
    venue_distance_km: float
    completed_date: str
    deliverables_summary: str
    creator_id: str
    creator_name: str
    creator_handle: str
    creator_specialization: str
    creator_avatar: str
    caption: str
    media_urls: list[str] = Field(default_factory=list)
    likes_count: int
    liked_by_me: bool
    comments: list[CommunityCommentDto] = Field(default_factory=list)
    created_at: str


class CommunityShareCompletedJobRequest(BaseModel):
    project_id: str
    project_title: str
    project_type: str = "Wedding"
    client_name: str = "Studio Client"
    location: str = "Tuscany, Italy"
    deliverables_summary: str = "Full Gallery + 4K Highlight Film"
    caption: str = Field(min_length=1, max_length=2000)
    media_urls: list[str] = Field(default_factory=list)


class CommunityCommentRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    author_role: Literal["creator", "client"] = "creator"


class CommunityFollowerDto(BaseModel):
    id: str
    name: str
    handle: str
    role: Literal["creator", "client"]
    specialization: str
    avatar: str
    followed_at: str
    auto_followed_via_like: bool = True


class CommunityCollaborationRequestDto(BaseModel):
    id: str
    post_id: str
    project_title: str
    requester_name: str
    requester_role: Literal["creator", "client"]
    requester_avatar: str
    target_creator_id: str
    target_creator_name: str
    proposed_role: str
    proposed_date: str
    budget_or_split: str
    message: str
    status: Literal["pending", "accepted", "declined"]
    direction: Literal["incoming", "outgoing"] = "incoming"
    created_at: str


class CommunityCollaborationCreateRequest(BaseModel):
    post_id: str
    project_title: str
    target_creator_id: str
    target_creator_name: str
    proposed_role: str = Field(default="Second Photographer / Drone Operator", max_length=200)
    proposed_date: str = Field(default="Nov 18, 2025", max_length=100)
    budget_or_split: str = Field(default="$1,800 Day Rate / 30% Split", max_length=120)
    message: str = Field(default="Loved your completed project! Would love to collaborate on an upcoming shoot.", max_length=1000)
    requester_role: Literal["creator", "client"] = "creator"


class CommunityCollaborationRespondRequest(BaseModel):
    action: Literal["accept", "decline"]


class CommunityFeedResponse(BaseModel):
    posts: list[CommunityPostDto]
    followers: list[CommunityFollowerDto]
    followers_count: int
    collaborations: list[CommunityCollaborationRequestDto]
    auto_followed_creator_ids: list[str] = Field(default_factory=list)


class CreatorBriefingResponse(BaseModel):
    headline: str
    summary_text: str
    projects_in_progress: int
    pending_tasks_count: int
    revision_requests_count: int
    unread_comments_count: int
    upcoming_deadlines_count: int
    pending_calls_count: int
    action_items: list[BriefingActionItemResponse]
    new_clients: list[NewClientNotificationDto] = Field(default_factory=list)
    next_project_weather: NextProjectWeatherDto | None = None
    pending_messages: list[PendingClientMessageDto] = Field(default_factory=list)
    referrals_summary: CreatorReferralSummaryDto | None = None


class BriefingChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    images: list[str] = Field(default_factory=list)


class BriefingChatResponse(BaseModel):
    reply: str
    suggested_links: list[BriefingActionItemResponse] = Field(default_factory=list)
    generated_invoice: AiGeneratedInvoiceDto | None = None
    weather_forecast: NextProjectWeatherDto | None = None
    images: list[AiVisualAttachmentDto] = Field(default_factory=list)
    new_clients: list[NewClientNotificationDto] = Field(default_factory=list)
    pending_messages: list[PendingClientMessageDto] = Field(default_factory=list)

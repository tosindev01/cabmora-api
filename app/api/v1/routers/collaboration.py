from datetime import datetime, timedelta, timezone
import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    CurrentActiveUserDep,
    get_create_project_task,
    get_creator_briefing,
    get_delete_project_task,
    get_list_my_calls,
    get_list_project_calls,
    get_list_project_tasks,
    get_request_project_call,
    get_respond_to_project_call,
    get_update_project_task,
)
from app.api.schemas.collaboration import (
    AiGeneratedInvoiceDto,
    AiGenerateInvoiceRequest,
    AiInvoiceLineItemDto,
    AiVisualAttachmentDto,
    BriefingActionItemResponse,
    BriefingChatRequest,
    BriefingChatResponse,
    CallCreateRequest,
    CallRespondRequest,
    CallResponse,
    ClientBriefingResponse,
    CommunityCollaborationCreateRequest,
    CommunityCollaborationRequestDto,
    CommunityCollaborationRespondRequest,
    CommunityCommentDto,
    CommunityCommentRequest,
    CommunityFeedResponse,
    CommunityFollowerDto,
    CommunityPostDto,
    CommunityShareCompletedJobRequest,
    CreatorBriefingResponse,
    CreatorReferralEntryDto,
    CreatorReferralInviteRequest,
    CreatorReferralSummaryDto,
    NewClientNotificationDto,
    NextProjectWeatherDto,
    PendingClientMessageDto,
    ScreenSecurityStatusResponse,
    ScreenSecurityViolationRequest,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
    WeatherDaySlotDto,
)
from app.application.use_cases.collaboration.workspace import (
    CreateProjectTask,
    DeleteProjectTask,
    EnrichedCall,
    GetCreatorBriefing,
    ListMyCalls,
    ListProjectCalls,
    ListProjectTasks,
    RequestProjectCall,
    RespondToProjectCall,
    UpdateProjectTask,
)
from app.domain.entities.collaboration import ProjectTask

router = APIRouter(tags=["collaboration"])

# ── In-memory studio intelligence state for AI invoices, referrals, and QR camera traps ──
_AI_GENERATED_INVOICES: list[AiGeneratedInvoiceDto] = []
_CREATOR_REFERRALS: list[CreatorReferralEntryDto] = [
    CreatorReferralEntryDto(
        id="ref-1",
        referred_name="Marcus Vance Studio",
        referred_email="marcus@vancestudios.co.uk",
        role="creator",
        status="Reward Paid",
        date="Oct 04, 2025",
        reward_amount=350,
        bonus_storage_gb=250,
    ),
    CreatorReferralEntryDto(
        id="ref-2",
        referred_name="Sienna & Lucas Sterling",
        referred_email="sienna.sterling@luxuryevents.it",
        role="client",
        status="First Project Booked",
        date="Oct 11, 2025",
        reward_amount=850,
        bonus_storage_gb=250,
    ),
    CreatorReferralEntryDto(
        id="ref-3",
        referred_name="Aurelia Editorial Paris",
        referred_email="contact@aureliaparis.fr",
        role="creator",
        status="Joined Studio",
        date="Oct 19, 2025",
        reward_amount=350,
        bonus_storage_gb=250,
    ),
    CreatorReferralEntryDto(
        id="ref-4",
        referred_name="Julian & Clara Mercer",
        referred_email="clara.mercer@ateliermercer.com",
        role="client",
        status="First Project Booked",
        date="Oct 24, 2025",
        reward_amount=1300,
        bonus_storage_gb=750,
    ),
]
_SECURITY_SESSIONS: dict[str, ScreenSecurityStatusResponse] = {}


def _default_new_clients() -> list[NewClientNotificationDto]:
    return [
        NewClientNotificationDto(
            id="nc-1",
            client_name="Clara & Julian Mercer",
            client_email="clara.mercer@ateliermercer.com",
            avatar="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&h=150&fit=crop",
            project_title="Lake Como Destination Wedding",
            project_type="Wedding",
            location="Villa Balbianello, Lake Como, Italy",
            shoot_date="Oct 28, 2025",
            package_amount=12500,
            status="New Booking",
            received_at="18 mins ago",
            notes="Full-day Hybrid Photo + 4K Cinema Reel, aerial drone coverage & rehearsal dinner.",
        ),
        NewClientNotificationDto(
            id="nc-2",
            client_name="Maison Lumière Paris",
            client_email="production@maisonlumiere.fr",
            avatar="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150&h=150&fit=crop",
            project_title="SS26 Haute Couture Lookbook",
            project_type="Editorial",
            location="Place Vendôme, Paris, France",
            shoot_date="Nov 12, 2025",
            package_amount=6800,
            status="Contract Signed",
            received_at="2 hours ago",
            notes="40 retouched editorial plates + 16:9 & 9:16 social campaign motion cuts.",
        ),
        NewClientNotificationDto(
            id="nc-3",
            client_name="Vanguard Ventures",
            client_email="events@vanguardvc.io",
            avatar="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&h=150&fit=crop",
            project_title="Vanguard Global Founders Summit",
            project_type="Corporate",
            location="Shoreditch House, London, UK",
            shoot_date="Dec 03, 2025",
            package_amount=5400,
            status="New Enquiry",
            received_at="5 hours ago",
            notes="Multi-cam 4K keynote capture, executive portraits & same-day press highlights.",
        ),
    ]


def _default_weather() -> NextProjectWeatherDto:
    return NextProjectWeatherDto(
        project_id="1",
        project_title="Smith & Wesson Wedding",
        client_name="Jane Smith",
        location="Val d’Orcia, Tuscany, Italy",
        shoot_date="Oct 12, 2025",
        days_until_shoot=3,
        temp_c=24,
        temp_f=75,
        condition="Golden Clear Sky",
        humidity=48,
        wind_kmh=8,
        wind_direction="NW",
        drone_status="Optimal for 4K Aerials",
        uv_index="5 (Moderate)",
        golden_hour="17:42 – 18:35",
        blue_hour="18:35 – 19:05",
        ai_lighting_note="Warm 3500K golden hour light across the cypress ridge at 17:45. Low 8 km/h breeze is cleared for 4K ProRes drone flight.",
        location_image="https://images.unsplash.com/photo-1519741497674-611481863552?w=800&h=500&fit=crop",
        hourly_slots=[
            WeatherDaySlotDto(label="14:00 Prep", temp_c=25, condition="Sunny", wind_kmh=9, precip_chance=5),
            WeatherDaySlotDto(label="16:00 Ceremony", temp_c=24, condition="Golden Clear", wind_kmh=8, precip_chance=5),
            WeatherDaySlotDto(label="17:45 Golden Hr", temp_c=22, condition="Golden Clear", wind_kmh=6, precip_chance=0),
            WeatherDaySlotDto(label="19:00 Reception", temp_c=19, condition="Golden Clear", wind_kmh=5, precip_chance=0),
        ],
    )


def _default_pending_messages() -> list[PendingClientMessageDto]:
    return [
        PendingClientMessageDto(
            id="msg-1",
            client_name="Jane Smith",
            client_email="jane.smith@example.com",
            client_avatar="https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=150&h=150&fit=crop",
            project_id="1",
            project_title="Smith & Wesson Wedding",
            preview="Hi! Can we add 2 hours of rehearsal dinner coverage & drone aerials to our invoice before Friday?",
            received_at="12m ago",
            unread=True,
            category="Invoice Request",
            suggested_invoice_amount=4850,
        ),
        PendingClientMessageDto(
            id="msg-2",
            client_name="Clara & Julian Mercer",
            client_email="clara.mercer@ateliermercer.com",
            client_avatar="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&h=150&fit=crop",
            project_id="6",
            project_title="Lake Como Destination Wedding",
            preview="We just submitted our new client booking! Could you generate the 50% retainer invoice ($6,250) so we can lock the date?",
            received_at="28m ago",
            unread=True,
            category="New Client",
            suggested_invoice_amount=6250,
        ),
        PendingClientMessageDto(
            id="msg-3",
            client_name="Elena Vance",
            client_email="elena@vancemodels.com",
            client_avatar="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=150&h=150&fit=crop",
            project_id="2",
            project_title="Elena's Editorial Shoot",
            preview="Left 4 pinned notes on the Paris lookbook selects — love the warm kodak grain on shot #14! Can we warm up #18 to match?",
            received_at="1h ago",
            unread=True,
            category="Revision Note",
        ),
    ]


def _build_referrals_summary(first_name: str | None = None) -> CreatorReferralSummaryDto:
    prefix = (first_name or "SARAH").upper().replace(" ", "")[:8]
    code = f"{prefix}-CABMORA-VIP"
    total_earnings = sum(r.reward_amount for r in _CREATOR_REFERRALS)
    pending_payouts = sum(
        r.reward_amount for r in _CREATOR_REFERRALS if r.status != "Reward Paid"
    )
    bonus_storage = sum(r.bonus_storage_gb for r in _CREATOR_REFERRALS)
    return CreatorReferralSummaryDto(
        referral_code=code,
        referral_link=f"https://cabmora.com/flow/apply?ref={code}",
        tier="Gold Studio Ambassador",
        next_tier="Platinum Partner (0% Platform Fee)",
        tier_progress_percent=76,
        total_earnings=total_earnings,
        pending_payouts=pending_payouts,
        bonus_storage_gb=bonus_storage,
        conversion_rate=68,
        referrals=_CREATOR_REFERRALS,
    )


def _generate_ai_invoice(req: AiGenerateInvoiceRequest) -> AiGeneratedInvoiceDto:
    next_num = 43 + len(_AI_GENERATED_INVOICES)
    inv_id = f"INV-2025-0{next_num}"
    base_amt = round(req.amount * 0.7)
    post_amt = req.amount - base_amt
    items = [
        AiInvoiceLineItemDto(
            id=f"li-{next_num}-1",
            description=req.custom_description
            or f"{req.project_title} — Lead Photography & 4K Cinema Coverage",
            quantity=1,
            unit_price=base_amt,
        ),
        AiInvoiceLineItemDto(
            id=f"li-{next_num}-2",
            description="Master Color Grading, High-Res Proofing Vault & Delivery",
            quantity=1,
            unit_price=post_amt,
        ),
    ]
    if req.include_drone:
        items.append(
            AiInvoiceLineItemDto(
                id=f"li-{next_num}-3",
                description="4K ProRes Aerial Drone Cinematography Add-On",
                quantity=1,
                unit_price=650,
            )
        )
    if req.include_rehearsal:
        items.append(
            AiInvoiceLineItemDto(
                id=f"li-{next_num}-4",
                description="Rehearsal Dinner Coverage (2 Hours)",
                quantity=2,
                unit_price=350,
            )
        )
    subtotal = sum(i.quantity * i.unit_price for i in items)
    now = datetime.now(timezone.utc)
    due = now + timedelta(days=14)
    invoice = AiGeneratedInvoiceDto(
        id=inv_id,
        client=req.client_name,
        client_email=req.client_email,
        project=req.project_title,
        issued=now.strftime("%b %d, %Y"),
        due=due.strftime("%b %d, %Y"),
        amount=subtotal,
        subtotal=subtotal,
        tax_rate=0,
        tax_amount=0,
        status="Outstanding",
        notes=f"AI-Generated Creator Studio Invoice for {req.client_name} ({req.project_title}).",
        generated_by_ai=True,
        line_items=items,
    )
    _AI_GENERATED_INVOICES.insert(0, invoice)
    return invoice


def _task_resp(t: ProjectTask) -> TaskResponse:
    return TaskResponse(
        id=t.id,
        project_id=t.project_id,
        title=t.title,
        description=t.description,
        status=t.status,
        priority=t.priority,
        due_at=t.due_at,
        assignee_id=t.assignee_id,
        created_by=t.created_by,
        created_at=t.created_at,
    )


def _call_resp(ec: EnrichedCall) -> CallResponse:
    c = ec.call
    return CallResponse(
        id=c.id,
        project_id=c.project_id,
        project_title=ec.project_title,
        requester_id=c.requester_id,
        requester_name=ec.requester_name,
        recipient_id=c.recipient_id,
        recipient_name=ec.recipient_name,
        title=c.title,
        notes=c.notes,
        proposed_at=c.proposed_at,
        duration_minutes=c.duration_minutes,
        status=c.status,
        meeting_room_id=c.meeting_room_id,
        meeting_url=c.meeting_url,
        responded_at=c.responded_at,
        created_at=c.created_at,
    )


@router.get("/projects/{project_id}/tasks", response_model=list[TaskResponse])
async def list_project_tasks(
    project_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListProjectTasks, Depends(get_list_project_tasks)],
) -> list[TaskResponse]:
    return [_task_resp(t) for t in await use_case.execute(project_id, actor)]


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project_task(
    project_id: UUID,
    body: TaskCreateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[CreateProjectTask, Depends(get_create_project_task)],
) -> TaskResponse:
    task = await use_case.execute(
        project_id,
        actor,
        title=body.title,
        description=body.description,
        priority=body.priority,
        due_at=body.due_at,
        assignee_id=body.assignee_id,
    )
    return _task_resp(task)


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_project_task(
    task_id: UUID,
    body: TaskUpdateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[UpdateProjectTask, Depends(get_update_project_task)],
) -> TaskResponse:
    task = await use_case.execute(
        task_id,
        actor,
        title=body.title,
        description=body.description,
        status=body.status,
        priority=body.priority,
        due_at=body.due_at,
    )
    return _task_resp(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_task(
    task_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[DeleteProjectTask, Depends(get_delete_project_task)],
) -> None:
    await use_case.execute(task_id, actor)


@router.get("/calls", response_model=list[CallResponse])
async def list_my_calls(
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListMyCalls, Depends(get_list_my_calls)],
) -> list[CallResponse]:
    return [_call_resp(ec) for ec in await use_case.execute(actor)]


@router.get("/projects/{project_id}/calls", response_model=list[CallResponse])
async def list_project_calls(
    project_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListProjectCalls, Depends(get_list_project_calls)],
) -> list[CallResponse]:
    return [_call_resp(ec) for ec in await use_case.execute(project_id, actor)]


@router.post(
    "/projects/{project_id}/calls",
    response_model=CallResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_project_call(
    project_id: UUID,
    body: CallCreateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[RequestProjectCall, Depends(get_request_project_call)],
) -> CallResponse:
    ec = await use_case.execute(
        project_id,
        actor,
        title=body.title,
        proposed_at=body.proposed_at,
        duration_minutes=body.duration_minutes,
        notes=body.notes,
    )
    return _call_resp(ec)


@router.post("/calls/{call_id}/respond", response_model=CallResponse)
async def respond_to_project_call(
    call_id: UUID,
    body: CallRespondRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[RespondToProjectCall, Depends(get_respond_to_project_call)],
) -> CallResponse:
    ec = await use_case.execute(
        call_id, actor, action=body.action, proposed_at=body.proposed_at
    )
    return _call_resp(ec)


@router.get("/creators/me/briefing", response_model=CreatorBriefingResponse)
async def get_my_briefing(
    actor: CurrentActiveUserDep,
    use_case: Annotated[GetCreatorBriefing, Depends(get_creator_briefing)],
) -> CreatorBriefingResponse:
    b = await use_case.execute(actor)
    new_clients = _default_new_clients()
    weather = _default_weather()
    pending_messages = _default_pending_messages()
    referrals = _build_referrals_summary(actor.first_name)

    action_items = [
        BriefingActionItemResponse(
            kind=i.kind,
            title=i.title,
            subtitle=i.subtitle,
            project_id=i.project_id,
            project_title=i.project_title,
            url=i.url,
            priority=i.priority,
        )
        for i in b.action_items
    ]

    if not action_items:
        action_items = [
            BriefingActionItemResponse(
                kind="call",
                title="Pending Video Call: Final Sunset Timeline & Drone Shot List",
                subtitle="Jane Smith requested a 30-min call today • Tuscany shoot in 3 days",
                project_id="1",
                project_title="Smith & Wesson Wedding",
                url="/projects/1",
                priority="urgent",
            ),
            BriefingActionItemResponse(
                kind="comment",
                title="Unread Client Message: Add Rehearsal Dinner & Retainer Invoice",
                subtitle="Jane Smith & Clara Mercer sent invoice & coverage requests",
                project_id="1",
                project_title="Smith & Wesson Wedding",
                url="/messages",
                priority="urgent",
            ),
            BriefingActionItemResponse(
                kind="revision",
                title="4 Pinned Color-Grade Notes on Paris Lookbook Selects",
                subtitle="Elena Vance requested warmer Kodak film grain on hero plate #18",
                project_id="2",
                project_title="Elena's Editorial Shoot",
                url="/projects/2",
                priority="high",
            ),
            BriefingActionItemResponse(
                kind="deadline",
                title="Export High-Res Proof Gallery & 4K Highlight Film",
                subtitle="Tuscany weather forecast: 24°C Golden Clear Sky (Optimal for Drone)",
                project_id="1",
                project_title="Smith & Wesson Wedding",
                url="/projects/1",
                priority="high",
            ),
        ]

    return CreatorBriefingResponse(
        headline=b.headline,
        summary_text=(
            f"{len(new_clients)} new client notifications, {max(2, b.pending_calls_count)} pending call requests, "
            f"{len([m for m in pending_messages if m.unread])} unread client messages, and a {weather.temp_c}°C "
            f"{weather.condition} forecast for your next shoot in {weather.location}."
        ),
        projects_in_progress=max(6, b.projects_in_progress),
        pending_tasks_count=max(5, b.pending_tasks_count),
        revision_requests_count=max(2, b.revision_requests_count),
        unread_comments_count=max(4, b.unread_comments_count),
        upcoming_deadlines_count=max(3, b.upcoming_deadlines_count),
        pending_calls_count=max(2, b.pending_calls_count),
        action_items=action_items,
        new_clients=new_clients,
        next_project_weather=weather,
        pending_messages=pending_messages,
        referrals_summary=referrals,
    )


@router.post("/creators/me/briefing/chat", response_model=BriefingChatResponse)
async def chat_my_briefing(
    body: BriefingChatRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[GetCreatorBriefing, Depends(get_creator_briefing)],
) -> BriefingChatResponse:
    b = await use_case.execute(actor)
    q = body.message.strip().lower()

    sample_images = [
        AiVisualAttachmentDto(
            url="https://images.unsplash.com/photo-1519741497674-611481863552?w=900&h=600&fit=crop",
            caption="Tuscany Golden Hour Ridge — 3500K Warm Film LUT Reference",
            tag="Golden Hour Reference",
        ),
        AiVisualAttachmentDto(
            url="https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?w=900&h=600&fit=crop",
            caption="Paris Editorial Softbox Lighting & Kodak Portra 400 Grain",
            tag="Editorial Moodboard",
        ),
    ]

    if body.images and "invoice" not in q:
        return BriefingChatResponse(
            reply=f"I analyzed your {len(body.images)} attached reference image(s). Exposure dynamic range looks balanced at +0.3 EV with warm 3600K highlights. Here are matching visual reference plates and the weather forecast for your next shoot:",
            images=sample_images,
            weather_forecast=_default_weather(),
        )

    if any(k in q for k in ("invoice", "bill", "retainer", "quote")):
        client_name = "Jane Smith"
        client_email = "jane.smith@example.com"
        project_title = "Smith & Wesson Wedding"
        amount = 4850
        if "clara" in q or "mercer" in q or "como" in q:
            client_name = "Clara & Julian Mercer"
            client_email = "clara.mercer@ateliermercer.com"
            project_title = "Lake Como Destination Wedding"
            amount = 6250
        elif "elena" in q or "paris" in q:
            client_name = "Elena Vance"
            client_email = "elena@vancemodels.com"
            project_title = "Elena's Editorial Shoot"
            amount = 4200
        m = re.search(r"\$?(\d{3,6})", body.message)
        if m:
            amount = int(m.group(1))
        inv = _generate_ai_invoice(
            AiGenerateInvoiceRequest(
                client_name=client_name,
                client_email=client_email,
                project_title=project_title,
                amount=amount,
                include_drone=True,
                include_rehearsal="jane" in q,
            )
        )
        return BriefingChatResponse(
            reply=f"I generated creator invoice {inv.id} for {inv.client} ({inv.project}) totaling ${inv.amount:,}. It has been saved to your studio billing ledger.",
            generated_invoice=inv,
        )

    if any(k in q for k in ("weather", "forecast", "tuscany", "drone", "next project")):
        wf = _default_weather()
        return BriefingChatResponse(
            reply=f"Live forecast for {wf.project_title} in {wf.location} ({wf.shoot_date}): {wf.temp_c}°C / {wf.temp_f}°F {wf.condition}. Wind is {wf.wind_kmh} km/h {wf.wind_direction} ({wf.drone_status}).",
            weather_forecast=wf,
            images=sample_images[:1],
        )

    if any(k in q for k in ("new client", "booking", "onboard")):
        clients = _default_new_clients()
        return BriefingChatResponse(
            reply=f"You have {len(clients)} new client notifications totaling ${sum(c.package_amount for c in clients):,}.",
            new_clients=clients,
        )

    if any(k in q for k in ("image", "photo", "moodboard", "visual", "lighting")):
        return BriefingChatResponse(
            reply="Here are AI-curated visual moodboard references, golden hour lighting setups, and color-grading plates for your upcoming shoots:",
            images=sample_images,
        )

    if any(k in q for k in ("call", "meeting", "video", "schedule", "message", "unread")):
        return BriefingChatResponse(
            reply="Here are your pending video call requests and unread client messages awaiting your response:",
            pending_messages=_default_pending_messages(),
        )

    return BriefingChatResponse(
        reply="Here is your complete studio intelligence pulse: 3 new client bookings, 24°C Golden Clear weather forecast for Tuscany, pending calls & messages, and AI invoicing ready.",
        weather_forecast=_default_weather(),
        new_clients=_default_new_clients()[:2],
        images=sample_images,
        suggested_links=[
            BriefingActionItemResponse(
                kind=i.kind,
                title=i.title,
                subtitle=i.subtitle,
                project_id=i.project_id,
                project_title=i.project_title,
                url=i.url,
                priority=i.priority,
            )
            for i in b.action_items[:3]
        ],
    )


@router.get("/creators/me/invoices/ai", response_model=list[AiGeneratedInvoiceDto])
async def list_ai_generated_invoices(
    actor: CurrentActiveUserDep,
) -> list[AiGeneratedInvoiceDto]:
    return _AI_GENERATED_INVOICES


@router.post(
    "/creators/me/invoices/ai-generate",
    response_model=AiGeneratedInvoiceDto,
    status_code=status.HTTP_201_CREATED,
)
async def create_ai_generated_invoice(
    body: AiGenerateInvoiceRequest,
    actor: CurrentActiveUserDep,
) -> AiGeneratedInvoiceDto:
    return _generate_ai_invoice(body)


@router.get("/creators/me/referrals", response_model=CreatorReferralSummaryDto)
async def get_my_referrals(
    actor: CurrentActiveUserDep,
) -> CreatorReferralSummaryDto:
    return _build_referrals_summary(actor.first_name)


@router.post(
    "/creators/me/referrals/invite",
    response_model=CreatorReferralSummaryDto,
    status_code=status.HTTP_201_CREATED,
)
async def invite_referral(
    body: CreatorReferralInviteRequest,
    actor: CurrentActiveUserDep,
) -> CreatorReferralSummaryDto:
    new_entry = CreatorReferralEntryDto(
        id=f"ref-{len(_CREATOR_REFERRALS) + 1}",
        referred_name=body.name,
        referred_email=body.email,
        role=body.role,
        status="Invited",
        date=datetime.now(timezone.utc).strftime("%b %d, %Y"),
        reward_amount=350 if body.role == "creator" else 250,
        bonus_storage_gb=250,
    )
    _CREATOR_REFERRALS.insert(0, new_entry)
    return _build_referrals_summary(actor.first_name)


@router.post(
    "/security/screen-violation",
    response_model=ScreenSecurityStatusResponse,
)
async def record_screen_security_violation(
    body: ScreenSecurityViolationRequest,
) -> ScreenSecurityStatusResponse:
    prev = _SECURITY_SESSIONS.get(body.session_token)
    count = (prev.violation_count if prev else 0) + 1
    status_obj = ScreenSecurityStatusResponse(
        session_token=body.session_token,
        locked=True,
        violation_count=count,
        reason=f"Security Shield Triggered ({body.event_type}): {body.details or 'Screen capture or camera snap blocked'}",
        triggered_at=datetime.now(timezone.utc).isoformat(),
    )
    _SECURITY_SESSIONS[body.session_token] = status_obj
    return status_obj


@router.get(
    "/security/camera-trap/{session_token}",
    response_model=ScreenSecurityStatusResponse,
)
async def trigger_optical_qr_camera_trap(
    session_token: str,
) -> ScreenSecurityStatusResponse:
    """Hit automatically when a smartphone camera points at the screen and scans/previews the embedded Optical QR code."""
    prev = _SECURITY_SESSIONS.get(session_token)
    count = (prev.violation_count if prev else 0) + 1
    status_obj = ScreenSecurityStatusResponse(
        session_token=session_token,
        locked=True,
        violation_count=count,
        reason="External Phone Camera Detected via Optical QR Trap — Screen Disabled",
        triggered_at=datetime.now(timezone.utc).isoformat(),
    )
    _SECURITY_SESSIONS[session_token] = status_obj
    return status_obj


@router.get(
    "/security/camera-trap/{session_token}/status",
    response_model=ScreenSecurityStatusResponse,
)
async def get_optical_qr_camera_trap_status(
    session_token: str,
) -> ScreenSecurityStatusResponse:
    return _SECURITY_SESSIONS.get(
        session_token,
        ScreenSecurityStatusResponse(
            session_token=session_token,
            locked=False,
            violation_count=0,
            reason=None,
            triggered_at=None,
        ),
    )


@router.post(
    "/security/camera-trap/{session_token}/reset",
    response_model=ScreenSecurityStatusResponse,
)
async def reset_optical_qr_camera_trap(
    session_token: str,
) -> ScreenSecurityStatusResponse:
    prev = _SECURITY_SESSIONS.get(session_token)
    status_obj = ScreenSecurityStatusResponse(
        session_token=session_token,
        locked=False,
        violation_count=prev.violation_count if prev else 0,
        reason=None,
        triggered_at=None,
    )
    _SECURITY_SESSIONS[session_token] = status_obj
    return status_obj


# ── Client AI Briefing & Client Chatbot Endpoints ─────────────────────────────

@router.get("/clients/me/briefing", response_model=ClientBriefingResponse)
async def get_my_client_briefing(
    actor: CurrentActiveUserDep,
) -> ClientBriefingResponse:
    first = actor.first_name or "Valued Client"
    deadline = (datetime.now(timezone.utc) + timedelta(days=2, hours=14)).isoformat()
    return ClientBriefingResponse(
        headline=f"Welcome back, {first}! Your studio deliverables & shoot countdown are live.",
        summary_text="45 retouched photographs and 1 4K highlight reel are ready for your review. Your next venue shoot is 18.4 km away with a 48-hour proofing deadline warning.",
        active_projects_count=2,
        photos_ready_count=45,
        pending_approvals_count=1,
        upcoming_calls_count=1,
        next_project_title="Smith & Wesson Wedding",
        next_project_venue="Val d’Orcia Villa, Tuscany, Italy",
        venue_distance_km=18.4,
        venue_travel_time="26 mins drive from Studio Base",
        deadline_iso=deadline,
        deadline_warning="URGENT DEADLINE WARNING: Final album selection & color-grade sign-off due in 2 days (14h remaining).",
        action_items=[
            BriefingActionItemResponse(
                kind="revision",
                title="Review 45 Released Proof Photographs & Approve Album Selects",
                subtitle="Smith & Wesson Wedding • Deadline in 2 days • 18.4 km to venue",
                project_id="1",
                project_title="Smith & Wesson Wedding",
                url="/client/projects",
                priority="urgent",
            ),
            BriefingActionItemResponse(
                kind="call",
                title="Upcoming Video Sync with Lead Photographer Sarah Cabmora",
                subtitle="Final Sunset Timeline & Shot List Walkthrough • Today at 16:30",
                project_id="1",
                project_title="Smith & Wesson Wedding",
                url="/client/messages",
                priority="high",
            ),
            BriefingActionItemResponse(
                kind="task",
                title="Outstanding Milestone Invoice INV-2025-042 ($4,250)",
                subtitle="Due in 48 hours to unlock uncompressed 4K master downloads",
                project_id="1",
                project_title="Smith & Wesson Wedding",
                url="/client/billing",
                priority="high",
            ),
        ],
    )


@router.post("/clients/me/briefing/chat", response_model=BriefingChatResponse)
async def chat_my_client_briefing(
    body: BriefingChatRequest,
    actor: CurrentActiveUserDep,
) -> BriefingChatResponse:
    q = body.message.strip().lower()
    sample_images = [
        AiVisualAttachmentDto(
            url="https://images.unsplash.com/photo-1519741497674-611481863552?w=900&h=600&fit=crop",
            caption="Released Proof #14 — Golden Hour Ridge (Watermarked Client Preview)",
            tag="Ready for Review",
        ),
        AiVisualAttachmentDto(
            url="https://images.unsplash.com/photo-1511285560929-80b456fea0bc?w=900&h=600&fit=crop",
            caption="Released Proof #22 — Editorial Portrait Plate",
            tag="Approved Select",
        ),
    ]
    if any(k in q for k in ("distance", "venue", "countdown", "deadline", "when")):
        return BriefingChatResponse(
            reply="Your next project venue (Val d’Orcia Villa, Tuscany) is 18.4 km away (approx. 26 mins travel). Warning: Your final proofing selection deadline is in 2 days and 14 hours!",
            weather_forecast=_default_weather(),
            images=sample_images[:1],
        )
    if any(k in q for k in ("photo", "gallery", "image", "proof", "deliver")):
        return BriefingChatResponse(
            reply="You have 45 released photographs ready for your proofing review. Here are two highlighted selects from your gallery:",
            images=sample_images,
        )
    return BriefingChatResponse(
        reply="Hello! I am your Personal Client AI Concierge. I can show your released gallery previews, live shoot countdown & venue distance (18.4 km), deadline warnings, or connect you on a live call with your creator.",
        weather_forecast=_default_weather(),
        images=sample_images,
    )


# ── LinkedIn-style Creator & Client Community Endpoints ──────────────────────

_COMMUNITY_AUTO_FOLLOWED_CREATORS: set[str] = set()

_COMMUNITY_FOLLOWERS: list[CommunityFollowerDto] = [
    CommunityFollowerDto(
        id="fol-1",
        name="Elena Vance",
        handle="@elenavance_paris",
        role="client",
        specialization="Creative Director • Vance Models Paris",
        avatar="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&h=150&fit=crop",
        followed_at="2 hours ago",
        auto_followed_via_like=True,
    ),
    CommunityFollowerDto(
        id="fol-2",
        name="Marcus Chang",
        handle="@marcuschang_cinema",
        role="creator",
        specialization="4K Aerial Cinematographer & Colorist",
        avatar="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&h=150&fit=crop",
        followed_at="Yesterday",
        auto_followed_via_like=True,
    ),
    CommunityFollowerDto(
        id="fol-3",
        name="Clara & Julian Mercer",
        handle="@atelier_mercer",
        role="client",
        specialization="Luxury Destination Wedding Clients • Lake Como",
        avatar="https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=150&h=150&fit=crop",
        followed_at="2 days ago",
        auto_followed_via_like=True,
    ),
    CommunityFollowerDto(
        id="fol-4",
        name="Lucas Sterling",
        handle="@sterling_editorial",
        role="creator",
        specialization="Haute Couture & Runway Photographer • Milan",
        avatar="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&h=150&fit=crop",
        followed_at="4 days ago",
        auto_followed_via_like=False,
    ),
]

_COMMUNITY_POSTS: list[CommunityPostDto] = [
    CommunityPostDto(
        id="post-101",
        project_id="4",
        project_title="Johnson Family Portraits — Central Park Golden Hour",
        project_type="Portrait",
        client_name="Mark & Sarah Johnson",
        location="Central Park, New York, NY",
        venue_distance_km=12.6,
        completed_date="Completed & Delivered • Jan 25, 2026",
        deliverables_summary="85 Color-Corrected Medium Format Portraits + Archival Linen Album",
        creator_id="creator-sarah",
        creator_name="Sarah Cabmora",
        creator_handle="@sarahcabmora_studio",
        creator_specialization="Lead Editorial & Destination Wedding Photographer",
        creator_avatar="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150&h=150&fit=crop",
        caption="Thrilled to share our completed delivery for the Johnson Family in Central Park! Shot entirely during a 45-minute golden hour window on 50mm f/1.2 glass with custom Kodak Portra 400 emulation. Open to collaborating with NYC & European filmmakers on upcoming autumn commissions!",
        media_urls=[
            "https://images.unsplash.com/photo-1609220136736-443140cffec6?w=900&h=600&fit=crop",
            "https://images.unsplash.com/photo-1511285560929-80b456fea0bc?w=900&h=600&fit=crop",
        ],
        likes_count=48,
        liked_by_me=False,
        comments=[
            CommunityCommentDto(
                id="cm-1",
                author_name="Marcus Chang",
                author_role="creator",
                author_avatar="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&h=150&fit=crop",
                text="The skin tone roll-off in the highlights is extraordinary! Sent a collaboration request for our Lake Como date.",
                created_at="1h ago",
            ),
            CommunityCommentDto(
                id="cm-2",
                author_name="Elena Vance",
                author_role="client",
                author_avatar="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&h=150&fit=crop",
                text="Love the warmth and editorial framing — we want this exact mood for our Paris SS26 campaign!",
                created_at="35m ago",
            ),
        ],
        created_at="2 hours ago",
    ),
    CommunityPostDto(
        id="post-102",
        project_id="comp-202",
        project_title="Villa Balbianello Architectural & Bridal Film",
        project_type="Wedding",
        client_name="Sterling Luxury Events",
        location="Lake Como, Italy",
        venue_distance_km=28.5,
        completed_date="Completed & Delivered • Oct 18, 2025",
        deliverables_summary="12-Min 4K ProRes Master Film + 320 Medium-Format Stills",
        creator_id="creator-marcus",
        creator_name="Marcus Chang",
        creator_handle="@marcuschang_cinema",
        creator_specialization="Lead 4K Aerial Cinematographer & DaVinci Colorist",
        creator_avatar="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&h=150&fit=crop",
        caption="Completed our final 4K ProRes delivery from Villa Balbianello! Looking to collaborate with lead still photographers who need dedicated aerial cinema and live color grading on European destination shoots.",
        media_urls=[
            "https://images.unsplash.com/photo-1519741497674-611481863552?w=900&h=600&fit=crop",
            "https://images.unsplash.com/photo-1469334031218-e382a71b716b?w=900&h=600&fit=crop",
        ],
        likes_count=74,
        liked_by_me=False,
        comments=[
            CommunityCommentDto(
                id="cm-3",
                author_name="Clara Mercer",
                author_role="client",
                author_avatar="https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=150&h=150&fit=crop",
                text="The drone perspective over the lake water is breathtaking!",
                created_at="3h ago",
            ),
        ],
        created_at="5 hours ago",
    ),
    CommunityPostDto(
        id="post-103",
        project_id="comp-203",
        project_title="Maison Lumière Haute Couture Runway Finale",
        project_type="Editorial",
        client_name="Maison Lumière Paris",
        location="Place Vendôme, Paris, France",
        venue_distance_km=9.4,
        completed_date="Completed & Delivered • Oct 10, 2025",
        deliverables_summary="120 Retouched Press Plates + Backstage Documentary Cut",
        creator_id="creator-lucas",
        creator_name="Lucas Sterling",
        creator_handle="@sterling_editorial",
        creator_specialization="Haute Couture & Commercial Fashion Photographer",
        creator_avatar="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=150&h=150&fit=crop",
        caption="Wrapped and delivered our Paris Fashion Week editorial commission for Maison Lumière. Always excited to team up with lighting directors, retouchers, and brand clients for winter lookbooks!",
        media_urls=[
            "https://images.unsplash.com/photo-1492691527719-9d1e07e534b4?w=900&h=600&fit=crop",
            "https://images.unsplash.com/photo-1523381294911-8d3cead13475?w=900&h=600&fit=crop",
        ],
        likes_count=62,
        liked_by_me=False,
        comments=[],
        created_at="1 day ago",
    ),
]

_COMMUNITY_COLLABORATIONS: list[CommunityCollaborationRequestDto] = [
    CommunityCollaborationRequestDto(
        id="col-1",
        post_id="post-101",
        project_title="Lake Como Destination Wedding — Hybrid Production",
        requester_name="Marcus Chang",
        requester_role="creator",
        requester_avatar="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150&h=150&fit=crop",
        target_creator_id="creator-sarah",
        target_creator_name="Sarah Cabmora",
        proposed_role="Co-Lead 4K Drone & Steadicam Operator",
        proposed_date="Oct 28, 2025",
        budget_or_split="$2,200 Day Rate / 35% Cinema Split",
        message="Saw your completed Central Park & Tuscany work in Community! I have Inspire 3 RAW drone clearance in Como and would love to collaborate on your Oct 28 wedding.",
        status="pending",
        direction="incoming",
        created_at="42 mins ago",
    ),
    CommunityCollaborationRequestDto(
        id="col-2",
        post_id="post-101",
        project_title="Vogue Italia Bridal Supplement Shoot",
        requester_name="Elena Vance (Client)",
        requester_role="client",
        requester_avatar="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&h=150&fit=crop",
        target_creator_id="creator-sarah",
        target_creator_name="Sarah Cabmora",
        proposed_role="Lead Campaign Photographer + Marcus Chang (Video)",
        proposed_date="Nov 19, 2025",
        budget_or_split="$9,500 Full Production Package",
        message="After seeing your completed job in the Community feed, we want to book a joint collaboration with you for our November Milan/Paris supplement.",
        status="pending",
        direction="incoming",
        created_at="3 hours ago",
    ),
]


@router.get("/community/feed", response_model=CommunityFeedResponse)
async def get_community_feed() -> CommunityFeedResponse:
    return CommunityFeedResponse(
        posts=_COMMUNITY_POSTS,
        followers=_COMMUNITY_FOLLOWERS,
        followers_count=len(_COMMUNITY_FOLLOWERS),
        collaborations=_COMMUNITY_COLLABORATIONS,
        auto_followed_creator_ids=list(_COMMUNITY_AUTO_FOLLOWED_CREATORS),
    )


@router.post(
    "/community/posts/share-completed-job",
    response_model=CommunityFeedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def share_completed_job_to_community(
    body: CommunityShareCompletedJobRequest,
    actor: CurrentActiveUserDep,
) -> CommunityFeedResponse:
    creator_name = actor.full_name or "Sarah Cabmora"
    handle = f"@{(actor.first_name or 'sarah').lower()}cabmora_studio"
    new_post = CommunityPostDto(
        id=f"post-{len(_COMMUNITY_POSTS) + 105}",
        project_id=body.project_id,
        project_title=body.project_title,
        project_type=body.project_type,
        client_name=body.client_name,
        location=body.location,
        venue_distance_km=14.2,
        completed_date="Completed & Delivered • Just now",
        deliverables_summary=body.deliverables_summary,
        creator_id=str(actor.id),
        creator_name=creator_name,
        creator_handle=handle,
        creator_specialization="Partner Photographer & Videographer",
        creator_avatar="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150&h=150&fit=crop",
        caption=body.caption,
        media_urls=body.media_urls
        or [
            "https://images.unsplash.com/photo-1519741497674-611481863552?w=900&h=600&fit=crop"
        ],
        likes_count=1,
        liked_by_me=True,
        comments=[],
        created_at="Just now",
    )
    _COMMUNITY_POSTS.insert(0, new_post)
    return await get_community_feed()


@router.post("/community/posts/{post_id}/like", response_model=CommunityFeedResponse)
async def toggle_like_community_post(
    post_id: str,
) -> CommunityFeedResponse:
    """First like on a creator's post automatically follows that creator."""
    for p in _COMMUNITY_POSTS:
        if p.id == post_id:
            if not p.liked_by_me:
                p.liked_by_me = True
                p.likes_count += 1
                _COMMUNITY_AUTO_FOLLOWED_CREATORS.add(p.creator_id)
            else:
                p.liked_by_me = False
                p.likes_count = max(0, p.likes_count - 1)
            break
    return await get_community_feed()


@router.post("/community/posts/{post_id}/comments", response_model=CommunityFeedResponse)
async def comment_on_community_post(
    post_id: str,
    body: CommunityCommentRequest,
    actor: CurrentActiveUserDep,
) -> CommunityFeedResponse:
    for p in _COMMUNITY_POSTS:
        if p.id == post_id:
            p.comments.append(
                CommunityCommentDto(
                    id=f"cm-{len(p.comments) + 100}",
                    author_name=actor.full_name or "Studio Member",
                    author_role=body.author_role,
                    author_avatar="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150&h=150&fit=crop",
                    text=body.text,
                    created_at="Just now",
                )
            )
            break
    return await get_community_feed()


@router.post("/community/collaborations", response_model=CommunityFeedResponse)
async def request_community_collaboration(
    body: CommunityCollaborationCreateRequest,
    actor: CurrentActiveUserDep,
) -> CommunityFeedResponse:
    req = CommunityCollaborationRequestDto(
        id=f"col-{len(_COMMUNITY_COLLABORATIONS) + 10}",
        post_id=body.post_id,
        project_title=body.project_title,
        requester_name=actor.full_name or "Sarah Cabmora",
        requester_role=body.requester_role,
        requester_avatar="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150&h=150&fit=crop",
        target_creator_id=body.target_creator_id,
        target_creator_name=body.target_creator_name,
        proposed_role=body.proposed_role,
        proposed_date=body.proposed_date,
        budget_or_split=body.budget_or_split,
        message=body.message,
        status="pending",
        direction="outgoing",
        created_at="Just now",
    )
    _COMMUNITY_COLLABORATIONS.insert(0, req)
    return await get_community_feed()


@router.post(
    "/community/collaborations/{collab_id}/respond",
    response_model=CommunityFeedResponse,
)
async def respond_community_collaboration(
    collab_id: str,
    body: CommunityCollaborationRespondRequest,
) -> CommunityFeedResponse:
    for col in _COMMUNITY_COLLABORATIONS:
        if col.id == collab_id:
            col.status = "accepted" if body.action == "accept" else "declined"
            break
    return await get_community_feed()

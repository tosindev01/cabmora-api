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
    BriefingActionItemResponse,
    BriefingChatRequest,
    BriefingChatResponse,
    CallCreateRequest,
    CallRespondRequest,
    CallResponse,
    CreatorBriefingResponse,
    TaskCreateRequest,
    TaskResponse,
    TaskUpdateRequest,
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
    return CreatorBriefingResponse(
        headline=b.headline,
        summary_text=b.summary_text,
        projects_in_progress=b.projects_in_progress,
        pending_tasks_count=b.pending_tasks_count,
        revision_requests_count=b.revision_requests_count,
        unread_comments_count=b.unread_comments_count,
        upcoming_deadlines_count=b.upcoming_deadlines_count,
        pending_calls_count=b.pending_calls_count,
        action_items=[
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
        ],
    )


@router.post("/creators/me/briefing/chat", response_model=BriefingChatResponse)
async def chat_my_briefing(
    body: BriefingChatRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[GetCreatorBriefing, Depends(get_creator_briefing)],
) -> BriefingChatResponse:
    b = await use_case.execute(actor)
    q = body.message.strip().lower()

    if any(k in q for k in ("call", "meeting", "video", "schedule")):
        relevant = [i for i in b.action_items if i.kind == "call"]
        reply = (
            f"You currently have {b.pending_calls_count} pending call request(s) awaiting your response."
            if b.pending_calls_count
            else "You have no pending call requests right now. You can request a video call from any project workspace."
        )
    elif any(k in q for k in ("revision", "feedback", "comment", "change")):
        relevant = [i for i in b.action_items if i.kind in ("revision", "comment")]
        reply = (
            f"There are {b.revision_requests_count} open revision request(s) and {b.unread_comments_count} client design comment(s) waiting for your review."
            if (b.revision_requests_count or b.unread_comments_count)
            else "All client design comments and revision requests are resolved!"
        )
    elif any(k in q for k in ("deadline", "due", "urgent", "soon")):
        relevant = [i for i in b.action_items if i.kind == "deadline"]
        reply = (
            f"You have {b.upcoming_deadlines_count} project(s) with deadlines in the next 14 days."
            if b.upcoming_deadlines_count
            else "No project deadlines fall within the next 14 days."
        )
    elif any(k in q for k in ("task", "todo", "deliverable", "work")):
        relevant = [i for i in b.action_items if i.kind == "task"]
        reply = (
            f"You have {b.pending_tasks_count} pending task(s) across {b.projects_in_progress} active project(s)."
            if b.pending_tasks_count
            else "All assigned project tasks are currently completed."
        )
    else:
        relevant = b.action_items[:3]
        reply = f"{b.summary_text} Ask me about your tasks, revisions, deadlines, or call requests."

    return BriefingChatResponse(
        reply=reply,
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
            for i in relevant
        ],
    )

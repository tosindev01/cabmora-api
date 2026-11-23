import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

from app.application.use_cases.notifications.notifier import Notifier
from app.core.exceptions import (
    EntityNotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.entities.collaboration import (
    CallStatus,
    ProjectCall,
    ProjectTask,
    TaskPriority,
    TaskStatus,
)
from app.domain.entities.comment import CommentKind
from app.domain.entities.notification import NotificationTopic
from app.domain.entities.project import ProjectStage
from app.domain.entities.user import User, UserRole
from app.domain.repositories.collaboration_repository import CollaborationRepository
from app.domain.repositories.comment_repository import CommentRepository
from app.domain.repositories.project_repository import ProjectRepository
from app.domain.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)


async def _user_display(users: UserRepository, user_id: UUID | None) -> str:
    if user_id is None:
        return "Studio Team"
    u = await users.get_by_id(user_id)
    if u is None:
        return "Team Member"
    return u.full_name or u.email


class ListProjectTasks:
    def __init__(
        self, projects: ProjectRepository, collab: CollaborationRepository
    ) -> None:
        self._projects = projects
        self._collab = collab

    async def execute(self, project_id: UUID, actor: User) -> list[ProjectTask]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")
        return await self._collab.list_tasks_for_project(project_id)


class CreateProjectTask:
    def __init__(
        self, projects: ProjectRepository, collab: CollaborationRepository
    ) -> None:
        self._projects = projects
        self._collab = collab

    async def execute(
        self,
        project_id: UUID,
        actor: User,
        *,
        title: str,
        description: str = "",
        priority: TaskPriority = TaskPriority.MEDIUM,
        due_at: datetime | None = None,
        assignee_id: UUID | None = None,
    ) -> ProjectTask:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_managed_by(actor):
            raise PermissionDeniedError("Only the studio team can create project tasks.")
        task = ProjectTask(
            project_id=project_id,
            title=title,
            description=description,
            priority=priority,
            due_at=due_at,
            assignee_id=assignee_id or actor.id,
            created_by=actor.id,
        )
        return await self._collab.add_task(task)


class UpdateProjectTask:
    def __init__(
        self, projects: ProjectRepository, collab: CollaborationRepository
    ) -> None:
        self._projects = projects
        self._collab = collab

    async def execute(
        self,
        task_id: UUID,
        actor: User,
        *,
        title: str | None = None,
        description: str | None = None,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        due_at: datetime | None = None,
    ) -> ProjectTask:
        task = await self._collab.get_task(task_id)
        if task is None:
            raise EntityNotFoundError("Task not found")
        project = await self._projects.get_by_id(task.project_id)
        if project is None or not project.is_managed_by(actor):
            raise PermissionDeniedError("Only the studio team can update tasks.")
        if title is not None:
            clean = title.strip()
            if not clean:
                raise ValidationError("A task needs a title.")
            task.title = clean
        if description is not None:
            task.description = description
        if status is not None:
            task.status = status
        if priority is not None:
            task.priority = priority
        if due_at is not None:
            task.due_at = due_at
        return await self._collab.save_task(task)


class DeleteProjectTask:
    def __init__(
        self, projects: ProjectRepository, collab: CollaborationRepository
    ) -> None:
        self._projects = projects
        self._collab = collab

    async def execute(self, task_id: UUID, actor: User) -> None:
        task = await self._collab.get_task(task_id)
        if task is None:
            raise EntityNotFoundError("Task not found")
        project = await self._projects.get_by_id(task.project_id)
        if project is None or not project.is_managed_by(actor):
            raise PermissionDeniedError("Only the studio team can delete tasks.")
        await self._collab.delete_task(task_id)


@dataclass
class EnrichedCall:
    call: ProjectCall
    project_title: str
    requester_name: str
    recipient_name: str


class RequestProjectCall:
    def __init__(
        self,
        projects: ProjectRepository,
        collab: CollaborationRepository,
        users: UserRepository,
        notifier: Notifier,
    ) -> None:
        self._projects = projects
        self._collab = collab
        self._users = users
        self._notifier = notifier

    async def execute(
        self,
        project_id: UUID,
        actor: User,
        *,
        title: str,
        proposed_at: datetime,
        duration_minutes: int = 30,
        notes: str = "",
    ) -> EnrichedCall:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")

        if project.customer_id is not None and actor.id == project.customer_id:
            recipient_id = project.creator_id or (
                project.member_ids[0] if project.member_ids else None
            )
            recipient_path = f"/projects/{project.id}"
        else:
            recipient_id = project.customer_id
            recipient_path = f"/client/projects/{project.id}"

        if recipient_id is None:
            raise ValidationError(
                "This project does not have an assigned collaborator to call yet."
            )
        if recipient_id == actor.id:
            raise ValidationError("You cannot request a call with yourself.")

        call = ProjectCall(
            project_id=project.id,
            requester_id=actor.id,
            recipient_id=recipient_id,
            title=title.strip() or f"Project Sync — {project.title}",
            proposed_at=proposed_at,
            duration_minutes=max(10, min(180, duration_minutes)),
            notes=notes.strip(),
        )
        saved = await self._collab.add_call(call)

        when_str = saved.proposed_at.strftime("%b %d at %H:%M UTC")
        await self._notifier._tell(
            recipient_id,
            topic=NotificationTopic.BOOKING,
            title=f"{actor.full_name} requested a video call for {project.title}",
            body=f"{saved.title} • Proposed: {when_str}. Open the project to Accept or Decline.",
            url=recipient_path,
        )

        return EnrichedCall(
            call=saved,
            project_title=project.title,
            requester_name=actor.full_name,
            recipient_name=await _user_display(self._users, recipient_id),
        )


class RespondToProjectCall:
    def __init__(
        self,
        projects: ProjectRepository,
        collab: CollaborationRepository,
        users: UserRepository,
        notifier: Notifier,
    ) -> None:
        self._projects = projects
        self._collab = collab
        self._users = users
        self._notifier = notifier

    async def execute(
        self,
        call_id: UUID,
        actor: User,
        *,
        action: str,
        proposed_at: datetime | None = None,
    ) -> EnrichedCall:
        call = await self._collab.get_call(call_id)
        if call is None:
            raise EntityNotFoundError("Call request not found")

        project = await self._projects.get_by_id(call.project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")

        is_participant = actor.id in (call.requester_id, call.recipient_id) or (
            actor.role is UserRole.ADMIN
        )
        if not is_participant:
            raise PermissionDeniedError("You are not part of this call request.")

        other_id = (
            call.requester_id if actor.id == call.recipient_id else call.recipient_id
        )
        other_is_customer = project.customer_id is not None and other_id == project.customer_id
        other_url = (
            f"/client/projects/{project.id}"
            if other_is_customer
            else f"/projects/{project.id}"
        )

        if action == "accept":
            if actor.id != call.recipient_id and actor.role is not UserRole.ADMIN:
                raise PermissionDeniedError("Only the call recipient can accept.")
            call.accept()
            notice_title = f"{actor.full_name} accepted your video call for {project.title}"
            notice_body = "Your video call is confirmed. You can now join the meeting room."
        elif action == "decline":
            if actor.id != call.recipient_id and actor.role is not UserRole.ADMIN:
                raise PermissionDeniedError("Only the call recipient can decline.")
            call.decline()
            notice_title = f"{actor.full_name} declined the call request for {project.title}"
            notice_body = "You can propose another date and time from the project workspace."
        elif action == "cancel":
            call.cancel()
            notice_title = f"Call cancelled for {project.title}"
            notice_body = f"{actor.full_name} cancelled '{call.title}'."
        elif action == "complete":
            call.complete()
            notice_title = None
            notice_body = ""
        elif action == "reschedule":
            if proposed_at is None:
                raise ValidationError("Choose a new date and time to reschedule.")
            call.reschedule(proposed_at)
            # Flip recipient to the other party so the other person must accept the new time
            if actor.id == call.recipient_id:
                call.requester_id, call.recipient_id = call.recipient_id, call.requester_id
            notice_title = f"{actor.full_name} proposed a new call time for {project.title}"
            notice_body = (
                f"New proposed time: {proposed_at.strftime('%b %d at %H:%M UTC')}."
            )
        else:
            raise ValidationError("Unsupported call action.")

        saved = await self._collab.save_call(call)
        if notice_title:
            await self._notifier._tell(
                other_id,
                topic=NotificationTopic.BOOKING,
                title=notice_title,
                body=notice_body,
                url=other_url,
            )

        return EnrichedCall(
            call=saved,
            project_title=project.title,
            requester_name=await _user_display(self._users, saved.requester_id),
            recipient_name=await _user_display(self._users, saved.recipient_id),
        )


class ListProjectCalls:
    def __init__(
        self,
        projects: ProjectRepository,
        collab: CollaborationRepository,
        users: UserRepository,
    ) -> None:
        self._projects = projects
        self._collab = collab
        self._users = users

    async def execute(self, project_id: UUID, actor: User) -> list[EnrichedCall]:
        project = await self._projects.get_by_id(project_id)
        if project is None:
            raise EntityNotFoundError("Project not found")
        if not project.is_visible_to(actor):
            raise PermissionDeniedError("You do not have access to this project.")
        calls = await self._collab.list_calls_for_project(project_id)
        return [
            EnrichedCall(
                call=c,
                project_title=project.title,
                requester_name=await _user_display(self._users, c.requester_id),
                recipient_name=await _user_display(self._users, c.recipient_id),
            )
            for c in calls
        ]


class ListMyCalls:
    def __init__(
        self,
        projects: ProjectRepository,
        collab: CollaborationRepository,
        users: UserRepository,
        notifier: Notifier,
    ) -> None:
        self._projects = projects
        self._collab = collab
        self._users = users
        self._notifier = notifier

    async def execute(self, actor: User) -> list[EnrichedCall]:
        calls = await self._collab.list_calls_for_user(actor.id)
        now = datetime.now(timezone.utc)
        soon = now + timedelta(hours=2)

        enriched: list[EnrichedCall] = []
        for c in calls:
            project = await self._projects.get_by_id(c.project_id)
            title = project.title if project else "Project"

            # Emit an in-app reminder if an accepted call starts within 2 hours
            if (
                c.status is CallStatus.ACCEPTED
                and c.reminder_sent_at is None
                and now <= c.proposed_at <= soon
            ):
                c.reminder_sent_at = now
                await self._collab.save_call(c)
                for uid in (c.requester_id, c.recipient_id):
                    is_client = project and project.customer_id == uid
                    await self._notifier._tell(
                        uid,
                        topic=NotificationTopic.BOOKING,
                        title=f"Upcoming call reminder: {c.title}",
                        body=f"Starting soon ({c.proposed_at.strftime('%H:%M UTC')}) for {title}.",
                        url=f"/client/projects/{c.project_id}"
                        if is_client
                        else f"/projects/{c.project_id}",
                    )

            enriched.append(
                EnrichedCall(
                    call=c,
                    project_title=title,
                    requester_name=await _user_display(self._users, c.requester_id),
                    recipient_name=await _user_display(self._users, c.recipient_id),
                )
            )
        return enriched


@dataclass
class BriefingActionItem:
    kind: str  # "revision" | "task" | "deadline" | "call" | "comment"
    title: str
    subtitle: str
    project_id: UUID
    project_title: str
    url: str
    priority: str  # "urgent" | "high" | "normal"


@dataclass
class CreatorBriefing:
    headline: str
    summary_text: str
    projects_in_progress: int
    pending_tasks_count: int
    revision_requests_count: int
    unread_comments_count: int
    upcoming_deadlines_count: int
    pending_calls_count: int
    action_items: list[BriefingActionItem]


class GetCreatorBriefing:
    """Analyses real assigned projects, tasks, comments, deadlines and call requests."""

    def __init__(
        self,
        projects: ProjectRepository,
        comments: CommentRepository,
        collab: CollaborationRepository,
    ) -> None:
        self._projects = projects
        self._comments = comments
        self._collab = collab

    async def execute(self, actor: User) -> CreatorBriefing:
        all_projects = await self._projects.list_all(
            limit=100,
            offset=0,
            creator_id=actor.id if actor.role is UserRole.CREATOR else None,
            access_for=actor.id if actor.role is UserRole.COORDINATOR else None,
        )
        active_projects = [
            p
            for p in all_projects
            if p.stage not in (ProjectStage.DELIVERED, ProjectStage.CLOSED)
        ]
        project_ids = [p.id for p in all_projects]
        project_map = {p.id: p for p in all_projects}

        tasks = await self._collab.list_tasks_for_projects(project_ids)
        pending_tasks = [t for t in tasks if t.status is not TaskStatus.COMPLETED]

        threads = await self._comments.list_for_projects(project_ids)
        open_revisions = []
        open_comments = []
        for pid, plist in threads.items():
            for c in plist:
                if not c.is_resolved:
                    if c.kind is CommentKind.AMENDMENT:
                        open_revisions.append((pid, c))
                    elif c.author_id != actor.id:
                        open_comments.append((pid, c))

        now_date = datetime.now(timezone.utc).date()
        horizon = now_date + timedelta(days=14)
        upcoming_deadlines = [
            p
            for p in active_projects
            if p.deadline is not None and now_date <= p.deadline <= horizon
        ]

        calls = await self._collab.list_calls_for_user(actor.id)
        pending_calls = [
            c
            for c in calls
            if c.status is CallStatus.PENDING and c.recipient_id == actor.id
        ]

        action_items: list[BriefingActionItem] = []

        for c in pending_calls[:3]:
            proj = project_map.get(c.project_id)
            action_items.append(
                BriefingActionItem(
                    kind="call",
                    title=f"Incoming call request: {c.title}",
                    subtitle=f"Proposed for {c.proposed_at.strftime('%b %d at %H:%M UTC')}",
                    project_id=c.project_id,
                    project_title=proj.title if proj else "Project",
                    url=f"/projects/{c.project_id}",
                    priority="urgent",
                )
            )

        for pid, rev in open_revisions[:4]:
            proj = project_map.get(pid)
            action_items.append(
                BriefingActionItem(
                    kind="revision",
                    title="Client requested revision",
                    subtitle=rev.body[:90] + ("…" if len(rev.body) > 90 else ""),
                    project_id=pid,
                    project_title=proj.title if proj else "Project",
                    url=f"/projects/{pid}",
                    priority="urgent",
                )
            )

        for p in upcoming_deadlines[:3]:
            days_left = (p.deadline - now_date).days if p.deadline else 0
            action_items.append(
                BriefingActionItem(
                    kind="deadline",
                    title=f"Upcoming deadline in {days_left} day(s)",
                    subtitle=f"Stage: {p.stage.value.replace('_', ' ').title()}",
                    project_id=p.id,
                    project_title=p.title,
                    url=f"/projects/{p.id}",
                    priority="high" if days_left <= 3 else "normal",
                )
            )

        for t in pending_tasks[:4]:
            proj = project_map.get(t.project_id)
            action_items.append(
                BriefingActionItem(
                    kind="task",
                    title=t.title,
                    subtitle=f"Priority: {t.priority.value.title()} • Status: {t.status.value.replace('_', ' ').title()}",
                    project_id=t.project_id,
                    project_title=proj.title if proj else "Project",
                    url=f"/projects/{t.project_id}",
                    priority="high" if t.priority is TaskPriority.HIGH else "normal",
                )
            )

        for pid, cm in open_comments[:3]:
            proj = project_map.get(pid)
            action_items.append(
                BriefingActionItem(
                    kind="comment",
                    title="Design feedback comment awaiting reply",
                    subtitle=cm.body[:90] + ("…" if len(cm.body) > 90 else ""),
                    project_id=pid,
                    project_title=proj.title if proj else "Project",
                    url=f"/projects/{pid}",
                    priority="normal",
                )
            )

        headline = f"Welcome back, {actor.first_name}! Here's what needs your attention today."
        parts = []
        if active_projects:
            parts.append(f"{len(active_projects)} project(s) currently in progress")
        if pending_tasks:
            parts.append(f"{len(pending_tasks)} task(s) awaiting completion")
        if open_revisions:
            parts.append(f"{len(open_revisions)} client revision request(s)")
        if pending_calls:
            parts.append(f"{len(pending_calls)} pending call request(s)")
        summary_text = (
            "You have " + ", ".join(parts) + "."
            if parts
            else "All assigned projects, deliverables, and feedback threads are up to date."
        )

        return CreatorBriefing(
            headline=headline,
            summary_text=summary_text,
            projects_in_progress=len(active_projects),
            pending_tasks_count=len(pending_tasks),
            revision_requests_count=len(open_revisions),
            unread_comments_count=len(open_comments),
            upcoming_deadlines_count=len(upcoming_deadlines),
            pending_calls_count=len(pending_calls),
            action_items=action_items,
        )

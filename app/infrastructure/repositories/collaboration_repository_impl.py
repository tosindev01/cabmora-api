from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.collaboration import ProjectCall, ProjectTask
from app.domain.repositories.collaboration_repository import CollaborationRepository
from app.infrastructure.models.collaboration import ProjectCallModel, ProjectTaskModel


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _task_entity(row: ProjectTaskModel) -> ProjectTask:
    t = row.to_entity()
    t.due_at = _aware(t.due_at)
    t.created_at = _aware(t.created_at) or t.created_at
    return t


def _call_entity(row: ProjectCallModel) -> ProjectCall:
    c = row.to_entity()
    c.proposed_at = _aware(c.proposed_at) or c.proposed_at
    c.responded_at = _aware(c.responded_at)
    c.reminder_sent_at = _aware(c.reminder_sent_at)
    c.created_at = _aware(c.created_at) or c.created_at
    return c


class SqlAlchemyCollaborationRepository(CollaborationRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_tasks_for_project(self, project_id: UUID) -> list[ProjectTask]:
        rows = await self._session.scalars(
            select(ProjectTaskModel)
            .where(ProjectTaskModel.project_id == str(project_id))
            .order_by(ProjectTaskModel.created_at.desc())
        )
        return [_task_entity(r) for r in rows]

    async def list_tasks_for_projects(
        self, project_ids: list[UUID]
    ) -> list[ProjectTask]:
        if not project_ids:
            return []
        rows = await self._session.scalars(
            select(ProjectTaskModel)
            .where(ProjectTaskModel.project_id.in_([str(pid) for pid in project_ids]))
            .order_by(ProjectTaskModel.created_at.desc())
        )
        return [_task_entity(r) for r in rows]

    async def add_task(self, task: ProjectTask) -> ProjectTask:
        self._session.add(ProjectTaskModel.from_entity(task))
        await self._session.commit()
        return task

    async def get_task(self, task_id: UUID) -> ProjectTask | None:
        row = await self._session.get(ProjectTaskModel, str(task_id))
        return _task_entity(row) if row else None

    async def save_task(self, task: ProjectTask) -> ProjectTask:
        row = await self._session.get(ProjectTaskModel, str(task.id))
        if row is None:
            self._session.add(ProjectTaskModel.from_entity(task))
        else:
            row.title = task.title
            row.description = task.description
            row.status = task.status.value
            row.priority = task.priority.value
            row.due_at = task.due_at
            row.assignee_id = str(task.assignee_id) if task.assignee_id else None
        await self._session.commit()
        return task

    async def delete_task(self, task_id: UUID) -> None:
        await self._session.execute(
            delete(ProjectTaskModel).where(ProjectTaskModel.id == str(task_id))
        )
        await self._session.commit()

    async def list_calls_for_project(self, project_id: UUID) -> list[ProjectCall]:
        rows = await self._session.scalars(
            select(ProjectCallModel)
            .where(ProjectCallModel.project_id == str(project_id))
            .order_by(ProjectCallModel.proposed_at.desc())
        )
        return [_call_entity(r) for r in rows]

    async def list_calls_for_user(self, user_id: UUID) -> list[ProjectCall]:
        uid = str(user_id)
        rows = await self._session.scalars(
            select(ProjectCallModel)
            .where(
                or_(
                    ProjectCallModel.requester_id == uid,
                    ProjectCallModel.recipient_id == uid,
                )
            )
            .order_by(ProjectCallModel.proposed_at.desc())
        )
        return [_call_entity(r) for r in rows]

    async def add_call(self, call: ProjectCall) -> ProjectCall:
        self._session.add(ProjectCallModel.from_entity(call))
        await self._session.commit()
        return call

    async def get_call(self, call_id: UUID) -> ProjectCall | None:
        row = await self._session.get(ProjectCallModel, str(call_id))
        return _call_entity(row) if row else None

    async def save_call(self, call: ProjectCall) -> ProjectCall:
        row = await self._session.get(ProjectCallModel, str(call.id))
        if row is None:
            self._session.add(ProjectCallModel.from_entity(call))
        else:
            row.proposed_at = call.proposed_at
            row.status = call.status.value
            row.meeting_room_id = call.meeting_room_id
            row.meeting_url = call.meeting_url
            row.responded_at = call.responded_at
            row.reminder_sent_at = call.reminder_sent_at
        await self._session.commit()
        return call

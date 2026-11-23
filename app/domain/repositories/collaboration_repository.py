from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.entities.collaboration import ProjectCall, ProjectTask


class CollaborationRepository(ABC):
    @abstractmethod
    async def list_tasks_for_project(self, project_id: UUID) -> list[ProjectTask]: ...

    @abstractmethod
    async def list_tasks_for_projects(
        self, project_ids: list[UUID]
    ) -> list[ProjectTask]: ...

    @abstractmethod
    async def add_task(self, task: ProjectTask) -> ProjectTask: ...

    @abstractmethod
    async def get_task(self, task_id: UUID) -> ProjectTask | None: ...

    @abstractmethod
    async def save_task(self, task: ProjectTask) -> ProjectTask: ...

    @abstractmethod
    async def delete_task(self, task_id: UUID) -> None: ...

    @abstractmethod
    async def list_calls_for_project(self, project_id: UUID) -> list[ProjectCall]: ...

    @abstractmethod
    async def list_calls_for_user(self, user_id: UUID) -> list[ProjectCall]: ...

    @abstractmethod
    async def add_call(self, call: ProjectCall) -> ProjectCall: ...

    @abstractmethod
    async def get_call(self, call_id: UUID) -> ProjectCall | None: ...

    @abstractmethod
    async def save_call(self, call: ProjectCall) -> ProjectCall: ...

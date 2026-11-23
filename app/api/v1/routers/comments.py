"""Feedback endpoints.

One path for both sides of the conversation. Who may say what is decided in
the use cases against the project, not by which router you reached — a client
and an admin post to the same place and the rules differ underneath.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    CurrentActiveUserDep,
    OptionalStorageDep,
    get_add_comment,
    get_list_comments,
    get_list_conversations,
    get_resolve_comment,
)
from app.api.schemas.comment import (
    CommentCreateRequest,
    CommentResponse,
    ConversationResponse,
)
from app.application.use_cases.comments.add_comment import AddComment
from app.application.use_cases.comments.list_comments import ListComments
from app.application.use_cases.comments.list_conversations import ListConversations
from app.application.use_cases.comments.resolve_comment import ResolveComment
from app.core.exceptions import ValidationError
from app.domain.entities.comment import Comment, CommentKind

router = APIRouter(tags=["comments"])


def _response(
    comment: Comment,
    author_name: str,
    *,
    author_role: str | None = None,
    author_avatar_url: str | None = None,
) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        project_id=comment.project_id,
        asset_id=comment.asset_id,
        parent_id=comment.parent_id,
        point_x=comment.point_x,
        point_y=comment.point_y,
        author_id=comment.author_id,
        author_name=author_name,
        author_role=author_role,
        author_avatar_url=author_avatar_url,
        body=comment.body,
        kind=comment.kind.value,
        resolved=comment.is_resolved,
        needs_action=comment.needs_action,
        created_at=comment.created_at,
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def my_conversations(
    actor: CurrentActiveUserDep,
    use_case: Annotated[ListConversations, Depends(get_list_conversations)],
) -> list[ConversationResponse]:
    """Everything said on the caller's own projects, grouped by project.

    Scoped to them by the use case rather than by a parameter: a project id
    in a query string is how one client reads another's conversation.
    """
    return [
        ConversationResponse(
            project_id=conversation.project_id,
            project_title=conversation.project_title,
            event_type=conversation.event_type,
            stage=conversation.stage,
            messages=[
                _response(m.comment, m.author_name) for m in conversation.messages
            ],
        )
        for conversation in await use_case.execute(actor)
    ]


@router.get("/projects/{project_id}/comments", response_model=list[CommentResponse])
async def list_comments(
    project_id: UUID,
    actor: CurrentActiveUserDep,
    storage: OptionalStorageDep,
    use_case: Annotated[ListComments, Depends(get_list_comments)],
) -> list[CommentResponse]:
    items = await use_case.execute(project_id, actor)
    avatar_cache: dict[str, str | None] = {}
    responses: list[CommentResponse] = []
    for item in items:
        avatar_url: str | None = None
        if item.author_avatar_key and storage is not None:
            if item.author_avatar_key not in avatar_cache:
                try:
                    avatar_cache[item.author_avatar_key] = await storage.presign_download(
                        key=item.author_avatar_key, expires_in=900
                    )
                except Exception:
                    avatar_cache[item.author_avatar_key] = None
            avatar_url = avatar_cache[item.author_avatar_key]
        responses.append(
            _response(
                item.comment,
                item.author_name,
                author_role=item.author_role,
                author_avatar_url=avatar_url,
            )
        )
    return responses


@router.post(
    "/projects/{project_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    project_id: UUID,
    body: CommentCreateRequest,
    actor: CurrentActiveUserDep,
    use_case: Annotated[AddComment, Depends(get_add_comment)],
) -> CommentResponse:
    try:
        kind = CommentKind(body.kind)
    except ValueError:
        raise ValidationError(
            f"{body.kind!r} is not a kind of feedback. Use 'comment' or 'amendment'."
        ) from None

    comment = await use_case.execute(
        project_id=project_id,
        actor=actor,
        body=body.body,
        asset_id=body.asset_id,
        parent_id=body.parent_id,
        point_x=body.point_x,
        point_y=body.point_y,
        kind=kind,
    )
    # The author is whoever just posted, so no lookup is needed here.
    return _response(
        comment,
        f"{actor.first_name} {actor.last_name}".strip(),
        author_role=actor.role.value,
    )


@router.post("/comments/{comment_id}/resolve", response_model=CommentResponse)
async def resolve_comment(
    comment_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ResolveComment, Depends(get_resolve_comment)],
) -> CommentResponse:
    resolved = await use_case.execute(comment_id, actor)
    # Named after whoever wrote it, not whoever closed it — otherwise the
    # console relabels a client's request as the admin's the moment it is
    # marked done, and only a reload puts it right.
    return _response(resolved.comment, resolved.author_name)


@router.post("/comments/{comment_id}/reopen", response_model=CommentResponse)
async def reopen_comment(
    comment_id: UUID,
    actor: CurrentActiveUserDep,
    use_case: Annotated[ResolveComment, Depends(get_resolve_comment)],
) -> CommentResponse:
    reopened = await use_case.reopen(comment_id, actor)
    return _response(reopened.comment, reopened.author_name)

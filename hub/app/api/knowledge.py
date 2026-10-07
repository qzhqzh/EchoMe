"""Authenticated knowledge workbench; scoped AI tokens cannot make review decisions."""

import hashlib
import secrets
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user, security
from app.core.config import settings
from app.core.database import get_session
from app.models.knowledge import (
    KnowledgeAgentToken,
    KnowledgeAsset,
    KnowledgeDecision,
    KnowledgeVersion,
)
from app.schemas.knowledge import (
    CONTRACTS,
    Kind,
    KnowledgeCapture,
    KnowledgeQuery,
    PlacementRemoval,
    RecordCreate,
    RecordUpdate,
    ReviewDecisionRequest,
    TokenCreate,
)
from app.services.knowledge import (
    Principal,
    compact,
    context_bundle,
    create_record,
    current_backlinks,
    decide,
    expand,
    get_record,
    query_records,
    update_record,
)
from app.services.knowledge_directory import directory_branch
from app.services.knowledge_editing import capture_entry, reference_choices, remove_placement
from app.services.knowledge_navigation import connections, project_tree
from app.services.knowledge_search import SearchCategory, search_knowledge

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


async def knowledge_principal(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    session: AsyncSession = Depends(get_session),
    review_key: str | None = Header(default=None, alias="X-EchoMe-Review-Key"),
) -> Principal:
    token = credentials.credentials
    if token.startswith("ek_agent_"):
        row = await session.scalar(
            select(KnowledgeAgentToken).where(
                KnowledgeAgentToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
                KnowledgeAgentToken.revoked.is_(False),
            )
        )
        if row is None:
            raise HTTPException(401, "Invalid or revoked knowledge agent token")
        return Principal(row.user_id, "agent-token:" + str(row.id), agent=True)
    user = await get_current_user(credentials, session)
    reviewer = bool(
        settings.knowledge_review_key
        and review_key
        and secrets.compare_digest(settings.knowledge_review_key, review_key)
    )
    if review_key and not reviewer:
        raise HTTPException(403, "Invalid reviewer credential")
    return Principal(str(user.id), "owner-credential:" + str(user.id), reviewer=reviewer)


P = Annotated[Principal, Depends(knowledge_principal)]
S = Annotated[AsyncSession, Depends(get_session)]


@router.get("/schema")
async def schema(principal: P) -> dict[str, Any]:
    return {
        "version": "echome.knowledge.v1",
        "contracts": {kind: model.model_json_schema() for kind, model in CONTRACTS.items()},
        "reviewer_configured": bool(settings.knowledge_review_key),
        "actor": principal.actor,
        "can_review": principal.reviewer,
        "rules": [
            "Knowledge has no project owner.",
            "Create coarse entities; split only when useful.",
            "Save source origin and actual excerpts; do not invent evidence.",
            "AI may propose changes; reviewer credential is a separate capability, not proof of a human.",
            "Query coverage is stored structured records, not all facts in Pages or the world.",
        ],
    }


@router.post("/records", status_code=201)
async def create(body: RecordCreate, principal: P, session: S) -> dict[str, Any]:
    row = await create_record(session, principal, body)
    return await expand(session, row)


@router.get("/records")
async def records(
    principal: P,
    session: S,
    kind: Kind = "project",
    search: str | None = Query(default=None, max_length=500),
    linked_to: UUID | None = None,
    include_inactive: bool = False,
    entity_kind: str | None = Query(default=None, max_length=32),
    exclude_entity_kind: Literal["topic", "concept", "tool", "method", "object"] | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    return await query_records(
        session,
        principal,
        KnowledgeQuery(
            kind=kind,
            offset=offset,
            limit=limit,
            include_inactive=include_inactive,
            filters={"entity_kind": entity_kind} if entity_kind else {},
            exclude_entity_kind=exclude_entity_kind,
        ),
        search=search,
        linked_to=linked_to,
    )


@router.post("/query")
async def exact_query(body: KnowledgeQuery, principal: P, session: S) -> dict[str, Any]:
    return await query_records(session, principal, body)


@router.post("/capture", status_code=201)
async def capture(body: KnowledgeCapture, principal: P, session: S) -> dict[str, Any]:
    return await capture_entry(session, principal, body)


@router.get("/choices")
async def choices(
    principal: P,
    session: S,
    kinds: str = "entity",
    search: str | None = Query(default=None, max_length=500),
    exclude_id: UUID | None = None,
    exclude_topics: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    return await reference_choices(
        session, principal, kinds, search, exclude_id, exclude_topics, offset, limit
    )


@router.post("/placements/{placement_id}/remove")
async def remove_classification(
    placement_id: UUID, body: PlacementRemoval, principal: P, session: S
) -> dict[str, Any]:
    return await remove_placement(session, principal, placement_id, body.expected_revision)


@router.get("/directory")
async def directory(
    principal: P,
    session: S,
    parent_id: UUID | None = None,
    unplaced: bool = False,
    search: str | None = Query(default=None, max_length=500),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    return await directory_branch(
        session,
        principal,
        parent_id=parent_id,
        unplaced=unplaced,
        search=search.strip() if search else None,
        offset=offset,
        limit=limit,
    )


@router.get("/records/{record_id}")
async def detail(
    record_id: UUID, principal: P, session: S, revision: int | None = Query(default=None, ge=1)
) -> dict[str, Any]:
    row = await get_record(session, principal.user_id, record_id)
    return await expand(session, row, revision)


@router.get("/search")
async def search(
    principal: P,
    session: S,
    q: str = Query(min_length=1, max_length=500),
    category: SearchCategory = "all",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    return await search_knowledge(session, principal, q, category, offset, limit)


@router.get("/project-tree")
async def projects_tree(
    principal: P,
    session: S,
    parent_id: UUID | None = None,
    independent: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    return await project_tree(
        session, principal, parent_id=parent_id, independent=independent, offset=offset, limit=limit
    )


@router.get("/records/{record_id}/connections")
async def knowledge_connections(
    record_id: UUID,
    principal: P,
    session: S,
    section: Literal["domains", "uses"] = "domains",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    return await connections(session, principal, record_id, section, offset, limit)


@router.patch("/records/{record_id}")
async def update(record_id: UUID, body: RecordUpdate, principal: P, session: S) -> dict[str, Any]:
    return await expand(session, await update_record(session, principal, record_id, body))


@router.get("/records/{record_id}/history")
async def history(
    record_id: UUID,
    principal: P,
    session: S,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=30, ge=1, le=100),
) -> dict[str, Any]:
    row = await get_record(session, principal.user_id, record_id)
    versions = await session.scalars(
        select(KnowledgeVersion)
        .where(KnowledgeVersion.user_id == principal.user_id, KnowledgeVersion.record_id == row.id)
        .order_by(KnowledgeVersion.revision.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        {
            "revision": v.revision,
            "version_id": str(v.id),
            "data": v.payload,
            "reason": v.reason,
            "actor": v.actor,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]
    return {
        "items": items,
        "total": row.revision,
        "next_offset": offset + len(items) if offset + len(items) < row.revision else None,
    }


@router.get("/records/{record_id}/backlinks")
async def backlinks(record_id: UUID, principal: P, session: S) -> dict[str, Any]:
    await get_record(session, principal.user_id, record_id)
    rows = await current_backlinks(session, principal.user_id, record_id)
    return {"items": [await expand(session, row) for row in rows], "total": len(rows)}


@router.get("/records/{record_id}/context")
async def context(
    record_id: UUID,
    principal: P,
    session: S,
    max_chars: int = Query(default=48000, ge=8000, le=200000),
) -> dict[str, Any]:
    return await context_bundle(session, principal, record_id, max_chars)


@router.post("/reviews/{review_id}/decisions")
async def decision(
    review_id: UUID, body: ReviewDecisionRequest, principal: P, session: S
) -> dict[str, Any]:
    return await decide(session, principal, review_id, body)


@router.get("/reviews/{review_id}/decisions")
async def decisions(review_id: UUID, principal: P, session: S) -> dict[str, Any]:
    await get_record(session, principal.user_id, review_id)
    rows = await session.scalars(
        select(KnowledgeDecision)
        .where(
            KnowledgeDecision.user_id == principal.user_id, KnowledgeDecision.review_id == review_id
        )
        .order_by(KnowledgeDecision.created_at)
    )
    return {
        "items": [
            {
                "id": str(r.id),
                "action": r.action,
                "note": r.note,
                "actor": r.actor,
                "results": r.results,
                "review_revision": r.review_revision,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    }


@router.post("/agent-tokens", status_code=201)
async def issue_token(body: TokenCreate, principal: P, session: S) -> dict[str, Any]:
    if principal.agent:
        raise HTTPException(403, "Agent credentials cannot manage credentials")
    token = "ek_agent_" + secrets.token_urlsafe(32)
    row = KnowledgeAgentToken(
        user_id=principal.user_id,
        name=body.name,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
    )
    session.add(row)
    await session.flush()
    return {
        "id": str(row.id),
        "name": row.name,
        "token": token,
        "scope": "knowledge:read,knowledge:write,review:propose",
    }


@router.get("/agent-tokens")
async def list_tokens(principal: P, session: S) -> dict[str, Any]:
    if principal.agent:
        raise HTTPException(403, "Agent credentials cannot manage credentials")
    rows = await session.scalars(
        select(KnowledgeAgentToken).where(KnowledgeAgentToken.user_id == principal.user_id)
    )
    return {"items": [{"id": str(r.id), "name": r.name, "revoked": r.revoked} for r in rows]}


@router.delete("/agent-tokens/{token_id}", status_code=204)
async def revoke_token(token_id: UUID, principal: P, session: S) -> Response:
    if principal.agent:
        raise HTTPException(403, "Agent credentials cannot manage credentials")
    row = await session.scalar(
        select(KnowledgeAgentToken).where(
            KnowledgeAgentToken.id == token_id, KnowledgeAgentToken.user_id == principal.user_id
        )
    )
    if row is None:
        raise HTTPException(404, "Agent token not found")
    row.revoked = True
    return Response(status_code=204)


@router.post("/assets", status_code=201)
async def upload_asset(
    request: Request, principal: P, session: S, filename: str = Query(min_length=1, max_length=256)
) -> dict[str, Any]:
    asset_id = uuid4()
    directory = Path(settings.knowledge_storage_path).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / str(asset_id)
    size = 0
    digest = hashlib.sha256()
    try:
        with path.open("xb") as stream:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 128 * 1024 * 1024:
                    raise HTTPException(
                        413, "Asset exceeds 128 MiB; use an external resource reference"
                    )
                digest.update(chunk)
                stream.write(chunk)
        if size == 0:
            raise HTTPException(422, "Empty asset")
        media_type = request.headers.get("content-type", "application/octet-stream").split(";")[0]
        if media_type not in (
            "image/png",
            "image/jpeg",
            "image/webp",
            "video/mp4",
            "application/pdf",
            "text/plain",
        ):
            media_type = "application/octet-stream"
        row = KnowledgeAsset(
            id=asset_id,
            user_id=principal.user_id,
            filename=Path(filename).name,
            media_type=media_type,
            content_hash=digest.hexdigest(),
            size=size,
        )
        session.add(row)
        await session.flush()
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {
        "id": str(asset_id),
        "resource_ref": "asset:" + str(asset_id),
        "filename": row.filename,
        "content_hash": row.content_hash,
        "size": size,
        "media_type": media_type,
    }


@router.get("/assets/{asset_id}")
async def download_asset(asset_id: UUID, principal: P, session: S) -> FileResponse:
    row = await session.scalar(
        select(KnowledgeAsset).where(
            KnowledgeAsset.id == asset_id, KnowledgeAsset.user_id == principal.user_id
        )
    )
    if row is None:
        raise HTTPException(404, "Asset not found")
    path = Path(settings.knowledge_storage_path).resolve() / str(row.id)
    if not path.is_file():
        raise HTTPException(404, "Asset file unavailable")
    return FileResponse(
        path,
        media_type=row.media_type,
        filename=row.filename,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )

"""Explicit scenario routing and resumable execution contracts."""

import json
import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.database import get_session
from app.models.memory import Project
from app.models.scenario import Scenario, ScenarioItem, ScenarioRun, ScenarioVersion
from app.schemas.scenario import (
    ScenarioClaim,
    ScenarioCreate,
    ScenarioDefinition,
    ScenarioItemBind,
    ScenarioItemCreate,
    ScenarioItemPatch,
    ScenarioItemUpgrade,
    ScenarioPatch,
    ScenarioPublish,
    ScenarioResolve,
    ScenarioRunFinish,
    ScenarioVersionCreate,
)
from app.services.content_safety import require_safe_content

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _safe_json(value: Any) -> None:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) > 100_000:
        raise HTTPException(status_code=422, detail="Scenario payload is too large")
    require_safe_content(encoded)


def _scenario_payload(item: Scenario) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "project_id": item.project_id,
        "slug": item.slug,
        "title": item.title,
        "summary": item.summary,
        "aliases": item.aliases,
        "status": item.status,
        "current_version": item.current_version,
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def _version_payload(item: ScenarioVersion) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "version": item.version,
        "definition": item.definition,
        "validation_evidence": item.validation_evidence,
        "published_at": _iso(item.published_at),
        "created_at": _iso(item.created_at),
    }


def _item_payload(item: ScenarioItem, slug: str | None = None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "scenario_id": str(item.scenario_id) if item.scenario_id else None,
        "scenario_slug": slug,
        "version_id": str(item.version_id) if item.version_id else None,
        "title": item.title,
        "goal": item.goal,
        "working_plan": item.working_plan,
        "mode": item.mode,
        "status": item.status,
        "phase": item.phase,
        "parameters": item.parameters,
        "environment": item.environment,
        "state": item.state,
        "version_history": item.version_history,
        "revision": item.revision,
        "current_observation": item.current_observation,
        "last_success_at": _iso(item.last_success_at),
        "last_success_summary": item.last_success_summary,
        "last_run_at": _iso(item.last_run_at),
        "next_check_at": _iso(item.next_check_at),
        "lease_expires_at": _iso(item.lease_expires_at),
        "created_at": _iso(item.created_at),
        "updated_at": _iso(item.updated_at),
    }


def _run_payload(item: ScenarioRun) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "item_id": str(item.item_id),
        "version_id": str(item.version_id) if item.version_id else None,
        "idempotency_key": item.idempotency_key,
        "status": item.status,
        "outcome": item.outcome,
        "observation": item.observation,
        "summary": item.summary,
        "evidence": item.evidence,
        "event_key": item.event_key,
        "signal": item.signal,
        "notification_recommended": item.notification_recommended,
        "started_at": _iso(item.started_at),
        "finished_at": _iso(item.finished_at),
        "lease_expires_at": _iso(item.lease_expires_at),
    }


async def _scenario(
    session: AsyncSession, slug: str, user_id: str, *, lock: bool = False
) -> Scenario:
    query = select(Scenario).where(Scenario.user_id == user_id, Scenario.slug == slug)
    if lock:
        query = query.with_for_update()
    item = await session.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return item


async def _version(
    session: AsyncSession, scenario: Scenario, version: int, user_id: str
) -> ScenarioVersion:
    item = await session.scalar(
        select(ScenarioVersion).where(
            ScenarioVersion.user_id == user_id,
            ScenarioVersion.scenario_id == scenario.id,
            ScenarioVersion.version == version,
        )
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Scenario version not found")
    return item


async def _item(
    session: AsyncSession, item_id: uuid.UUID, user_id: str, *, lock: bool = False
) -> ScenarioItem:
    query = select(ScenarioItem).where(ScenarioItem.id == item_id, ScenarioItem.user_id == user_id)
    if lock:
        query = query.with_for_update()
    item = await session.scalar(query)
    if item is None:
        raise HTTPException(status_code=404, detail="Scenario item not found")
    return item


async def _check_selector_unique(
    session: AsyncSession,
    user_id: str,
    slug: str,
    aliases: list[str],
    exclude_id: uuid.UUID | None = None,
) -> None:
    incoming = {slug.casefold(), *(alias.casefold() for alias in aliases)}
    if len(incoming) != len(aliases) + 1:
        raise HTTPException(status_code=409, detail="Scenario slug and aliases overlap")
    existing = (await session.scalars(select(Scenario).where(Scenario.user_id == user_id))).all()
    for item in existing:
        if item.id == exclude_id:
            continue
        if incoming & {item.slug.casefold(), *(alias.casefold() for alias in item.aliases)}:
            raise HTTPException(status_code=409, detail="Scenario selector already exists")


async def _lock_user_selectors(session: AsyncSession, user_id: str) -> None:
    """Serialize alias edits for one user, including concurrent first creates."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"scenario-selectors:{user_id}"},
    )


def _evaluate(
    definition: ScenarioDefinition,
    parameters: dict[str, str],
    environment: dict[str, str],
) -> dict[str, Any]:
    fields = {field.name: field for field in definition.input_fields}
    invalid = sorted(set(parameters) - set(fields))
    invalid += sorted(name for name in parameters if name in fields and fields[name].secret)
    invalid += sorted(
        name for name, value in parameters.items() if not value.strip() or len(value) > 2000
    )
    defaults = {
        name: field.default
        for name, field in fields.items()
        if field.default is not None and name not in parameters
    }
    accepted = {
        name: value
        for name, value in parameters.items()
        if name in fields and not fields[name].secret and value.strip() and len(value) <= 2000
    }
    bound = {**defaults, **accepted}
    missing = sorted(
        name
        for name, field in fields.items()
        if field.required and not field.secret and name not in bound
    )
    mismatched = {
        key: {"expected": expected, "actual": environment.get(key)}
        for key, expected in definition.required_environment.items()
        if environment.get(key) != expected
    }
    runtime_secrets = [name for name, field in fields.items() if field.secret]
    if invalid or mismatched:
        decision = "incompatible"
    elif missing:
        decision = "missing_inputs"
    else:
        decision = "ready_for_manual_checks"
    return {
        "decision": decision,
        "parameters": bound,
        "missing_inputs": missing,
        "invalid_inputs": sorted(set(invalid)),
        "environment_mismatches": mismatched,
        "runtime_secrets": runtime_secrets,
        "manual_checks": [definition.applicability, definition.exclusions],
    }


def _require_routable(evaluation: dict[str, Any]) -> None:
    if evaluation["decision"] != "ready_for_manual_checks":
        raise HTTPException(status_code=422, detail=evaluation)


def _ensure_no_live_lease(item: ScenarioItem) -> None:
    if item.lease_token and item.lease_expires_at and item.lease_expires_at > _now():
        raise HTTPException(status_code=409, detail="Item has an active execution lease")


@router.post("", status_code=201)
async def create_scenario(
    body: ScenarioCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump())
    await _lock_user_selectors(session, user_id)
    await _check_selector_unique(session, user_id, body.slug, body.aliases)
    if (
        body.project_id
        and await session.scalar(
            select(Project.id).where(Project.id == body.project_id, Project.user_id == user_id)
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Project not found")
    item = Scenario(
        user_id=user_id,
        project_id=body.project_id,
        slug=body.slug,
        title=body.title,
        summary=body.summary,
        aliases=body.aliases,
    )
    session.add(item)
    await session.flush()
    version = ScenarioVersion(
        user_id=user_id,
        scenario_id=item.id,
        version=1,
        definition=body.definition.model_dump(),
    )
    session.add(version)
    await session.flush()
    return {"scenario": _scenario_payload(item), "version": _version_payload(version)}


@router.get("")
async def list_scenarios(
    project_id: str | None = None,
    status: str | None = Query(None, pattern=r"^(draft|active|disabled)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    filters = [Scenario.user_id == user_id]
    if project_id is not None:
        filters.append(Scenario.project_id == project_id)
    if status is not None:
        filters.append(Scenario.status == status)
    total = await session.scalar(select(func.count()).select_from(Scenario).where(*filters))
    items = (
        await session.scalars(
            select(Scenario)
            .where(*filters)
            .order_by(Scenario.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return {"total": total, "items": [_scenario_payload(item) for item in items]}


@router.post("/resolve")
async def resolve_scenario(
    body: ScenarioResolve,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump())
    candidates = (await session.scalars(select(Scenario).where(Scenario.user_id == user_id))).all()
    selector = body.selector.casefold().strip()
    matching = [
        item
        for item in candidates
        if selector == item.slug.casefold()
        or selector in {alias.casefold() for alias in item.aliases}
    ]
    if not matching:
        return {"decision": "not_found", "selector": body.selector}
    if len(matching) > 1:
        return {
            "decision": "ambiguous",
            "selector": body.selector,
            "candidates": [item.slug for item in matching],
        }
    item = matching[0]
    if item.status != "active" or item.current_version is None:
        return {"decision": "unavailable", "scenario": _scenario_payload(item)}
    version = await _version(session, item, item.current_version, user_id)
    evaluation = _evaluate(
        ScenarioDefinition.model_validate(version.definition), body.parameters, body.environment
    )
    return {**evaluation, "scenario": _scenario_payload(item), "version": _version_payload(version)}


@router.get("/due")
async def list_due_items(
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    now = _now()
    items = (
        await session.scalars(
            select(ScenarioItem)
            .where(
                ScenarioItem.user_id == user_id,
                ScenarioItem.mode == "continuous",
                ScenarioItem.status == "active",
                ScenarioItem.next_check_at <= now,
                (ScenarioItem.lease_expires_at.is_(None)) | (ScenarioItem.lease_expires_at <= now),
            )
            .order_by(ScenarioItem.next_check_at)
            .limit(limit)
        )
    ).all()
    slugs = await _scenario_slugs(session, items)
    return {
        "items": [
            _item_payload(item, slugs.get(item.scenario_id) if item.scenario_id else None)
            for item in items
        ]
    }


async def _scenario_slugs(
    session: AsyncSession, items: Sequence[ScenarioItem]
) -> dict[uuid.UUID, str]:
    ids = {item.scenario_id for item in items if item.scenario_id is not None}
    if not ids:
        return {}
    scenarios = (await session.scalars(select(Scenario).where(Scenario.id.in_(ids)))).all()
    return {scenario.id: scenario.slug for scenario in scenarios}


@router.get("/catalog/{slug}")
async def get_scenario(
    slug: str,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    item = await _scenario(session, slug, user_id)
    versions = (
        await session.scalars(
            select(ScenarioVersion)
            .where(ScenarioVersion.scenario_id == item.id, ScenarioVersion.user_id == user_id)
            .order_by(ScenarioVersion.version.desc())
        )
    ).all()
    return {
        "scenario": _scenario_payload(item),
        "versions": [_version_payload(version) for version in versions],
    }


@router.patch("/catalog/{slug}")
async def patch_scenario(
    slug: str,
    body: ScenarioPatch,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump(exclude_unset=True))
    if body.aliases is not None:
        await _lock_user_selectors(session, user_id)
    item = await _scenario(session, slug, user_id, lock=True)
    if body.aliases is not None:
        await _check_selector_unique(session, user_id, item.slug, body.aliases, item.id)
        item.aliases = body.aliases
    if body.title is not None:
        item.title = body.title
    if body.summary is not None:
        item.summary = body.summary
    if body.enabled is not None:
        if body.enabled and item.current_version is None:
            raise HTTPException(status_code=409, detail="Publish a version before enabling")
        item.status = "active" if body.enabled else "disabled"
    item.updated_at = _now()
    return _scenario_payload(item)


@router.post("/catalog/{slug}/versions", status_code=201)
async def create_version(
    slug: str,
    body: ScenarioVersionCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump())
    item = await _scenario(session, slug, user_id, lock=True)
    latest = await session.scalar(
        select(func.max(ScenarioVersion.version)).where(ScenarioVersion.scenario_id == item.id)
    )
    version = ScenarioVersion(
        user_id=user_id,
        scenario_id=item.id,
        version=(latest or 0) + 1,
        definition=body.definition.model_dump(),
    )
    session.add(version)
    item.updated_at = _now()
    await session.flush()
    return _version_payload(version)


@router.post("/catalog/{slug}/versions/{number}/publish")
async def publish_version(
    slug: str,
    number: int,
    body: ScenarioPublish,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    require_safe_content(body.validation_evidence)
    item = await _scenario(session, slug, user_id, lock=True)
    version = await _version(session, item, number, user_id)
    if version.published_at is not None:
        raise HTTPException(status_code=409, detail="Version is already published; use activate")
    version.published_at = _now()
    version.validation_evidence = body.validation_evidence
    item.current_version = version.version
    item.status = "active"
    item.updated_at = _now()
    return {"scenario": _scenario_payload(item), "version": _version_payload(version)}


@router.post("/catalog/{slug}/versions/{number}/activate")
async def activate_version(
    slug: str,
    number: int,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    item = await _scenario(session, slug, user_id, lock=True)
    version = await _version(session, item, number, user_id)
    if version.published_at is None:
        raise HTTPException(status_code=409, detail="Version has not been published")
    item.current_version = number
    item.status = "active"
    item.updated_at = _now()
    return {"scenario": _scenario_payload(item), "version": _version_payload(version)}


@router.post("/items", status_code=201)
async def create_item(
    body: ScenarioItemCreate,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump())
    scenario = None
    version = None
    evaluation: dict[str, Any] = {
        "parameters": body.parameters,
        "runtime_secrets": [],
        "manual_checks": [],
    }
    if body.scenario_slug is not None:
        scenario = await _scenario(session, body.scenario_slug, user_id)
        if scenario.status != "active":
            raise HTTPException(status_code=409, detail="Scenario is not active")
        number = body.version or scenario.current_version
        if number is None:
            raise HTTPException(status_code=409, detail="Scenario has no published version")
        version = await _version(session, scenario, number, user_id)
        if version.published_at is None:
            raise HTTPException(status_code=409, detail="Scenario version has not been published")
        evaluation = _evaluate(
            ScenarioDefinition.model_validate(version.definition), body.parameters, body.environment
        )
        _require_routable(evaluation)
    elif any(not value.strip() or len(value) > 2000 for value in body.parameters.values()):
        raise HTTPException(status_code=422, detail="Standalone parameters must be bounded strings")
    item = ScenarioItem(
        user_id=user_id,
        scenario_id=scenario.id if scenario else None,
        version_id=version.id if version else None,
        title=body.title,
        goal=body.goal,
        working_plan=body.working_plan,
        mode=body.mode,
        phase=body.phase,
        state=body.state,
        parameters=evaluation["parameters"],
        environment=body.environment,
        next_check_at=body.next_check_at,
        version_history=(
            [{"version": version.version, "at": _now().isoformat(), "reason": "created"}]
            if version
            else []
        ),
    )
    session.add(item)
    await session.flush()
    return {
        "item": _item_payload(item, scenario.slug if scenario else None),
        "version": _version_payload(version) if version else None,
        "runtime_secrets": evaluation["runtime_secrets"],
        "manual_checks": evaluation["manual_checks"],
    }


@router.get("/items")
async def list_items(
    status: str | None = Query(None, pattern=r"^(active|paused|completed)$"),
    mode: str | None = Query(None, pattern=r"^(one_off|continuous)$"),
    query: str | None = Query(None, min_length=1, max_length=256),
    scenario_slug: str | None = Query(None, min_length=1, max_length=128),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    filters = [ScenarioItem.user_id == user_id]
    if scenario_slug is not None:
        scenario = await _scenario(session, scenario_slug, user_id)
        filters.append(ScenarioItem.scenario_id == scenario.id)
    if query is not None:
        term = query.strip()
        if not term:
            raise HTTPException(status_code=422, detail="Search query must contain text")
        filters.append(
            func.lower(ScenarioItem.title).contains(term.lower(), autoescape=True)
            | func.lower(ScenarioItem.goal).contains(term.lower(), autoescape=True)
        )
    if status:
        filters.append(ScenarioItem.status == status)
    if mode:
        filters.append(ScenarioItem.mode == mode)
    total = await session.scalar(select(func.count()).select_from(ScenarioItem).where(*filters))
    items = (
        await session.scalars(
            select(ScenarioItem)
            .where(*filters)
            .order_by(ScenarioItem.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    slugs = await _scenario_slugs(session, items)
    return {
        "total": total,
        "items": [
            _item_payload(item, slugs.get(item.scenario_id) if item.scenario_id else None)
            for item in items
        ],
    }


@router.get("/items/{item_id}")
async def get_item(
    item_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    item = await _item(session, item_id, user_id)
    scenario = (
        await session.scalar(select(Scenario).where(Scenario.id == item.scenario_id))
        if item.scenario_id
        else None
    )
    version = (
        await session.scalar(select(ScenarioVersion).where(ScenarioVersion.id == item.version_id))
        if item.version_id
        else None
    )
    return {
        "item": _item_payload(item, scenario.slug if scenario else None),
        "version": _version_payload(version) if version else None,
    }


@router.patch("/items/{item_id}")
async def patch_item(
    item_id: uuid.UUID,
    body: ScenarioItemPatch,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump(exclude_unset=True))
    item = await _item(session, item_id, user_id, lock=True)
    if item.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail="Item revision changed; reload before updating")
    _ensure_no_live_lease(item)
    if item.status == "completed" and body.status != "completed":
        raise HTTPException(status_code=409, detail="Completed items cannot be resumed")
    if body.status is not None:
        item.status = body.status
        if body.status == "completed":
            item.next_check_at = None
    if body.phase is not None:
        item.phase = body.phase
    if body.state is not None:
        item.state = body.state
    if body.working_plan is not None:
        if item.scenario_id is not None:
            raise HTTPException(status_code=409, detail="Bound items use the published scenario")
        item.working_plan = body.working_plan
    if "next_check_at" in body.model_fields_set and item.status != "completed":
        item.next_check_at = body.next_check_at
    item.revision += 1
    item.updated_at = _now()
    return _item_payload(item)


@router.post("/items/{item_id}/bind")
async def bind_item(
    item_id: uuid.UUID,
    body: ScenarioItemBind,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump())
    item = await _item(session, item_id, user_id, lock=True)
    if item.revision != body.expected_revision:
        raise HTTPException(status_code=409, detail="Item revision changed; reload before binding")
    _ensure_no_live_lease(item)
    if item.scenario_id is not None or item.status == "completed":
        raise HTTPException(status_code=409, detail="Only open standalone items can be bound")
    scenario = await _scenario(session, body.scenario_slug, user_id)
    if scenario.status != "active":
        raise HTTPException(status_code=409, detail="Scenario is not active")
    number = body.version or scenario.current_version
    if number is None:
        raise HTTPException(status_code=409, detail="Scenario has no published version")
    version = await _version(session, scenario, number, user_id)
    if version.published_at is None:
        raise HTTPException(status_code=409, detail="Scenario version has not been published")
    parameters = body.parameters if body.parameters is not None else item.parameters
    environment = body.environment if body.environment is not None else item.environment
    evaluation = _evaluate(
        ScenarioDefinition.model_validate(version.definition), parameters, environment
    )
    _require_routable(evaluation)
    item.scenario_id = scenario.id
    item.version_id = version.id
    item.parameters = evaluation["parameters"]
    item.environment = environment
    item.version_history = [
        *item.version_history,
        {"version": version.version, "at": _now().isoformat(), "reason": body.reason},
    ]
    item.revision += 1
    item.updated_at = _now()
    return {
        "item": _item_payload(item, scenario.slug),
        "version": _version_payload(version),
        "prior_working_plan": item.working_plan,
    }


@router.post("/items/{item_id}/upgrade")
async def upgrade_item(
    item_id: uuid.UUID,
    body: ScenarioItemUpgrade,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    require_safe_content(body.reason)
    item = await _item(session, item_id, user_id, lock=True)
    if item.revision != body.expected_revision:
        raise HTTPException(
            status_code=409, detail="Item revision changed; reload before upgrading"
        )
    _ensure_no_live_lease(item)
    if item.status == "completed":
        raise HTTPException(status_code=409, detail="Completed items cannot be upgraded")
    scenario = await session.scalar(select(Scenario).where(Scenario.id == item.scenario_id))
    if scenario is None or scenario.status != "active":
        raise HTTPException(status_code=409, detail="Scenario is unavailable")
    version = await _version(session, scenario, body.version, user_id)
    if version.published_at is None:
        raise HTTPException(status_code=409, detail="Scenario version has not been published")
    evaluation = _evaluate(
        ScenarioDefinition.model_validate(version.definition), item.parameters, item.environment
    )
    _require_routable(evaluation)
    item.version_id = version.id
    item.parameters = evaluation["parameters"]
    item.version_history = [
        *item.version_history,
        {"version": version.version, "at": _now().isoformat(), "reason": body.reason},
    ]
    item.revision += 1
    item.updated_at = _now()
    return {"item": _item_payload(item, scenario.slug), "version": _version_payload(version)}


@router.post("/items/{item_id}/claim")
async def claim_item(
    item_id: uuid.UUID,
    body: ScenarioClaim,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    item = await _item(session, item_id, user_id, lock=True)
    existing = await session.scalar(
        select(ScenarioRun).where(
            ScenarioRun.item_id == item_id,
            ScenarioRun.user_id == user_id,
            ScenarioRun.idempotency_key == body.idempotency_key,
        )
    )
    if existing is not None:
        return {"claimed": False, "run": _run_payload(existing)}
    if item.status != "active":
        raise HTTPException(status_code=409, detail="Item is not active")
    now = _now()
    if item.lease_token and item.lease_expires_at and item.lease_expires_at > now:
        raise HTTPException(status_code=409, detail="Item is already claimed")
    if item.lease_token:
        stale = await session.scalar(
            select(ScenarioRun).where(
                ScenarioRun.item_id == item_id,
                ScenarioRun.lease_token == item.lease_token,
                ScenarioRun.status == "running",
            )
        )
        if stale is not None:
            stale.status = "abandoned"
            stale.outcome = "failure"
            stale.observation = "unknown"
            stale.summary = "Execution lease expired without a result"
            stale.finished_at = now
        item.current_observation = "unknown"
        item.lease_token = None
        item.lease_expires_at = None
    if (
        item.mode == "continuous"
        and not body.force
        and (item.next_check_at is None or item.next_check_at > now)
    ):
        raise HTTPException(status_code=409, detail="Continuous item is not due")
    token = uuid.uuid4()
    expiry = now + timedelta(seconds=body.lease_seconds)
    run = ScenarioRun(
        user_id=user_id,
        item_id=item.id,
        version_id=item.version_id,
        idempotency_key=body.idempotency_key,
        lease_token=token,
        lease_expires_at=expiry,
    )
    item.lease_token = token
    item.lease_expires_at = expiry
    item.revision += 1
    item.updated_at = now
    session.add(run)
    await session.flush()
    version = await session.scalar(
        select(ScenarioVersion).where(ScenarioVersion.id == item.version_id)
    )
    if item.version_id is not None and version is None:
        raise HTTPException(status_code=409, detail="Pinned scenario version is missing")
    return {
        "claimed": True,
        "lease_token": str(token),
        "run": _run_payload(run),
        "item": _item_payload(item),
        "version": _version_payload(version) if version else None,
    }


@router.post("/items/{item_id}/runs/{run_id}/finish")
async def finish_run(
    item_id: uuid.UUID,
    run_id: uuid.UUID,
    body: ScenarioRunFinish,
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    _safe_json(body.model_dump())
    if (
        body.outcome == "success"
        and (body.observation == "alert" or body.action_required)
        and not body.event_key
    ):
        raise HTTPException(
            status_code=422, detail="Alert or action-required results need an event_key"
        )
    item = await _item(session, item_id, user_id, lock=True)
    run = await session.scalar(
        select(ScenarioRun).where(
            ScenarioRun.id == run_id, ScenarioRun.item_id == item_id, ScenarioRun.user_id == user_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Scenario run not found")
    if run.lease_token != body.lease_token:
        raise HTTPException(status_code=403, detail="Invalid execution lease")
    if run.status == "completed":
        return {"run": _run_payload(run), "item": _item_payload(item)}
    now = _now()
    if (
        run.status != "running"
        or item.lease_token != body.lease_token
        or run.lease_expires_at <= now
    ):
        raise HTTPException(status_code=409, detail="Execution lease is no longer valid")
    if item.mode == "continuous" and not body.complete_item and body.next_check_at is None:
        raise HTTPException(status_code=422, detail="Continuous items require next_check_at")
    previous = item.current_observation
    prior_run = item.last_run_at is not None
    run.status = "completed"
    run.outcome = body.outcome
    run.observation = body.observation
    run.summary = body.summary
    run.evidence = body.evidence
    run.event_key = body.event_key
    run.finished_at = now
    signal: str | None = None
    if body.complete_item:
        signal = "completed"
    elif body.outcome == "failure":
        signal = "check_failed"
    elif body.outcome == "success" and body.action_required:
        signal = "action_required"
    elif body.outcome == "success" and body.observation == "alert":
        signal = "alert"
    elif (
        body.outcome == "success"
        and body.observation == "normal"
        and previous in {"alert", "unknown"}
        and prior_run
    ):
        signal = "recovery"
    signal_key = f"{signal}:{body.event_key or ''}" if signal else None
    run.signal = signal
    run.notification_recommended = signal_key is not None and item.last_signal_key != signal_key
    if signal_key:
        item.last_signal_key = signal_key
    elif body.outcome == "success" and body.observation == "normal":
        item.last_signal_key = None
    item.current_observation = body.observation
    item.last_run_at = now
    if body.outcome == "success":
        item.last_success_at = now
        item.last_success_summary = body.summary
    if body.phase is not None:
        item.phase = body.phase
    if body.state is not None:
        item.state = body.state
    item.next_check_at = None if body.complete_item else body.next_check_at
    if body.complete_item:
        item.status = "completed"
    item.lease_token = None
    item.lease_expires_at = None
    item.revision += 1
    item.updated_at = now
    return {"run": _run_payload(run), "item": _item_payload(item)}


@router.get("/items/{item_id}/runs")
async def list_runs(
    item_id: uuid.UUID,
    limit: int = Query(30, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    user_id: str = Depends(verify_token),
) -> dict[str, Any]:
    await _item(session, item_id, user_id)
    runs = (
        await session.scalars(
            select(ScenarioRun)
            .where(ScenarioRun.item_id == item_id, ScenarioRun.user_id == user_id)
            .order_by(ScenarioRun.started_at.desc())
            .limit(limit)
        )
    ).all()
    return {"items": [_run_payload(run) for run in runs]}

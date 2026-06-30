"""SIBYL central memory API."""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.core.auth import require_auth, require_scopes
from app.core.db import get_db
from app.core.types import AuthContext
from app.schemas.key import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.schemas.memory_event import MemoryEventCreate, MemoryEventOut, SyncBatchIn, SyncBatchOut
from app.services.key_service import KeyService
from app.services.memory_service import MemoryService, event_to_dict

app = FastAPI(title="SIBYL", version="0.2.0", description="Shared project memory API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    _ = db  # ensures DB connectivity when configured
    return {"status": "ok", "service": "sibyl-api", "storage": "postgres"}


@app.get("/v1/whoami")
def whoami(auth: AuthContext = Depends(require_auth)) -> dict:
    return {
        "actor": auth.actor_name or "unknown",
        "organization": auth.organization_slug,
        "organization_id": auth.organization_id,
        "scopes": list(auth.scopes),
        "api": "sibyl",
        "bootstrap": auth.bootstrap,
    }


@app.post("/v1/memory-events", response_model=MemoryEventOut)
def create_memory_event(
    body: MemoryEventCreate,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> MemoryEventOut:
    require_scopes(auth, "memory:write")
    service = MemoryService(db, auth)
    try:
        event = service.create(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data = event_to_dict(event)
    return MemoryEventOut(**data)


@app.get("/v1/memory-events")
def list_memory_events(
    project: str | None = Query(None),
    days: int | None = Query(None, ge=1, le=365),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:read")
    service = MemoryService(db, auth)
    if days is not None:
        rows = service.recent(project=project, days=days, limit=limit)
    else:
        rows = service.list_events(project=project, limit=limit)
    return {"results": [event_to_dict(row) for row in rows]}


@app.get("/v1/memory-events/{event_id}")
def get_memory_event(
    event_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:read")
    service = MemoryService(db, auth)
    event = service.get(event_id)
    if event is None or event.organization_id != auth.organization_id:
        raise HTTPException(status_code=404, detail="not found")
    return event_to_dict(event)


@app.get("/v1/search")
def search(
    q: str = Query(..., min_length=1),
    project: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:read")
    service = MemoryService(db, auth)
    rows = service.search(q=q, project=project, limit=limit)
    return {"results": [event_to_dict(row) for row in rows]}


@app.get("/v1/projects/{project_slug}/context")
def project_context(
    project_slug: str,
    limit: int = Query(10, ge=1, le=50),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:read")
    service = MemoryService(db, auth)
    return service.project_context(project=project_slug, limit=limit)


@app.post("/v1/sync/batch", response_model=SyncBatchOut)
def sync_batch(
    body: SyncBatchIn,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SyncBatchOut:
    require_scopes(auth, "memory:sync", "memory:write")
    service = MemoryService(db, auth)
    synced: list[dict] = []
    failed: list[dict] = []
    for raw in body.events:
        local_id = raw.get("local_id", "")
        try:
            payload = {k: v for k, v in raw.items() if k != "local_id"}
            create = MemoryEventCreate(**payload)
            event = service.create(create, local_id=local_id or None)
            synced.append({"local_id": local_id, "remote_id": event.id, "status": "created"})
        except Exception as exc:  # noqa: BLE001 - batch sync reports per-row errors
            failed.append({"local_id": local_id, "error": str(exc)})
    return SyncBatchOut(synced=synced, failed=failed)


@app.post("/v1/api-keys", response_model=ApiKeyCreated)
def create_api_key(
    body: ApiKeyCreate,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> ApiKeyCreated:
    require_scopes(auth, "keys:manage", "admin")
    keys = KeyService(db)
    row, raw_key = keys.create_key(
        organization_id=auth.organization_id,
        name=body.name,
        actor_id=body.actor_id,
        scopes=body.scopes,
        prefix=body.prefix,
    )
    payload = keys.key_to_dict(row)
    return ApiKeyCreated(**payload, raw_key=raw_key)


@app.get("/v1/api-keys")
def list_api_keys(
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "keys:manage", "admin")
    keys = KeyService(db)
    return {"results": [keys.key_to_dict(row) for row in keys.list_keys(organization_id=auth.organization_id)]}


@app.post("/v1/api-keys/{key_id}/revoke", response_model=ApiKeyOut)
def revoke_api_key(
    key_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> ApiKeyOut:
    require_scopes(auth, "keys:manage", "admin")
    keys = KeyService(db)
    row = keys.revoke(key_id=key_id, organization_id=auth.organization_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return ApiKeyOut(**keys.key_to_dict(row))

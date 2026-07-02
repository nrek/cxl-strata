"""STRATA central memory API."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from app.core.auth import require_auth, require_scopes
from app.core.db import get_db
from app.core.types import AuthContext
from app.schemas.key import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.schemas.memory_event import MemoryEventCreate, MemoryEventOut, SyncBatchIn, SyncBatchOut
from app.schemas.shared_document import (
    SharedDocumentCreate,
    SharedDocumentImportBatchIn,
    SharedDocumentImportBatchOut,
    SharedDocumentOut,
)
from app.services.client_install import client_manifest, render_install_ps1, render_install_sh
from app.services.document_service import DocumentService, document_to_dict
from app.services.key_service import KeyService
from app.services.memory_service import MemoryService, event_to_dict

app = FastAPI(title="STRATA", version="0.3.0", description="Shared project memory API")
STATIC_DIR = Path(__file__).resolve().parent / "static"
ICONS_DIR = STATIC_DIR / "icons"
LANDING_PATH = STATIC_DIR / "index.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse)
def landing() -> HTMLResponse:
    if not LANDING_PATH.is_file():
        raise HTTPException(status_code=404, detail="landing not found")
    return HTMLResponse(LANDING_PATH.read_text(encoding="utf-8"))


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, str]:
    _ = db  # ensures DB connectivity when configured
    return {"status": "ok", "service": "strata-api", "storage": "postgres"}


@app.get("/install.sh", response_class=PlainTextResponse)
def install_sh() -> PlainTextResponse:
    return PlainTextResponse(
        content=render_install_sh(),
        media_type="text/x-sh",
        headers={"Content-Disposition": "inline; filename=install.sh"},
    )


@app.get("/assets/strata-logo.png", response_class=FileResponse)
def strata_logo() -> FileResponse:
    logo = STATIC_DIR / "strata-logo.png"
    if not logo.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(logo, media_type="image/png")


@app.get("/assets/strata_large.png", response_class=FileResponse)
def strata_large_logo() -> FileResponse:
    logo = STATIC_DIR / "strata_large.png"
    if not logo.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(logo, media_type="image/png")


@app.get("/favicon.ico", response_class=FileResponse)
def favicon() -> FileResponse:
    icon = ICONS_DIR / "favicon.ico"
    if not icon.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(icon, media_type="image/x-icon")


@app.get("/assets/icons/manifest.json", response_class=FileResponse)
def icons_manifest() -> FileResponse:
    manifest = ICONS_DIR / "manifest.json"
    if not manifest.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(manifest, media_type="application/manifest+json")


@app.get("/assets/icons/browserconfig.xml", response_class=FileResponse)
def icons_browserconfig() -> FileResponse:
    config = ICONS_DIR / "browserconfig.xml"
    if not config.is_file():
        raise HTTPException(status_code=404, detail="asset not found")
    return FileResponse(config, media_type="application/xml")


@app.get("/assets/icons/{filename}", response_class=FileResponse)
def icon_asset(filename: str) -> FileResponse:
    if filename in {"manifest.json", "browserconfig.xml"}:
        raise HTTPException(status_code=404, detail="asset not found")
    icon = ICONS_DIR / filename
    if not icon.is_file() or ICONS_DIR not in icon.resolve().parents:
        raise HTTPException(status_code=404, detail="asset not found")
    media = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(icon, media_type=media)


@app.get("/install.ps1", response_class=PlainTextResponse)
def install_ps1() -> PlainTextResponse:
    return PlainTextResponse(
        content=render_install_ps1(),
        media_type="text/plain",
        headers={"Content-Disposition": "inline; filename=install.ps1"},
    )


@app.get("/v1/client/manifest")
def get_client_manifest() -> dict:
    return client_manifest()


@app.get("/v1/whoami")
def whoami(auth: AuthContext = Depends(require_auth)) -> dict:
    return {
        "actor": auth.actor_name or "unknown",
        "organization": auth.organization_slug,
        "organization_id": auth.organization_id,
        "scopes": list(auth.scopes),
        "api": "strata",
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


@app.post("/v1/documents", response_model=SharedDocumentOut)
def create_document(
    body: SharedDocumentCreate,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SharedDocumentOut:
    require_scopes(auth, "memory:write")
    service = DocumentService(db, auth)
    try:
        row = service.upsert(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SharedDocumentOut(**document_to_dict(row))


@app.get("/v1/documents")
def list_documents(
    project: str | None = Query(None),
    kind: str | None = Query(None),
    author: str | None = Query(None),
    since: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    include_body: bool = Query(False),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:read")
    service = DocumentService(db, auth)
    rows = service.list_documents(
        project=project,
        kind=kind,
        author=author,
        since=since,
        limit=limit,
        offset=offset,
    )
    return {
        "results": [
            document_to_dict(r, include_body=include_body) for r in rows
        ]
    }


@app.get("/v1/documents/search")
def search_documents(
    q: str = Query(..., min_length=1),
    project: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:read")
    service = DocumentService(db, auth)
    rows = service.search(q, project=project, limit=limit)
    return {"results": [document_to_dict(r, include_body=False) for r in rows]}


@app.get("/v1/documents/{document_id}")
def get_document(
    document_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:read")
    service = DocumentService(db, auth)
    row = service.get(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return document_to_dict(row)


@app.delete("/v1/documents/{document_id}")
def delete_document(
    document_id: str,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> dict:
    require_scopes(auth, "memory:sync", "memory:write")
    service = DocumentService(db, auth)
    if not service.delete(document_id):
        raise HTTPException(status_code=404, detail="not found")
    return {"id": document_id, "deleted": True}


@app.post("/v1/documents/import-batch", response_model=SharedDocumentImportBatchOut)
def import_documents_batch(
    body: SharedDocumentImportBatchIn,
    auth: AuthContext = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SharedDocumentImportBatchOut:
    require_scopes(auth, "memory:sync", "memory:write")
    service = DocumentService(db, auth)
    synced, failed = service.import_batch(body.documents)
    return SharedDocumentImportBatchOut(synced=synced, failed=failed)

"""HTTP client for central STRATA API."""

from __future__ import annotations

from typing import Any

import httpx

from .local_store import load_api_key, load_config


def _client() -> httpx.Client:
    cfg = load_config()
    base = cfg.get("api_base_url", "http://127.0.0.1:8015").rstrip("/")
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {load_api_key()}"},
        timeout=30.0,
    )


def whoami() -> dict[str, Any]:
    with _client() as client:
        r = client.get("/v1/whoami")
        r.raise_for_status()
        return r.json()


def sync_batch(events: list[dict[str, Any]], workspace_id: str | None = None) -> dict[str, Any]:
    cfg = load_config()
    with _client() as client:
        r = client.post(
            "/v1/sync/batch",
            json={
                "workspace_id": workspace_id or cfg.get("workspace_id"),
                "events": events,
            },
        )
        r.raise_for_status()
        return r.json()


def search(q: str, project: str | None = None) -> dict[str, Any]:
    params: dict[str, str] = {"q": q}
    if project:
        params["project"] = project
    with _client() as client:
        r = client.get("/v1/search", params=params)
        r.raise_for_status()
        return r.json()


def list_documents(
    *,
    project: str | None = None,
    kind: str | None = None,
    author: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_body: bool = True,
) -> list[dict[str, Any]]:
    params: dict[str, str | int | bool] = {
        "limit": limit,
        "offset": offset,
        "include_body": include_body,
    }
    if project:
        params["project"] = project
    if kind:
        params["kind"] = kind
    if author:
        params["author"] = author
    if since:
        params["since"] = since
    with _client() as client:
        r = client.get("/v1/documents", params=params)
        r.raise_for_status()
        return r.json().get("results", [])


def search_documents(
    q: str, *, project: str | None = None, limit: int = 50, author: str | None = None
) -> dict[str, Any]:
    params: dict[str, str | int] = {"q": q, "limit": limit}
    if project:
        params["project"] = project
    if author:
        params["author"] = author
    with _client() as client:
        r = client.get("/v1/documents/search", params=params)
        r.raise_for_status()
        return r.json()


def documents_import_batch(documents: list[dict[str, Any]]) -> dict[str, Any]:
    with _client() as client:
        r = client.post("/v1/documents/import-batch", json={"documents": documents})
        r.raise_for_status()
        return r.json()


def delete_document(document_id: str) -> dict[str, Any]:
    with _client() as client:
        r = client.delete(f"/v1/documents/{document_id}")
        r.raise_for_status()
        return r.json()

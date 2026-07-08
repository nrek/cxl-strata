"""HTTP client for central STRATA API."""

from __future__ import annotations

from typing import Any

import httpx

from .local_store import load_api_key, load_config


def _client(*, timeout: float = 30.0) -> httpx.Client:
    cfg = load_config()
    base = cfg.get("api_base_url", "http://127.0.0.1:8015").rstrip("/")
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {load_api_key()}"},
        timeout=timeout,
    )


def whoami(*, timeout: float = 30.0) -> dict[str, Any]:
    with _client(timeout=timeout) as client:
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
    repo: str | None = None,
    kind: str | None = None,
    author: str | None = None,
    since: str | None = None,
    limit: int = 50,
    offset: int = 0,
    include_body: bool = True,
    include_comments: bool = False,
) -> list[dict[str, Any]]:
    params: dict[str, str | int | bool] = {
        "limit": limit,
        "offset": offset,
        "include_body": include_body,
        "include_comments": include_comments,
    }
    if project:
        params["project"] = project
    if repo:
        params["repo"] = repo
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
    q: str,
    *,
    project: str | None = None,
    repo: str | None = None,
    limit: int = 50,
    author: str | None = None,
) -> dict[str, Any]:
    params: dict[str, str | int] = {"q": q, "limit": limit}
    if project:
        params["project"] = project
    if repo:
        params["repo"] = repo
    if author:
        params["author"] = author
    with _client() as client:
        r = client.get("/v1/documents/search", params=params)
        r.raise_for_status()
        return r.json()


def create_document_comment(
    document_id: str,
    body: str,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"body": body}
    if author_name:
        payload["author_name"] = author_name
    if author_email:
        payload["author_email"] = author_email
    if created_at:
        payload["created_at"] = created_at
    with _client() as client:
        r = client.post(f"/v1/documents/{document_id}/comments", json=payload)
        r.raise_for_status()
        return r.json()


def list_document_comments(document_id: str) -> list[dict[str, Any]]:
    with _client() as client:
        r = client.get(f"/v1/documents/{document_id}/comments")
        r.raise_for_status()
        return r.json().get("results", [])


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

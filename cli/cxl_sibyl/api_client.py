"""HTTP client for central SIBYL API."""

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

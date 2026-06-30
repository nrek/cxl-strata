from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class AuthContext:
    token: str
    organization_id: str
    organization_slug: str
    actor_id: str | None
    actor_name: str | None
    scopes: tuple[str, ...]
    api_key_id: str | None = None
    bootstrap: bool = False


def dump_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def load_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    data = json.loads(raw)
    return [str(item) for item in data]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)

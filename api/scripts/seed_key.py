#!/usr/bin/env python3
"""Create organization, actor, and hashed API key for SIBYL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.services.key_service import KeyService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed SIBYL org/actor and API key")
    parser.add_argument("--org-slug", default=settings.bootstrap_org_slug)
    parser.add_argument("--org-name", default=settings.bootstrap_org_name)
    parser.add_argument("--actor-name", default="admin")
    parser.add_argument("--actor-email", default=None)
    parser.add_argument("--key-name", default="bootstrap-admin")
    parser.add_argument("--prefix", default="sibyl_dev_", choices=["sibyl_dev_", "sibyl_live_"])
    args = parser.parse_args()

    db = SessionLocal()
    try:
        keys = KeyService(db)
        org = keys.ensure_organization(args.org_slug, args.org_name)
        actor = keys.ensure_actor(
            organization_id=org.id,
            name=args.actor_name,
            email=args.actor_email,
        )
        row, raw_key = keys.create_key(
            organization_id=org.id,
            actor_id=actor.id,
            name=args.key_name,
            scopes=[
                "memory:read",
                "memory:write",
                "memory:sync",
                "keys:manage",
                "admin",
            ],
            prefix=args.prefix,
        )
    finally:
        db.close()

    print("SIBYL seed complete")
    print(f"  organization: {org.slug} ({org.id})")
    print(f"  actor:        {actor.name} ({actor.id})")
    print(f"  api_key_id:   {row.id}")
    print(f"  key_prefix:   {row.key_prefix}")
    print("")
    print("Save this access token now (shown once):")
    print(raw_key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

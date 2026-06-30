"""API key creation, verification, and revocation."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_api_key, hash_api_key, key_prefix_for
from app.core.types import AuthContext, dump_json, load_json_list, utcnow
from app.models import Actor, ApiKey, Organization


DEFAULT_SCOPES = ("memory:read", "memory:write", "memory:sync")
BOOTSTRAP_SCOPES = DEFAULT_SCOPES + ("keys:manage", "admin")


class KeyService:
    def __init__(self, db: Session):
        self.db = db

    def authenticate(self, raw_token: str) -> AuthContext | None:
        prefix = key_prefix_for(raw_token)
        stmt = select(ApiKey).where(
            ApiKey.key_prefix == prefix,
            ApiKey.is_active.is_(True),
            ApiKey.revoked_at.is_(None),
        )
        for row in self.db.scalars(stmt):
            if hash_api_key(raw_token, settings.api_key_pepper) == row.key_hash:
                row.last_used_at = utcnow()
                self.db.commit()
                org = self.db.get(Organization, row.organization_id)
                actor = self.db.get(Actor, row.actor_id) if row.actor_id else None
                return AuthContext(
                    token=raw_token,
                    organization_id=row.organization_id,
                    organization_slug=org.slug if org else "unknown",
                    actor_id=row.actor_id,
                    actor_name=actor.name if actor else None,
                    scopes=tuple(load_json_list(row.scopes_json)),
                    api_key_id=row.id,
                )
        return None

    def bootstrap_context(self, raw_token: str) -> AuthContext | None:
        if raw_token not in settings.allowed_api_keys():
            return None
        org = self.ensure_organization(settings.bootstrap_org_slug, settings.bootstrap_org_name)
        return AuthContext(
            token=raw_token,
            organization_id=org.id,
            organization_slug=org.slug,
            actor_id=None,
            actor_name=None,
            scopes=BOOTSTRAP_SCOPES,
            bootstrap=True,
        )

    def create_key(
        self,
        *,
        organization_id: str,
        name: str,
        actor_id: str | None = None,
        scopes: list[str] | None = None,
        prefix: str = "sibyl_dev_",
    ) -> tuple[ApiKey, str]:
        raw_key, key_prefix, key_hash = generate_api_key(prefix=prefix, pepper=settings.api_key_pepper)
        row = ApiKey(
            organization_id=organization_id,
            actor_id=actor_id,
            name=name,
            key_prefix=key_prefix,
            key_hash=key_hash,
            scopes_json=dump_json(scopes or list(DEFAULT_SCOPES)),
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row, raw_key

    def list_keys(self, *, organization_id: str) -> list[ApiKey]:
        stmt = (
            select(ApiKey)
            .where(ApiKey.organization_id == organization_id)
            .order_by(ApiKey.created_at.desc())
        )
        return list(self.db.scalars(stmt))

    def revoke(self, *, key_id: str, organization_id: str) -> ApiKey | None:
        row = self.db.get(ApiKey, key_id)
        if row is None or row.organization_id != organization_id:
            return None
        row.is_active = False
        row.revoked_at = utcnow()
        self.db.commit()
        self.db.refresh(row)
        return row

    def ensure_organization(self, slug: str, name: str | None = None) -> Organization:
        stmt = select(Organization).where(Organization.slug == slug)
        org = self.db.scalar(stmt)
        if org:
            return org
        org = Organization(slug=slug, name=name or slug)
        self.db.add(org)
        self.db.commit()
        self.db.refresh(org)
        return org

    def ensure_actor(
        self,
        *,
        organization_id: str,
        name: str,
        email: str | None = None,
    ) -> Actor:
        stmt = select(Actor).where(
            Actor.organization_id == organization_id,
            Actor.name == name,
        )
        actor = self.db.scalar(stmt)
        if actor:
            return actor
        actor = Actor(organization_id=organization_id, name=name, email=email)
        self.db.add(actor)
        self.db.commit()
        self.db.refresh(actor)
        return actor

    def key_to_dict(self, row: ApiKey) -> dict:
        return {
            "id": row.id,
            "organization_id": row.organization_id,
            "actor_id": row.actor_id,
            "name": row.name,
            "key_prefix": row.key_prefix,
            "scopes": load_json_list(row.scopes_json),
            "is_active": row.is_active,
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
        }

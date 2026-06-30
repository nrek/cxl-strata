"""Access token generation and verification."""

from __future__ import annotations

import hashlib
import secrets


def hash_api_key(raw_key: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{raw_key}".encode("utf-8")).hexdigest()


def generate_api_key(*, prefix: str = "sibyl_dev_", pepper: str) -> tuple[str, str, str]:
    """Return (raw_key, key_prefix, key_hash). Raw key is shown once at creation."""
    secret = secrets.token_urlsafe(32)
    raw_key = f"{prefix}{secret}"
    key_prefix = raw_key[:20]
    return raw_key, key_prefix, hash_api_key(raw_key, pepper)


def key_prefix_for(raw_key: str) -> str:
    return raw_key[:20]

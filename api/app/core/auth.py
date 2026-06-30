"""Bearer access-token auth backed by hashed API keys in Postgres."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.types import AuthContext
from app.services.key_service import KeyService

_bearer = HTTPBearer(auto_error=False)


async def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AuthContext:
    if creds is None or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer access token",
        )
    token = creds.credentials.strip()
    if not token.startswith(("strata_live_", "strata_dev_")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token prefix",
        )

    keys = KeyService(db)
    auth = keys.authenticate(token) or keys.bootstrap_context(token)
    if auth is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown access token",
        )
    return auth


def require_scopes(auth: AuthContext, *needed: str) -> None:
    if "admin" in auth.scopes:
        return
    missing = [scope for scope in needed if scope not in auth.scopes]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing scopes: {', '.join(missing)}",
        )

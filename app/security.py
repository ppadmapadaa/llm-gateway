import hashlib
import secrets

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_session
from app.models import ApiKey


bearer = HTTPBearer(auto_error=False)


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def get_current_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> ApiKey:
    if credentials is None:
        raise HTTPException(status_code=401, detail="API key required")

    key_hash = hash_api_key(credentials.credentials)
    api_key = session.scalar(
        select(ApiKey).where(
            ApiKey.key_hash == key_hash,
            ApiKey.revoked.is_(False),
        )
    )

    if api_key is None:
        raise HTTPException(status_code=401, detail="Invalid or revoked API key")

    return api_key
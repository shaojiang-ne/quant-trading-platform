import os
from fastapi import Header, HTTPException


def verify_api_key(x_api_key: str = Header(default=None)) -> str | None:
    from core.config import settings
    effective_key = settings.auth.get_effective_api_key()
    if not effective_key:
        return None
    if x_api_key != effective_key:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return x_api_key


def verify_ws_api_key(apikey: str) -> bool:
    from core.config import settings
    effective_key = settings.auth.get_effective_api_key()
    if not effective_key:
        return True
    return apikey == effective_key
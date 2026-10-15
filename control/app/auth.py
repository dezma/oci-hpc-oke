from __future__ import annotations

import hmac
import os
from pathlib import Path
from fastapi import Header, HTTPException

from .config import load_settings


def _expected_token() -> str:
    settings = load_settings()
    if settings.mode == "demo":
        return os.environ.get("HPC_CONTROL_DEMO_TOKEN", "demo")
    token_file = Path(os.environ.get("HPC_CONTROL_TOKEN_FILE", "/etc/oke-rdma-control/admin.token"))
    try:
        return token_file.read_text().strip()
    except OSError as exc:
        raise HTTPException(status_code=503, detail="Control Center authentication is not initialized") from exc


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    supplied = authorization[7:].strip()
    expected = _expected_token()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid token")

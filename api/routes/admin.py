"""POST/GET /api/v1/telegram/admin/* — admin REST endpoints."""

import os
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from services import storage

router = APIRouter()

_BOT_SECRET = os.getenv("BOT_SECRET", "")
_ADMIN_KEY = os.getenv("ADMIN_API_KEY", "")


# ── Auth ──────────────────────────────────────────────────────────────────────

async def admin_auth(x_bot_secret: str = Header(default="")) -> None:
    """Accept X-Bot-Secret header OR no-auth-configured (open dev mode)."""
    if not _BOT_SECRET and not _ADMIN_KEY:
        return  # no auth configured — open
    if _BOT_SECRET and x_bot_secret == _BOT_SECRET:
        return
    raise HTTPException(status_code=403, detail="Forbidden")


def _check_key(key: str) -> None:
    """Legacy body-api_key check for text-command callers."""
    if _ADMIN_KEY and key != _ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Schemas ───────────────────────────────────────────────────────────────────

class AdminKeyRequest(BaseModel):
    api_key: str = ""


class AddUserRequest(AdminKeyRequest):
    user_id: int


class AiConfigRequest(BaseModel):
    url: str
    model: str
    key: str = ""
    enabled: bool = True


# ── User management (body-key auth for backward compat) ───────────────────────

@router.post("/adduser")
async def add_admin_user(req: AddUserRequest, _: None = Depends(admin_auth)):
    storage.add_admin_user(req.user_id)
    return {"ok": True, "user_id": req.user_id}


@router.post("/removeuser")
async def remove_admin_user(req: AddUserRequest, _: None = Depends(admin_auth)):
    storage.remove_admin_user(req.user_id)
    return {"ok": True, "user_id": req.user_id}


# ── Scalate overview ──────────────────────────────────────────────────────────

@router.get("/scalate")
async def list_all_scalate(_: None = Depends(admin_auth)):
    data = storage.get_all()
    return {"ok": True, "scalate": list(data["scalate"].values())}


# ── AI config ─────────────────────────────────────────────────────────────────

@router.get("/ai-config")
async def get_ai_config(_: None = Depends(admin_auth)):
    cfg = storage.get_ai_config()
    # Never expose the full key — mask it
    masked = dict(cfg)
    if masked.get("key"):
        masked["key_set"] = True
        masked["key"] = ""  # client sends back empty to keep existing key
    else:
        masked["key_set"] = False
    return {"ok": True, "config": masked}


@router.post("/ai-config")
async def set_ai_config(req: AiConfigRequest, _: None = Depends(admin_auth)):
    current = storage.get_ai_config()
    new_key = req.key if req.key else current.get("key", "")
    storage.save_ai_config({
        "url": req.url,
        "model": req.model,
        "key": new_key,
        "enabled": req.enabled,
    })
    return {"ok": True}

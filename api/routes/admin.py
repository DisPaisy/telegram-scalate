"""POST /api/v1/telegram/admin/* — admin REST endpoints."""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services import storage

router = APIRouter()

_ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")


def _check_key(key: str) -> None:
    if _ADMIN_API_KEY and key != _ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")


class AdminKeyRequest(BaseModel):
    api_key: str = ""


class AddUserRequest(AdminKeyRequest):
    user_id: int


@router.post("/adduser")
async def add_admin_user(req: AddUserRequest):
    _check_key(req.api_key)
    storage.add_admin_user(req.user_id)
    return {"ok": True, "user_id": req.user_id}


@router.post("/removeuser")
async def remove_admin_user(req: AddUserRequest):
    _check_key(req.api_key)
    storage.remove_admin_user(req.user_id)
    return {"ok": True, "user_id": req.user_id}


@router.get("/scalate")
async def list_all_scalate(api_key: str = ""):
    _check_key(api_key)
    data = storage.get_all()
    return {"ok": True, "scalate": list(data["scalate"].values())}

"""Mini App HTML pages served under /api/v1/telegram/app/."""

import os
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_TEMPLATES = Path(__file__).parent.parent / "templates"
_BOT_SECRET = os.getenv("BOT_SECRET", "")


@router.get("/nuova", response_class=HTMLResponse)
async def mini_app_nuova() -> HTMLResponse:
    return HTMLResponse(content=(_TEMPLATES / "nuova.html").read_text(encoding="utf-8"))


@router.get("/admin", response_class=HTMLResponse)
async def mini_app_admin() -> HTMLResponse:
    html = (_TEMPLATES / "admin.html").read_text(encoding="utf-8")
    html = html.replace("__BOT_SECRET__", _BOT_SECRET)
    return HTMLResponse(content=html)


@router.get("/configure-step", response_class=HTMLResponse)
async def mini_app_configure_step() -> HTMLResponse:
    return HTMLResponse(content=(_TEMPLATES / "configure-step.html").read_text(encoding="utf-8"))


@router.get("/edit-scalata", response_class=HTMLResponse)
async def mini_app_edit_scalata() -> HTMLResponse:
    return HTMLResponse(content=(_TEMPLATES / "edit-scalata.html").read_text(encoding="utf-8"))

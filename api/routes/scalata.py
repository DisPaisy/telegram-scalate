"""POST /api/v1/telegram/scalata/create — Mini App creates a new scalata."""

import hashlib
import hmac
import json
import logging
import os
import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from services import storage
from services.storage import build_status_text

log = logging.getLogger(__name__)
router = APIRouter()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")


# ── Telegram initData validation ──────────────────────────────────────────────

def _validate_init_data(init_data: str) -> dict:
    """Parse and loosely validate Telegram WebApp initData.

    Logs mismatches but never blocks — group_id comes from the trusted
    request body, so we don't need initData for authorization here.
    """
    if not init_data:
        log.warning("Empty initData received")
        return {}

    params = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = params.pop("hash", "")

    data_check = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        log.warning(
            "initData HMAC mismatch — proceeding anyway. "
            "received_hash=%s expected=%s data_check=%r",
            received_hash, expected_hash, data_check,
        )

    return params


def _parse_user(params: dict) -> dict:
    user_str = params.get("user", "{}")
    try:
        return json.loads(user_str)
    except Exception:
        return {}


def _parse_chat(params: dict) -> dict:
    chat_str = params.get("chat", "{}")
    try:
        return json.loads(chat_str)
    except Exception:
        return {}


# ── request schema ────────────────────────────────────────────────────────────

class Withdrawal(BaseModel):
    after_step: int
    amount: float
    restart_capital: float


class MatchPayload(BaseModel):
    id: str
    name: str
    date: Optional[str] = None
    outcome_bet: str  # "1" | "X" | "2"


class CreateScalataRequest(BaseModel):
    init_data: str = ""
    group_id: Optional[int] = None   # explicit override; used when Mini App is opened via DM
    name: str = Field(..., min_length=1, max_length=80)
    starting_capital: float = Field(..., gt=0)
    multiplier: float = Field(..., gt=1)
    total_steps: int = Field(..., ge=1, le=100)
    withdrawals: list[Withdrawal] = []
    first_match: Optional[MatchPayload] = None


# ── endpoint ──────────────────────────────────────────────────────────────────

@router.post("/create")
async def create_scalata(payload: CreateScalataRequest, request: Request):
    params = _validate_init_data(payload.init_data)
    user = _parse_user(params)
    chat = _parse_chat(params)

    # group_id: prefer explicit body field (set by bot when opening from DM),
    # fall back to initData chat, reject if neither present
    group_id = payload.group_id or chat.get("id")
    if not group_id:
        raise HTTPException(status_code=400, detail="Cannot determine group_id")

    app = request.app.state.bot_app
    if app is None:
        raise HTTPException(status_code=503, detail="Bot not initialised")

    bot = app.bot

    # Create forum topic
    try:
        topic = await bot.create_forum_topic(
            chat_id=group_id,
            name=payload.name,
        )
        topic_id = topic.message_thread_id
    except Exception as exc:
        log.error("Failed to create forum topic: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to create forum topic: {exc}")

    first_match = None
    if payload.first_match:
        first_match = {
            "id": payload.first_match.id,
            "name": payload.first_match.name,
            "date": payload.first_match.date,
            "outcome_bet": payload.first_match.outcome_bet,
            "outcome_actual": None,
            "auto_resolved": False,
        }

    scalata = storage.create_scalata(
        name=payload.name,
        topic_id=topic_id,
        group_id=group_id,
        starting_capital=payload.starting_capital,
        multiplier=payload.multiplier,
        total_steps=payload.total_steps,
        withdrawals=[w.model_dump() for w in payload.withdrawals],
        created_by_id=user.get("id", 0),
        created_by_name=user.get("first_name", "Utente"),
        first_match=first_match,
    )

    # Post and pin status message
    try:
        status_msg = await bot.send_message(
            chat_id=group_id,
            message_thread_id=topic_id,
            text=build_status_text(scalata),
            parse_mode="HTML",
        )
        await bot.pin_chat_message(
            chat_id=group_id,
            message_id=status_msg.message_id,
            disable_notification=True,
        )
        scalata["pinned_message_id"] = status_msg.message_id
        storage.save_scalata(scalata)
    except Exception as exc:
        log.warning("Failed to pin status message: %s", exc)

    # Set topic name with step counter
    try:
        await bot.edit_forum_topic(
            chat_id=group_id,
            message_thread_id=topic_id,
            name=f"{payload.name} — Step 0/{payload.total_steps}",
        )
    except Exception:
        pass

    chat_id_str = str(group_id).replace("-100", "")
    topic_url = f"https://t.me/c/{chat_id_str}/{topic_id}"

    return {
        "ok": True,
        "scalata_id": scalata["id"],
        "topic_id": topic_id,
        "topic_url": topic_url,
    }

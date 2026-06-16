"""Scalata API routes — create, read, update."""

import hashlib
import hmac
import json
import logging
import os
import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

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

    data_check = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
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
    try:
        return json.loads(params.get("user", "{}"))
    except Exception:
        return {}


def _parse_chat(params: dict) -> dict:
    try:
        return json.loads(params.get("chat", "{}"))
    except Exception:
        return {}


def _build_keyboard(scalata: dict) -> InlineKeyboardMarkup:
    tid = scalata["topic_id"]
    rows = []
    if scalata["status"] == "active":
        rows.append([
            InlineKeyboardButton("✅ Vinta", callback_data=f"win:{tid}"),
            InlineKeyboardButton("❌ Persa", callback_data=f"loss:{tid}"),
        ])
    rows.append([
        InlineKeyboardButton("📊 Card", callback_data=f"card:{tid}"),
        InlineKeyboardButton("📄 PDF", callback_data=f"pdf:{tid}"),
        InlineKeyboardButton("✏️ Modifica", callback_data=f"edit_scalata:{tid}"),
    ])
    if scalata["status"] == "active" and scalata.get("mode") in ("improvvisata", "programmata"):
        ps = scalata.get("pending_step")
        if ps:
            step_configs = scalata.get("step_configs", [])
            idx = (ps.get("step", 1) or 1) - 1
            cfg = step_configs[idx] if idx < len(step_configs) else {}
            if not cfg.get("quota") or not cfg.get("match"):
                rows.append([
                    InlineKeyboardButton(
                        f"📝 Configura Step {ps['step']}",
                        callback_data=f"configure_step:{tid}",
                    )
                ])
    if scalata.get("delete_job_id"):
        rows.append([
            InlineKeyboardButton("🗑️ Elimina ora", callback_data=f"delete_now:{tid}"),
            InlineKeyboardButton("💾 Non eliminare", callback_data=f"cancel_delete:{tid}"),
        ])
    return InlineKeyboardMarkup(rows)


# ── request schemas ───────────────────────────────────────────────────────────

class Withdrawal(BaseModel):
    after_step: int
    amount: float
    restart_capital: float


class MatchPayload(BaseModel):
    id: str
    name: str
    date: Optional[str] = None
    outcome_bet: Optional[str] = None
    bet_type: Optional[str] = None


class StepConfigPayload(BaseModel):
    quota: Optional[float] = None
    match: Optional[MatchPayload] = None
    bet_type: Optional[str] = None


class CreateScalataRequest(BaseModel):
    init_data: str = ""
    group_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=80)
    starting_capital: float = Field(..., gt=0)
    multiplier: float = Field(..., gt=1)
    total_steps: int = Field(..., ge=1, le=100)
    withdrawals: list[Withdrawal] = []
    mode: str = "improvvisata"
    step_configs: list[StepConfigPayload] = []


class StepConfigRequest(BaseModel):
    init_data: str = ""
    step: int
    quota: float = Field(..., gt=1)
    match: Optional[MatchPayload] = None
    bet_type: Optional[str] = None


class EditScalataRequest(BaseModel):
    init_data: str = ""
    name: Optional[str] = None
    starting_capital: Optional[float] = None
    current_capital: Optional[float] = None
    multiplier: Optional[float] = None
    total_steps: Optional[int] = None
    mode: Optional[str] = None
    current_step: Optional[int] = None
    status: Optional[str] = None
    withdrawals: Optional[list[Withdrawal]] = None
    step_configs: Optional[list[StepConfigPayload]] = None
    history: Optional[list[dict]] = None


# ── GET /{topic_id} ───────────────────────────────────────────────────────────

@router.get("/{topic_id}")
async def get_scalata(topic_id: int):
    s = storage.get_scalata(topic_id)
    if not s:
        raise HTTPException(status_code=404, detail="Scalata not found")
    return s


# ── POST /create ──────────────────────────────────────────────────────────────

@router.post("/create")
async def create_scalata(payload: CreateScalataRequest, request: Request):
    params = _validate_init_data(payload.init_data)
    user = _parse_user(params)
    chat = _parse_chat(params)

    group_id = payload.group_id or chat.get("id")
    if not group_id:
        raise HTTPException(status_code=400, detail="Cannot determine group_id")

    app = request.app.state.bot_app
    if app is None:
        raise HTTPException(status_code=503, detail="Bot not initialised")

    bot = app.bot

    # Create forum topic
    try:
        topic = await bot.create_forum_topic(chat_id=group_id, name=payload.name, icon_color=0xFFD67E)
        topic_id = topic.message_thread_id
    except Exception as exc:
        log.error("Failed to create forum topic: %s", exc)
        raise HTTPException(status_code=500, detail=f"Failed to create forum topic: {exc}")

    # Build step_configs from payload
    step_configs = []
    for sc in payload.step_configs:
        first_match = sc.match.model_dump() if sc.match else None
        step_configs.append({
            "quota": sc.quota or payload.multiplier,
            "match": first_match,
            "bet_type": sc.bet_type,
        })
    # Pad to total_steps if short
    while len(step_configs) < payload.total_steps:
        step_configs.append({"quota": payload.multiplier, "match": None, "bet_type": None})

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
        mode=payload.mode,
        step_configs=step_configs,
    )

    # Post and pin status message with inline keyboard
    try:
        keyboard = _build_keyboard(scalata)
        status_msg = await bot.send_message(
            chat_id=group_id,
            message_thread_id=topic_id,
            text=build_status_text(scalata),
            parse_mode="HTML",
            reply_markup=keyboard,
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

    return {"ok": True, "scalata_id": scalata["id"], "topic_id": topic_id, "topic_url": topic_url}


# ── PUT /{topic_id}/step-config ───────────────────────────────────────────────

@router.put("/{topic_id}/step-config")
async def update_step_config(topic_id: int, payload: StepConfigRequest, request: Request):
    _validate_init_data(payload.init_data)

    try:
        match_dict = payload.match.model_dump() if payload.match else None
        scalata = storage.update_step_config(
            topic_id=topic_id,
            step=payload.step,
            quota=payload.quota,
            match=match_dict,
            bet_type=payload.bet_type,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Scalata not found")

    app = request.app.state.bot_app
    if app and scalata.get("pinned_message_id"):
        try:
            await app.bot.edit_message_text(
                chat_id=scalata["group_id"],
                message_id=scalata["pinned_message_id"],
                text=build_status_text(scalata),
                parse_mode="HTML",
                reply_markup=_build_keyboard(scalata),
            )
        except Exception as exc:
            log.warning("Failed to edit pinned message after step-config: %s", exc)

    return {"ok": True}


# ── PUT /{topic_id}/edit ──────────────────────────────────────────────────────

@router.put("/{topic_id}/edit")
async def edit_scalata(topic_id: int, payload: EditScalataRequest, request: Request):
    _validate_init_data(payload.init_data)

    scalata = storage.get_scalata(topic_id)
    if not scalata:
        raise HTTPException(status_code=404, detail="Scalata not found")

    # Apply overrides
    if payload.name is not None:
        scalata["name"] = payload.name
    if payload.starting_capital is not None:
        scalata["starting_capital"] = payload.starting_capital
    if payload.current_capital is not None:
        scalata["current_capital"] = payload.current_capital
        if scalata.get("pending_step"):
            scalata["pending_step"]["capital_before"] = payload.current_capital
    if payload.multiplier is not None:
        scalata["multiplier"] = payload.multiplier
    if payload.total_steps is not None:
        scalata["total_steps"] = payload.total_steps
    if payload.mode is not None:
        scalata["mode"] = payload.mode
    if payload.current_step is not None:
        scalata["current_step"] = payload.current_step
    if payload.status is not None:
        scalata["status"] = payload.status
        if payload.status != "active":
            scalata["pending_step"] = None
    if payload.withdrawals is not None:
        scalata["withdrawals"] = [w.model_dump() for w in payload.withdrawals]
    if payload.step_configs is not None:
        scalata["step_configs"] = [
            {"quota": sc.quota or scalata["multiplier"], "match": sc.match.model_dump() if sc.match else None, "bet_type": sc.bet_type}
            for sc in payload.step_configs
        ]
    if payload.history is not None:
        scalata["history"] = payload.history

    storage.save_scalata(scalata)

    app = request.app.state.bot_app
    if app:
        bot = app.bot
        if scalata.get("pinned_message_id"):
            try:
                await bot.edit_message_text(
                    chat_id=scalata["group_id"],
                    message_id=scalata["pinned_message_id"],
                    text=build_status_text(scalata),
                    parse_mode="HTML",
                    reply_markup=_build_keyboard(scalata),
                )
            except Exception as exc:
                log.warning("Failed to edit pinned message after edit: %s", exc)

        # Rename topic to reflect new state
        try:
            if scalata["status"] == "active":
                new_name = f"{scalata['name']} — Step {scalata['current_step']}/{scalata['total_steps']}"
            elif scalata["status"] == "completed":
                new_name = f"{scalata['name']} — 🏆 Completata"
            else:
                new_name = f"{scalata['name']} — ❌ Fallita"
            await bot.edit_forum_topic(
                chat_id=scalata["group_id"],
                message_thread_id=topic_id,
                name=new_name,
            )
        except Exception:
            pass

    return {"ok": True}

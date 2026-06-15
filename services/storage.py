"""Atomic JSON persistence and scalata business logic."""

import json
import os
import threading
from pathlib import Path
from typing import Optional
import uuid

DATA_FILE = Path("data/data.json")
_lock = threading.Lock()


# ── low-level I/O ─────────────────────────────────────────────────────────────

def _read() -> dict:
    if not DATA_FILE.exists():
        return {"scalate": {}, "admin_users": []}
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False, default=str)
    tmp.rename(DATA_FILE)


# ── CRUD helpers ──────────────────────────────────────────────────────────────

def get_all() -> dict:
    with _lock:
        return _read()


def get_scalata(topic_id: int) -> Optional[dict]:
    with _lock:
        return _read()["scalate"].get(str(topic_id))


def save_scalata(scalata: dict) -> None:
    with _lock:
        data = _read()
        data["scalate"][str(scalata["topic_id"])] = scalata
        _write(data)


def delete_scalata(topic_id: int) -> None:
    with _lock:
        data = _read()
        data["scalate"].pop(str(topic_id), None)
        _write(data)


def get_scalate_by_group(group_id: int) -> list[dict]:
    with _lock:
        return [
            s for s in _read()["scalate"].values()
            if s["group_id"] == group_id
        ]


def get_active_scalate() -> list[dict]:
    with _lock:
        return [
            s for s in _read()["scalate"].values()
            if s["status"] == "active"
        ]


# ── admin users ───────────────────────────────────────────────────────────────

def get_admin_users() -> list[int]:
    with _lock:
        return _read().get("admin_users", [])


def is_admin(user_id: int) -> bool:
    return user_id in get_admin_users()


def add_admin_user(user_id: int) -> None:
    with _lock:
        data = _read()
        if user_id not in data["admin_users"]:
            data["admin_users"].append(user_id)
        _write(data)


def remove_admin_user(user_id: int) -> None:
    with _lock:
        data = _read()
        data["admin_users"] = [u for u in data["admin_users"] if u != user_id]
        _write(data)


# ── Known groups ──────────────────────────────────────────────────────────────

def get_groups() -> dict[str, dict]:
    with _lock:
        return _read().get("groups", {})


def save_group(group_id: int, name: str) -> None:
    with _lock:
        data = _read()
        data.setdefault("groups", {})[str(group_id)] = {"id": group_id, "name": name}
        _write(data)


# ── AI config ─────────────────────────────────────────────────────────────────

_AI_CONFIG_DEFAULT: dict = {
    "url": "https://ai.hackclub.com/proxy/v1/chat/completions",
    "model": "qwen/qwen3-32b",
    "key": "",
    "enabled": True,
}


def get_ai_config() -> dict:
    with _lock:
        data = _read()
        return {**_AI_CONFIG_DEFAULT, **data.get("ai_config", {})}


def save_ai_config(config: dict) -> None:
    with _lock:
        data = _read()
        data["ai_config"] = config
        _write(data)


# ── ID generation ─────────────────────────────────────────────────────────────

def new_id() -> str:
    return "c" + uuid.uuid4().hex[:24]


# ── Scalata business logic ────────────────────────────────────────────────────

def compute_bet(capital: float, multiplier: float) -> float:
    """Amount to stake for the current step."""
    return round(capital * (1 - 1 / multiplier), 2)


def build_status_text(s: dict) -> str:
    """Format the pinned status message text."""
    icon = "📊" if s["status"] == "active" else ("🏆" if s["status"] == "completed" else "❌")
    lines = [
        f"{icon} <b>{s['name']}</b>",
        "━━━━━━━━━━━━━━━",
        f"Step: <b>{s['current_step']}/{s['total_steps']}</b>",
        f"Capitale: <b>€{s['current_capital']:.2f}</b>",
    ]
    if s["status"] == "active" and s.get("pending_step"):
        bet = compute_bet(s["current_capital"], s["multiplier"])
        lines.append(f"Prossima puntata: <b>€{bet:.2f}</b>")
        ps = s["pending_step"]
        if ps.get("match") and ps["match"].get("name"):
            match = ps["match"]
            outcome_label = {"1": "Casa", "X": "Pareggio", "2": "Ospite"}.get(
                match.get("outcome_bet", ""), match.get("outcome_bet", "")
            )
            lines.append(f"Match: {match['name']} → <b>{outcome_label}</b>")

    lines.append("")
    lines.append("<b>Storico:</b>")
    for h in s.get("history", []):
        res_icon = "✅" if h["result"] == "win" else "❌"
        match_str = ""
        if h.get("match") and h["match"].get("name"):
            match_str = f" — {h['match']['name']}"
        lines.append(
            f"{res_icon} Step {h['step']}{match_str} → €{h['capital_after']:.2f}"
        )

    if s.get("pending_step"):
        ps = s["pending_step"]
        match_str = ""
        if ps.get("match") and ps["match"].get("name"):
            match_str = f" — {ps['match']['name']}"
        lines.append(f"⏳ Step {ps['step']}{match_str} → In attesa…")

    return "\n".join(lines)


def create_scalata(
    *,
    name: str,
    topic_id: int,
    group_id: int,
    starting_capital: float,
    multiplier: float,
    total_steps: int,
    withdrawals: list[dict],
    created_by_id: int,
    created_by_name: str,
    first_match: Optional[dict] = None,
    pinned_message_id: int = 0,
) -> dict:
    from datetime import datetime, timezone
    scalata = {
        "id": new_id(),
        "name": name,
        "topic_id": topic_id,
        "group_id": group_id,
        "pinned_message_id": pinned_message_id,
        "starting_capital": starting_capital,
        "multiplier": multiplier,
        "total_steps": total_steps,
        "withdrawals": withdrawals,
        "current_step": 0,
        "current_capital": starting_capital,
        "history": [],
        "pending_step": {
            "step": 1,
            "capital_before": starting_capital,
            "match": first_match,
        },
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by_id": created_by_id,
        "created_by_name": created_by_name,
    }
    save_scalata(scalata)
    return scalata


def apply_win(scalata: dict) -> tuple[dict, Optional[dict]]:
    """
    Advance the scalata by one winning step.

    Returns (updated_scalata, withdrawal_info | None).
    Mutates scalata in place and persists.
    """
    ps = scalata["pending_step"]
    step = ps["step"]
    capital_before = ps["capital_before"]
    new_capital = round(capital_before * scalata["multiplier"], 2)

    # commit step to history
    history_entry = {
        "step": step,
        "result": "win",
        "capital_before": capital_before,
        "capital_after": new_capital,
        "match": ps.get("match"),
    }
    scalata["history"].append(history_entry)
    scalata["current_step"] = step
    scalata["current_capital"] = new_capital

    # check withdrawal
    withdrawal_info = None
    for w in scalata.get("withdrawals", []):
        if w["after_step"] == step:
            withdrawal_info = w
            scalata["current_capital"] = w["restart_capital"]
            new_capital = w["restart_capital"]
            break

    # check completion
    if step >= scalata["total_steps"]:
        scalata["status"] = "completed"
        scalata["pending_step"] = None
    else:
        scalata["pending_step"] = {
            "step": step + 1,
            "capital_before": new_capital,
            "match": None,
        }

    save_scalata(scalata)
    return scalata, withdrawal_info


def apply_loss(scalata: dict) -> dict:
    """Mark the scalata as failed. Mutates and persists."""
    ps = scalata["pending_step"]
    history_entry = {
        "step": ps["step"],
        "result": "loss",
        "capital_before": ps["capital_before"],
        "capital_after": 0.0,
        "match": ps.get("match"),
    }
    scalata["history"].append(history_entry)
    scalata["current_step"] = ps["step"]
    scalata["status"] = "failed"
    scalata["pending_step"] = None
    save_scalata(scalata)
    return scalata

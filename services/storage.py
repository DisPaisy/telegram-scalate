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


# ── Special topics (Vincite / Perdite) ───────────────────────────────────────

def get_special_topic(group_id: int, name: str) -> Optional[int]:
    """Return the topic_id for a named special topic in a group, or None."""
    with _lock:
        group_topics = _read().get("special_topics", {}).get(str(group_id), {})
        return group_topics.get(name)


def save_special_topic(group_id: int, name: str, topic_id: int) -> None:
    with _lock:
        data = _read()
        data.setdefault("special_topics", {}).setdefault(str(group_id), {})[name] = topic_id
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

def compute_bet(capital: float, multiplier: float, quota: Optional[float] = None) -> float:
    """Always bet the full capital (all-in on every step)."""
    return round(capital, 2)


def build_status_text(s: dict) -> str:
    """Format the pinned status message — the single source of truth for the topic."""
    icon = {"active": "📊", "completed": "🏆", "failed": "❌"}.get(s["status"], "•")
    lines = [
        "━━━━━━━━",
        f"{icon} <b>{s['name']}</b> — Step {s['current_step']}/{s['total_steps']}",
        "━━━━━━━━",
        f"Capitale: <b>€{s['current_capital']:.2f}</b>",
        "",
    ]

    withdrawals_by_step = {w["after_step"]: w for w in s.get("withdrawals", [])}
    step_configs = s.get("step_configs", [])
    _outcome_label = {"1": "Casa", "X": "Par.", "2": "Ospite"}

    for h in s.get("history", []):
        res_icon = "✅" if h["result"] == "win" else "❌"
        match_str = ""
        if h.get("match") and h["match"].get("name"):
            m = h["match"]
            lbl = _outcome_label.get(m.get("outcome_bet", ""), "")
            match_str = f" — {m['name']} {lbl}".rstrip()
        if h["result"] == "win":
            cap_str = f"→ €{h['capital_after']:.2f}"
            if h["step"] in withdrawals_by_step:
                w = withdrawals_by_step[h["step"]]
                cap_str += f"  💰 -€{w['amount']:.2f} → €{w['restart_capital']:.2f}"
        else:
            cap_str = "→ ❌"
        lines.append(f"{res_icon} Step {h['step']}{match_str} {cap_str}")

    ps = s.get("pending_step")
    if ps and s["status"] == "active":
        quota = ps.get("quota")
        after_win = round(ps["capital_before"] * (quota or s["multiplier"]), 2)
        bet_str = f"Punta tutto: <b>€{ps['capital_before']:.2f}</b> → ~€{after_win:.2f}"
        match_str = ""
        if ps.get("match") and ps["match"].get("name"):
            m = ps["match"]
            lbl = _outcome_label.get(m.get("outcome_bet", ""), "")
            match_str = f" — {m['name']} {lbl}".rstrip()
        lines.append(f"⏳ Step {ps['step']}{match_str} — {bet_str}")

        # Simulate future steps assuming all wins (show only resulting capital)
        sim_cap = ps["capital_before"]
        for step_n in range(ps["step"] + 1, s["total_steps"] + 1):
            prev = step_n - 1
            idx_prev = prev - 1
            prev_quota = step_configs[idx_prev].get("quota") if 0 <= idx_prev < len(step_configs) else None
            eff_q = prev_quota if prev_quota else s["multiplier"]
            sim_cap = round(sim_cap * eff_q, 2)
            if prev in withdrawals_by_step:
                sim_cap = withdrawals_by_step[prev]["restart_capital"]
            idx_n = step_n - 1
            next_quota = step_configs[idx_n].get("quota") if 0 <= idx_n < len(step_configs) else None
            eff_qn = next_quota if next_quota else s["multiplier"]
            sim_after = round(sim_cap * eff_qn, 2)
            lines.append(f"◻️ Step {step_n} — ~€{sim_after:.2f}")

    # Completion / failure footer
    if s["status"] == "completed":
        lines.append("")
        lines.append(f"🏆 <b>Scalata completata!</b> Capitale finale: €{s['current_capital']:.2f}")
        if s.get("delete_job_id"):
            lines.append("<i>⚠️ Topic eliminato automaticamente tra 24 ore.</i>")
    elif s["status"] == "failed":
        lost = s["history"][-1]["capital_before"] if s.get("history") else s.get("starting_capital", 0.0)
        lines.append("")
        lines.append(f"❌ <b>Fallita allo Step {s['current_step']}.</b> Capitale persa: €{lost:.2f}")
        if s.get("delete_job_id"):
            lines.append("<i>⚠️ Topic eliminato automaticamente tra 24 ore.</i>")

    if s.get("ai_comment"):
        lines.append("")
        lines.append(f"<i>🤖 {s['ai_comment']}</i>")

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
    mode: str = "improvvisata",
    step_configs: Optional[list[dict]] = None,
    pinned_message_id: int = 0,
) -> dict:
    from datetime import datetime, timezone

    if not step_configs:
        step_configs = [{"quota": multiplier, "match": None, "bet_type": None}] * total_steps

    first_cfg = step_configs[0] if step_configs else {}
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
        "mode": mode,
        "step_configs": step_configs,
        "current_step": 0,
        "current_capital": starting_capital,
        "history": [],
        "pending_step": {
            "step": 1,
            "capital_before": starting_capital,
            "quota": first_cfg.get("quota"),
            "match": first_cfg.get("match"),
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

    # Use per-step quota if set, else default multiplier
    quota = ps.get("quota")
    effective_quota = quota if quota else scalata["multiplier"]
    new_capital = round(capital_before * effective_quota, 2)

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
        # copy quota and match from step_configs for next step
        step_configs = scalata.get("step_configs", [])
        next_cfg = step_configs[step] if len(step_configs) > step else {}
        scalata["pending_step"] = {
            "step": step + 1,
            "capital_before": new_capital,
            "quota": next_cfg.get("quota"),
            "match": next_cfg.get("match"),
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


def update_step_config(
    topic_id: int,
    step: int,
    quota: float,
    match: Optional[dict],
    bet_type: Optional[str],
) -> dict:
    """Update step_configs for a specific step and sync pending_step if active."""
    with _lock:
        data = _read()
        scalata = data["scalate"].get(str(topic_id))
        if not scalata:
            raise KeyError(f"Scalata {topic_id} not found")

        configs = scalata.setdefault("step_configs", [])
        # Pad list if needed
        while len(configs) < step:
            configs.append({"quota": scalata["multiplier"], "match": None, "bet_type": None})

        configs[step - 1] = {"quota": quota, "match": match, "bet_type": bet_type}

        # Sync with live pending_step
        ps = scalata.get("pending_step")
        if ps and ps.get("step") == step:
            scalata["pending_step"]["quota"] = quota
            if match:
                scalata["pending_step"]["match"] = match

        data["scalate"][str(topic_id)] = scalata
        _write(data)
        return scalata

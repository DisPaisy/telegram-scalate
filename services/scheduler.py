"""APScheduler job: auto-resolve pending steps via football API every 3 minutes."""

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.football_api import football_api
from services import storage

if TYPE_CHECKING:
    from telegram.ext import Application

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()
_app: "Application | None" = None


def init_scheduler(app: "Application") -> None:
    global _app
    _app = app
    scheduler.add_job(_poll_results, "interval", minutes=3, id="auto_resolve")
    scheduler.start()
    log.info("Scheduler started.")


async def _poll_results() -> None:
    if _app is None:
        return

    active = storage.get_active_scalate()
    for s in active:
        ps = s.get("pending_step")
        if not ps:
            continue
        match = ps.get("match")
        if not match or not match.get("id") or match.get("outcome_actual") is not None:
            continue

        result = await football_api.get_result(match["id"])
        if result is None:
            continue

        log.info(
            "Auto-resolving scalata topic=%s step=%s result=%s",
            s["topic_id"], ps["step"], result,
        )

        won = result == match.get("outcome_bet")
        # update outcome_actual on pending match
        s["pending_step"]["match"]["outcome_actual"] = result
        s["pending_step"]["match"]["auto_resolved"] = True
        storage.save_scalata(s)

        score_str = _score_str(match)
        msg = (
            f"🤖 Risultato rilevato automaticamente: "
            f"<b>{match['name']}</b> finita {score_str}.\n"
            f"Step {ps['step']} segnato come "
            + ("✅ <b>Vinta</b>" if won else "❌ <b>Persa</b>")
        )

        try:
            sent = await _app.bot.send_message(
                chat_id=s["group_id"],
                message_thread_id=s["topic_id"],
                text=msg,
                parse_mode="HTML",
            )
        except Exception as exc:
            log.warning("Failed to send auto-resolve message: %s", exc)
            sent = None

        if won:
            await _auto_win(s, auto_resolved=True)
        else:
            await _auto_loss(s, auto_resolved=True)


def _score_str(match: dict) -> str:
    h = match.get("home_score")
    a = match.get("away_score")
    if h is not None and a is not None:
        return f"{h}-{a}"
    return ""


async def _auto_win(scalata: dict, *, auto_resolved: bool) -> None:
    from handlers.scalata import _handle_win
    await _handle_win(_app, scalata, auto_resolved=auto_resolved)


async def _auto_loss(scalata: dict, *, auto_resolved: bool) -> None:
    from handlers.scalata import _handle_loss
    await _handle_loss(_app, scalata, auto_resolved=auto_resolved)

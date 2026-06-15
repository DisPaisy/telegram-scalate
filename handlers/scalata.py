"""
Scalata command handlers:
  /nuova /vinta /persa /status /scalate /annulla
"""

import asyncio
import logging
import os
from typing import Optional, TYPE_CHECKING

from telegram import (
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.ext import CommandHandler, ContextTypes

from services import storage

if TYPE_CHECKING:
    from telegram.ext import Application

log = logging.getLogger(__name__)

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://scalata.ammirabet.com/api/v1/telegram/app/nuova")


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_topic_scalata(update: Update) -> Optional[dict]:
    thread_id = update.message.message_thread_id
    if not thread_id:
        return None
    return storage.get_scalata(thread_id)


async def _ephemeral(context: ContextTypes.DEFAULT_TYPE, chat_id: int,
                     thread_id: Optional[int], text: str, delay: int = 5) -> None:
    """Send a message then auto-delete it after `delay` seconds."""
    try:
        msg = await context.bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=text,
            parse_mode=ParseMode.HTML,
        )
        await asyncio.sleep(delay)
        await context.bot.delete_message(chat_id=chat_id, message_id=msg.message_id)
    except Exception as exc:
        log.debug("Ephemeral message error: %s", exc)


async def _update_pinned(bot, scalata: dict) -> None:
    if not scalata.get("pinned_message_id"):
        return
    try:
        await bot.edit_message_text(
            chat_id=scalata["group_id"],
            message_id=scalata["pinned_message_id"],
            text=storage.build_status_text(scalata),
            parse_mode=ParseMode.HTML,
        )
    except Exception as exc:
        log.debug("Failed to edit pinned message: %s", exc)


async def _rename_topic(bot, scalata: dict, name: str) -> None:
    try:
        await bot.edit_forum_topic(
            chat_id=scalata["group_id"],
            message_thread_id=scalata["topic_id"],
            name=name,
        )
    except Exception as exc:
        log.debug("Failed to rename topic: %s", exc)


# ── /nuova ────────────────────────────────────────────────────────────────────

async def cmd_nuova(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📊 Crea Scalata", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await update.message.reply_text(
        "Apri il pannello per configurare una nuova scalata:",
        reply_markup=keyboard,
    )


# ── shared win / loss logic (also called by scheduler) ───────────────────────

async def _handle_win(
    app: "Application",
    scalata: dict,
    *,
    auto_resolved: bool = False,
) -> None:
    """Advance scalata by one winning step and post updates."""
    ps = scalata.get("pending_step")
    if not ps:
        return

    step = ps["step"]

    # If there was a pending match, stamp outcome_actual = outcome_bet
    if ps.get("match") and ps["match"].get("outcome_actual") is None:
        scalata["pending_step"]["match"]["outcome_actual"] = ps["match"].get("outcome_bet")
        scalata["pending_step"]["match"]["auto_resolved"] = auto_resolved
        storage.save_scalata(scalata)

    updated, withdrawal = storage.apply_win(scalata)
    bot = app.bot
    chat_id = updated["group_id"]
    thread_id = updated["topic_id"]

    # Withdrawal notice
    if withdrawal:
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=(
                f"💰 <b>Prelievo dopo Step {withdrawal['after_step']}:</b> "
                f"€{withdrawal['amount']:.2f}\n"
                f"Capitale di ripartenza: €{withdrawal['restart_capital']:.2f}"
            ),
            parse_mode=ParseMode.HTML,
        )

    # Completion
    if updated["status"] == "completed":
        await bot.send_message(
            chat_id=chat_id,
            message_thread_id=thread_id,
            text=(
                f"🏆 <b>{updated['name']} completata!</b>\n"
                f"Hai completato tutti e {updated['total_steps']} gli step.\n"
                f"Capitale finale: €{updated['current_capital']:.2f}"
            ),
            parse_mode=ParseMode.HTML,
        )
        await _rename_topic(bot, updated, f"{updated['name']} — 🏆 Completata")
    else:
        await _rename_topic(
            bot, updated,
            f"{updated['name']} — Step {updated['current_step']}/{updated['total_steps']}"
        )

    # AI comment (fire and forget)
    asyncio.create_task(_post_ai_win_comment(bot, updated, step))
    await _update_pinned(bot, updated)


async def _post_ai_win_comment(bot, scalata: dict, step: int) -> None:
    from services.ai_client import win_comment
    comment = await win_comment(scalata, step)
    if comment:
        try:
            await bot.send_message(
                chat_id=scalata["group_id"],
                message_thread_id=scalata["topic_id"],
                text=comment,
            )
        except Exception:
            pass


async def _handle_loss(
    app: "Application",
    scalata: dict,
    *,
    auto_resolved: bool = False,
) -> None:
    ps = scalata.get("pending_step")
    if not ps:
        return

    step = ps["step"]
    if ps.get("match") and ps["match"].get("outcome_actual") is None:
        match = ps["match"]
        # set actual to the opposite of the bet
        opposite = {"1": "2", "2": "1", "X": "1"}.get(match.get("outcome_bet", ""), "—")
        scalata["pending_step"]["match"]["outcome_actual"] = opposite
        scalata["pending_step"]["match"]["auto_resolved"] = auto_resolved
        storage.save_scalata(scalata)

    updated = storage.apply_loss(scalata)
    bot = app.bot
    chat_id = updated["group_id"]
    thread_id = updated["topic_id"]

    await bot.send_message(
        chat_id=chat_id,
        message_thread_id=thread_id,
        text=(
            f"❌ <b>{updated['name']} — Scalata Fallita</b>\n"
            f"Persa allo Step {step}/{updated['total_steps']}.\n"
            f"Capitale persa: €{ps['capital_before']:.2f}"
        ),
        parse_mode=ParseMode.HTML,
    )
    await _rename_topic(bot, updated, f"{updated['name']} — ❌ Fallita al Step {step}")
    asyncio.create_task(_post_ai_loss_comment(bot, updated, step))
    await _update_pinned(bot, updated)


async def _post_ai_loss_comment(bot, scalata: dict, step: int) -> None:
    from services.ai_client import loss_comment
    comment = await loss_comment(scalata, step)
    if comment:
        try:
            await bot.send_message(
                chat_id=scalata["group_id"],
                message_thread_id=scalata["topic_id"],
                text=comment,
            )
        except Exception:
            pass


# ── /vinta ────────────────────────────────────────────────────────────────────

async def cmd_vinta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scalata = _get_topic_scalata(update)
    if not scalata:
        await update.message.reply_text("❌ Questo comando funziona solo in un topic di una scalata.")
        return
    if scalata["status"] != "active":
        await update.message.reply_text("❌ Questa scalata non è attiva.")
        return
    if not scalata.get("pending_step"):
        await update.message.reply_text("❌ Nessuno step in attesa.")
        return

    step = scalata["pending_step"]["step"]
    try:
        await update.message.delete()
    except Exception:
        pass

    await _handle_win(context.application, scalata)

    asyncio.create_task(_ephemeral(
        context,
        update.effective_chat.id,
        update.message.message_thread_id,
        f"✅ Step {step} segnato come <b>Vinta</b>!",
    ))


# ── /persa ────────────────────────────────────────────────────────────────────

async def cmd_persa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scalata = _get_topic_scalata(update)
    if not scalata:
        await update.message.reply_text("❌ Questo comando funziona solo in un topic di una scalata.")
        return
    if scalata["status"] != "active":
        await update.message.reply_text("❌ Questa scalata non è attiva.")
        return
    if not scalata.get("pending_step"):
        await update.message.reply_text("❌ Nessuno step in attesa.")
        return

    step = scalata["pending_step"]["step"]
    try:
        await update.message.delete()
    except Exception:
        pass

    await _handle_loss(context.application, scalata)


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scalata = _get_topic_scalata(update)

    if scalata:
        text = storage.build_status_text(scalata)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
        return

    # In general chat: list active scalate for this group
    group_id = update.effective_chat.id
    scalate = storage.get_scalate_by_group(group_id)
    active = [s for s in scalate if s["status"] == "active"]
    if not active:
        await update.message.reply_text("Nessuna scalata attiva in questo gruppo.")
        return

    lines = ["📊 <b>Scalate Attive</b>\n"]
    for s in active:
        lines.append(
            f"• <b>{s['name']}</b> — Step {s['current_step']}/{s['total_steps']} "
            f"— €{s['current_capital']:.2f}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)


# ── /scalate ──────────────────────────────────────────────────────────────────

async def cmd_scalate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_id = update.effective_chat.id
    scalate = storage.get_scalate_by_group(group_id)
    if not scalate:
        await update.message.reply_text("Nessuna scalata trovata in questo gruppo.")
        return

    status_icon = {"active": "📊", "completed": "🏆", "failed": "❌"}

    lines = ["<b>Tutte le Scalate</b>\n"]
    buttons = []
    for s in sorted(scalate, key=lambda x: x["created_at"], reverse=True):
        icon = status_icon.get(s["status"], "•")
        lines.append(
            f"{icon} <b>{s['name']}</b> — Step {s['current_step']}/{s['total_steps']}"
            f" — €{s['current_capital']:.2f}"
        )
        # Build a link to the topic
        chat_id_str = str(group_id).replace("-100", "")
        topic_url = f"https://t.me/c/{chat_id_str}/{s['topic_id']}"
        buttons.append([InlineKeyboardButton(f"{icon} {s['name']}", url=topic_url)])

    markup = InlineKeyboardMarkup(buttons) if buttons else None
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=markup,
    )


# ── /annulla ──────────────────────────────────────────────────────────────────

async def cmd_annulla(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scalata = _get_topic_scalata(update)
    if not scalata:
        await update.message.reply_text("❌ Questo comando funziona solo in un topic di una scalata.")
        return
    if scalata["status"] != "active":
        await update.message.reply_text("❌ Questa scalata non è attiva.")
        return

    user_id = update.effective_user.id
    admin_users = storage.get_admin_users()
    if admin_users and user_id not in admin_users:
        await update.message.reply_text("❌ Solo gli admin possono annullare una scalata.")
        return

    step = scalata.get("current_step", 0)
    scalata["status"] = "failed"
    scalata["pending_step"] = None
    storage.save_scalata(scalata)

    await update.message.reply_text(
        f"🚫 Scalata <b>{scalata['name']}</b> annullata al Step {step}.",
        parse_mode=ParseMode.HTML,
    )
    await _rename_topic(
        context.bot, scalata,
        f"{scalata['name']} — ❌ Annullata"
    )
    await _update_pinned(context.bot, scalata)


# ── registration ──────────────────────────────────────────────────────────────

def register(app) -> None:
    app.add_handler(CommandHandler("nuova", cmd_nuova))
    app.add_handler(CommandHandler("vinta", cmd_vinta))
    app.add_handler(CommandHandler("persa", cmd_persa))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scalate", cmd_scalate))
    app.add_handler(CommandHandler("annulla", cmd_annulla))

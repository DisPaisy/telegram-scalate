"""
Scalata command handlers:
  /nuova /vinta /persa /status /scalate /annulla
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

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


def _build_inline_keyboard(scalata: dict) -> InlineKeyboardMarkup:
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


async def _update_pinned(bot, scalata: dict) -> None:
    if not scalata.get("pinned_message_id"):
        return
    try:
        await bot.edit_message_text(
            chat_id=scalata["group_id"],
            message_id=scalata["pinned_message_id"],
            text=storage.build_status_text(scalata),
            parse_mode=ParseMode.HTML,
            reply_markup=_build_inline_keyboard(scalata),
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


async def _get_or_create_special_topic(bot, group_id: int, name: str) -> Optional[int]:
    """Return (creating if needed) the topic_id for a special topic like Vincite."""
    topic_id = storage.get_special_topic(group_id, name)
    if topic_id:
        return topic_id
    try:
        topic = await bot.create_forum_topic(chat_id=group_id, name=name, icon_color=0xFFD67E)
        topic_id = topic.message_thread_id
        storage.save_special_topic(group_id, name, topic_id)
        return topic_id
    except Exception as exc:
        log.warning("Could not create special topic '%s' in %s: %s", name, group_id, exc)
        return None


def _schedule_topic_deletion(topic_id: int, group_id: int) -> str:
    from services.scheduler import scheduler
    job_id = f"delete_topic_{topic_id}"
    scheduler.add_job(
        _delete_topic_job,
        "date",
        run_date=datetime.now() + timedelta(hours=24),
        id=job_id,
        args=[group_id, topic_id],
        replace_existing=True,
    )
    return job_id


async def _delete_topic_job(group_id: int, topic_id: int) -> None:
    from services.scheduler import _app
    if _app is None:
        return
    try:
        await _app.bot.delete_forum_topic(chat_id=group_id, message_thread_id=topic_id)
    except Exception as exc:
        log.warning("Auto-delete topic %s failed: %s", topic_id, exc)
    storage.delete_scalata(topic_id)


# ── /nuova ────────────────────────────────────────────────────────────────────

async def cmd_nuova(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    user = update.effective_user

    if chat.type in ("group", "supergroup"):
        group_id = chat.id
        thread_id = update.message.message_thread_id
        url = f"{WEBAPP_URL}?group_id={group_id}"
        if thread_id:
            url += f"&thread_id={thread_id}"

        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("📊 Crea Scalata", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        try:
            await context.bot.send_message(
                chat_id=user.id,
                text=f"Crea una nuova scalata nel gruppo <b>{chat.title}</b>:",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
            await update.message.reply_text("👆 Ti ho inviato un messaggio in privato per creare la scalata!")
        except (Forbidden, BadRequest):
            username = context.bot.username
            await update.message.reply_text(
                f"❌ Non riesco a scriverti in privato. "
                f"Avvia prima il bot: t.me/{username}?start=setup"
            )

    else:
        groups = storage.get_groups()
        if not groups:
            await update.message.reply_text(
                "Aggiungimi prima a un gruppo e usa /nuova lì."
            )
            return

        buttons = [
            [KeyboardButton(
                f"📊 {g['name']}",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}?group_id={g['id']}"),
            )]
            for g in groups.values()
        ]
        keyboard = ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text(
            "Scegli il gruppo in cui creare la scalata:",
            reply_markup=keyboard,
        )


# ── shared win / loss logic (also called by scheduler) ───────────────────────

async def _handle_win(
    app: "Application",
    scalata: dict,
    *,
    auto_resolved: bool = False,
) -> None:
    """Advance scalata by one winning step. Only edits the pinned message."""
    ps = scalata.get("pending_step")
    if not ps:
        return

    step = ps["step"]

    if ps.get("match") and ps["match"].get("outcome_actual") is None:
        scalata["pending_step"]["match"]["outcome_actual"] = ps["match"].get("outcome_bet")
        scalata["pending_step"]["match"]["auto_resolved"] = auto_resolved
        storage.save_scalata(scalata)

    updated, withdrawal = storage.apply_win(scalata)
    bot = app.bot
    chat_id = updated["group_id"]
    thread_id = updated["topic_id"]

    if updated["status"] == "completed":
        # Schedule deletion and persist job_id before first edit
        job_id = _schedule_topic_deletion(thread_id, chat_id)
        updated["delete_job_id"] = job_id
        storage.save_scalata(updated)

        await _update_pinned(bot, updated)
        await _rename_topic(bot, updated, f"{updated['name']} — 🏆 Completata")

        # Post recap in Vincite topic
        vincite_id = await _get_or_create_special_topic(bot, chat_id, "Vincite")
        if vincite_id:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    message_thread_id=vincite_id,
                    text=storage.build_status_text(updated),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as exc:
                log.warning("Failed to post Vincite recap: %s", exc)
    else:
        await _update_pinned(bot, updated)
        await _rename_topic(
            bot, updated,
            f"{updated['name']} — Step {updated['current_step']}/{updated['total_steps']}"
        )

    asyncio.create_task(_post_ai_win_comment(bot, updated, step))


async def _post_ai_win_comment(bot, scalata: dict, step: int) -> None:
    from services.ai_client import win_comment
    comment = await win_comment(scalata, step)
    if comment:
        scalata = storage.get_scalata(scalata["topic_id"]) or scalata
        scalata["ai_comment"] = comment
        storage.save_scalata(scalata)
        await _update_pinned(bot, scalata)


async def _handle_loss(
    app: "Application",
    scalata: dict,
    *,
    auto_resolved: bool = False,
) -> None:
    """Mark scalata as failed. Only edits the pinned message."""
    ps = scalata.get("pending_step")
    if not ps:
        return

    step = ps["step"]
    if ps.get("match") and ps["match"].get("outcome_actual") is None:
        match = ps["match"]
        opposite = {"1": "2", "2": "1", "X": "1"}.get(match.get("outcome_bet", ""), "—")
        scalata["pending_step"]["match"]["outcome_actual"] = opposite
        scalata["pending_step"]["match"]["auto_resolved"] = auto_resolved
        storage.save_scalata(scalata)

    updated = storage.apply_loss(scalata)
    bot = app.bot
    chat_id = updated["group_id"]
    thread_id = updated["topic_id"]

    # Schedule deletion and persist job_id before first edit
    job_id = _schedule_topic_deletion(thread_id, chat_id)
    updated["delete_job_id"] = job_id
    storage.save_scalata(updated)

    await _update_pinned(bot, updated)
    await _rename_topic(bot, updated, f"{updated['name']} — ❌ Fallita al Step {step}")

    asyncio.create_task(_post_ai_loss_comment(bot, updated, step))


async def _post_ai_loss_comment(bot, scalata: dict, step: int) -> None:
    from services.ai_client import loss_comment
    comment = await loss_comment(scalata, step)
    if comment:
        scalata = storage.get_scalata(scalata["topic_id"]) or scalata
        scalata["ai_comment"] = comment
        storage.save_scalata(scalata)
        await _update_pinned(bot, scalata)


# ── callback query handler ────────────────────────────────────────────────────

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return

    action, topic_id_str = data.split(":", 1)
    try:
        topic_id = int(topic_id_str)
    except ValueError:
        return

    scalata = storage.get_scalata(topic_id)
    if not scalata:
        await query.answer("Scalata non trovata.", show_alert=True)
        return

    if action in ("win", "loss"):
        if scalata["status"] != "active":
            await query.answer("Questa scalata non è più attiva.", show_alert=True)
            return
        if not scalata.get("pending_step"):
            await query.answer("Nessuno step in attesa.", show_alert=True)
            return
        step = scalata["pending_step"]["step"]
        if action == "win":
            await _handle_win(context.application, scalata)
            await query.answer(f"✅ Step {step} segnato come Vinta!")
        else:
            await _handle_loss(context.application, scalata)
            await query.answer(f"❌ Step {step} segnato come Persa.")

    elif action == "card":
        chat_id = query.message.chat_id
        thread_id = scalata["topic_id"]
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_photo",
                                               message_thread_id=thread_id)
            from services.image_gen import generate_card
            buf = await asyncio.get_event_loop().run_in_executor(None, generate_card, scalata)
            await context.bot.send_photo(
                chat_id=chat_id,
                message_thread_id=thread_id,
                photo=buf,
                caption=f"📊 <b>{scalata['name']}</b> — Step {scalata['current_step']}/{scalata['total_steps']}",
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            log.error("Card generation failed: %s", exc)
            await query.answer("Errore nella generazione della card.", show_alert=True)

    elif action == "pdf":
        chat_id = query.message.chat_id
        thread_id = scalata["topic_id"]
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="upload_document",
                                               message_thread_id=thread_id)
            from services.pdf_gen import generate_pdf
            buf = await asyncio.get_event_loop().run_in_executor(None, generate_pdf, scalata)
            filename = f"{scalata['name'].replace(' ', '_')}_report.pdf"
            await context.bot.send_document(
                chat_id=chat_id,
                message_thread_id=thread_id,
                document=buf,
                filename=filename,
                caption=f"📄 Report PDF per <b>{scalata['name']}</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            log.error("PDF generation failed: %s", exc)
            await query.answer("Errore nella generazione del PDF.", show_alert=True)

    elif action == "delete_now":
        job_id = scalata.get("delete_job_id")
        if job_id:
            try:
                from services.scheduler import scheduler
                scheduler.remove_job(job_id)
            except Exception:
                pass
        try:
            await context.bot.delete_forum_topic(
                chat_id=scalata["group_id"],
                message_thread_id=topic_id,
            )
        except Exception as exc:
            log.warning("delete_now forum topic failed: %s", exc)
        storage.delete_scalata(topic_id)
        await query.answer("🗑️ Topic eliminato.")

    elif action == "cancel_delete":
        job_id = scalata.get("delete_job_id")
        if job_id:
            try:
                from services.scheduler import scheduler
                scheduler.remove_job(job_id)
            except Exception:
                pass
        scalata.pop("delete_job_id", None)
        storage.save_scalata(scalata)
        await _update_pinned(context.bot, scalata)
        await query.answer("💾 Eliminazione annullata.")

    elif action == "configure_step":
        user_id = query.from_user.id
        configure_url = os.getenv(
            "WEBAPP_CONFIGURE_STEP_URL",
            "https://scalata.ammirabet.com/api/v1/telegram/app/configure-step",
        )
        url = f"{configure_url}?topic_id={topic_id}"
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton(f"📝 Configura Step", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Configura lo step corrente di <b>{scalata['name']}</b>:",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except (Forbidden, BadRequest):
            await query.answer("Non riesco a scriverti in privato. Avvia prima il bot.", show_alert=True)

    elif action == "edit_scalata":
        user_id = query.from_user.id
        edit_url = os.getenv(
            "WEBAPP_EDIT_URL",
            "https://scalata.ammirabet.com/api/v1/telegram/app/edit-scalata",
        )
        url = f"{edit_url}?topic_id={topic_id}"
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("✏️ Modifica Scalata", web_app=WebAppInfo(url=url))]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"Modifica <b>{scalata['name']}</b>:",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except (Forbidden, BadRequest):
            await query.answer("Non riesco a scriverti in privato. Avvia prima il bot.", show_alert=True)


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

    try:
        await update.message.delete()
    except Exception:
        pass

    await _handle_win(context.application, scalata)


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
    job_id = _schedule_topic_deletion(scalata["topic_id"], scalata["group_id"])
    scalata["delete_job_id"] = job_id
    storage.save_scalata(scalata)

    await _rename_topic(
        context.bot, scalata,
        f"{scalata['name']} — ❌ Annullata"
    )
    await _update_pinned(context.bot, scalata)

    try:
        await update.message.delete()
    except Exception:
        pass


# ── auto-delete forum system messages ─────────────────────────────────────────

async def _delete_system_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        await update.message.delete()
    except Exception:
        pass


# ── registration ──────────────────────────────────────────────────────────────

def register(app) -> None:
    app.add_handler(CommandHandler("nuova", cmd_nuova))
    app.add_handler(CommandHandler("vinta", cmd_vinta))
    app.add_handler(CommandHandler("persa", cmd_persa))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("scalate", cmd_scalate))
    app.add_handler(CommandHandler("annulla", cmd_annulla))
    app.add_handler(CallbackQueryHandler(handle_callback_query))
    app.add_handler(
        MessageHandler(
            filters.StatusUpdate.FORUM_TOPIC_EDITED
            | filters.StatusUpdate.FORUM_TOPIC_CREATED
            | filters.StatusUpdate.FORUM_TOPIC_CLOSED
            | filters.StatusUpdate.FORUM_TOPIC_REOPENED,
            _delete_system_message,
        ),
        group=1,
    )

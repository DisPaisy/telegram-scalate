"""
Media handlers:
  /card  — send Pillow-generated image card
  /pdf   — send WeasyPrint PDF report
"""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from services import storage

log = logging.getLogger(__name__)


def _resolve_scalata(update: Update) -> Optional[dict]:
    """Return the scalata for the current topic, or the most recent active one."""
    thread_id = update.message.message_thread_id
    if thread_id:
        s = storage.get_scalata(thread_id)
        if s:
            return s

    group_id = update.effective_chat.id
    scalate = [s for s in storage.get_scalate_by_group(group_id) if s["status"] == "active"]
    if scalate:
        return scalate[0]
    # fall back to any scalata in the group
    all_s = storage.get_scalate_by_group(group_id)
    return all_s[0] if all_s else None


async def cmd_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scalata = _resolve_scalata(update)
    if not scalata:
        await update.message.reply_text("❌ Nessuna scalata trovata.")
        return

    await update.message.chat.send_action("upload_photo")
    try:
        from services.image_gen import generate_card
        buf = generate_card(scalata)
        await update.message.reply_photo(
            photo=buf,
            caption=f"📊 <b>{scalata['name']}</b> — Step {scalata['current_step']}/{scalata['total_steps']}",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.error("Card generation failed: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Errore nella generazione della card: {exc}")


async def cmd_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    scalata = _resolve_scalata(update)
    if not scalata:
        await update.message.reply_text("❌ Nessuna scalata trovata.")
        return

    await update.message.chat.send_action("upload_document")
    try:
        from services.pdf_gen import generate_pdf
        buf = generate_pdf(scalata)
        filename = f"{scalata['name'].replace(' ', '_')}_report.pdf"
        await update.message.reply_document(
            document=buf,
            filename=filename,
            caption=f"📄 Report PDF per <b>{scalata['name']}</b>",
            parse_mode="HTML",
        )
    except Exception as exc:
        log.error("PDF generation failed: %s", exc, exc_info=True)
        await update.message.reply_text(f"❌ Errore nella generazione del PDF: {exc}")


def register(app) -> None:
    app.add_handler(CommandHandler("card", cmd_card))
    app.add_handler(CommandHandler("pdf", cmd_pdf))

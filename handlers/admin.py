"""
Admin handler: /admin
Only usable by users listed in admin_users.
"""

import logging
import os

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update, WebAppInfo
from telegram.ext import CommandHandler, ContextTypes

from services import storage

ADMIN_WEBAPP_URL = os.getenv(
    "WEBAPP_ADMIN_URL",
    "https://scalata.ammirabet.com/api/v1/telegram/app/admin",
)

log = logging.getLogger(__name__)

HELP_TEXT = """🔧 <b>Comandi Admin</b>

/admin adduser &lt;user_id&gt;     — aggiungi admin
/admin removeuser &lt;user_id&gt;  — rimuovi admin
/admin listusers             — lista admin
/admin scalate               — tutte le scalate (globale)
/admin delete &lt;topic_id&gt;     — elimina scalata
"""


def _is_admin(update: Update) -> bool:
    admins = storage.get_admin_users()
    if not admins:
        return True  # no admins configured → everyone can use /admin
    return update.effective_user.id in admins


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        await update.message.reply_text("❌ Non sei autorizzato.")
        return

    args = context.args or []
    sub = args[0].lower() if args else ""

    if sub == "adduser":
        if len(args) < 2:
            await update.message.reply_text("Uso: /admin adduser <user_id>")
            return
        uid = int(args[1])
        storage.add_admin_user(uid)
        await update.message.reply_text(f"✅ Utente {uid} aggiunto agli admin.")

    elif sub == "removeuser":
        if len(args) < 2:
            await update.message.reply_text("Uso: /admin removeuser <user_id>")
            return
        uid = int(args[1])
        storage.remove_admin_user(uid)
        await update.message.reply_text(f"✅ Utente {uid} rimosso dagli admin.")

    elif sub == "listusers":
        admins = storage.get_admin_users()
        if admins:
            await update.message.reply_text(
                "👤 Admin:\n" + "\n".join(f"• {uid}" for uid in admins),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("Nessun admin configurato (tutti possono usare /admin).")

    elif sub == "scalate":
        data = storage.get_all()
        scalate = list(data["scalate"].values())
        if not scalate:
            await update.message.reply_text("Nessuna scalata.")
            return
        lines = ["<b>Tutte le Scalate</b>\n"]
        for s in scalate:
            icon = {"active": "📊", "completed": "🏆", "failed": "❌"}.get(s["status"], "•")
            lines.append(
                f"{icon} [{s['group_id']}/{s['topic_id']}] <b>{s['name']}</b> "
                f"Step {s['current_step']}/{s['total_steps']}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    elif sub == "delete":
        if len(args) < 2:
            await update.message.reply_text("Uso: /admin delete <topic_id>")
            return
        tid = int(args[1])
        storage.delete_scalata(tid)
        await update.message.reply_text(f"✅ Scalata topic={tid} eliminata.")

    else:
        keyboard = ReplyKeyboardMarkup(
            [[KeyboardButton("⚙️ Pannello Admin", web_app=WebAppInfo(url=ADMIN_WEBAPP_URL))]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )
        await update.message.reply_text(
            "🔧 <b>Admin Panel</b>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )


def register(app) -> None:
    app.add_handler(CommandHandler("admin", cmd_admin))

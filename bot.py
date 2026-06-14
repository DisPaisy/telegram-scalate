"""Entry point: starts the Telegram bot, FastAPI server, and APScheduler."""

import asyncio
import logging
import os

import uvicorn
from dotenv import load_dotenv
from telegram.ext import Application

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
API_PORT = int(os.getenv("API_PORT", "8000"))


def _seed_admin_users() -> None:
    """Add any admin user IDs from ADMIN_USERS env var."""
    from services import storage
    raw = os.getenv("ADMIN_USERS", "")
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            storage.add_admin_user(int(part))


def _build_application() -> Application:
    from handlers import scalata as scalata_handlers
    from handlers import media as media_handlers
    from handlers import admin as admin_handlers

    app = Application.builder().token(BOT_TOKEN).build()
    scalata_handlers.register(app)
    media_handlers.register(app)
    admin_handlers.register(app)
    return app


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set")

    _seed_admin_users()

    tg_app = _build_application()

    from api.server import create_app
    fastapi_app = create_app(bot_app=tg_app)

    from services.scheduler import init_scheduler
    init_scheduler(tg_app)

    await tg_app.initialize()
    await tg_app.start()

    if WEBHOOK_URL:
        webhook_path = f"/webhook/{WEBHOOK_SECRET or 'scalata'}"
        full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"

        await tg_app.bot.set_webhook(
            url=full_webhook_url,
            secret_token=WEBHOOK_SECRET or None,
        )
        log.info("Webhook set: %s", full_webhook_url)

        # Mount the PTB webhook handler into FastAPI
        from starlette.requests import Request
        from starlette.responses import Response

        async def telegram_webhook(request: Request) -> Response:
            body = await request.body()
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
                return Response(status_code=403)
            import json
            from telegram import Update
            update = Update.de_json(json.loads(body), tg_app.bot)
            await tg_app.process_update(update)
            return Response(status_code=200)

        fastapi_app.add_route(webhook_path, telegram_webhook, methods=["POST"])

    else:
        await tg_app.updater.start_polling(drop_pending_updates=True)
        log.info("Polling started.")

    config = uvicorn.Config(
        app=fastapi_app,
        host="0.0.0.0",
        port=API_PORT,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        log.info("Shutting down…")
        if WEBHOOK_URL:
            await tg_app.bot.delete_webhook()
        else:
            await tg_app.updater.stop()
        await tg_app.stop()
        await tg_app.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

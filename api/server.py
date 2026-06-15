"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from api.routes import scalata as scalata_routes
from api.routes import matches as matches_routes
from api.routes import admin as admin_routes
from api.routes import app as app_routes


def create_app(bot_app=None) -> FastAPI:
    app = FastAPI(title="Scalata Bot API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.bot_app = bot_app

    app.include_router(
        scalata_routes.router,
        prefix="/api/v1/telegram/scalata",
        tags=["scalata"],
    )
    app.include_router(
        matches_routes.router,
        prefix="/api/v1/telegram/matches",
        tags=["matches"],
    )
    app.include_router(
        admin_routes.router,
        prefix="/api/v1/telegram/admin",
        tags=["admin"],
    )
    app.include_router(
        app_routes.router,
        prefix="/api/v1/telegram/app",
        tags=["app"],
    )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app

"""GET /api/v1/telegram/matches/search — proxy to football API."""

from fastapi import APIRouter, Query

from services.football_api import football_api

router = APIRouter()


@router.get("/search")
async def search_matches(q: str = Query(..., min_length=1)):
    matches = await football_api.search_matches(q)
    return {
        "ok": True,
        "matches": [
            {
                "id": m.id,
                "name": m.name,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "date": m.date,
                "status": m.status,
            }
            for m in matches
        ],
    }

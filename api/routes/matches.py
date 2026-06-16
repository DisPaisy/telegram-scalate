"""GET /api/v1/telegram/matches/search — proxy to football API."""

from fastapi import APIRouter, Query

from services.football_api import football_api

router = APIRouter()


@router.get("/search")
async def search_matches(q: str = Query(..., min_length=1)):
    matches = await football_api.search_matches(q)
    return {
        "ok": True,
        "api_down": football_api.last_error,
        "matches": [
            {
                "id": m.id,
                "name": m.name,
                "home_team": m.home_team,
                "away_team": m.away_team,
                "date": m.date,
                "status": m.status,
                "home_score": m.home_score,
                "away_score": m.away_score,
            }
            for m in matches
        ],
    }

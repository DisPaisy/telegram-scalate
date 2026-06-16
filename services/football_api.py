"""football-data.org v4 API client with silent fallback."""

import logging
import os
from dataclasses import dataclass
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

BASE_URL = "https://api.football-data.org/v4"
TOKEN = os.getenv("FOOTBALL_API_TOKEN", "")
TIMEOUT = aiohttp.ClientTimeout(total=5)

_FINISHED_STATUSES = {"FINISHED"}
_LIVE_STATUSES = {"LIVE", "IN_PLAY", "PAUSED"}


@dataclass
class Match:
    id: str
    name: str           # "Home vs Away"
    home_team: str
    away_team: str
    date: Optional[str]
    status: str
    home_score: Optional[int]
    away_score: Optional[int]


def _parse_match(raw: dict) -> Optional[Match]:
    try:
        home = raw.get("homeTeam") or {}
        away = raw.get("awayTeam") or {}
        home_name = home.get("name") or ""
        away_name = away.get("name") or ""
        if not home_name and not away_name:
            return None

        status = raw.get("status", "NS")
        date_val = raw.get("utcDate")

        ft = (raw.get("score") or {}).get("fullTime") or {}
        home_score = ft.get("home")
        away_score = ft.get("away")

        return Match(
            id=str(raw["id"]),
            name=f"{home_name} vs {away_name}",
            home_team=home_name,
            away_team=away_name,
            date=date_val,
            status=str(status),
            home_score=int(home_score) if home_score is not None else None,
            away_score=int(away_score) if away_score is not None else None,
        )
    except Exception:
        log.debug("Failed to parse match: %s", raw, exc_info=True)
        return None


class FootballAPI:
    def __init__(self) -> None:
        self.last_error: bool = False

    async def _get(self, path: str, **params) -> Optional[dict | list]:
        try:
            headers = {"X-Auth-Token": TOKEN}
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(f"{BASE_URL}{path}", params=params, headers=headers) as resp:
                    resp.raise_for_status()
                    self.last_error = False
                    return await resp.json(content_type=None)
        except Exception as exc:
            log.warning("football-data.org request failed (%s %s): %s", path, params, exc)
            self.last_error = True
            return None

    async def search_matches(self, query: str) -> list[Match]:
        raw = await self._get("/competitions/WC/matches")
        if raw is None:
            return []
        items = raw.get("matches", [])
        q = query.lower()
        results = []
        for item in items:
            if item.get("status") == "FINISHED":
                continue
            home = (item.get("homeTeam") or {}).get("name") or ""
            away = (item.get("awayTeam") or {}).get("name") or ""
            if not home and not away:
                continue
            if q in home.lower() or q in away.lower():
                m = _parse_match(item)
                if m:
                    results.append(m)
        return results[:10]

    async def get_match(self, match_id: str) -> Optional[Match]:
        raw = await self._get(f"/matches/{match_id}")
        if raw is None:
            return None
        item = raw.get("match") or raw
        return _parse_match(item)

    async def get_result(self, match_id: str) -> Optional[str]:
        """Returns '1', 'X', or '2' when the match is FINISHED, else None."""
        match = await self.get_match(match_id)
        if match is None:
            return None
        if match.status not in _FINISHED_STATUSES:
            return None
        if match.home_score is None or match.away_score is None:
            return None
        if match.home_score > match.away_score:
            return "1"
        if match.home_score == match.away_score:
            return "X"
        return "2"


football_api = FootballAPI()

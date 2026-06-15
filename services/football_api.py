"""worldcup26.ir football API client with silent fallback."""

import logging
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone

import aiohttp

log = logging.getLogger(__name__)

BASE_URL = "https://worldcup26.ir/api"
TIMEOUT = aiohttp.ClientTimeout(total=5)

_FINISHED_STATUSES = {"FT", "finished", "completed", "FINISHED", "FULL_TIME", "AET", "PEN"}
_LIVE_STATUSES = {"LIVE", "in_play", "IN_PLAY", "1H", "2H", "HT", "ET", "P"}


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
        home = raw.get("home_team") or raw.get("homeTeam") or raw.get("home", {})
        away = raw.get("away_team") or raw.get("awayTeam") or raw.get("away", {})

        # handle nested team objects {"name": "..."} or plain strings
        home_name = home if isinstance(home, str) else home.get("name", "?")
        away_name = away if isinstance(away, str) else away.get("name", "?")

        score = raw.get("score") or {}
        home_score = raw.get("home_score") or raw.get("homeScore")
        away_score = raw.get("away_score") or raw.get("awayScore")
        if home_score is None and score:
            home_score = score.get("home") or score.get("fullTime", {}).get("home")
        if away_score is None and score:
            away_score = score.get("away") or score.get("fullTime", {}).get("away")

        status = (
            raw.get("status")
            or raw.get("state")
            or raw.get("matchStatus", "NS")
        )
        if isinstance(status, dict):
            status = status.get("short", "NS")

        date_val = raw.get("date") or raw.get("utcDate") or raw.get("datetime")

        return Match(
            id=str(raw.get("id") or raw.get("match_id") or ""),
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
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(f"{BASE_URL}{path}", params=params) as resp:
                    resp.raise_for_status()
                    self.last_error = False
                    return await resp.json(content_type=None)
        except Exception as exc:
            log.warning("worldcup26.ir request failed (%s %s): %s", path, params, exc)
            self.last_error = True
            return None

    async def search_matches(self, query: str) -> list[Match]:
        """Search matches by team name substring (today + upcoming)."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw = await self._get("/matches", date=today)
        if raw is None:
            raw = await self._get("/matches")
        if raw is None:
            return []

        items = raw if isinstance(raw, list) else raw.get("matches", raw.get("data", []))
        q = query.lower()
        results: list[Match] = []
        for item in items:
            m = _parse_match(item)
            if m and (q in m.home_team.lower() or q in m.away_team.lower()):
                results.append(m)
        return results[:10]

    async def get_match(self, match_id: str) -> Optional[Match]:
        raw = await self._get(f"/matches/{match_id}")
        if raw is None:
            return None
        if isinstance(raw, dict):
            item = raw.get("match") or raw.get("data") or raw
            return _parse_match(item)
        return None

    async def get_result(self, match_id: str) -> Optional[str]:
        """
        Returns "1" (home win), "X" (draw), "2" (away win), or None (not finished).
        """
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

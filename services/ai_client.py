"""HackClub AI text generation client (OpenAI-compatible endpoint)."""

import logging
import os
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

_URL = os.getenv("HACKCLUB_AI_URL", "https://ai.hackclub.com/chat/completions")
_MODEL = os.getenv("HACKCLUB_AI_MODEL", "gpt-4o-mini")
_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def generate(
    prompt: str,
    system: str = "Sei un assistente per scommesse sportive. Rispondi in italiano, in modo conciso.",
    max_tokens: int = 300,
) -> Optional[str]:
    payload = {
        "model": _MODEL,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(_URL, json=payload) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("HackClub AI request failed: %s", exc)
        return None


async def win_comment(scalata: dict, step: int) -> Optional[str]:
    capital = scalata["current_capital"]
    name = scalata["name"]
    prompt = (
        f"La scalata '{name}' ha appena vinto lo step {step}. "
        f"Il capitale attuale è €{capital:.2f}. "
        "Scrivi un breve commento entusiasta (max 2 righe) con qualche emoji."
    )
    return await generate(prompt)


async def loss_comment(scalata: dict, step: int) -> Optional[str]:
    name = scalata["name"]
    prompt = (
        f"La scalata '{name}' ha perso allo step {step}. "
        "Scrivi un breve messaggio di consolazione (max 2 righe) con qualche emoji."
    )
    return await generate(prompt)

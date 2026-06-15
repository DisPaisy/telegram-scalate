"""AI text generation — reads URL/model/key from storage at call time."""

import logging
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=15)


async def generate(
    prompt: str,
    system: str = "Sei un assistente per scommesse sportive. Rispondi in italiano, in modo conciso.",
    max_tokens: int = 300,
) -> Optional[str]:
    from services import storage
    config = storage.get_ai_config()
    if not config.get("enabled", True):
        return None

    url = config["url"]
    model = config["model"]
    key = config.get("key", "")

    headers: dict[str, str] = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        log.warning("AI request failed (%s): %s", url, exc)
        return None


async def win_comment(scalata: dict, step: int) -> Optional[str]:
    return await generate(
        f"La scalata '{scalata['name']}' ha appena vinto lo step {step}. "
        f"Il capitale attuale è €{scalata['current_capital']:.2f}. "
        "Scrivi un breve commento entusiasta (max 2 righe) con qualche emoji."
    )


async def loss_comment(scalata: dict, step: int) -> Optional[str]:
    return await generate(
        f"La scalata '{scalata['name']}' ha perso allo step {step}. "
        "Scrivi un breve messaggio di consolazione (max 2 righe) con qualche emoji."
    )

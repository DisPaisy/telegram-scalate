"""Generate a visual card image for a scalata using Pillow."""

import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path("assets")
FONT_PATH = ASSETS / "GeistVF.woff"

# Try to produce a usable TTF from the WOFF; fall back to default.
_font_data: Optional[bytes] = None
_font_path_resolved: Optional[str] = None


def _resolve_font() -> Optional[str]:
    global _font_path_resolved
    if _font_path_resolved is not None:
        return _font_path_resolved

    if FONT_PATH.exists():
        # Try loading directly (Pillow ≥9.2 + FreeType may support WOFF)
        try:
            ImageFont.truetype(str(FONT_PATH), 16)
            _font_path_resolved = str(FONT_PATH)
            return _font_path_resolved
        except Exception:
            pass

        # Convert WOFF → TTF in-memory via fonttools
        try:
            from fontTools.ttLib import TTFont
            tt = TTFont(str(FONT_PATH))
            tmp = Path("/tmp/GeistVF.ttf")
            tt.save(str(tmp))
            _font_path_resolved = str(tmp)
            return _font_path_resolved
        except Exception:
            pass

    # System fallback: look for DejaVu or Liberation
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ]:
        if os.path.exists(candidate):
            _font_path_resolved = candidate
            return _font_path_resolved

    return None


def _font(size: int) -> ImageFont.FreeTypeFont:
    path = _resolve_font()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── colour palette ────────────────────────────────────────────────────────────
BG = (15, 17, 35)
PANEL = (26, 28, 52)
ACCENT = (99, 102, 241)   # indigo
GREEN = (34, 197, 94)
RED = (239, 68, 68)
GOLD = (234, 179, 8)
TEXT = (226, 232, 240)
MUTED = (100, 116, 139)


def generate_card(scalata: dict) -> io.BytesIO:
    W, H = 900, 560
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    f_title = _font(28)
    f_head = _font(20)
    f_body = _font(16)
    f_small = _font(13)

    # header panel
    draw.rectangle([(0, 0), (W, 80)], fill=PANEL)
    draw.rectangle([(0, 78), (W, 80)], fill=ACCENT)

    status_icon = "📊" if scalata["status"] == "active" else ("🏆" if scalata["status"] == "completed" else "❌")
    draw.text((24, 20), f"{scalata['name']}", font=f_title, fill=TEXT)

    step_label = f"Step {scalata['current_step']}/{scalata['total_steps']}"
    bbox = draw.textbbox((0, 0), step_label, font=f_head)
    sw = bbox[2] - bbox[0]
    draw.text((W - sw - 24, 26), step_label, font=f_head, fill=ACCENT)

    # capital block
    y = 100
    draw.text((24, y), "Capitale attuale", font=f_small, fill=MUTED)
    draw.text((24, y + 18), f"€{scalata['current_capital']:.2f}", font=_font(36), fill=TEXT)

    if scalata["status"] == "active" and scalata.get("pending_step"):
        from services.storage import compute_bet
        bet = compute_bet(scalata["current_capital"], scalata["multiplier"])
        draw.text((200, y), "Prossima puntata", font=f_small, fill=MUTED)
        draw.text((200, y + 18), f"€{bet:.2f}", font=_font(36), fill=GOLD)

        mult = scalata["multiplier"]
        draw.text((400, y), "Moltiplicatore", font=f_small, fill=MUTED)
        draw.text((400, y + 18), f"×{mult}", font=_font(36), fill=ACCENT)

    # progress bar
    y = 170
    total = scalata["total_steps"]
    done = scalata["current_step"]
    bar_w = W - 48
    draw.rectangle([(24, y), (24 + bar_w, y + 12)], fill=PANEL, outline=ACCENT, width=1)
    if total > 0:
        fill_w = int(bar_w * done / total)
        if fill_w > 0:
            colour = GREEN if scalata["status"] != "failed" else RED
            draw.rectangle([(24, y), (24 + fill_w, y + 12)], fill=colour)
    draw.text((24, y + 16), f"{done}/{total} steps completati", font=f_small, fill=MUTED)

    # history table
    y = 212
    draw.text((24, y), "STORICO", font=f_small, fill=MUTED)
    y += 20
    col_w = [48, 320, 120, 120]
    headers = ["#", "Match", "Scommessa", "Capitale"]
    x_positions = [24, 72, 392, 512]

    for i, (h, x) in enumerate(zip(headers, x_positions)):
        draw.text((x, y), h, font=f_small, fill=MUTED)
    y += 18
    draw.rectangle([(24, y), (W - 24, y + 1)], fill=PANEL)
    y += 6

    for entry in scalata.get("history", [])[-8:]:
        if y > H - 40:
            break
        is_win = entry["result"] == "win"
        colour = GREEN if is_win else RED
        icon = "✓" if is_win else "✗"

        draw.text((x_positions[0], y), icon, font=f_body, fill=colour)
        draw.text((x_positions[0] + 16, y), str(entry["step"]), font=f_body, fill=TEXT)

        match_name = (entry.get("match") or {}).get("name", "—")
        if len(match_name) > 28:
            match_name = match_name[:26] + "…"
        draw.text((x_positions[1], y), match_name, font=f_body, fill=TEXT)

        bet = entry.get("match", {}) or {}
        ob = bet.get("outcome_bet", "—")
        oa = bet.get("outcome_actual", "—")
        draw.text((x_positions[2], y), f"{ob} → {oa}", font=f_body, fill=colour)

        draw.text((x_positions[3], y), f"€{entry['capital_after']:.2f}", font=f_body, fill=TEXT)
        y += 24

    # footer
    draw.rectangle([(0, H - 28), (W, H)], fill=PANEL)
    footer = f"ID: {scalata['id']}  •  Creata da {scalata['created_by_name']}"
    draw.text((24, H - 20), footer, font=f_small, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

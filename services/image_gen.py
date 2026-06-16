"""Generate a visual card image for a scalata using Pillow."""

import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path("assets")
FONT_PATH = ASSETS / "GeistVF.woff"

_font_path_resolved: Optional[str] = None


def _resolve_font() -> Optional[str]:
    global _font_path_resolved
    if _font_path_resolved is not None:
        return _font_path_resolved

    if FONT_PATH.exists():
        try:
            ImageFont.truetype(str(FONT_PATH), 16)
            _font_path_resolved = str(FONT_PATH)
            return _font_path_resolved
        except Exception:
            pass
        try:
            from fontTools.ttLib import TTFont
            tt = TTFont(str(FONT_PATH))
            tmp = Path("/tmp/GeistVF.ttf")
            tt.save(str(tmp))
            _font_path_resolved = str(tmp)
            return _font_path_resolved
        except Exception:
            pass

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


# ── Monochrome palette ────────────────────────────────────────────────────────
BG      = (10, 10, 10)
PANEL   = (24, 24, 24)
BORDER  = (255, 255, 255)
TEXT    = (255, 255, 255)
MUTED   = (150, 150, 150)
DIM     = (60, 60, 60)
WIN_COL = (255, 255, 255)
LOSS_COL= (70, 70, 70)
GOLD    = (220, 220, 220)
PEND_BG = (255, 255, 255)
PEND_TXT= (10, 10, 10)


def _build_step_data(scalata: dict) -> list[dict]:
    """Build state data for every step (history + pending + future)."""
    total = scalata["total_steps"]
    step_configs = scalata.get("step_configs", [])
    mult = scalata["multiplier"]
    history_map = {h["step"]: h for h in scalata.get("history", [])}
    withdrawals = {w["after_step"]: w for w in scalata.get("withdrawals", [])}
    ps = scalata.get("pending_step")

    steps = []
    sim_cap = scalata["starting_capital"]

    for step in range(1, total + 1):
        idx = step - 1
        q = (step_configs[idx].get("quota") if idx < len(step_configs) else None) or mult

        if step in history_map:
            h = history_map[step]
            is_win = h["result"] == "win"
            state = "win" if is_win else "loss"
            cap_before = h["capital_before"]
            cap_after = h["capital_after"]
            sim_cap = cap_after
            wd = withdrawals.get(step)
            if wd:
                sim_cap = wd["restart_capital"]
        elif ps and step == ps["step"]:
            state = "pending"
            cap_before = ps["capital_before"]
            cap_after = round(cap_before * q, 2)
            wd = None
            # Don't advance sim_cap; will be set by future steps from cap_before
            sim_cap = cap_before
        else:
            state = "future"
            cap_before = round(sim_cap, 2)
            cap_after = round(sim_cap * q, 2)
            sim_cap = cap_after
            wd = withdrawals.get(step)
            if wd:
                sim_cap = wd["restart_capital"]

        steps.append({
            "step": step,
            "state": state,
            "cap_before": cap_before,
            "cap_after": cap_after,
            "wd": wd,
        })

    return steps


def generate_card(scalata: dict) -> io.BytesIO:
    total_steps = scalata["total_steps"]
    all_steps = _build_step_data(scalata)

    # ── Grid layout ───────────────────────────────────────────────────────────
    if total_steps <= 4:
        cols = 2
    elif total_steps <= 9:
        cols = 3
    elif total_steps <= 16:
        cols = 4
    else:
        cols = 5

    rows = (total_steps + cols - 1) // cols
    W = 900
    HEADER_H = 88
    STATS_H = 58
    CELL_W = (W - 48 - (cols - 1) * 8) // cols
    CELL_H = 68
    GAP = 8
    GRID_Y = HEADER_H + STATS_H + 14
    FOOTER_H = 36
    H = GRID_Y + rows * (CELL_H + GAP) - GAP + 14 + FOOTER_H

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    f28  = _font(28)
    f20  = _font(20)
    f16  = _font(16)
    f14  = _font(14)
    f13  = _font(13)
    f12  = _font(12)
    f11  = _font(11)

    # ── Header ────────────────────────────────────────────────────────────────
    draw.rectangle([(0, 0), (W, HEADER_H)], fill=PANEL)
    draw.rectangle([(0, HEADER_H - 2), (W, HEADER_H)], fill=BORDER)
    draw.text((24, 20), scalata["name"], font=f28, fill=TEXT)
    step_label = f"Step {scalata['current_step']}/{total_steps}"
    bbox = draw.textbbox((0, 0), step_label, font=f20)
    sw = bbox[2] - bbox[0]
    draw.text((W - sw - 24, 28), step_label, font=f20, fill=GOLD)

    # ── Stats row ─────────────────────────────────────────────────────────────
    safe_total = sum(
        w["amount"] for w in scalata.get("withdrawals", [])
        if w["after_step"] in {h["step"] for h in scalata.get("history", []) if h["result"] == "win"}
    )
    total_value = round(scalata["current_capital"] + safe_total, 2)

    stats = [
        ("Capitale", f"E{scalata['current_capital']:.2f}"),
        ("In tasca", f"E{safe_total:.2f}"),
        ("Totale", f"E{total_value:.2f}"),
        ("Molt.", f"x{scalata['multiplier']}"),
    ]
    col_w_stat = (W - 48) // 4
    y_stats = HEADER_H + 8
    for i, (lbl, val) in enumerate(stats):
        x = 24 + i * col_w_stat
        draw.text((x, y_stats), lbl, font=f11, fill=MUTED)
        draw.text((x, y_stats + 14), val, font=f20, fill=TEXT)

    # ── Step grid ─────────────────────────────────────────────────────────────
    for i, s in enumerate(all_steps):
        col = i % cols
        row_idx = i // cols
        x = 24 + col * (CELL_W + GAP)
        y = GRID_Y + row_idx * (CELL_H + GAP)

        state = s["state"]

        if state == "pending":
            bg = PEND_BG
            tc = PEND_TXT
            bc = PEND_BG
            bw = 2
            prefix = ">"
            cap_fmt = f"E{s['cap_before']:.2f}"
            cap_col = PEND_TXT
            after_fmt = f"->~E{s['cap_after']:.2f}"
            after_col = (80, 80, 80)
        elif state == "win":
            bg = PANEL
            tc = WIN_COL
            bc = WIN_COL
            bw = 1
            prefix = "W"
            cap_fmt = f"E{s['cap_before']:.2f}"
            cap_col = MUTED
            after_fmt = f"->E{s['cap_after']:.2f}"
            after_col = WIN_COL
        elif state == "loss":
            bg = (16, 16, 16)
            tc = LOSS_COL
            bc = DIM
            bw = 1
            prefix = "L"
            cap_fmt = f"E{s['cap_before']:.2f}"
            cap_col = LOSS_COL
            after_fmt = ""
            after_col = LOSS_COL
        else:  # future
            bg = PANEL
            tc = DIM
            bc = (35, 35, 35)
            bw = 1
            prefix = " "
            cap_fmt = f"~E{s['cap_before']:.2f}"
            cap_col = DIM
            after_fmt = f"->~E{s['cap_after']:.2f}"
            after_col = DIM

        draw.rectangle([(x, y), (x + CELL_W, y + CELL_H)], fill=bg, outline=bc, width=bw)

        # Step number line
        step_txt = f"{prefix} {s['step']}"
        draw.text((x + 7, y + 6), step_txt, font=f13, fill=tc)

        # Capital before
        draw.text((x + 7, y + 26), cap_fmt, font=f14, fill=cap_col)

        # Capital after (if available)
        if after_fmt:
            draw.text((x + 7, y + 46), after_fmt, font=f11, fill=after_col)

        # Withdrawal indicator (bottom-right of cell)
        if s["wd"]:
            wd_txt = f"-E{s['wd']['amount']:.0f}"
            draw.text((x + CELL_W - 46, y + CELL_H - 16), wd_txt, font=f11, fill=GOLD)

    # ── Footer ────────────────────────────────────────────────────────────────
    footer_y = H - FOOTER_H
    draw.rectangle([(0, footer_y), (W, H)], fill=PANEL)
    footer = (
        f"ID: {scalata['id']}  |  "
        f"In tasca: E{safe_total:.2f}  |  "
        f"Capitale: E{scalata['current_capital']:.2f}  |  "
        f"Totale: E{total_value:.2f}"
    )
    draw.text((24, footer_y + 11), footer, font=f12, fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

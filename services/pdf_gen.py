"""Generate a PDF report for a scalata using WeasyPrint."""

import io
from typing import Optional


def _outcome_label(code: Optional[str]) -> str:
    return {"1": "Casa", "X": "Pareggio", "2": "Ospite"}.get(code or "", code or "—")


def _all_steps_rows(scalata: dict) -> str:
    """Build HTML table rows for ALL steps: history + pending + future simulated."""
    total = scalata["total_steps"]
    step_configs = scalata.get("step_configs", [])
    mult = scalata["multiplier"]
    history_map = {h["step"]: h for h in scalata.get("history", [])}
    withdrawals = {w["after_step"]: w for w in scalata.get("withdrawals", [])}
    ps = scalata.get("pending_step")

    rows = []
    sim_cap = scalata["starting_capital"]

    for step in range(1, total + 1):
        idx = step - 1
        q = (step_configs[idx].get("quota") if idx < len(step_configs) else None) or mult

        if step in history_map:
            h = history_map[step]
            is_win = h["result"] == "win"
            icon = "OK" if is_win else "XX"
            match = h.get("match") or {}
            name = match.get("name", "—")
            bet = _outcome_label(match.get("outcome_bet"))
            actual = _outcome_label(match.get("outcome_actual"))
            cap_before = h["capital_before"]
            cap_after = h["capital_after"]
            row_cls = "win" if is_win else "loss"
            rows.append(f"""
        <tr class="{row_cls}">
          <td>[{icon}] {step}</td><td>{name}</td><td>{bet}</td>
          <td>{actual}</td><td>€{cap_before:.2f}</td><td>€{cap_after:.2f}</td>
        </tr>""")
            sim_cap = cap_after
            if step in withdrawals:
                w = withdrawals[step]
                rows.append(f"""
        <tr class="wd-row">
          <td colspan="6">Prelievo dopo Step {step}: -{w['amount']:.2f} euro | Riparti con {w['restart_capital']:.2f} euro</td>
        </tr>""")
                sim_cap = w["restart_capital"]

        elif ps and step == ps["step"]:
            match = ps.get("match") or {}
            match_name = match.get("name", "—")
            bet_type = match.get("bet_type") or match.get("outcome_bet") or "—"
            cap_before = ps["capital_before"]
            cap_after = round(cap_before * q, 2)
            rows.append(f"""
        <tr class="pending">
          <td>[..] {step}</td><td>{match_name}</td><td>{bet_type}</td>
          <td>In attesa</td><td>€{cap_before:.2f}</td><td>~€{cap_after:.2f}</td>
        </tr>""")
            sim_cap = cap_before

        else:
            cap_before = round(sim_cap, 2)
            cap_after = round(sim_cap * q, 2)
            rows.append(f"""
        <tr class="future">
          <td>[ ] {step}</td><td>—</td><td>—</td>
          <td>—</td><td>~€{cap_before:.2f}</td><td>~€{cap_after:.2f}</td>
        </tr>""")
            sim_cap = cap_after
            if step in withdrawals:
                w = withdrawals[step]
                rows.append(f"""
        <tr class="wd-row">
          <td colspan="6">Prelievo programmato dopo Step {step}: -{w['amount']:.2f} euro | Riparti con {w['restart_capital']:.2f} euro</td>
        </tr>""")
                sim_cap = w["restart_capital"]

    return "\n".join(rows)


def generate_pdf(scalata: dict) -> io.BytesIO:
    from weasyprint import HTML

    status_map = {
        "active": ("In Corso", "#6366f1"),
        "completed": ("Completata", "#22c55e"),
        "failed": ("Fallita", "#ef4444"),
    }
    status_label, status_color = status_map.get(scalata["status"], ("—", "#94a3b8"))

    safe_total = sum(
        w["amount"] for w in scalata.get("withdrawals", [])
        if w["after_step"] in {h["step"] for h in scalata.get("history", []) if h["result"] == "win"}
    )
    total_value = round(scalata["current_capital"] + safe_total, 2)

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Arial, Helvetica, sans-serif;
    font-size: 12px; color: #1e293b;
    padding: 32px 40px; line-height: 1.5;
  }}
  h1 {{ font-size: 24px; font-weight: 700; color: #0f172a; }}
  h2 {{ font-size: 14px; font-weight: 600; color: #475569; margin: 20px 0 8px;
        text-transform: uppercase; letter-spacing: .05em; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    color: white; font-weight: 600; background: {status_color};
    font-size: 11px; margin-left: 10px; vertical-align: middle;
  }}
  .stats-table {{ width: 100%; border-collapse: separate; border-spacing: 8px; margin: 16px 0; }}
  .stat {{
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px;
    padding: 12px; vertical-align: top; width: 20%;
  }}
  .stat .label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }}
  .stat .value {{ font-size: 18px; font-weight: 700; color: #0f172a; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
  th {{
    background: #1e293b; color: white; padding: 8px 10px;
    text-align: left; font-weight: 600;
  }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #f1f5f9; }}
  tr.win td {{ background: #f0fdf4; }}
  tr.loss td {{ background: #fff1f2; color: #94a3b8; }}
  tr.pending td {{ background: #eff6ff; }}
  tr.future td {{ color: #94a3b8; }}
  tr.wd-row td {{ background: #fefce8; color: #92400e; font-size: 11px; padding: 5px 10px; }}
  tr:last-child td {{ border-bottom: none; }}
  .footer {{ margin-top: 24px; color: #94a3b8; font-size: 10px; text-align: center; }}
  .progress-bar {{ height: 8px; background: #e2e8f0; border-radius: 4px; margin: 8px 0 4px; overflow: hidden; }}
  .progress-fill {{
    height: 100%; border-radius: 4px;
    background: {'#22c55e' if scalata['status'] != 'failed' else '#ef4444'};
    width: {min(100, int(scalata['current_step'] / scalata['total_steps'] * 100))}%;
  }}
</style>
</head>
<body>
  <h1>{scalata['name']} <span class="badge">{status_label}</span></h1>
  <p style="color:#64748b;margin-top:4px">
    Creata da {scalata['created_by_name']} · {scalata['created_at'][:10]}
    · ID: {scalata['id']}
  </p>

  <div class="progress-bar"><div class="progress-fill"></div></div>
  <p style="color:#64748b;font-size:10px">{scalata['current_step']} / {scalata['total_steps']} steps</p>

  <table class="stats-table">
    <tr>
      <td class="stat">
        <div class="label">Capitale Attuale</div>
        <div class="value">€{scalata['current_capital']:.2f}</div>
      </td>
      <td class="stat">
        <div class="label">In Tasca</div>
        <div class="value">€{safe_total:.2f}</div>
      </td>
      <td class="stat">
        <div class="label">Totale Complessivo</div>
        <div class="value">€{total_value:.2f}</div>
      </td>
      <td class="stat">
        <div class="label">Moltiplicatore</div>
        <div class="value">x{scalata['multiplier']}</div>
      </td>
      <td class="stat">
        <div class="label">Capitale Iniziale</div>
        <div class="value">€{scalata['starting_capital']:.2f}</div>
      </td>
    </tr>
  </table>

  <h2>Tutti gli Step</h2>
  <table>
    <thead>
      <tr>
        <th>Step</th><th>Match</th><th>Scommessa</th>
        <th>Risultato</th><th>Cap. Prima</th><th>Cap. Dopo</th>
      </tr>
    </thead>
    <tbody>
      {_all_steps_rows(scalata)}
    </tbody>
  </table>

  <div class="footer">Generato da ScalataBot · {scalata['name']}</div>
</body>
</html>"""

    pdf_bytes = HTML(string=html).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf

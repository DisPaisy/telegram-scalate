"""Generate a PDF report for a scalata using WeasyPrint."""

import io
from typing import Optional


def _outcome_label(code: Optional[str]) -> str:
    return {"1": "Casa", "X": "Pareggio", "2": "Ospite"}.get(code or "", code or "—")


def _history_rows(scalata: dict) -> str:
    rows = []
    for h in scalata.get("history", []):
        is_win = h["result"] == "win"
        icon = "✅" if is_win else "❌"
        match = h.get("match") or {}
        name = match.get("name", "—")
        bet = _outcome_label(match.get("outcome_bet"))
        actual = _outcome_label(match.get("outcome_actual"))
        auto = "🤖" if match.get("auto_resolved") else "👤"
        rows.append(f"""
        <tr class="{'win' if is_win else 'loss'}">
          <td>{icon} {h['step']}</td>
          <td>{name}</td>
          <td>{bet}</td>
          <td>{actual} {auto}</td>
          <td>€{h['capital_before']:.2f}</td>
          <td>€{h['capital_after']:.2f}</td>
        </tr>""")
    return "\n".join(rows)


def _withdrawal_rows(scalata: dict) -> str:
    rows = []
    for w in scalata.get("withdrawals", []):
        rows.append(f"""
        <tr>
          <td>Dopo Step {w['after_step']}</td>
          <td>€{w['amount']:.2f}</td>
          <td>€{w['restart_capital']:.2f}</td>
        </tr>""")
    return "\n".join(rows) or "<tr><td colspan='3'>Nessuna</td></tr>"


def generate_pdf(scalata: dict) -> io.BytesIO:
    from weasyprint import HTML

    status_map = {
        "active": ("In Corso", "#6366f1"),
        "completed": ("Completata 🏆", "#22c55e"),
        "failed": ("Fallita ❌", "#ef4444"),
    }
    status_label, status_color = status_map.get(scalata["status"], ("—", "#94a3b8"))

    from services.storage import compute_bet
    bet_amount = (
        compute_bet(scalata["current_capital"], scalata["multiplier"])
        if scalata["status"] == "active"
        else 0.0
    )

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: 'Inter', sans-serif;
    font-size: 12px;
    color: #1e293b;
    padding: 32px 40px;
    line-height: 1.5;
  }}
  h1 {{ font-size: 24px; font-weight: 700; color: #0f172a; }}
  h2 {{ font-size: 14px; font-weight: 600; color: #475569; margin: 20px 0 8px; text-transform: uppercase; letter-spacing: .05em; }}
  .badge {{
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    color: white;
    font-weight: 600;
    background: {status_color};
    font-size: 11px;
    margin-left: 10px;
    vertical-align: middle;
  }}
  .stats {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin: 16px 0;
  }}
  .stat {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px;
  }}
  .stat .label {{ font-size: 10px; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }}
  .stat .value {{ font-size: 18px; font-weight: 700; color: #0f172a; margin-top: 4px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
  }}
  th {{
    background: #1e293b;
    color: white;
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
  }}
  td {{ padding: 7px 10px; border-bottom: 1px solid #f1f5f9; }}
  tr.win td {{ background: #f0fdf4; }}
  tr.loss td {{ background: #fff1f2; }}
  tr:last-child td {{ border-bottom: none; }}
  .footer {{ margin-top: 24px; color: #94a3b8; font-size: 10px; text-align: center; }}
  .progress-bar {{
    height: 8px;
    background: #e2e8f0;
    border-radius: 4px;
    margin: 8px 0 4px;
    overflow: hidden;
  }}
  .progress-fill {{
    height: 100%;
    background: {'#22c55e' if scalata['status'] != 'failed' else '#ef4444'};
    border-radius: 4px;
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

  <div class="stats">
    <div class="stat">
      <div class="label">Capitale Iniziale</div>
      <div class="value">€{scalata['starting_capital']:.2f}</div>
    </div>
    <div class="stat">
      <div class="label">Capitale Attuale</div>
      <div class="value">€{scalata['current_capital']:.2f}</div>
    </div>
    <div class="stat">
      <div class="label">Moltiplicatore</div>
      <div class="value">×{scalata['multiplier']}</div>
    </div>
    <div class="stat">
      <div class="label">{'Prossima Puntata' if scalata['status'] == 'active' else 'Step'}</div>
      <div class="value">{'€' + str(bet_amount) if scalata['status'] == 'active' else scalata['current_step']}</div>
    </div>
  </div>

  <h2>Storico Steps</h2>
  <table>
    <thead>
      <tr>
        <th>Step</th>
        <th>Match</th>
        <th>Scommessa</th>
        <th>Risultato</th>
        <th>Cap. Prima</th>
        <th>Cap. Dopo</th>
      </tr>
    </thead>
    <tbody>
      {_history_rows(scalata)}
    </tbody>
  </table>

  <h2>Prelievi Programmati</h2>
  <table>
    <thead>
      <tr>
        <th>Quando</th>
        <th>Importo Prelievo</th>
        <th>Capitale Ripartenza</th>
      </tr>
    </thead>
    <tbody>
      {_withdrawal_rows(scalata)}
    </tbody>
  </table>

  <div class="footer">Generato da ScalataBot · {scalata['name']}</div>
</body>
</html>"""

    pdf_bytes = HTML(string=html).write_pdf()
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf

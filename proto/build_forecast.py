"""Orb v1: publish the hashed Madrid pre-race forecast (roadmap v5 task 0.13 / F2).
Reads out/lock.json (live block + strategy) and out/lock_v2.json (forecast_hash); writes
out/forecast_<event>_2026.json, out/forecast_<event>_2026.pdf and out/forecast_<event>_2026.sha256.
Run after the last pre-race refresh, before the race. Lead-only."""
import hashlib, json, sys
from datetime import datetime
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

OUT = Path('out'); EVENT = sys.argv[1] if len(sys.argv) > 1 else 'Madrid'
L = json.load(open(OUT / 'lock.json')); V2 = json.load(open(OUT / 'lock_v2.json'))
live = L['live'][EVENT]; assert live['meta']['event'] == EVENT, live['meta']['event']
strat = L['strategy'][EVENT]; views = strat['views']

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

now = datetime.now().astimezone()
comps = [dict(compound=c['compound'], prediction_s_per_lap=round(c['prediction'], 4), band90=[round(b, 4) for b in c['band90']],
              issued=c['issued'], gate=c['gate'], basis=c['basis'], clean_practice_laps=c['n_prac'],
              second_opinion=(round(c['second_opinion']['prediction'], 4) if c.get('second_opinion') else None)) for c in live['compounds']]
plan = views['Orb v1']; lo = views['Orb v1, band low']; hi = views['Orb v1, band high']
doc = dict(
    product='Orb v1 (team FireBolt)', event=f'{EVENT} 2026', kind='pre-race tyre-degradation forecast',
    issued_at=now.isoformat(timespec='seconds'), lock_generated_at=L['generated_at'], sessions_used=live['meta']['sessions'],
    lock_v2_forecast_hash=V2['shared']['forecast_hash'], lock_v2_sha256=sha(OUT / 'lock_v2.json'), lock_sha256=sha(OUT / 'lock.json'),
    rules=L['rules'], compounds=comps,
    strategy=dict(race_laps=strat['n_laps'], pit_loss_s=strat['pit_loss'], offsets_s=strat['offsets'], offsets_source=strat['offsets_source'],
                  central=dict(plan=plan['plan'], stints=plan['stints'], stops=plan['stops'], crossover_lap=plan['crossover'],
                               margin_over_next_family_s=round(next((a['delta_to_best'] for a in plan['alternatives'] if a['stops'] != plan['stops']), float('nan')), 1)),
                  band_low=dict(plan=lo['plan'], stints=lo['stints']), band_high=dict(plan=hi['plan'], stints=hi['stints']),
                  assumptions=['linear degradation curves', 'no safety car', 'no traffic', 'standard pit loss', 'fuel and evolution corrected per lock rules'],
                  note=strat.get('note')),
    scoring=dict(when='after the race, same estimator on race laps, all drivers', reference='race-derived pace-loss reference (not ground truth)',
                 published='whatever it says, with the miss'),
)
jpath = OUT / f'forecast_{EVENT}_2026.json'; jpath.write_text(json.dumps(doc, indent=1, ensure_ascii=False)); jsha = sha(jpath)

# one-page PDF
ss = getSampleStyleSheet(); body = ParagraphStyle('b', parent=ss['BodyText'], fontSize=9.5, leading=12); small = ParagraphStyle('s', parent=body, fontSize=8, leading=10, textColor=colors.grey)
S = [Paragraph(f'Orb v1 pre-race forecast: {EVENT} 2026', ss['Title']),
     Paragraph(f'Issued {doc["issued_at"]} from sessions {", ".join(doc["sessions_used"])}. Lock built {doc["lock_generated_at"]}. '
               f'Forecast hash (lock v2) {doc["lock_v2_forecast_hash"]}. This document is frozen before the race and scored after it.', body), Spacer(1, 8)]
rows = [['Compound', 'Race degradation (s/lap of age)', '90% band', 'Status', 'Clean Friday laps', 'Basis']]
for c in comps:
    rows.append([c['compound'], f'{c["prediction_s_per_lap"]:+.3f}', f'{c["band90"][0]:+.3f} to {c["band90"][1]:+.3f}', 'issued' if c['issued'] else 'withheld (fallback)', str(c['clean_practice_laps']), Paragraph(c['basis'], small)])
t = Table(rows, colWidths=[55, 110, 90, 80, 70, 130]); t.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.3, colors.grey), ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDE3EA')), ('FONTSIZE', (0, 0), (-1, -1), 8.5), ('VALIGN', (0, 0), (-1, -1), 'TOP')]))
S += [t, Spacer(1, 10), Paragraph('<b>Strategy on the central curve.</b> ' + f'{plan["plan"]} with stints {plan["stints"]} over {strat["n_laps"]} laps; pit loss {strat["pit_loss"]:.0f} s; '
      f'compound offsets {json.dumps(strat["offsets"])} s ({"; ".join(f"{k}: {v}" for k, v in strat["offsets_source"].items())}). '
      f'Low edge of the band: {lo["plan"]} {lo["stints"]}; high edge: {hi["plan"]} {hi["stints"]}. Assumptions: linear curves, no safety car, no traffic.', body), Spacer(1, 6),
      Paragraph('<b>Rules.</b> ' + ', '.join(f'{k} = {v}' for k, v in L['rules'].items()), small), Spacer(1, 6),
      Paragraph(f'<b>Integrity.</b> JSON sha256 {jsha}; lock.json sha256 {doc["lock_sha256"]}; lock_v2.json sha256 {doc["lock_v2_sha256"]}. '
                'Scoring after the race uses the same estimator on race laps (race-derived pace-loss reference, all drivers) and is published whatever it says.', small)]
ppath = OUT / f'forecast_{EVENT}_2026.pdf'; SimpleDocTemplate(str(ppath), pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36).build(S)
(OUT / f'forecast_{EVENT}_2026.sha256').write_text(f'{jsha}  {jpath.name}\n{sha(ppath)}  {ppath.name}\n')
print(f'published {jpath.name} ({jsha[:16]}...), {ppath.name}, sessions {live["meta"]["sessions"]}, issued at {doc["issued_at"]}')
for c in comps: print(f'  {c["compound"]:6s} {c["prediction_s_per_lap"]:+.3f} [{c["band90"][0]:+.3f}, {c["band90"][1]:+.3f}] {"issued" if c["issued"] else "withheld"} n={c["clean_practice_laps"]}')
print(f'  plan {plan["plan"]} {plan["stints"]} | band low {lo["plan"]} {lo["stints"]} | band high {hi["plan"]} {hi["stints"]}')

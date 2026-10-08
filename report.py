"""Generate a self-contained HTML dashboard (dashboard.html) from sysmon.db.

Usage: python report.py [--db sysmon.db] [--hours 24]
"""
import argparse, html, sqlite3
from datetime import datetime, timedelta, timezone

def sparkline(values, w=160, h=32):
    pts = [v for v in values if v is not None]
    if len(pts) < 2:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1
    step = w / (len(values) - 1)
    coords = []
    for i, v in enumerate(values):
        if v is None:
            continue
        coords.append(f"{i*step:.1f},{h-2-((v-lo)/span)*(h-4):.1f}")
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline fill="none" stroke="#2f6fed" stroke-width="1.5" points="{" ".join(coords)}"/></svg>')

def build(db_path, hours):
    db = sqlite3.connect(db_path)
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    targets = [r[0] for r in db.execute("SELECT DISTINCT target FROM checks ORDER BY target")]
    cards = []
    for t in targets:
        rows = db.execute("SELECT ok, latency_ms, detail, ts FROM checks WHERE target=? AND ts>=? ORDER BY id", (t, since)).fetchall()
        if not rows:
            continue
        total = len(rows)
        up = sum(r[0] for r in rows)
        lat = [r[1] for r in rows if r[1] is not None]
        avg = sum(lat) / len(lat) if lat else 0
        last = rows[-1]
        status = "UP" if last[0] else "DOWN"
        cards.append(
            f'<div class="card {status.lower()}"><h3>{html.escape(t)}</h3>'
            f'<div class="status">{status}</div>'
            f'<div>Uptime ({hours}h): <b>{up/total*100:.2f}%</b> ({up}/{total} checks)</div>'
            f'<div>Avg latency: <b>{avg:.0f} ms</b></div>'
            f'<div class="muted">Last: {html.escape(last[2])}<br>{last[3]}</div>'
            f'{sparkline([r[1] for r in rows][-60:])}</div>')
    inc = db.execute("SELECT target, opened, closed, reason FROM incidents ORDER BY id DESC LIMIT 20").fetchall()
    inc_rows = "".join(
        f"<tr><td>{html.escape(a)}</td><td>{b}</td><td>{c or '<b style=color:#c0392b>OPEN</b>'}</td><td>{html.escape(d or '')}</td></tr>"
        for a, b, c, d in inc) or '<tr><td colspan="4">No incidents recorded.</td></tr>'
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>IT Systems Availability Monitoring and Incident Reporting System</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;background:#f5f7fa;color:#222}}
h1{{margin-top:0}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}}
.card{{background:#fff;border-radius:8px;padding:14px;border-left:6px solid #2e9e5b;box-shadow:0 1px 3px #0002}}
.card.down{{border-color:#c0392b}}.status{{font-weight:bold;font-size:20px;margin:4px 0}}
.up .status{{color:#2e9e5b}}.down .status{{color:#c0392b}}.muted{{color:#777;font-size:12px;margin:6px 0}}
table{{border-collapse:collapse;width:100%;background:#fff}}td,th{{border:1px solid #ddd;padding:6px 8px;text-align:left;font-size:13px}}
th{{background:#1f3a5f;color:#fff}}</style></head><body>
<h1>IT Systems Availability Monitoring and Incident Reporting System</h1><h2 style='margin-top:0;font-weight:normal;color:#555'>Availability dashboard</h2><p class="muted">Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} - last {hours} hours</p>
<div class="grid">{''.join(cards) or '<p>No data yet. Run sysmon.py first.</p>'}</div>
<h2>Recent incidents</h2><table><tr><th>Service</th><th>Opened (UTC)</th><th>Closed (UTC)</th><th>Reason</th></tr>{inc_rows}</table>
</body></html>"""
    with open("dashboard.html", "w", encoding="utf-8") as f:
        f.write(page)
    print("Wrote dashboard.html")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sysmon.db")
    ap.add_argument("--hours", type=int, default=24)
    a = ap.parse_args()
    build(a.db, a.hours)

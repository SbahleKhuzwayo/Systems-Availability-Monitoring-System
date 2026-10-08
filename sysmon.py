"""IT Systems Availability Monitoring and Incident Reporting System (SAMS).

Checks websites (HTTP) and services (TCP ports) on a schedule, stores every
result in SQLite, opens an incident after N consecutive failures, closes it
when the service recovers, and logs alerts.

Usage:
    python sysmon.py --once            # run all checks one time
    python sysmon.py                   # run forever (Ctrl+C to stop)
    python sysmon.py --config my.json
"""
import argparse, json, logging, socket, sqlite3, time, urllib.request, urllib.error
from datetime import datetime, timezone

DB_FILE = "sysmon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    ts TEXT NOT NULL,
    ok INTEGER NOT NULL,
    latency_ms REAL,
    detail TEXT
);
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target TEXT NOT NULL,
    opened TEXT NOT NULL,
    closed TEXT,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_checks_target_ts ON checks(target, ts);
"""

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def get_db(path=DB_FILE):
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    return db

def check_http(url, timeout):
    """Return (ok, latency_ms, detail). Success = HTTP status below 400."""
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "sysmon/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ms = (time.perf_counter() - start) * 1000
            return resp.status < 400, ms, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, (time.perf_counter() - start) * 1000, f"HTTP {e.code}"
    except Exception as e:  # DNS failure, refused, timeout, SSL error...
        return False, None, f"{type(e).__name__}: {e}"

def check_tcp(host, port, timeout):
    """Return (ok, latency_ms, detail). Success = TCP connection opens."""
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, (time.perf_counter() - start) * 1000, f"port {port} open"
    except Exception as e:
        return False, None, f"{type(e).__name__}: {e}"

def run_check(target, timeout):
    if target["type"] == "http":
        return check_http(target["url"], timeout)
    if target["type"] == "tcp":
        return check_tcp(target["host"], target["port"], timeout)
    return False, None, f"unknown type {target['type']}"

def open_incident(db, name):
    return db.execute("SELECT id FROM incidents WHERE target=? AND closed IS NULL", (name,)).fetchone()

def recent_failures(db, name, n):
    rows = db.execute("SELECT ok FROM checks WHERE target=? ORDER BY id DESC LIMIT ?", (name, n)).fetchall()
    return len(rows) == n and all(r[0] == 0 for r in rows)

def process(db, cfg, target):
    name = target["name"]
    ok, ms, detail = run_check(target, cfg["timeout_seconds"])
    db.execute("INSERT INTO checks(target, ts, ok, latency_ms, detail) VALUES (?,?,?,?,?)",
               (name, now(), int(ok), ms, detail))
    n = cfg["failures_before_incident"]
    inc = open_incident(db, name)
    if not ok and not inc and recent_failures(db, name, n):
        db.execute("INSERT INTO incidents(target, opened, reason) VALUES (?,?,?)", (name, now(), detail))
        logging.error("INCIDENT OPENED: %s is DOWN (%s)", name, detail)
    elif ok and inc:
        db.execute("UPDATE incidents SET closed=? WHERE id=?", (now(), inc[0]))
        logging.warning("INCIDENT CLOSED: %s has RECOVERED", name)
    elif ok and ms and ms > cfg["latency_warn_ms"]:
        logging.warning("SLOW: %s took %.0f ms", name, ms)
    else:
        logging.info("%s: %s (%s)", name, "UP" if ok else "FAIL", detail)
    db.commit()
    return ok

def run_once(db, cfg):
    return [process(db, cfg, t) for t in cfg["targets"]]

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="config.json")
    ap.add_argument("--db", default=DB_FILE)
    ap.add_argument("--once", action="store_true", help="run one round of checks and exit")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("alerts.log")])
    with open(args.config) as f:
        cfg = json.load(f)
    db = get_db(args.db)
    if args.once:
        run_once(db, cfg)
        return
    logging.info("Monitoring %d targets every %ss", len(cfg["targets"]), cfg["interval_seconds"])
    try:
        while True:
            run_once(db, cfg)
            time.sleep(cfg["interval_seconds"])
    except KeyboardInterrupt:
        logging.info("Stopped.")

if __name__ == "__main__":
    main()

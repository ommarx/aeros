"""Run AEROS locally.  python cli.py --simulate | --watch events.csv"""
import os, sys, csv, json, time, random, argparse
from datetime import date, timedelta
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "api"))
from _aeros import Monitor, validate, deliver, format_msg

mon = Monitor(limit=int(os.getenv("AEROS_LAG_LIMIT_DAYS", "14")))
COOLDOWN, last = int(os.getenv("AEROS_COOLDOWN_SEC", "0")), {}


def handle(raw):
    for r in mon.process(validate(raw), use_llm=True, max_llm=None):
        k = (r["process"], r["rule"])
        if COOLDOWN and time.time() - last.get(k, 0) < COOLDOWN:
            continue
        last[k] = time.time()
        os.makedirs("logs", exist_ok=True)
        open("logs/alerts.jsonl", "a").write(json.dumps(r) + "\n")
        print(format_msg(r) + "\n")
        deliver(r)


def simulate(n=60):
    random.seed(11)
    procs, base = ["Rewards crediting", "Benefits fulfilment", "Vendor data access", "Fee billing"], date(2026, 9, 1)
    for i in range(1, n + 1):
        p, exp = random.choice(procs), random.choice([500, 1200, 3000])
        rate = 0.30 if p == "Rewards crediting" and 25 < i < 45 else 0.05
        act = exp - random.choice([50, 100, 300]) if random.random() < rate else exp
        occ = base + timedelta(days=random.randint(0, 20))
        det = (occ + timedelta(days=random.choice([2, 5, 21, 30]))).isoformat() if act != exp else ""
        handle(dict(id=f"EV-{i:03d}", process=p, expected=exp, actual=act, occurred=occ.isoformat(), detected=det))
        time.sleep(0.05)


def watch(path):
    seen = 0
    print(f"watching {path} (Ctrl+C to stop)")
    while True:
        if os.path.exists(path):
            rows = list(csv.DictReader(open(path)))
            for r in rows[seen:]:
                handle(r)
            seen = len(rows)
        time.sleep(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--watch")
    a = ap.parse_args()
    simulate() if a.simulate else watch(a.watch) if a.watch else ap.print_help()

"""Send a CSV of control events to AEROS in small batches.
  python tools/send.py events.csv            # live: needs AEROS_API_TOKEN in your environment
  python tools/send.py events.csv --dry-run  # no alerts, no AI, no token needed
Env: AEROS_URL (default https://aeros-peach.vercel.app/api/ingest), AEROS_API_TOKEN.
CSV columns: id,process,expected,actual,occurred,detected  (dates YYYY-MM-DD, detected may be blank).
Accepted ids go in sent.txt so a re-run never re-sends them. Bad rows are logged in rejected.log and skipped on
later runs (fix the row and give it a new id to send it)."""
import csv, json, os, sys, urllib.error, urllib.request

URL = os.getenv("AEROS_URL", "https://aeros-peach.vercel.app/api/ingest")
dry = "--dry-run" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args:
    sys.exit(__doc__)
token = os.getenv("AEROS_API_TOKEN", "")
if not dry and not token:
    sys.exit("Set AEROS_API_TOKEN in your environment first (export AEROS_API_TOKEN=...), or use --dry-run.")
seen = set()
for f in ("sent.txt", "rejected_ids.txt"):
    if os.path.exists(f):
        seen |= set(open(f).read().split())
rows = [r for r in csv.DictReader(open(args[0])) if r.get("id") and r["id"] not in seen]
print(f"{len(rows)} new row(s) to send ({'dry run' if dry else 'LIVE'})")
for i in range(0, len(rows), 50):
    batch = rows[i:i + 50]
    headers = {"content-type": "application/json"}
    if not dry:
        headers["authorization"] = f"Bearer {token}"
    req = urllib.request.Request(URL, json.dumps({"dry_run": dry, "skip_invalid": True, "events": batch}).encode(), headers)
    try:
        res = json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        sys.exit(f"Stopped. Server said {e.code}: {e.read().decode()[:300]}\nNothing from this batch was marked as sent.")
    except Exception as e:
        sys.exit(f"Stopped. Could not reach the server: {e}\nNothing from this batch was marked as sent.")
    bad = {r["index"] for r in res.get("rejected", [])}
    with open("rejected.log", "a") as f, open("rejected_ids.txt", "a") as g:
        for r in res.get("rejected", []):
            f.write(f"{batch[r['index']].get('id')}: {r['error']}\n")
            g.write(f"{batch[r['index']].get('id')}\n")
    if not dry:
        with open("sent.txt", "a") as f:
            f.write("".join(r["id"] + "\n" for j, r in enumerate(batch) if j not in bad))
    print(f"batch {i // 50 + 1}: {res['events']} accepted, {len(bad)} rejected, {len(res['alerts'])} alert(s), "
          f"delivered via {res['delivered'] or 'nothing (dry run or no channel set)'}")

"""POST /api/ingest  {"events":[...], "dry_run": true|false, "skip_invalid": false, "limit_days": 14}
GET  /api/ingest    health check

Safety defaults:
- dry_run (the default) uses rule-based triage only and sends NO alerts and makes NO AI calls.
- Live mode (alerts + Claude triage) needs AEROS_API_TOKEN set on the server and sent as
  'Authorization: Bearer <token>'. Without the token, live mode is disabled.
- Unauthenticated dry runs are small (50 events, 20 KB) and rate limited per client (best effort:
  in-memory per instance; add a Vercel WAF rate-limit rule for a hard limit).
"""
import os, sys, json, hmac, time
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler
from _aeros import Monitor, validate, deliver_digest

LIVE_EVENTS, LIVE_BODY = 200, 100_000
DRY_EVENTS, DRY_BODY = 50, 20_000
RATE_N, RATE_S = 30, 60
_hits = defaultdict(deque)


def _limited(ip):
    now = time.monotonic()
    if len(_hits) > 1000:
        _hits.clear()
    q = _hits[ip]
    while q and now - q[0] > RATE_S:
        q.popleft()
    if len(q) >= RATE_N:
        return True
    q.append(now)
    return False


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep request lines out of logs
        pass

    def do_GET(self):
        self._send(200, dict(service="aeros", status="ok"))

    def do_POST(self):
        ip = (self.headers.get("x-forwarded-for", "").split(",")[0].strip() or self.client_address[0])
        try:
            n = int(self.headers.get("content-length", 0))
            if n <= 0:
                return self._send(400, dict(error="empty body"))
            if n > LIVE_BODY:
                return self._send(413, dict(error="body too large"))
            data = json.loads(self.rfile.read(n))
            if not isinstance(data, dict):
                return self._send(400, dict(error="body must be a JSON object"))
            events = data.get("events")
            live = data.get("dry_run") is False
            if live:
                token = os.getenv("AEROS_API_TOKEN", "")
                sent = self.headers.get("authorization", "").removeprefix("Bearer ").strip()
                if not token or not hmac.compare_digest(sent.encode(), token.encode()):
                    if _limited(ip):
                        return self._send(429, dict(error="too many requests"))
                    return self._send(401, dict(error="live mode needs a valid bearer token; use dry_run for demos"))
                max_events = LIVE_EVENTS
            else:
                if n > DRY_BODY:
                    return self._send(413, dict(error="demo requests are limited to 20 KB"))
                if _limited(ip):
                    return self._send(429, dict(error="too many requests, slow down"))
                max_events = DRY_EVENTS
            if not isinstance(events, list) or not events or len(events) > max_events:
                return self._send(400, dict(error=f"'events' must be a list of 1 to {max_events} items"))

            good, rejected = [], []
            for i, raw in enumerate(events):
                try:
                    good.append(validate(raw))
                except ValueError as ex:
                    rejected.append(dict(index=i, error=str(ex)))
            if rejected and data.get("skip_invalid") is not True:
                return self._send(400, dict(error="invalid events", rejected=rejected[:5]))

            limit = max(1, min(365, int(data.get("limit_days", os.getenv("AEROS_LAG_LIMIT_DAYS", 14)))))
            tol = data.get("tolerance")
            mon = Monitor(limit=limit, tolerance=None if tol is None else max(0.0, min(1e6, float(tol))),
                          max_llm=5, deadline_s=20)
            alerts = [a for e in good for a in mon.process(e)]
            for a in alerts:
                a["triage"] = mon.rule_triage(a["process"])
            delivered = []
            if live:
                mon.enrich(alerts)
                delivered = deliver_digest(alerts)
            self._send(200, dict(mode="live" if live else "dry_run", events=len(good), rejected=rejected,
                                 alerts=alerts, delivered=delivered, ai_calls=mon.llm_used))
        except (ValueError, KeyError, TypeError) as ex:
            self._send(400, dict(error=str(ex)))
        except Exception as ex:
            print("ingest error:", type(ex).__name__, file=sys.stderr)
            self._send(500, dict(error="internal error"))

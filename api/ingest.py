"""POST /api/ingest  {"events":[...], "dry_run": true|false}
GET  /api/ingest    health check

Safety defaults:
- dry_run (the default) uses rule-based triage only and sends NO alerts and makes NO AI calls.
- Live mode (alerts + Claude triage) requires AEROS_API_TOKEN to be set on the server and sent as
  'Authorization: Bearer <token>'. Without the token, live mode is disabled.
"""
import os, json, hmac
from http.server import BaseHTTPRequestHandler
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _aeros import Monitor, validate, deliver

MAX_EVENTS, MAX_BODY = 200, 100_000


class handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, dict(service="aeros", status="ok", live_mode=bool(os.getenv("AEROS_API_TOKEN"))))

    def do_POST(self):
        try:
            n = int(self.headers.get("content-length", 0))
            if n <= 0 or n > MAX_BODY:
                return self._send(413 if n > MAX_BODY else 400, dict(error="body must be 1 to 100000 bytes"))
            data = json.loads(self.rfile.read(n))
            events = data.get("events")
            if not isinstance(events, list) or not events or len(events) > MAX_EVENTS:
                return self._send(400, dict(error=f"'events' must be a list of 1 to {MAX_EVENTS} items"))
            live = data.get("dry_run") is False
            if live:
                token = os.getenv("AEROS_API_TOKEN", "")
                sent = self.headers.get("authorization", "").removeprefix("Bearer ").strip()
                if not token or not hmac.compare_digest(sent.encode(), token.encode()):
                    return self._send(401, dict(error="live mode needs a valid bearer token; use dry_run for demos"))
            limit = max(1, min(365, int(data.get("limit_days", os.getenv("AEROS_LAG_LIMIT_DAYS", 14)))))
            mon, alerts = Monitor(limit=limit), []
            for e in map(validate, events):
                alerts += mon.process(e, use_llm=live)
            if live:
                for a in alerts:
                    a["delivered"] = deliver(a)
            self._send(200, dict(mode="live" if live else "dry_run", events=len(events), alerts=alerts))
        except (ValueError, KeyError, TypeError) as ex:
            self._send(400, dict(error=str(ex)))
        except Exception:
            self._send(500, dict(error="internal error"))

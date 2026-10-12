"""AEROS API v1.   POST /api/ingest  (also /api/v1/ingest)   GET /api/ingest  (health)

Body: {"events":[...], "dry_run": true|false, "skip_invalid": false, "limit_days": 14, "tolerance": 0.005}

Safety defaults
- dry_run (the default) uses rule-based triage only: NO alerts, NO AI calls, no token needed.
- Live mode (alerts + Claude triage) needs a client token: AEROS_API_TOKENS='acme:<token>,beta:<token>'
  (or the single AEROS_API_TOKEN). Tokens must be 32+ characters. Sent as 'Authorization: Bearer <token>'.
- Every request gets a request_id (also in the x-request-id header) and one structured audit line on stderr
  containing counts and the client name only: never event contents, tokens or IP addresses.
"""
import os, re, sys, json, time, uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

# Vercel's Python runtime does not put this folder on sys.path, so add it before importing the sibling module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _aeros import Monitor, validate, deliver_digest, parse_tokens, authenticate  # noqa: E402

API_VERSION = "1"
LIVE_EVENTS, LIVE_BODY = 200, 100_000
DRY_EVENTS, DRY_BODY = 50, 20_000
RATE_S, RATE_DRY, RATE_CLIENT = 60, 30, 60
_hits = defaultdict(deque)
_RID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _limited(key, n):
    now = time.monotonic()
    if len(_hits) > 1000:
        _hits.clear()
    q = _hits[key]
    while q and now - q[0] > RATE_S:
        q.popleft()
    if len(q) >= n:
        return True
    q.append(now)
    return False


class handler(BaseHTTPRequestHandler):
    rid, client, status, info, t0, audited = "-", "-", 0, {}, 0.0, False

    # ---- plumbing ----
    def log_message(self, *a):
        pass

    def _reply(self, code, obj):
        self.status = code
        self._audit()          # log first, so the line exists before the client sees the response
        obj["request_id"] = self.rid
        body = json.dumps(obj).encode()
        self.send_response(code)
        for k, v in (("content-type", "application/json"), ("content-length", str(len(body))),
                     ("cache-control", "no-store"), ("x-content-type-options", "nosniff"),
                     ("x-request-id", self.rid), ("x-aeros-api-version", API_VERSION)):
            self.send_header(k, v)
        if code == 429:
            self.send_header("retry-after", str(RATE_S))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, http, code, message, **extra):
        self._reply(http, dict(error=dict(code=code, message=message), **extra))

    def _begin(self):
        given = self.headers.get("x-request-id", "")
        self.rid = given if _RID.match(given) else uuid.uuid4().hex[:16]
        self.client, self.status, self.info, self.t0, self.audited = "-", 0, {}, time.monotonic(), False

    def _audit(self):
        if self.audited:
            return
        self.audited = True
        print(json.dumps(dict(ts=datetime.now(timezone.utc).isoformat(timespec="seconds"), request_id=self.rid,
                              client=self.client, method=self.command, status=self.status,
                              ms=round((time.monotonic() - self.t0) * 1000), **self.info)), file=sys.stderr)

    # ---- routes ----
    def do_GET(self):
        self._begin()
        self._reply(200, dict(service="aeros", status="ok", api_version=API_VERSION))

    def do_POST(self):
        self._begin()
        try:
            self._post()
        except (ValueError, KeyError, TypeError) as ex:
            self._fail(400, "bad_request", str(ex))
        except Exception as ex:
            print("ingest error:", type(ex).__name__, self.rid, file=sys.stderr)
            self._fail(500, "internal_error", "internal error")

    def _post(self):
        ip = self.headers.get("x-forwarded-for", "").split(",")[0].strip() or self.client_address[0]
        n = int(self.headers.get("content-length", 0))
        if n <= 0:
            return self._fail(400, "empty_body", "empty body")
        if n > LIVE_BODY:
            return self._fail(413, "body_too_large", "body too large")
        data = json.loads(self.rfile.read(n))
        if not isinstance(data, dict):
            return self._fail(400, "bad_request", "body must be a JSON object")
        events, live = data.get("events"), data.get("dry_run") is False
        if live:
            tokens = parse_tokens(os.getenv("AEROS_API_TOKENS", ""), os.getenv("AEROS_API_TOKEN", ""))
            who = authenticate(self.headers.get("authorization", ""), tokens)
            if who is None:
                if _limited("ip:" + ip, RATE_DRY):
                    return self._fail(429, "rate_limited", "too many requests")
                return self._fail(401, "unauthorized", "live mode needs a valid bearer token; use dry_run for demos")
            self.client = who
            if _limited("client:" + who, RATE_CLIENT):
                return self._fail(429, "rate_limited", "too many requests for this client")
            max_events = LIVE_EVENTS
        else:
            if n > DRY_BODY:
                return self._fail(413, "body_too_large", "demo requests are limited to 20 KB")
            if _limited("ip:" + ip, RATE_DRY):
                return self._fail(429, "rate_limited", "too many requests, slow down")
            max_events = DRY_EVENTS
        if not isinstance(events, list) or not events or len(events) > max_events:
            return self._fail(400, "bad_events", f"'events' must be a list of 1 to {max_events} items")

        good, rejected = [], []
        for i, raw in enumerate(events):
            try:
                good.append(validate(raw))
            except ValueError as ex:
                rejected.append(dict(index=i, error=str(ex)))
        if rejected and data.get("skip_invalid") is not True:
            return self._fail(400, "invalid_events", "one or more events are invalid", rejected=rejected[:5])

        limit = max(1, min(365, int(data.get("limit_days", os.getenv("AEROS_LAG_LIMIT_DAYS", 14)))))
        tol = data.get("tolerance")
        mon = Monitor(limit=limit, tolerance=None if tol is None else max(0.0, min(1e6, float(tol))),
                      max_llm=5, deadline_s=20)
        alerts = [a for e in good for a in mon.process(e)]
        delivered = []
        if live:
            mon.enrich(alerts)
            delivered = deliver_digest(alerts)
        self.info = dict(mode="live" if live else "dry_run", received=len(events), accepted=len(good),
                         rejected=len(rejected), alerts=len(alerts), high=sum(a["severity"] == "High" for a in alerts),
                         delivered=delivered, ai_calls=mon.llm_used)
        self._reply(200, dict(api_version=API_VERSION, mode=self.info["mode"], events=len(good), rejected=rejected,
                              alerts=alerts, delivered=delivered, ai_calls=mon.llm_used))

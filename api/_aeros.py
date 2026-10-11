"""AEROS core: control-error detection, detection-lag statistics, AI triage, alert delivery.
Standard library only. Read-only: it alerts and recommends, it never changes data."""
import os, json, statistics, smtplib, urllib.request
from collections import defaultdict, deque
from datetime import date
from email.message import EmailMessage

REQUIRED = ("id", "process", "expected", "actual", "occurred")


def validate(e):
    """Return a clean event dict or raise ValueError with a plain message."""
    if not isinstance(e, dict):
        raise ValueError("each event must be an object")
    miss = [k for k in REQUIRED if e.get(k) in (None, "")]
    if miss:
        raise ValueError(f"event {e.get('id', '?')}: missing {', '.join(miss)}")
    try:
        out = dict(id=str(e["id"]), process=str(e["process"]), expected=float(e["expected"]),
                   actual=float(e["actual"]), occurred=date.fromisoformat(str(e["occurred"])).isoformat(),
                   detected=(date.fromisoformat(str(e["detected"])).isoformat() if e.get("detected") else ""))
    except ValueError:
        raise ValueError(f"event {e.get('id', '?')}: expected/actual must be numbers and dates YYYY-MM-DD")
    if out["detected"] and out["detected"] < out["occurred"]:
        raise ValueError(f"event {out['id']}: detected is before occurred")
    return out


def lag_days(e):
    if not e.get("detected"):
        return None
    return (date.fromisoformat(e["detected"]) - date.fromisoformat(e["occurred"])).days


class Monitor:
    def __init__(self, limit=14, repeat_n=3, window=20):
        self.limit, self.repeat_n, self.window = limit, repeat_n, window
        self.history = defaultdict(lambda: deque(maxlen=200))

    def detect(self, e):
        alerts = []
        if e["expected"] != e["actual"]:
            alerts.append(dict(rule="reconciliation_break", severity="Medium",
                               detail=f"expected {e['expected']:g} but actual {e['actual']:g} (gap {e['expected'] - e['actual']:+g})"))
        lag = lag_days(e)
        if lag is not None and lag > self.limit:
            alerts.append(dict(rule="late_detection", severity="Medium",
                               detail=f"error ran {lag} days before detection (limit {self.limit})"))
        hist = self.history[e["process"]]
        recent = list(hist)[-self.window:]
        breaks = sum(1 for x in recent if x.get("broken")) + (1 if alerts else 0)
        if alerts and breaks >= self.repeat_n:
            alerts.append(dict(rule="repeat_pattern", severity="High",
                               detail=f"{breaks} control errors in the last {self.window} events for this process"))
        e = dict(e, broken=bool(alerts))
        hist.append(e)
        return alerts

    def stats(self, process):
        h = list(self.history[process])
        lags = [l for l in map(lag_days, h) if l is not None]
        return dict(process=process, events=len(h),
                    break_rate_pct=round(100 * sum(x["broken"] for x in h) / max(1, len(h)), 1),
                    median_detection_lag_days=statistics.median(lags) if lags else None,
                    late_pct=round(100 * sum(l > self.limit for l in lags) / len(lags), 1) if lags else None)

    def triage(self, alert, e, use_llm=False):
        ctx = dict(alert=alert, event=dict(id=e["id"], process=e["process"]), aeros=self.stats(e["process"]))
        key = os.getenv("ANTHROPIC_API_KEY")
        if use_llm and key:
            try:
                body = json.dumps(dict(model=os.getenv("AEROS_MODEL", "claude-sonnet-5-5"), max_tokens=500,
                    messages=[dict(role="user", content=(
                        "You are an operational risk analyst assistant. From this control alert and detection-lag stats, "
                        'reply with JSON only: {"likely_causes":[up to 3],"impact":"...","next_steps":[up to 3],'
                        '"confidence":"low|medium|high"}. Do not invent facts beyond the data. Data: ' + json.dumps(ctx)))]))
                req = urllib.request.Request("https://api.anthropic.com/v1/messages", body.encode(),
                    {"content-type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"})
                txt = json.load(urllib.request.urlopen(req, timeout=25))["content"][0]["text"]
                out = json.loads(txt[txt.find("{"):txt.rfind("}") + 1])
                out["source"] = "claude"
                return out
            except Exception:
                pass  # fall through to rule-based triage
        s = ctx["aeros"]
        return dict(source="rules", confidence="low",
                    likely_causes=["Process step failing silently", "Upstream data or posting rule changed"],
                    impact=f"Break rate {s['break_rate_pct']}% on {s['process']}; median detection lag {s['median_detection_lag_days']} days.",
                    next_steps=["Open an issue and assign an owner", "Sample affected records and confirm the break",
                                "Check recent changes to this process"])

    def process(self, e, use_llm=False, max_llm=5):
        """Check one event. Returns a list of alert records (with triage attached)."""
        out = []
        for a in self.detect(e):
            llm = use_llm and (max_llm is None or sum(r["triage"]["source"] == "claude" for r in out) < max_llm)
            out.append(dict(event_id=e["id"], process=e["process"], **a, triage=self.triage(a, e, llm)))
        return out


def format_msg(r):
    t = r["triage"]
    return (f"[{r['severity']}] {r['rule']} | {r['process']} | {r['event_id']}\n{r['detail']}\n"
            f"Triage ({t['source']}, confidence {t['confidence']}): {t['impact']}\nNext: " + "; ".join(t["next_steps"]))


def deliver(r):
    """Send an alert to Slack and/or email if configured. Returns list of channels used."""
    msg, used = format_msg(r), []
    if os.getenv("SLACK_WEBHOOK_URL"):
        try:
            urllib.request.urlopen(urllib.request.Request(os.environ["SLACK_WEBHOOK_URL"], json.dumps({"text": msg}).encode(),
                                   {"content-type": "application/json"}), timeout=10)
            used.append("slack")
        except Exception:
            pass
    if os.getenv("SMTP_HOST") and os.getenv("ALERT_TO"):
        try:
            m = EmailMessage()
            m["Subject"] = f"AEROS alert: {r['rule']} ({r['process']})"
            m["From"] = os.getenv("SMTP_USER", "aeros@localhost")
            m["To"] = os.environ["ALERT_TO"]
            m.set_content(msg)
            with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.getenv("SMTP_PORT", "587"))) as s:
                s.starttls()
                s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
                s.send_message(m)
            used.append("email")
        except Exception:
            pass
    return used

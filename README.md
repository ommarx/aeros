# AEROS

Catch control errors the moment they happen, measure how long errors run before anyone notices, and get an AI agent's first-pass triage.

**Prototype. Demo data is synthetic. Do not point it at real customer or employer data without authorisation, and keep personal data out of events.**

## What it does
1. **Detects, per event:** `reconciliation_break` (expected value differs from actual), `late_detection` (error ran past your limit before detection, default 14 days), `repeat_pattern` (3+ errors in the last 20 events of one process, escalated to High).
2. **Alerts** by Slack webhook and/or email, and logs locally in CLI mode.
3. **AI triage agent:** Claude receives only the alert, the process name and aggregate detection-lag stats, and returns likely causes, impact, next steps and a confidence level. Falls back to rule-based triage with no API key.
4. **Read-only:** it alerts and recommends. It never changes data. A person reviews every alert.

## Run locally
```
python cli.py --simulate               # synthetic stream
python cli.py --watch sample/events.csv  # alert as rows are appended
python -m unittest discover -s tests   # tests
```
CSV columns: `id,process,expected,actual,occurred,detected` (dates YYYY-MM-DD, `detected` may be blank).

## Deploy to Vercel
Import the repo in Vercel (Framework preset: Other). `public/` is served as the site and `api/ingest.py` as a Python function.

Environment variables (all optional):
| Name | Purpose |
|---|---|
| `AEROS_API_TOKEN` | Enables live mode. Callers must send `Authorization: Bearer <token>`. Without it, live mode is off. |
| `ANTHROPIC_API_KEY`, `AEROS_MODEL` | Claude triage (default model claude-sonnet-5-5) |
| `SLACK_WEBHOOK_URL` | Slack alerts |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `ALERT_TO` | Email alerts |
| `AEROS_LAG_LIMIT_DAYS` | Detection limit in days (default 14) |

## API
`POST /api/ingest` with `{"events":[...], "dry_run": true|false, "limit_days": 14}`. Up to 200 events and 100 KB per request.
`dry_run` is the default: rule-based triage only, no alerts, no AI calls. `GET /api/ingest` is a health check.

## Security notes
- The public demo can only run dry-run mode. Live mode requires the server-side token.
- AI calls per request are capped at 5 to limit cost.
- The Vercel function is stateless, so repeat-pattern detection works within one request. For cross-request memory, add a database (planned).
- Claude's triage is a hypothesis, not a finding. Keep a human in the loop.

## Limits and roadmap
- Fixed, simple rules; tune thresholds to avoid alert fatigue.
- Planned: persistent storage, configurable rules, alert deduplication across requests, dashboard.
- The Claude path is untested in the build environment (no API key there); the rule-based path and API are tested.

## Contributing
Issues and pull requests are welcome. Please add a test for any new rule.

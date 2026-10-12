# AEROS

Catch control errors as events arrive, measure how long errors run before anyone notices, and get a first-pass AI triage.

**Prototype. Demo data is synthetic. Do not point it at real customer or employer data without authorisation, and keep personal data out of events (use opaque IDs).**

## What it does
For every event (`id, process, expected, actual, occurred, detected`) AEROS raises at most **one alert**:
- `reconciliation_break`: expected and actual differ by more than a tolerance (default 0.005, so float noise is ignored).
- `late_detection`: the error ran longer than your limit (default 14 days) before detection. If a break arrives with no `detected` date, AEROS treats it as detected now, so an old undetected error is measured from `occurred` to today.
- `repeat_pattern` (High): 3+ control errors in the last 20 events of one process. It escalates once per window, not on every event.

An alert lists every rule it triggered. Rates are only shown once a process has 5+ events, so one event never reads as "100% break rate".

**AI triage (optional, Claude).** Live mode only. For the most severe alerts, Claude gets the alert, the process name, the event ID and aggregate stats, and must return JSON in an exact shape. Anything malformed, slow or failing silently falls back to rule-based triage. Hard limits: **5 AI calls per API request** (50 per CLI run, `AEROS_MAX_LLM`), High severity first, and no AI calls after 20 seconds of a request. Event text is treated as untrusted data in the prompt.

**Alerts.** One Slack message and/or one email **per batch** (a digest of up to 10 alerts, High first). All text is escaped so data cannot create `@channel` pings or links.

It is **read-only**: it alerts and recommends, never changes data. A person reviews every alert.

## Run locally
```
python cli.py --simulate                  # synthetic stream
python cli.py --watch sample/events.csv   # alert as rows are appended (restart-safe, bad rows skipped)
python -m unittest discover -s tests      # 27 tests
```

## Send real events to the deployed API
```
export AEROS_API_TOKEN='...'              # never put this in a file or in git
python tools/send.py events.csv --dry-run # check first: no alerts, no AI, no token needed
python tools/send.py events.csv           # live
```
Batches of 50. Accepted IDs are remembered (`sent.txt`), bad rows are logged (`rejected.log`) and skipped, and one bad row never blocks the rest.

## Deploy to Vercel
Import the repo (Framework preset: Other). `public/` is the site, `api/ingest.py` is a Python function.

| Environment variable | Purpose |
|---|---|
| `AEROS_API_TOKEN` | Enables live mode. Callers send `Authorization: Bearer <token>`. Without it live mode is off. |
| `ANTHROPIC_API_KEY`, `AEROS_MODEL` | Claude triage (default model claude-sonnet-5-5) |
| `SLACK_WEBHOOK_URL` | Slack alerts |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `ALERT_TO` | Email alerts |
| `AEROS_LAG_LIMIT_DAYS`, `AEROS_TOLERANCE` | Detection limit (days) and comparison tolerance |

## API
`POST /api/ingest` with `{"events":[...], "dry_run": true|false, "skip_invalid": false, "limit_days": 14, "tolerance": 0.005}`.
- `dry_run` is the default: rule-based triage only, no alerts, no AI. Limited to 50 events / 20 KB and 30 requests per minute per client.
- Live mode: up to 200 events / 100 KB, needs the bearer token. Failed token attempts count toward the rate limit.
- `skip_invalid: true` processes valid rows and lists the rest under `rejected`; otherwise any invalid row rejects the batch with a 400 before anything is sent.
- `GET /api/ingest` is a health check and reveals no configuration.

## Security notes
- Secrets live only in Vercel environment variables and your terminal session. `.gitignore` excludes `.env*`, keys, `logs/`, `.vercel/`, `sent.txt` and `*.csv` (except the synthetic sample).
- The in-memory rate limit is per serverless instance (best effort). For a hard limit add a rate-limit rule for `/api/ingest` in the Vercel Firewall.
- The function is stateless, so repeat detection and rates work within one request. Add a database for cross-request memory.
- If a request times out client-side, a retry can resend that digest. Keep batches small.
- Claude's triage is a hypothesis, not a finding. Keep a human in the loop.

## Limits and roadmap
Simple fixed rules; tune thresholds to avoid alert fatigue. Planned: persistent storage, configurable rules, cross-request deduplication, dashboard. The Claude call itself has not been run against the live API (no key in the build environment); everything around it (budget, schema check, fallback, timeouts) is covered by tests with a fake client.

## Contributing
Issues and pull requests welcome. Add a test for any new rule.

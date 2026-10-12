# AEROS API v1

Base URL: your deployment, e.g. `https://aeros-peach.vercel.app`. Endpoint: `POST /api/v1/ingest` (alias: `/api/ingest`).
Call it from a server or script. Browsers on other origins are blocked by design.

## Quickstart (5 minutes)
1. **Dry run, no token needed.** Nothing is sent and no AI is used:
```
curl -s -X POST https://YOUR-HOST/api/v1/ingest -H "content-type: application/json" -d '{
  "events":[{"id":"EV-1","process":"Rewards crediting","expected":1200,"actual":1150,"occurred":"2026-09-03"}]}'
```
2. **Get a client token** from the operator (32+ characters). Store it as an environment variable, never in code or git.
3. **Go live** by adding `"dry_run": false` and the header `Authorization: Bearer $AEROS_API_TOKEN`. Alerts go to the operator's Slack/email as one digest per request.

## Request
| Field | Type | Notes |
|---|---|---|
| `events` | array, required | 1 to 50 (dry run) or 1 to 200 (live). Max body 20 KB / 100 KB. |
| `dry_run` | bool | Default `true`. Only `false` is live. |
| `skip_invalid` | bool | Default `false`: any invalid event rejects the whole batch. `true`: valid events are processed, the rest listed in `rejected`. |
| `limit_days` | int 1-365 | Detection limit. Default 14. |
| `tolerance` | number | Differences up to this are ignored. Default 0.005. |

Event: `id`, `process`, `expected`, `actual` (finite numbers), `occurred` (YYYY-MM-DD), optional `detected` (YYYY-MM-DD).
Use opaque IDs. Do not send names, card numbers or other personal data.

## Response (200)
`api_version`, `mode`, `events` (accepted), `rejected` [{index, error}], `alerts`, `delivered` (channels used), `ai_calls`, `request_id`.
Each alert: `event_id`, `process`, `rule` (primary), `rules` (all triggered), `severity` (Medium/High), `detail`, `triage` {source, confidence, likely_causes, impact, next_steps}.

Rules: `reconciliation_break`, `late_detection` (a break with no `detected` date is measured to today), `repeat_pattern` (High; 3+ errors in 20 events, escalates once per window).

## Errors
`{"error": {"code": "...", "message": "..."}, "request_id": "..."}`

| HTTP | code | Meaning |
|---|---|---|
| 400 | `bad_request`, `bad_events`, `invalid_events`, `empty_body` | Fix the request. `invalid_events` includes `rejected`. |
| 401 | `unauthorized` | Missing or wrong token for live mode. |
| 413 | `body_too_large` | Over the size limit. |
| 429 | `rate_limited` | Slow down. See `Retry-After`. |
| 500 | `internal_error` | Report the `request_id` to the operator. |

## Limits and behaviour
- Rate limits (best effort, per server instance): 30 requests/min for dry runs per client address; 60 requests/min per client token in live mode.
- Stateless: nothing is stored. Repeat detection and rates apply within one request, so send related events together.
- A retry after a timeout can send a duplicate alert digest. Keep batches small and track what you have sent (`tools/send.py` does this).
- AI triage: at most 5 AI calls per request, none after 20 seconds, and malformed AI replies fall back to rule-based triage. AI output is a hypothesis for a human to review.
- Send `x-request-id` (8-64 chars: letters, digits, `_`, `-`) to correlate your logs. Otherwise one is generated.
- Versioning: breaking changes will ship as a new path (`/api/v2/...`). The `x-aeros-api-version` header is on every response.

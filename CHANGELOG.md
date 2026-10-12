# Changelog

## 0.3.0
- API v1: stable error codes, `request_id` and `x-request-id`, version header, `/api/v1/ingest` alias.
- Per-client tokens (`AEROS_API_TOKENS`), 32-character minimum, per-client rate limit.
- Structured audit line per request (no secrets, event data or IPs), written before the response.
- Security headers on the site and API. Health endpoint no longer reveals configuration.
- Docs: API reference, data handling, security policy, client-readiness checklist.

## 0.2.0
- Real AI call budget (5 per request), time limit, schema-checked AI replies with rule-based fallback.
- Float tolerance, finite-number validation, readable number formatting, one alert per event, digests, escaped Slack text.
- Undetected errors measured to today. Rate limits, `skip_invalid`, send script and restart-safe watcher.
- Fix: Vercel could not import the sibling module (explicit import path and `includeFiles`).

## 0.1.0
- First prototype: reconciliation break, late detection, repeat pattern, optional Claude triage.

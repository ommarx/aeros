# Client readiness: honest status

| Area | Status |
|---|---|
| Versioned API, stable error codes, request IDs | Done |
| Per-client tokens (32+ chars), rotation by redeploy | Done |
| Rate limits (per client address and per token) | Done, best effort per instance. Add a Vercel Firewall rule for a hard limit |
| Structured audit line per request (no secrets, no event data, no IPs) | Done, but only in provider logs |
| Input validation, tolerance for float noise, bad rows isolated | Done |
| AI safeguards: call budget, time limit, schema check, fallback, untrusted-data prompt | Done and tested with a fake client. Not yet run against a live key |
| Alert hygiene: one alert per event, one digest per request, markup escaped | Done |
| Security headers, no CORS, secrets only in environment variables | Done |
| Automated tests incl. leak and auth regressions | Done |
| Data handling description, security policy, API docs | Done (this folder) |

## Not done. Needed before a paying client relies on it
1. **Persistence:** a database for cross-request history, idempotency keys (no duplicate alerts on retry), and a durable audit trail.
2. **Per-client configuration** (own thresholds and rules, stored) and a self-service way to rotate tokens.
3. **Monitoring and on-call:** uptime checks, error alerting, a status page and a support contact.
4. **Validation on real data:** thresholds tuned, false-alarm rate measured, results reviewed with the client.
5. **Model risk governance for the AI step:** documented purpose, human review process, evaluation, change control.
6. **Security assurance:** independent penetration test, dependency scanning, secret scanning enforced.
7. **Legal and commercial:** terms, SLA, data processing agreement, liability position, and any required certifications.
8. **Scale and resilience:** load testing, backups, a defined recovery plan.

Until these are done, describe AEROS as a working prototype.

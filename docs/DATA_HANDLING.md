# Data handling

Plain description of what this service does with data. It is not a legal agreement or a compliance certification.

**What AEROS receives:** the events you send (`id`, `process`, numbers, dates) and your token.
**What it stores:** nothing. There is no database. Events are processed in memory and discarded.
**What it logs:** one line per request with the request ID, client name, HTTP status, duration and counts (events, alerts, High alerts, channels, AI calls). It never logs event contents, process names, tokens or IP addresses. Logs sit in the hosting provider's log system under its retention rules, so they are not a durable audit trail.

**What leaves the service (live mode only):**
| To | What | When |
|---|---|---|
| Anthropic (Claude API) | For up to 5 alerts per request: rule, severity, detail text (amounts and dates), event ID, process name, aggregate stats | Only if an API key is configured |
| Slack / email provider | A digest with the same fields plus the triage text | Only if a webhook or SMTP is configured |

Dry runs send nothing anywhere.

**Subprocessors in the default setup:** Vercel (hosting and logs), Anthropic (AI triage, optional), Slack or an SMTP provider (alerts, optional). Review each one's terms before sending real data.

**Your responsibilities:** send opaque IDs only; do not include personal, card or account data in any field; confirm you are authorised to process the data; keep tokens in environment variables.

**Not covered yet:** data residency choices, retention controls, deletion requests (nothing is stored, but provider logs are), a data processing agreement, and any certification (SOC 2, ISO 27001). See CLIENT_READINESS.md.

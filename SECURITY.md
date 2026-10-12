# Security policy

## Reporting a vulnerability
Please do not open a public issue. Use GitHub's private reporting: the repository's **Security** tab, then **Report a vulnerability**. Include steps to reproduce and the affected version. Expect an acknowledgement within a few days. This is a small open source project without a bounty.

## Supported versions
Only the latest release on `main`.

## For operators
- Keep `AEROS_API_TOKENS`, `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL` and SMTP settings in Vercel environment variables only. Never commit them or paste them into chat or tickets.
- Use tokens of 32+ characters (`openssl rand -hex 32`). Shorter tokens are ignored and cannot enable live mode.
- Rotate a token by changing it in Vercel and redeploying. Revoke a leaked Slack webhook or API key at its source, not just in this project.
- Turn on secret scanning and push protection for the repository.
- Add a Vercel Firewall rate-limit rule for `/api/ingest` for a hard limit.
- Do not send personal data. See docs/DATA_HANDLING.md.

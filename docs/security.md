# Security Notes

What this service protects against, and what's left to the deployment.

## Secrets

- Twilio and Anthropic keys, the admin token, and real client config live only in `.env` and `config/clients.yaml`. Both are gitignored. The repo ships `.env.example` and `config/clients.example.yaml` with placeholders and fictional businesses.
- Use a long random `ADMIN_TOKEN` (for example `python -c "import secrets; print(secrets.token_urlsafe(32))"`). Admin endpoints return 401 when it is unset.

## Inbound requests

| Entry point | Who can call it | Protection |
| --- | --- | --- |
| `/twilio/*` | Twilio | `X-Twilio-Signature` checked against `PUBLIC_BASE_URL` + path. Keep `VALIDATE_TWILIO_SIGNATURE=true` outside local testing |
| `/forms/{client_id}` | Client's website | Required per-client `form_key` (403 without one), hidden `website` honeypot, US numbers only, name and message length caps |
| `/tasks/flush-stale`, `/admin/*` | Cron and me | Bearer `ADMIN_TOKEN`, compared in constant time |
| `/docs`, `/openapi.json` | Nobody | Off unless `ENABLE_DOCS=true` |

A `form_key` sits in the client's page source, so treat it as a speed bump, not a secret. The real cost control is below.

## Cost abuse (SMS pumping)

Anyone can call a client's Twilio number with a spoofed caller ID, or post the form with someone else's number. Each of those triggers an outbound text. Limits:

- Only US +1 numbers are accepted from the form, which rules out premium international routes.
- One text thread per number per `DEDUPE_WINDOW_MINUTES`.
- At most `MAX_NEW_CONVERSATIONS_PER_HOUR` new threads per client. Set it a little above the client's real peak.
- Also turn on Twilio's SMS Pumping Protection and Geo Permissions (US only) in the console.

## The AI layer

- Customer texts are untrusted input to Claude. The worst a hostile customer can do is change the reply sent back to themselves. Claude can't send messages to anyone else or reach other conversations.
- The model never decides who gets texted, when a lead is complete, or what the owner's lead looks like. Code does.
- Customer and model text is flattened to one line and capped before it goes into the owner's lead, so a reply can't add a forged "Call back:" line.

## Data

- SQLite holds customer phone numbers and transcripts. Keep the volume private, back it up encrypted, and delete old rows on whatever schedule the client agrees to.
- Logs record only the last four digits of phone numbers.
- The container runs as a non-root user.

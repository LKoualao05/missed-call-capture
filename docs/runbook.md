# Runbook

## Deploy

Single container behind HTTPS (Caddy or a managed platform like Fly.io or Render). Mount `/srv/data` as a persistent volume for SQLite.

```bash
docker build -t missed-call-capture .
docker run -d --name mcc --restart unless-stopped \
  --env-file .env -p 8000:8000 \
  -v mcc-data:/srv/data -v $(pwd)/config/clients.yaml:/srv/config/clients.yaml:ro \
  missed-call-capture
```

Config changes (new client, edited questions) need a restart to load.

## Scheduled jobs

Send partial leads for conversations that went quiet, every 5 minutes:

```cron
*/5 * * * * curl -fsS -X POST -H "Authorization: Bearer $ADMIN_TOKEN" https://<host>/tasks/flush-stale
```

## Monitoring

- Uptime check on `GET /healthz` every minute. A down service means every missed call goes unanswered, so alert immediately.
- Twilio Console, Monitor, then Errors: watch for 11200 (webhook unreachable), 30007 (carrier filtered), 30034 (unregistered A2P number).
- Logs: every Claude fallback logs `claude turn failed, using scripted fallback`. A spike means an API or model problem.

## Common issues

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Every webhook returns 403 | `PUBLIC_BASE_URL` doesn't match the URL Twilio calls (http vs https, trailing path, proxy) | Set it to the exact public origin and restart |
| Calls get no text-back at all | Carrier forwarding not set or reset, or webhook URL wrong | Call the client's line and check Twilio call logs; re-dial the forwarding code |
| Texts show "sent" but never arrive | A2P campaign not approved or number not in the Messaging Service | Check campaign status in Twilio Trust Hub |
| 404 on webhooks | `To` number not in `clients.yaml` or not E.164 | Fix the entry, restart |
| Owner says leads stopped | Owner's number changed, or owner replied STOP to the tracking number | Check `owner_phone`; check `opt_outs` for the owner's number |
| Customer got two texts | Called from two numbers, or dedupe window passed | Expected behavior; tune `DEDUPE_WINDOW_MINUTES` if needed |

## Inspecting a conversation

```bash
sqlite3 data/leads.db \
  "SELECT id, status, source, answers, created_at FROM conversations WHERE client_id='<id>' ORDER BY id DESC LIMIT 10;"
sqlite3 data/leads.db "SELECT transcript FROM conversations WHERE id=<n>;"
```

## Monthly metrics for a client

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" https://<host>/admin/clients/<id>/metrics
```

Returns conversation count by source, median seconds to first text, reply rate, qualified rate, leads sent, emergencies, and opt-outs.

## Backups and secrets

- Back up `data/leads.db` nightly (`sqlite3 data/leads.db ".backup leads-$(date +%F).db"`). It holds customer phone numbers, so store backups encrypted and keep them for 90 days.
- Rotate the Twilio auth token and Anthropic key from their consoles, update `.env`, restart.
- Never commit `.env` or `config/clients.yaml`. Both are gitignored.

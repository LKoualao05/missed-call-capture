# Client Onboarding Playbook

How I take a new home-service business from signed to live. Target: live within a week of the discovery call, with most of that time spent waiting on A2P 10DLC approval.

## 1. Discovery call

Run through [discovery-checklist.md](discovery-checklist.md). The output is a filled-in client entry and a list of anything non-standard (a dispatcher who answers until noon, a second line for commercial accounts, a "never book roofs in the rain" rule).

The most important question is **"When you call someone back, what do you ask them first?"** Their answer becomes the three qualifying questions. A roofer cares about storm damage and insurance. A plumber cares whether water is actively leaking. Generic questions produce leads the owner still has to re-qualify.

## 2. Configure

Add the client to `config/clients.yaml`:

- `questions`: their three questions, in their words. Keep the `need`, `urgency`, `location` keys if they fit so the lead uses the standard labels.
- `business_hours` and `timezone`: decides "on another job" versus "after hours" wording and whether front-number mode rings the owner.
- `service_area_zips`: from the ZIPs they actually drive to.
- `emergency_keywords`: add trade-specific ones (`"water in the ceiling"` for roofers, `"burning smell"` for electricians).
- `voice_message`: what callers hear before the text arrives. Short, in the owner's voice if they want.
- `form_key`: a random string for their website form.

Run the simulator against the new entry and read every message out loud. If it doesn't sound like their business, change it.

```bash
python scripts/simulate.py --config config/clients.yaml --client <id> --claude
```

## 3. Provision Twilio

1. **Buy a local number** in the client's area code. A local number gets more replies than a toll-free one.
2. **A2P 10DLC.** Register the client's brand and a "customer care" campaign under a Messaging Service, and add the number to it. US carriers filter unregistered business SMS. Approval can take several days, so start this right after discovery.
   - Sample message: the client's actual first text from step 2.
   - Opt-in description: the customer initiated contact by calling the business or submitting its website form.
3. **Webhooks** on the number:
   - Voice, a call comes in: `POST https://<host>/twilio/voice`
   - Messaging, a message comes in: `POST https://<host>/twilio/sms`
4. Confirm `PUBLIC_BASE_URL` matches the host exactly, or signature validation will reject Twilio's requests.

## 4. Connect the phone line

**Conditional forward mode (default).** The owner keeps their number. Set their line to forward on busy and no answer to the Twilio number. Codes vary by carrier and plan, so confirm with the carrier. Common ones:

| Carrier type | Typical setup |
| --- | --- |
| Verizon mobile | `*71` + Twilio number (no-answer/busy forwarding) |
| AT&T / T-Mobile mobile | `**004*` + Twilio number + `#` (all conditional forwarding) |
| VoIP (RingCentral, Grasshopper, Google Voice, etc.) | Admin portal: unanswered calls forward to an external number |
| Landline | Carrier's "call forward no answer" feature, often has to be ordered |

Set the ring time so the owner still has a fair chance to answer. Around 20 seconds is a good default.

**Front number mode.** Put the Twilio number on their Google Business Profile and website. Set `owner_phone` and `ring_timeout_seconds`.

**Website form.** Point their after-hours or contact form at:

```
POST https://<host>/forms/<client_id>?key=<form_key>
fields: name, phone, message
```

Most site builders (Wix, Squarespace, WordPress form plugins) support a webhook on submit, or it can go through Zapier.

## 5. Acceptance test with the owner

Do this live, with the owner, before calling it done:

- [ ] Owner calls the business line from a personal phone and lets it ring out
- [ ] Text arrives within seconds
- [ ] Owner answers as a customer, messy, like a real customer would
- [ ] Lead lands on the owner's phone and they say it has what they need to call back
- [ ] Call again inside 30 minutes: no second text (dedupe works)
- [ ] Reply STOP from the test phone: no further texts
- [ ] Submit the website form: text arrives and skips the question the form already answered
- [ ] Say "I smell gas" in a test: owner gets the urgent alert immediately

Any "that's not how I'd say it" from the owner gets fixed now, not after launch.

## 6. Go live and first week

- Turn on the stale-lead cron if it isn't already running for other clients.
- Check the conversations table daily for the first week. Read every transcript.
- Day 7 check-in: show them `/admin/clients/<id>/metrics`, ask which leads turned into jobs, adjust questions if leads keep missing something.

## Offboarding

Remove forwarding on their line, release or port the Twilio number, delete their entry from `clients.yaml`, and export their conversations if they want them.

# Discovery Checklist

A 20-minute call with the owner. Every answer maps to a config field or a setup step.

## How calls work today

- [ ] Roughly how many calls a week? How many do you think you miss?
- [ ] Who answers? You, a spouse, an office person, a dispatcher? During what hours?
- [ ] What happens to a missed call right now? Voicemail? Do people leave one?
- [ ] Which phone company and what kind of line (cell, VoIP, landline)? → `call_mode`, forwarding steps
- [ ] Is that number on your trucks, Google profile, and website? Would you change it? → `conditional_forward` vs `front_number`
- [ ] Do you have a website form? What does it collect? Who sees submissions after hours? → form hookup

## What a good lead looks like

- [ ] When you call someone back, what do you ask first? Second? Third? → `questions`
- [ ] What makes you say "not for us"? (Job type, too far, too small) → `service_area_zips`, question wording
- [ ] Which ZIPs or towns do you actually drive to? → `service_area_zips`
- [ ] What counts as an emergency for you? Do you do emergency calls after hours? → `emergency_keywords`, closing wording
- [ ] Anything the text should never say? (Prices, "we'll be there today", competitor names)

## Hours and voice

- [ ] Business hours, by day. Seasonal changes? → `business_hours`
- [ ] Time zone (almost always America/New_York for Ohio)
- [ ] How do you want to sound? Your name in the texts or just the company? → `owner_name`, `greeting`
- [ ] What should callers hear before the text comes? → `voice_message`

## Delivery

- [ ] Which cell gets the lead texts? Should anyone else get them? → `owner_phone`
- [ ] How fast do you usually call back once you see a lead?
- [ ] What would make you say this is working after a month?

## Legal and carrier registration (needed for A2P 10DLC)

- [ ] Legal business name, EIN, business address, website
- [ ] Contact email for the registration

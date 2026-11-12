"""Formats the lead text that lands on the owner's phone.

Owners read these between jobs, often in a truck. The format is fixed so they
learn where to look: urgency first, then what, where, and who.
"""

from __future__ import annotations

import re
from datetime import datetime

from app.clients import ClientConfig
from app.store import Conversation

ZIP_RE = re.compile(r"\b(\d{5})\b")

SOURCE_LABELS = {
    "missed_call": "Missed call",
    "after_hours_call": "After-hours call",
    "web_form": "After-hours web form",
}


def pretty_phone(e164: str) -> str:
    digits = re.sub(r"\D", "", e164)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return e164


def outside_service_area(client: ClientConfig, location: str) -> bool:
    if not client.service_area_zips or not location:
        return False
    m = ZIP_RE.search(location)
    return bool(m) and m.group(1) not in client.service_area_zips


def format_lead(client: ClientConfig, conv: Conversation, partial: bool = False) -> str:
    answers = conv.answers
    labels = {q.key: q.key.replace("_", " ").title() for q in client.questions}
    labels.update({"need": "Need", "urgency": "When", "location": "Where"})

    if conv.emergency:
        header = "URGENT LEAD"
    elif partial:
        header = "PARTIAL LEAD (stopped replying)"
    else:
        header = "NEW LEAD"

    created = datetime.fromisoformat(conv.created_at).astimezone(client.tz)
    lines = [f"{header} - {SOURCE_LABELS.get(conv.source, conv.source)} {created:%-I:%M %p}"]
    if conv.caller_name:
        lines.append(f"Name: {conv.caller_name}")
    lines.append(f"Phone: {pretty_phone(conv.caller)}")
    for q in client.questions:
        lines.append(f"{labels[q.key]}: {answers.get(q.key) or '-'}")
    if outside_service_area(client, answers.get("location", "")):
        lines.append("Note: ZIP is outside your service area")
    lines.append(f"Call back: {conv.caller}")
    return "\n".join(lines)

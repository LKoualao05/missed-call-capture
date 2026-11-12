"""Per-client configuration.

Each home-service business is one entry in config/clients.yaml. Onboarding a new
client means adding an entry, buying a Twilio number, and pointing that number's
webhooks at this service. No code changes.
"""

from __future__ import annotations

from datetime import datetime, time
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field, field_validator

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class QualifyingQuestion(BaseModel):
    key: str
    ask: str
    purpose: str = ""


DEFAULT_QUESTIONS = [
    QualifyingQuestion(
        key="need",
        ask="What can we help you with today?",
        purpose="The service or problem, in the customer's words (e.g. AC not cooling, leaking water heater).",
    ),
    QualifyingQuestion(
        key="urgency",
        ask="How soon do you need someone out? Is this an emergency?",
        purpose="Timeline: emergency / today, this week, or just getting a quote.",
    ),
    QualifyingQuestion(
        key="location",
        ask="What's the address or ZIP code for the job?",
        purpose="Where the work is, so the owner can check it's in the service area.",
    ),
]


class ClientConfig(BaseModel):
    id: str
    business_name: str
    trade: str
    tracking_number: str = Field(description="Twilio number (E.164) callers reach or get forwarded to")
    owner_phone: str = Field(description="Where formatted leads are texted (E.164)")
    owner_name: str = ""
    timezone: str = "America/New_York"
    call_mode: Literal["conditional_forward", "front_number"] = "conditional_forward"
    ring_timeout_seconds: int = 20
    business_hours: dict[str, list[str]] = Field(default_factory=dict)
    service_area_zips: list[str] = Field(default_factory=list)
    emergency_keywords: list[str] = Field(
        default_factory=lambda: ["gas", "smell gas", "carbon monoxide", "flood", "flooding", "sparks", "fire", "no heat"]
    )
    questions: list[QualifyingQuestion] = Field(default_factory=lambda: list(DEFAULT_QUESTIONS))
    greeting: str = ""
    voice_message: str = ""
    form_key: str = Field(default="", description="Shared key the client's website form sends as ?key=")

    @field_validator("business_hours")
    @classmethod
    def _validate_hours(cls, v: dict[str, list[str]]) -> dict[str, list[str]]:
        for day, window in v.items():
            if day not in DAYS:
                raise ValueError(f"unknown day '{day}', use one of {DAYS}")
            if len(window) != 2:
                raise ValueError(f"{day} must be [open, close] like ['08:00', '17:00']")
        return v

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def is_open(self, at: datetime | None = None) -> bool:
        """True when `at` falls inside configured business hours (client's local time)."""
        now = (at or datetime.now(tz=self.tz)).astimezone(self.tz)
        window = self.business_hours.get(DAYS[now.weekday()])
        if not window:
            return False
        open_t, close_t = (time.fromisoformat(t) for t in window)
        return open_t <= now.time() < close_t

    def first_text(self, after_hours: bool) -> str:
        if self.greeting:
            return self.greeting
        reason = "after hours" if after_hours else "on another job"
        return (
            f"Hi, this is {self.business_name}. Sorry we missed your call, we're {reason} right now. "
            f"{self.questions[0].ask}"
        )


class ClientRegistry:
    """Looks up the client a webhook belongs to by the Twilio number that received it."""

    def __init__(self, clients: list[ClientConfig]):
        self._by_id = {c.id: c for c in clients}
        self._by_number = {c.tracking_number: c for c in clients}
        if len(self._by_number) != len(clients):
            raise ValueError("two clients share a tracking_number")

    @classmethod
    def from_yaml(cls, path: str | Path) -> ClientRegistry:
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls([ClientConfig(**c) for c in raw.get("clients", [])])

    def by_number(self, number: str) -> ClientConfig | None:
        return self._by_number.get(number)

    def by_id(self, client_id: str) -> ClientConfig | None:
        return self._by_id.get(client_id)

    def all(self) -> list[ClientConfig]:
        return list(self._by_id.values())

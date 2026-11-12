"""Twilio boundary: outbound SMS, TwiML responses, and webhook signature checks.

Everything that talks to Twilio lives here so the rest of the app can be tested
with a fake messenger and no network.
"""

from __future__ import annotations

import logging
from typing import Protocol
from xml.sax.saxutils import escape

from twilio.request_validator import RequestValidator
from twilio.rest import Client as TwilioClient

log = logging.getLogger(__name__)


class Messenger(Protocol):
    def send_sms(self, from_: str, to: str, body: str) -> str: ...


class TwilioMessenger:
    def __init__(self, account_sid: str, auth_token: str):
        self._client = TwilioClient(account_sid, auth_token)

    def send_sms(self, from_: str, to: str, body: str) -> str:
        msg = self._client.messages.create(from_=from_, to=to, body=body)
        log.info("sms sent sid=%s to=%s", msg.sid, to[-4:])
        return msg.sid


class RecordingMessenger:
    """In-memory messenger for tests and the local simulator."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_sms(self, from_: str, to: str, body: str) -> str:
        self.sent.append({"from": from_, "to": to, "body": body})
        return f"SM{len(self.sent):032d}"

    def to(self, number: str) -> list[str]:
        return [m["body"] for m in self.sent if m["to"] == number]


# TwiML ------------------------------------------------------------------

def twiml(*verbs: str) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?><Response>' + "".join(verbs) + "</Response>"


def say(text: str) -> str:
    return f'<Say voice="Polly.Joanna">{escape(text)}</Say>'


def dial(number: str, timeout: int, action_url: str) -> str:
    return (
        f'<Dial timeout="{int(timeout)}" action="{escape(action_url)}" method="POST">'
        f"{escape(number)}</Dial>"
    )


HANGUP = "<Hangup/>"
EMPTY = twiml()


# Signature validation ---------------------------------------------------

def signature_is_valid(auth_token: str, url: str, params: dict, signature: str | None) -> bool:
    if not signature or not auth_token:
        return False
    return RequestValidator(auth_token).validate(url, params, signature)

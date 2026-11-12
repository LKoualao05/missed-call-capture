"""SMS keyword handling required for US carrier (A2P 10DLC) compliance.

Twilio Messaging Services also handle STOP at the carrier level. We still track
opt-outs ourselves so the app never tries to text someone who opted out, and so
an opt-out ends the qualifying conversation cleanly.
"""

from __future__ import annotations

from enum import StrEnum

STOP_WORDS = {"stop", "stopall", "unsubscribe", "cancel", "end", "quit", "revoke", "optout"}
START_WORDS = {"start", "unstop"}  # not "yes": customers say yes to "is this an emergency?"
HELP_WORDS = {"help", "info"}


class Keyword(StrEnum):
    STOP = "stop"
    START = "start"
    HELP = "help"
    NONE = "none"


def classify(body: str) -> Keyword:
    word = body.strip().lower().rstrip(".!")
    if word in STOP_WORDS:
        return Keyword.STOP
    if word in START_WORDS:
        return Keyword.START
    if word in HELP_WORDS:
        return Keyword.HELP
    return Keyword.NONE


def help_text(business_name: str) -> str:
    return (
        f"{business_name}: we text you back when we miss your call so we can get you help faster. "
        "Msg & data rates may apply. Reply STOP to opt out."
    )

"""Lead qualification over SMS.

The caller gets three qualifying questions (configurable per client). Claude runs
the conversation so it can handle real replies ("it's the upstairs unit, been
blowing warm air since last night, I'm on Maple off Morse Rd") and pull several
answers out of one text. The app, not the model, decides when the lead is done:
Claude proposes answers, and code checks every question has one.

If the Claude call fails or returns something unusable, ScriptedQualifier takes
over for that turn so a caller never sits waiting on a dead thread.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from app.clients import ClientConfig
from app.store import Conversation

log = logging.getLogger(__name__)

MAX_SMS_CHARS = 320
SAFETY_LINE = "If anyone is in danger, get out of the house and call 911. We're alerting the owner now."
ZIP_RE = re.compile(r"\b(\d{5})\b")


@dataclass
class TurnResult:
    reply: str
    answers: dict[str, str] = field(default_factory=dict)
    caller_name: str | None = None
    emergency: bool = False
    complete: bool = False
    used_fallback: bool = False


class Qualifier(Protocol):
    def next_turn(self, client: ClientConfig, conv: Conversation, inbound: str) -> TurnResult: ...


# Shared helpers ----------------------------------------------------------

def missing_keys(client: ClientConfig, answers: dict[str, str]) -> list[str]:
    return [q.key for q in client.questions if not answers.get(q.key, "").strip()]


def is_emergency(client: ClientConfig, text: str) -> bool:
    t = text.lower()
    return any(k in t for k in client.emergency_keywords)


def closing_message(client: ClientConfig, name: str | None, emergency: bool) -> str:
    who = client.owner_name or "the owner"
    hi = f"Thanks {name}! " if name else "Thanks! "
    if emergency:
        return (
            f"{hi}I've flagged this as urgent and sent it to {who} right now. "
            "If you smell gas or there's any danger, leave the home and call 911."
        )
    return f"{hi}I've sent your details to {who}. They'll reach out shortly to get you scheduled."


def finalize(client: ClientConfig, conv: Conversation, result: TurnResult) -> TurnResult:
    """Apply the rules the model is not trusted with."""
    merged = {**conv.answers, **{k: v for k, v in result.answers.items() if v and v.strip()}}
    known = {q.key for q in client.questions}
    result.answers = {k: v.strip() for k, v in merged.items() if k in known}
    result.complete = not missing_keys(client, result.answers)
    result.emergency = result.emergency or conv.emergency
    name = result.caller_name or conv.caller_name
    if result.complete:
        result.reply = closing_message(client, name, result.emergency)
    elif result.emergency and not conv.emergency and "911" not in result.reply:
        # First mention of danger: safety line goes out even if the model (or fallback) skipped it.
        result.reply = f"{SAFETY_LINE} {result.reply}"
    result.reply = result.reply.strip()[:MAX_SMS_CHARS]
    return result


# Scripted fallback -------------------------------------------------------

class ScriptedQualifier:
    """Deterministic: each reply answers the next open question, in order."""

    def next_turn(self, client: ClientConfig, conv: Conversation, inbound: str) -> TurnResult:
        answers = dict(conv.answers)
        open_keys = missing_keys(client, answers)
        if open_keys:
            answers[open_keys[0]] = inbound.strip()
        if "location" in open_keys and (m := ZIP_RE.search(inbound)) and open_keys[0] != "location":
            answers["location"] = m.group(1)
        remaining = missing_keys(client, answers)
        by_key = {q.key: q for q in client.questions}
        reply = by_key[remaining[0]].ask if remaining else ""
        result = TurnResult(
            reply=reply,
            answers=answers,
            emergency=is_emergency(client, inbound),
            used_fallback=True,
        )
        return finalize(client, conv, result)


# Claude ------------------------------------------------------------------

SYSTEM_PROMPT = """You are the text-message assistant for {business_name}, a {trade} company. \
A customer called and nobody could pick up, so you're texting them back to collect what the \
owner needs to call them back ready to quote and schedule.

You need an answer to each of these:
{question_block}

Rules:
- Write like a friendly front-desk person texting: short, plain, no emojis, no markdown.
- Ask for one missing thing at a time. If one message answers several questions, record all of them.
- Record answers in the customer's own words, lightly cleaned up. Never invent an answer.
- Never quote prices, promise an arrival time, or diagnose the problem.
- If asked whether you're a person, say you're {business_name}'s automated assistant and the owner will call them.
- If the customer describes danger (gas smell, carbon monoxide, sparks, fire, flooding), set emergency=true \
and tell them to get to safety and call 911 if anyone is at risk.
- If they share their name, record it.
- Keep every reply under 300 characters.

Always respond by calling the record_turn tool."""


def _tool_schema(client: ClientConfig) -> dict:
    return {
        "name": "record_turn",
        "description": "Record what the customer has told us so far and the next text to send them.",
        "input_schema": {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "object",
                    "description": "Answers given so far. Omit or leave empty any question not yet answered.",
                    "properties": {q.key: {"type": "string", "description": q.purpose} for q in client.questions},
                },
                "caller_name": {"type": "string", "description": "Customer's name if they gave it, else empty."},
                "emergency": {"type": "boolean"},
                "reply": {"type": "string", "description": "The next SMS to send the customer."},
            },
            "required": ["answers", "emergency", "reply"],
        },
    }


class ClaudeQualifier:
    def __init__(self, client, model: str, fallback: Qualifier | None = None):
        self._client = client  # anthropic.Anthropic instance (injected for testability)
        self._model = model
        self._fallback = fallback or ScriptedQualifier()

    def _prompt(self, client: ClientConfig, conv: Conversation, inbound: str) -> tuple[str, str]:
        questions = "\n".join(f"- {q.key}: {q.ask} ({q.purpose})" for q in client.questions)
        system = SYSTEM_PROMPT.format(
            business_name=client.business_name, trade=client.trade, question_block=questions
        )
        history = "\n".join(
            f"{'Us' if m['role'] == 'assistant' else 'Customer'}: {m['text']}" for m in conv.transcript
        )
        user = (
            f"Answers recorded so far: {json.dumps(conv.answers)}\n\n"
            f"Conversation so far:\n{history or '(none)'}\n\n"
            f"Customer's newest text: {inbound}"
        )
        return system, user

    def next_turn(self, client: ClientConfig, conv: Conversation, inbound: str) -> TurnResult:
        system, user = self._prompt(client, conv, inbound)
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=400,
                system=system,
                tools=[_tool_schema(client)],
                tool_choice={"type": "tool", "name": "record_turn"},
                messages=[{"role": "user", "content": user}],
            )
            block = next(b for b in resp.content if getattr(b, "type", "") == "tool_use")
            data = block.input
            answers = data.get("answers") or {}
            if not isinstance(answers, dict) or not str(data.get("reply", "")).strip():
                raise ValueError("model returned an empty or malformed turn")
            result = TurnResult(
                reply=str(data["reply"]),
                answers={k: str(v) for k, v in answers.items() if v},
                caller_name=(data.get("caller_name") or None),
                emergency=bool(data.get("emergency")) or is_emergency(client, inbound),
            )
            return finalize(client, conv, result)
        except Exception as exc:  # network, rate limit, schema drift: never strand the caller
            log.warning("claude turn failed, using scripted fallback: %s", exc)
            return self._fallback.next_turn(client, conv, inbound)

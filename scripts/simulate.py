"""Play the caller in your terminal, no Twilio account needed.

    python scripts/simulate.py                 # scripted qualifier
    ANTHROPIC_API_KEY=... python scripts/simulate.py --claude

Useful on a discovery call: let the business owner type replies as if they were
a customer and watch the lead text they would get.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.clients import ClientRegistry  # noqa: E402
from app.qualifier import ClaudeQualifier, ScriptedQualifier  # noqa: E402
from app.service import LeadService  # noqa: E402
from app.store import Store  # noqa: E402
from app.telephony import RecordingMessenger  # noqa: E402

CALLER = "+16145551234"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/clients.example.yaml")
    p.add_argument("--client", default=None, help="client id (defaults to the first one)")
    p.add_argument("--claude", action="store_true", help="use Claude instead of the scripted flow")
    args = p.parse_args()

    registry = ClientRegistry.from_yaml(args.config)
    client = registry.by_id(args.client) if args.client else registry.all()[0]

    if args.claude:
        import anthropic

        qualifier = ClaudeQualifier(anthropic.Anthropic(), os.getenv("ANTHROPIC_MODEL", "claude-haiku-5-5"))
    else:
        qualifier = ScriptedQualifier()

    messenger = RecordingMessenger()
    service = LeadService(store=Store(":memory:"), messenger=messenger, qualifier=qualifier)

    def show_new(start: int) -> int:
        for m in messenger.sent[start:]:
            who = "OWNER PHONE" if m["to"] == client.owner_phone else client.business_name
            print(f"\n[{who}]\n{m['body']}")
        return len(messenger.sent)

    print(f"Simulating a missed call to {client.business_name}. Type replies, Ctrl-C to quit.")
    service.start_conversation(client, CALLER, "missed_call" if client.is_open() else "after_hours_call")
    seen = show_new(0)
    while True:
        conv = service.store.active_for(client.id, CALLER)
        if conv is None:
            print("\n(conversation finished)")
            return
        try:
            reply = input("\nyou> ")
        except (EOFError, KeyboardInterrupt):
            return
        service.handle_reply(client, CALLER, reply)
        seen = show_new(seen)


if __name__ == "__main__":
    main()

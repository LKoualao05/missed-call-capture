"""Core speed-to-lead flow, independent of HTTP.

    missed call / after-hours form
        -> instant text to the caller          (start_conversation)
        -> AI asks the qualifying questions     (handle_reply)
        -> formatted lead texted to the owner   (_send_lead)

Conversations that stall get sent to the owner as partial leads (flush_stale),
because a name and number the owner can call is still worth more than nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app import compliance
from app.clients import ClientConfig
from app.leads import format_lead
from app.qualifier import Qualifier, closing_message
from app.store import Conversation, Store, utcnow
from app.telephony import Messenger

log = logging.getLogger(__name__)


@dataclass
class LeadService:
    store: Store
    messenger: Messenger
    qualifier: Qualifier
    dedupe_window_minutes: int = 30
    stale_after_minutes: int = 20
    max_caller_turns: int = 6
    max_new_conversations_per_hour: int = 60

    # entry points -------------------------------------------------------

    def start_conversation(
        self,
        client: ClientConfig,
        caller: str,
        source: str,
        name: str | None = None,
        message: str | None = None,
    ) -> Conversation | None:
        """Text the caller back. Returns None when we deliberately stay quiet."""
        if self.store.is_opted_out(client.id, caller):
            log.info("skip text-back: %s opted out of %s", caller[-4:], client.id)
            return None
        if self.store.recent_for(client.id, caller, self.dedupe_window_minutes):
            log.info("skip text-back: %s already contacted within window", caller[-4:])
            return None
        if self.store.count_since(client.id, 60) >= self.max_new_conversations_per_hour:
            # Protects the client's Twilio bill from SMS pumping (spoofed calls or form spam).
            log.warning("hourly text-back cap reached for %s, skipping %s", client.id, caller[-4:])
            return None

        conv = self.store.create(client.id, caller, source)
        conv.caller_name = name or None

        if message:
            # Web forms usually include a description; let the qualifier use it so we
            # don't ask a question the customer already answered.
            conv.transcript.append({"role": "caller", "text": message, "at": utcnow().isoformat()})
            turn = self.qualifier.next_turn(client, conv, message)
            self._apply(conv, turn)
            first = f"Hi{' ' + name if name else ''}, this is {client.business_name}. Thanks for reaching out! {turn.reply}"
            if turn.complete:
                first = turn.reply
        else:
            first = client.first_text(after_hours=source != "missed_call")

        self._text_caller(client, conv, first)
        conv.first_text_at = utcnow().isoformat()
        self.store.save(conv)
        if conv.status == "complete":
            self._send_lead(client, conv)
        elif conv.emergency:
            self._alert_owner_emergency(client, conv)
        return conv

    def handle_reply(self, client: ClientConfig, caller: str, body: str) -> None:
        keyword = compliance.classify(body)
        if keyword is compliance.Keyword.STOP:
            self.store.opt_out(client.id, caller)
            return  # Twilio's carrier-level STOP handling sends the confirmation
        if keyword is compliance.Keyword.START:
            self.store.opt_in(client.id, caller)
            return
        if keyword is compliance.Keyword.HELP:
            self.messenger.send_sms(client.tracking_number, caller, compliance.help_text(client.business_name))
            return

        conv = self.store.active_for(client.id, caller)
        if conv is None:
            # Texted the number out of the blue, or after the lead was already sent.
            # Treat it as a new inbound lead.
            self.start_conversation(client, caller, "missed_call", message=body)
            return

        now = utcnow().isoformat()
        conv.first_reply_at = conv.first_reply_at or now
        conv.transcript.append({"role": "caller", "text": body, "at": now})
        was_emergency = conv.emergency

        turn = self.qualifier.next_turn(client, conv, body)
        self._apply(conv, turn)

        if not turn.complete and conv.caller_turns >= self.max_caller_turns:
            # Long back-and-forth: hand it to a human rather than keep the AI talking.
            conv.status = "complete"
            turn.reply = closing_message(client, conv.caller_name, conv.emergency)

        self._text_caller(client, conv, turn.reply)
        self.store.save(conv)

        if conv.status == "complete":
            self._send_lead(client, conv)
        elif conv.emergency and not was_emergency:
            self._alert_owner_emergency(client, conv)

    def flush_stale(self, clients_by_id: dict[str, ClientConfig]) -> int:
        """Send partial leads for conversations that went quiet. Run from cron every few minutes."""
        sent = 0
        for conv in self.store.stale(self.stale_after_minutes):
            client = clients_by_id.get(conv.client_id)
            if client is None:
                continue
            conv.status = "stale"
            self._send_lead(client, conv, partial=True)
            sent += 1
        return sent

    # internals ----------------------------------------------------------

    def _apply(self, conv: Conversation, turn) -> None:
        conv.answers = turn.answers
        conv.caller_name = turn.caller_name or conv.caller_name
        conv.emergency = conv.emergency or turn.emergency
        if turn.complete:
            conv.status = "complete"

    def _text_caller(self, client: ClientConfig, conv: Conversation, body: str) -> None:
        if not body:
            return
        self.messenger.send_sms(client.tracking_number, conv.caller, body)
        conv.transcript.append({"role": "assistant", "text": body, "at": utcnow().isoformat()})

    def _send_lead(self, client: ClientConfig, conv: Conversation, partial: bool = False) -> None:
        if conv.lead_sent_at:
            return
        self.messenger.send_sms(client.tracking_number, client.owner_phone, format_lead(client, conv, partial))
        conv.lead_sent_at = utcnow().isoformat()
        self.store.save(conv)

    def _alert_owner_emergency(self, client: ClientConfig, conv: Conversation) -> None:
        # Don't wait for all three answers when someone reports danger.
        self.messenger.send_sms(
            client.tracking_number,
            client.owner_phone,
            format_lead(client, conv, partial=True) + "\n(Still collecting details. Call now.)",
        )

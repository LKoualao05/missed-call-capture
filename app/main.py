"""HTTP layer: Twilio webhooks, the web-form webhook, and a small admin surface."""

from __future__ import annotations

import hmac
import logging
import statistics
from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, Response

from app.clients import ClientConfig, ClientRegistry
from app.qualifier import ClaudeQualifier, Qualifier, ScriptedQualifier
from app.service import LeadService
from app.settings import Settings, get_settings
from app.store import Store
from app.telephony import EMPTY, HANGUP, Messenger, TwilioMessenger, dial, say, signature_is_valid, twiml

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

XML = "application/xml"
DEFAULT_VOICE_MESSAGE = "Sorry we missed you. We're sending you a text right now so we can help you faster."


def create_app(
    settings: Settings | None = None,
    registry: ClientRegistry | None = None,
    store: Store | None = None,
    messenger: Messenger | None = None,
    qualifier: Qualifier | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    registry = registry or ClientRegistry.from_yaml(settings.clients_file)
    store = store or Store(settings.database_path)
    messenger = messenger or TwilioMessenger(settings.twilio_account_sid, settings.twilio_auth_token)
    if qualifier is None:
        if settings.anthropic_api_key:
            import anthropic

            qualifier = ClaudeQualifier(anthropic.Anthropic(api_key=settings.anthropic_api_key), settings.anthropic_model)
        else:
            log.warning("ANTHROPIC_API_KEY not set, using scripted qualifier")
            qualifier = ScriptedQualifier()

    service = LeadService(
        store=store,
        messenger=messenger,
        qualifier=qualifier,
        dedupe_window_minutes=settings.dedupe_window_minutes,
        stale_after_minutes=settings.stale_after_minutes,
        max_caller_turns=settings.max_caller_turns,
    )

    app = FastAPI(title="Missed Call Capture", version="1.0.0")
    app.state.service = service
    app.state.registry = registry

    # dependencies -------------------------------------------------------

    async def twilio_params(request: Request) -> dict:
        form = await request.form()
        params = {k: str(v) for k, v in form.items()}
        if settings.validate_twilio_signature:
            url = settings.public_base_url.rstrip("/") + request.url.path
            if not signature_is_valid(
                settings.twilio_auth_token, url, params, request.headers.get("X-Twilio-Signature")
            ):
                raise HTTPException(status_code=403, detail="invalid Twilio signature")
        return params

    def client_for(params: dict) -> ClientConfig:
        client = registry.by_number(params.get("To", ""))
        if client is None:
            raise HTTPException(status_code=404, detail="no client for this number")
        return client

    def require_admin(authorization: str = Header(default="")) -> None:
        expected = f"Bearer {settings.admin_token}"
        if not settings.admin_token or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401)

    def missed(client: ClientConfig, caller: str, source: str, tasks: BackgroundTasks) -> Response:
        tasks.add_task(service.start_conversation, client, caller, source)
        return Response(twiml(say(client.voice_message or DEFAULT_VOICE_MESSAGE), HANGUP), media_type=XML)

    # routes -------------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True, "clients": len(registry.all())}

    @app.post("/twilio/voice")
    def voice(tasks: BackgroundTasks, params: dict = Depends(twilio_params)) -> Response:
        """Incoming call on a client's Twilio number."""
        client = client_for(params)
        caller = params.get("From", "")
        if client.call_mode == "conditional_forward":
            # The client's carrier only forwards calls they didn't answer, so every
            # call that reaches us is already a missed call.
            source = "missed_call" if client.is_open() else "after_hours_call"
            return missed(client, caller, source, tasks)
        if not client.is_open():
            return missed(client, caller, "after_hours_call", tasks)
        action = settings.public_base_url.rstrip("/") + "/twilio/dial-status"
        return Response(twiml(dial(client.owner_phone, client.ring_timeout_seconds, action)), media_type=XML)

    @app.post("/twilio/dial-status")
    def dial_status(tasks: BackgroundTasks, params: dict = Depends(twilio_params)) -> Response:
        """Twilio calls this after <Dial> ends. Anything but 'completed' means nobody picked up."""
        client = client_for(params)
        if params.get("DialCallStatus") == "completed":
            return Response(twiml(HANGUP), media_type=XML)
        return missed(client, params.get("From", ""), "missed_call", tasks)

    @app.post("/twilio/sms")
    def sms(tasks: BackgroundTasks, params: dict = Depends(twilio_params)) -> Response:
        """Inbound text. Reply asynchronously so Twilio's webhook never waits on the LLM."""
        client = client_for(params)
        tasks.add_task(service.handle_reply, client, params.get("From", ""), params.get("Body", ""))
        return Response(EMPTY, media_type=XML)

    @app.post("/forms/{client_id}")
    async def web_form(client_id: str, request: Request, tasks: BackgroundTasks) -> dict:
        """After-hours website form. Accepts JSON or form-encoded posts from the client's site."""
        client = registry.by_id(client_id)
        if client is None:
            raise HTTPException(status_code=404)
        if client.form_key and not hmac.compare_digest(request.query_params.get("key", ""), client.form_key):
            raise HTTPException(status_code=403)
        if request.headers.get("content-type", "").startswith("application/json"):
            data = await request.json()
        else:
            data = dict(await request.form())
        phone = _normalize_us(str(data.get("phone", "")))
        if not phone:
            raise HTTPException(status_code=422, detail="phone is required")
        tasks.add_task(
            service.start_conversation,
            client,
            phone,
            "web_form",
            name=(str(data.get("name", "")).strip() or None),
            message=(str(data.get("message", "")).strip() or None),
        )
        return {"ok": True}

    @app.post("/tasks/flush-stale", dependencies=[Depends(require_admin)])
    def flush_stale() -> dict:
        return {"partial_leads_sent": service.flush_stale({c.id: c for c in registry.all()})}

    @app.get("/admin/clients/{client_id}/metrics", dependencies=[Depends(require_admin)])
    def metrics(client_id: str) -> dict:
        if registry.by_id(client_id) is None:
            raise HTTPException(status_code=404)
        return compute_metrics(store.all_for(client_id))

    return app


def compute_metrics(convs) -> dict:
    """The numbers a client actually asks about on a monthly check-in."""

    def secs(a: str | None, b: str | None) -> float | None:
        if not a or not b:
            return None
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()

    to_text = [s for c in convs if (s := secs(c.created_at, c.first_text_at)) is not None]
    total = len(convs)
    replied = sum(1 for c in convs if c.first_reply_at)
    qualified = sum(1 for c in convs if c.status == "complete")
    return {
        "conversations": total,
        "by_source": {s: sum(1 for c in convs if c.source == s) for s in {c.source for c in convs}},
        "median_seconds_to_first_text": statistics.median(to_text) if to_text else None,
        "reply_rate": round(replied / total, 3) if total else None,
        "qualified_rate": round(qualified / total, 3) if total else None,
        "leads_sent": sum(1 for c in convs if c.lead_sent_at),
        "emergencies": sum(1 for c in convs if c.emergency),
        "opted_out": sum(1 for c in convs if c.status == "opted_out"),
    }


def _normalize_us(raw: str) -> str:
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return ""


def app_factory() -> FastAPI:  # uvicorn --factory app.main:app_factory
    return create_app()

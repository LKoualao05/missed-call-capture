"""Full flow through the HTTP layer with fake Twilio and the scripted qualifier."""

from conftest import CALLER, make_client


def call(http, to="+16145550100", frm=CALLER):
    return http.post("/twilio/voice", data={"To": to, "From": frm, "CallSid": "CA1"})


def text(http, body, to="+16145550100", frm=CALLER):
    return http.post("/twilio/sms", data={"To": to, "From": frm, "Body": body})


def test_missed_call_to_qualified_lead(make_http, messenger):
    http = make_http()

    r = call(http)
    assert r.status_code == 200
    assert "<Say" in r.text and "<Hangup/>" in r.text

    first = messenger.to(CALLER)
    assert len(first) == 1
    assert "Acme HVAC" in first[0] and "What can we help you with" in first[0]

    text(http, "AC is blowing warm air")
    assert "How soon" in messenger.to(CALLER)[-1]

    text(http, "today if possible")
    assert "address or ZIP" in messenger.to(CALLER)[-1]

    text(http, "1200 Morse Rd 43219")
    assert "sent your details to Mike" in messenger.to(CALLER)[-1]

    lead = messenger.to("+16145550199")
    assert len(lead) == 1
    assert lead[0].startswith("NEW LEAD - Missed call")
    assert "Need: AC is blowing warm air" in lead[0]
    assert "When: today if possible" in lead[0]
    assert "Where: 1200 Morse Rd 43219" in lead[0]
    assert "Phone: (614) 555-1234" in lead[0]
    assert "outside your service area" not in lead[0]


def test_lead_flags_out_of_area_zip(make_http, messenger):
    http = make_http()
    call(http)
    for body in ["furnace not working", "this week", "44101"]:
        text(http, body)
    assert "outside your service area" in messenger.to("+16145550199")[0]


def test_repeat_call_within_window_does_not_double_text(make_http, messenger):
    http = make_http()
    call(http)
    call(http)
    assert len(messenger.to(CALLER)) == 1


def test_after_hours_wording(make_http, messenger):
    http = make_http(make_client(business_hours={}))
    call(http)
    assert "after hours" in messenger.to(CALLER)[0]


def test_front_number_rings_owner_first(make_http, messenger):
    http = make_http(make_client(call_mode="front_number"))
    r = call(http)
    assert "<Dial" in r.text and "+16145550199" in r.text
    assert 'action="https://leads.test/twilio/dial-status"' in r.text
    assert messenger.sent == []

    answered = http.post(
        "/twilio/dial-status", data={"To": "+16145550100", "From": CALLER, "DialCallStatus": "completed"}
    )
    assert "<Hangup/>" in answered.text and messenger.sent == []

    http.post("/twilio/dial-status", data={"To": "+16145550100", "From": CALLER, "DialCallStatus": "no-answer"})
    assert len(messenger.to(CALLER)) == 1


def test_front_number_after_hours_skips_ringing(make_http, messenger):
    http = make_http(make_client(call_mode="front_number", business_hours={}))
    r = call(http)
    assert "<Dial" not in r.text
    assert len(messenger.to(CALLER)) == 1


def test_unknown_number_404(make_http):
    http = make_http()
    assert call(http, to="+19995550000").status_code == 404


def test_web_form_uses_message_and_skips_answered_question(make_http, messenger):
    http = make_http()
    r = http.post(
        "/forms/acme-hvac?key=secret",
        json={"name": "Sarah", "phone": "(614) 555-1234", "message": "Water heater is leaking"},
    )
    assert r.status_code == 200
    first = messenger.to(CALLER)[0]
    assert first.startswith("Hi Sarah, this is Acme HVAC")
    assert "How soon" in first

    text(http, "asap")
    text(http, "43230")
    lead = messenger.to("+16145550199")[0]
    assert "After-hours web form" in lead
    assert "Name: Sarah" in lead
    assert "Need: Water heater is leaking" in lead


def test_web_form_rejects_bad_key_and_missing_phone(make_http):
    http = make_http()
    assert http.post("/forms/acme-hvac?key=nope", json={"phone": "6145551234"}).status_code == 403
    assert http.post("/forms/acme-hvac?key=secret", json={"name": "x"}).status_code == 422


def test_stop_ends_conversation_and_blocks_future_texts(make_http, messenger):
    http = make_http()
    call(http)
    text(http, "STOP")
    text(http, "hello?")  # Twilio would block this anyway; we must not respond either
    assert len(messenger.to(CALLER)) == 1
    assert messenger.to("+16145550199") == []


def test_help_keyword(make_http, messenger):
    http = make_http()
    text(http, "HELP")
    assert "Reply STOP" in messenger.to(CALLER)[0]


def test_emergency_alerts_owner_immediately(make_http, messenger):
    http = make_http()
    call(http)
    text(http, "I smell gas in the basement")
    owner = messenger.to("+16145550199")
    assert len(owner) == 1 and owner[0].startswith("URGENT LEAD") and "Call now" in owner[0]


def test_stale_conversation_sent_as_partial_lead(make_http, messenger, store):
    http = make_http()
    call(http)
    text(http, "AC making a grinding noise")
    store._db.execute("UPDATE conversations SET updated_at = '2000-01-01T00:00:00+00:00'")

    assert http.post("/tasks/flush-stale").status_code == 401
    r = http.post("/tasks/flush-stale", headers={"Authorization": "Bearer admin"})
    assert r.json() == {"partial_leads_sent": 1}
    lead = messenger.to("+16145550199")[0]
    assert lead.startswith("PARTIAL LEAD") and "grinding noise" in lead and "When: -" in lead

    # Running it again sends nothing new
    assert http.post("/tasks/flush-stale", headers={"Authorization": "Bearer admin"}).json()["partial_leads_sent"] == 0


def test_metrics(make_http):
    http = make_http()
    call(http)
    for body in ["no cooling", "today", "43219"]:
        text(http, body)
    m = http.get("/admin/clients/acme-hvac/metrics", headers={"Authorization": "Bearer admin"}).json()
    assert m["conversations"] == 1 and m["qualified_rate"] == 1.0 and m["leads_sent"] == 1
    assert m["median_seconds_to_first_text"] is not None


def test_signature_required_when_enabled(settings, store, messenger):
    from fastapi.testclient import TestClient

    from app.clients import ClientRegistry
    from app.main import create_app
    from app.qualifier import ScriptedQualifier

    settings.validate_twilio_signature = True
    settings.twilio_auth_token = "token"
    app = create_app(settings, ClientRegistry([make_client()]), store, messenger, ScriptedQualifier())
    r = TestClient(app).post("/twilio/voice", data={"To": "+16145550100", "From": CALLER})
    assert r.status_code == 403


def test_yes_is_an_answer_not_a_keyword(make_http, messenger):
    http = make_http()
    call(http)
    text(http, "water heater leaking")
    text(http, "yes")
    assert "address or ZIP" in messenger.to(CALLER)[-1]


def test_emergency_safety_line_reaches_customer_even_on_fallback(make_http, messenger):
    http = make_http()
    call(http)
    text(http, "smell gas near the furnace")
    assert "call 911" in messenger.to(CALLER)[-1]
    text(http, "right now")
    assert "call 911" not in messenger.to(CALLER)[-1]  # only on first mention

"""Claude qualifier behavior with a stubbed Anthropic client."""

from types import SimpleNamespace

from conftest import make_client

from app.qualifier import ClaudeQualifier, ScriptedQualifier
from app.store import Store


class StubAnthropic:
    def __init__(self, tool_input=None, error=None):
        self.calls = []
        self._input = tool_input
        self._error = error
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error:
            raise self._error
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=self._input)])


def conv():
    s = Store(":memory:")
    c = s.create("acme-hvac", "+16145551234", "missed_call")
    c.transcript.append({"role": "assistant", "text": "What can we help you with?", "at": ""})
    return c


def test_extracts_multiple_answers_from_one_text():
    stub = StubAnthropic(
        {
            "answers": {"need": "AC blowing warm air", "location": "43219"},
            "caller_name": "Tom",
            "emergency": False,
            "reply": "Got it Tom. How soon do you need someone out?",
        }
    )
    q = ClaudeQualifier(stub, "claude-haiku-5-5")
    result = q.next_turn(make_client(), conv(), "Tom here, AC blowing warm air, I'm in 43219")
    assert result.answers == {"need": "AC blowing warm air", "location": "43219"}
    assert result.caller_name == "Tom" and not result.complete
    assert result.reply.startswith("Got it Tom")

    call = stub.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "record_turn"}
    assert set(call["tools"][0]["input_schema"]["properties"]["answers"]["properties"]) == {"need", "urgency", "location"}


def test_code_decides_completion_not_the_model():
    stub = StubAnthropic(
        {"answers": {"need": "leak", "urgency": "today", "location": "43230", "budget": "cheap"},
         "emergency": False, "reply": "anything else?"}
    )
    result = ClaudeQualifier(stub, "m").next_turn(make_client(), conv(), "43230")
    assert result.complete
    assert "budget" not in result.answers  # unknown keys dropped
    assert "sent your details to Mike" in result.reply  # deterministic closing text


def test_keyword_emergency_overrides_model():
    stub = StubAnthropic({"answers": {}, "emergency": False, "reply": "What's going on?"})
    result = ClaudeQualifier(stub, "m").next_turn(make_client(), conv(), "there's a carbon monoxide alarm going off")
    assert result.emergency


def test_api_failure_falls_back_to_script():
    stub = StubAnthropic(error=RuntimeError("overloaded"))
    result = ClaudeQualifier(stub, "m").next_turn(make_client(), conv(), "furnace is out")
    assert result.used_fallback
    assert result.answers["need"] == "furnace is out"
    assert "How soon" in result.reply


def test_malformed_output_falls_back():
    stub = StubAnthropic({"answers": "not a dict", "emergency": False, "reply": ""})
    assert ClaudeQualifier(stub, "m").next_turn(make_client(), conv(), "hi").used_fallback


def test_reply_is_capped_for_sms():
    stub = StubAnthropic({"answers": {}, "emergency": False, "reply": "x" * 1000})
    assert len(ClaudeQualifier(stub, "m").next_turn(make_client(), conv(), "hi").reply) <= 320


def test_scripted_picks_up_zip_early():
    result = ScriptedQualifier().next_turn(make_client(), conv(), "no heat at 43219")
    assert result.answers["need"] == "no heat at 43219"
    assert result.answers["location"] == "43219"
    assert result.emergency  # "no heat" is a default emergency keyword

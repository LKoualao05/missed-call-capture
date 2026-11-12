from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from conftest import make_client

from app.clients import ClientRegistry
from app.compliance import Keyword, classify
from app.leads import pretty_phone

ET = ZoneInfo("America/New_York")
HOURS = {"mon": ["08:00", "17:00"]}


def test_business_hours_in_client_timezone():
    c = make_client(business_hours=HOURS)
    assert c.is_open(datetime(2026, 11, 9, 9, 0, tzinfo=ET))       # Monday 9am
    assert not c.is_open(datetime(2026, 11, 9, 17, 0, tzinfo=ET))  # close is exclusive
    assert not c.is_open(datetime(2026, 11, 10, 9, 0, tzinfo=ET))  # Tuesday not configured
    # 13:30 UTC on Monday is 8:30am Eastern
    assert c.is_open(datetime(2026, 11, 9, 13, 30, tzinfo=ZoneInfo("UTC")))


def test_bad_hours_rejected():
    with pytest.raises(ValueError):
        make_client(business_hours={"monday": ["08:00", "17:00"]})


def test_example_config_loads():
    path = Path(__file__).resolve().parents[1] / "config" / "clients.example.yaml"
    reg = ClientRegistry.from_yaml(path)
    assert len(reg.all()) == 2
    assert reg.by_number("+16145550100").id == "buckeye-hvac"
    assert reg.by_id("lakeside-plumbing").call_mode == "front_number"


def test_duplicate_tracking_numbers_rejected():
    with pytest.raises(ValueError):
        ClientRegistry([make_client(id="a"), make_client(id="b")])


@pytest.mark.parametrize("body,expected", [
    ("STOP", Keyword.STOP), (" stop. ", Keyword.STOP), ("Unsubscribe", Keyword.STOP),
    ("START", Keyword.START), ("help", Keyword.HELP), ("stop by tomorrow?", Keyword.NONE),
])
def test_keywords(body, expected):
    assert classify(body) is expected


def test_pretty_phone():
    assert pretty_phone("+16145551234") == "(614) 555-1234"
    assert pretty_phone("+442071234567") == "+442071234567"

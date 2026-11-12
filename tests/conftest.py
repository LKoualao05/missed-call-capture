from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.clients import ClientConfig, ClientRegistry
from app.main import create_app
from app.qualifier import ScriptedQualifier
from app.settings import Settings
from app.store import Store
from app.telephony import RecordingMessenger

ALL_DAY = {d: ["00:00", "23:59"] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}

CALLER = "+16145551234"


def make_client(**overrides) -> ClientConfig:
    base = dict(
        id="acme-hvac",
        business_name="Acme HVAC",
        trade="HVAC",
        owner_name="Mike",
        tracking_number="+16145550100",
        owner_phone="+16145550199",
        business_hours=ALL_DAY,
        service_area_zips=["43219", "43230"],
        form_key="secret",
    )
    base.update(overrides)
    return ClientConfig(**base)


@pytest.fixture
def client_cfg() -> ClientConfig:
    return make_client()


@pytest.fixture
def messenger() -> RecordingMessenger:
    return RecordingMessenger()


@pytest.fixture
def store() -> Store:
    return Store(":memory:")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        validate_twilio_signature=False,
        admin_token="admin",
        public_base_url="https://leads.test",
        _env_file=None,
    )


@pytest.fixture
def make_http(settings, store, messenger):
    def _make(*clients: ClientConfig, qualifier=None) -> TestClient:
        app = create_app(
            settings=settings,
            registry=ClientRegistry(list(clients) or [make_client()]),
            store=store,
            messenger=messenger,
            qualifier=qualifier or ScriptedQualifier(),
        )
        return TestClient(app)

    return _make

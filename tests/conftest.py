from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from copilot.api.main import create_app
from copilot.config import Settings

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/support-cases.json"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        environment="test",
        dataset_path=DATASET,
        zendesk_cli_path=Path("/nonexistent/zendesk-cli"),
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as value:
        yield value

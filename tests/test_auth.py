from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import copilot.auth as auth
from copilot.api.main import create_app
from copilot.auth import AuthenticationError
from copilot.config import Settings

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/support-cases.json"


def test_bearer_mode_rejects_missing_token() -> None:
    settings = Settings(
        environment="test",
        auth_mode="bearer",
        api_key="test-secret",
        dataset_path=DATASET,
    )
    with TestClient(create_app(settings)) as client:
        rejected = client.get("/v1/cases")
        accepted = client.get(
            "/v1/cases",
            headers={"Authorization": "Bearer test-secret"},
        )

    assert rejected.status_code == 401
    assert accepted.status_code == 200


def test_alb_mode_rejects_unsigned_headers() -> None:
    settings = Settings(
        environment="test",
        auth_mode="alb_oidc",
        aws_region="ap-southeast-2",
        alb_arn="arn:aws:elasticloadbalancing:ap-southeast-2:123456789012:"
        "loadbalancer/app/copilot/example",
        alb_client_id="client-id",
        dataset_path=DATASET,
    )
    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/v1/cases",
            headers={
                "x-amzn-oidc-data": "not-a-jwt",
                "x-amzn-oidc-identity": "subject",
            },
        )

    assert response.status_code == 401


async def test_alb_key_fetch_errors_fail_closed_and_are_negative_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key_id = "missing-key-regression"
    cache_key = ("ap-southeast-2", key_id)
    auth._key_cache.pop(cache_key, None)
    auth._negative_key_cache.pop(cache_key, None)
    requests = 0

    class FailingClient:
        async def __aenter__(self) -> "FailingClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str) -> httpx.Response:
            nonlocal requests
            requests += 1
            request = httpx.Request("GET", url)
            raise httpx.ConnectError("synthetic key endpoint failure", request=request)

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FailingClient())

    with pytest.raises(AuthenticationError, match="could not be retrieved"):
        await auth._public_key(*cache_key)
    with pytest.raises(AuthenticationError, match="unavailable"):
        await auth._public_key(*cache_key)

    assert requests == 1
    auth._negative_key_cache.pop(cache_key, None)


def test_negative_key_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    auth._negative_key_cache.clear()
    monkeypatch.setattr(auth, "NEGATIVE_KEY_CACHE_LIMIT", 2)

    auth._remember_negative_key(("ap-southeast-2", "key-1"))
    auth._remember_negative_key(("ap-southeast-2", "key-2"))
    auth._remember_negative_key(("ap-southeast-2", "key-3"))

    assert len(auth._negative_key_cache) == 2
    assert ("ap-southeast-2", "key-1") not in auth._negative_key_cache
    auth._negative_key_cache.clear()

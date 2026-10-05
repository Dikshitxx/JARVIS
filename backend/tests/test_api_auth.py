import pytest
from fastapi import HTTPException

from app.api.auth import require_api_secret
from app.core import config


def test_api_auth_fails_closed_when_secret_is_missing(monkeypatch):
    monkeypatch.setattr(config, "API_SECRET", "")

    with pytest.raises(HTTPException) as error:
        require_api_secret("")

    assert error.value.status_code == 503


def test_api_auth_requires_the_configured_secret(monkeypatch):
    monkeypatch.setattr(config, "API_SECRET", "configured-test-secret")

    with pytest.raises(HTTPException) as error:
        require_api_secret("wrong-secret")
    assert error.value.status_code == 401

    assert require_api_secret("configured-test-secret") is None

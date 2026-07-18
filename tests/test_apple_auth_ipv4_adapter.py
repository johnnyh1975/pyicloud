"""Tests for the AppleAuthIPv4Adapter in pyicloud.session."""

import socket
from typing import Any
from unittest.mock import MagicMock

import pytest
import urllib3.util.connection
from pytest import MonkeyPatch

from pyicloud.session import APPLE_AUTH_ENDPOINT, AppleAuthIPv4Adapter, PyiCloudSession


def test_adapter_forces_af_inet_during_send_and_restores_after(
    monkeypatch: MonkeyPatch,
) -> None:
    """allowed_gai_family is swapped to AF_INET for the duration of send()
    and restored afterwards, even though the underlying HTTPAdapter.send
    is mocked out (no real network call is made)."""
    observed: dict[str, Any] = {}

    def fake_send(self, request, **kwargs) -> str:  # pylint: disable=unused-argument
        # Record what the resolver family is *while the request is in flight*.
        observed["family_during_send"] = urllib3.util.connection.allowed_gai_family()
        return "fake-response"

    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", fake_send)

    sentinel_family = urllib3.util.connection.allowed_gai_family
    adapter = AppleAuthIPv4Adapter()

    result = adapter.send(MagicMock())

    assert result == "fake-response"
    assert observed["family_during_send"] == socket.AF_INET
    # Global resolver override must not leak past the call.
    assert urllib3.util.connection.allowed_gai_family is sentinel_family


def test_adapter_restores_family_even_if_send_raises(monkeypatch: MonkeyPatch) -> None:
    """The finally-block restoration must run even on a failed request,
    otherwise a single failed auth request would force IPv4 globally for
    every subsequent request in the process."""

    def failing_send(self, request, **kwargs):  # pylint: disable=unused-argument
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr("requests.adapters.HTTPAdapter.send", failing_send)

    sentinel_family = urllib3.util.connection.allowed_gai_family
    adapter = AppleAuthIPv4Adapter()

    with pytest.raises(ConnectionError):
        adapter.send(MagicMock())

    assert urllib3.util.connection.allowed_gai_family is sentinel_family


def test_apple_auth_endpoint_adapter_is_mounted_on_idmsa_only(
    pyicloud_service,  # fixture from conftest.py
) -> None:
    """The IPv4-only adapter must be mounted specifically on the idmsa auth
    host, and must not replace the default adapter used for every other
    iCloud host (calendar, drive, photos, setup, etc.)."""
    session: PyiCloudSession = pyicloud_service.session

    mounted = session.get_adapter(f"{APPLE_AUTH_ENDPOINT}/appleauth/auth")
    assert isinstance(mounted, AppleAuthIPv4Adapter)

    other_host_adapter = session.get_adapter("https://www.icloud.com/setup/ws/1")
    assert not isinstance(other_host_adapter, AppleAuthIPv4Adapter)

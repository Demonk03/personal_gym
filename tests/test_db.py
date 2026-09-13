import sys
from types import ModuleType

import httpx
import pytest

import db
from db import MemoryRepository, NotFound
from operations import OperationConflict, execute_operation


def test_memory_operation_returns_saved_result_and_rejects_changed_body():
    repository = MemoryRepository()
    operation_id = "60000000-0000-4000-8000-000000000001"
    calls = []

    first = execute_operation(repository, operation_id, "example", None, {"value": 1}, lambda: calls.append(1) or {"saved": True})
    repeated = execute_operation(repository, operation_id, "example", None, {"value": 1}, lambda: calls.append(2) or {})

    assert first == repeated == {"saved": True}
    assert calls == [1]
    with pytest.raises(OperationConflict):
        execute_operation(repository, operation_id, "example", None, {"value": 2}, lambda: {})


def test_missing_operation_is_not_found():
    with pytest.raises(NotFound):
        MemoryRepository().operation_status("60000000-0000-4000-8000-000000000002")


def test_failed_operation_can_be_retried_with_the_same_id():
    repository = MemoryRepository()
    operation_id = "60000000-0000-4000-8000-000000000003"
    attempts = []

    with pytest.raises(RuntimeError):
        execute_operation(repository, operation_id, "retry", None, {}, lambda: (_ for _ in ()).throw(RuntimeError("temporary")))
    result = execute_operation(
        repository, operation_id, "retry", None, {}, lambda: attempts.append(1) or {"saved": True},
    )

    assert result == {"saved": True}
    assert attempts == [1]


def test_supabase_client_uses_http1_transport(monkeypatch):
    recorded = {}
    transport = object()
    client = object()

    def fake_http_client(**kwargs):
        recorded["httpx"] = kwargs
        return transport

    class FakeClientOptions:
        def __init__(self, **kwargs):
            recorded["options"] = kwargs

    def fake_create_client(url, key, options=None):
        recorded["create"] = {"url": url, "key": key, "options": options}
        return client

    fake_supabase = ModuleType("supabase")
    fake_supabase.ClientOptions = FakeClientOptions
    fake_supabase.create_client = fake_create_client
    monkeypatch.setitem(sys.modules, "supabase", fake_supabase)
    monkeypatch.setattr(httpx, "Client", fake_http_client)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "secret")

    assert db.get_client() is client
    assert recorded["httpx"]["http2"] is False
    assert recorded["options"]["httpx_client"] is transport
    assert recorded["create"]["url"] == "https://example.supabase.co"
    assert recorded["create"]["key"] == "secret"

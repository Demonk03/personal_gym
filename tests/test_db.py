import pytest

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

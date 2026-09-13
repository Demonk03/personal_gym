"""Idempotency helpers shared by memory tests and the Supabase boundary."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable


class OperationConflict(Exception):
    pass


class OperationPending(Exception):
    pass


def body_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def execute_operation(
    repository: Any,
    operation_id: str,
    kind: str,
    resource_id: str | None,
    payload: dict[str, Any],
    callback: Callable[[], dict[str, Any]],
    payload_digest: str | None = None,
) -> dict[str, Any]:
    """Execute once and persist the result using a repository operation store."""
    claim = repository.claim_operation(operation_id, kind, resource_id, payload_digest or body_hash(payload))
    status = claim["status"]
    if status == "conflict":
        raise OperationConflict
    if status == "pending":
        raise OperationPending
    if status == "succeeded":
        return claim["result"]
    token = claim["token"]
    try:
        result = callback()
    except Exception as error:
        repository.fail_operation(operation_id, token, {"message": str(error)})
        raise
    repository.commit_operation(operation_id, token, result)
    return result

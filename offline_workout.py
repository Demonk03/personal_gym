"""Validate one immutable offline-workout snapshot before committing it."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from db import validate_set_fact, Conflict


def _uuid(value: Any) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("invalid_offline_id") from None


def _timestamp(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.isoformat()
    except ValueError:
        raise ValueError("invalid_offline_timestamp") from None


def validate_snapshot(bundle: dict[str, Any], payload: dict[str, Any],
                      catalog: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return canonical entries and sets, rejecting every partial/ambiguous snapshot."""
    workout = bundle["workout"]
    if workout["status"] != "in_progress":
        raise ValueError("invalid_workout_state")
    if payload.get("revision") != workout["revision"]:
        raise ValueError("revision_conflict")
    if payload.get("status") not in {"completed", "stopped_early"}:
        raise ValueError("invalid_terminal_status")
    if payload["status"] == "stopped_early" and not payload.get("stop_reason"):
        raise ValueError("stop_reason_required")
    _timestamp(payload.get("finished_at"))
    entries = payload.get("entries")
    sets = payload.get("sets")
    if not isinstance(entries, list) or not isinstance(sets, list) or not entries:
        raise ValueError("invalid_offline_snapshot")
    if len(entries) > 100 or len(sets) > 500:
        raise ValueError("offline_snapshot_too_large")
    baseline = {row["id"]: row for row in bundle["exercises"]}
    seen, positions, cards, normalized = set(), set(), {}, []
    equipment = next((c["payload"].get("equipment", []) for c in bundle["checkins"] if c["kind"] == "pre"), [])
    library = workout["program_snapshot"].get("exercise_library", {})
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("invalid_offline_entry")
        entry_id = _uuid(item.get("id"))
        pos = item.get("position")
        if entry_id in seen or isinstance(pos, bool) or not isinstance(pos, int) or pos in positions or pos < 1:
            raise ValueError("duplicate_offline_entry")
        seen.add(entry_id)
        positions.add(pos)
        if not isinstance(item.get("removed"), bool) or not isinstance(item.get("skipped"), bool):
            raise ValueError("invalid_offline_flags")
        original = baseline.get(entry_id)
        if original:
            selected = item.get("exercise_id")
            if not isinstance(selected, str):
                raise ValueError("invalid_offline_exercise")
            if selected != original["exercise_id"]:
                if original.get("is_ad_hoc"):
                    raise ValueError("replacement_not_allowed")
                source = next((s for s in workout["program_snapshot"].get("exercises", [])
                               if s["exercise_id"] == original["original_exercise_id"]), None)
                definition = library.get(selected)
                if (not source or selected not in source.get("allowed_replacements", [])
                        or not definition or definition.get("review_status") != "allowed"
                        or not definition.get("active", True)
                        or not set(definition.get("equipment", [])).issubset(equipment)
                        or definition.get("measurement_type") != original["definition_snapshot"].get("measurement_type")):
                    raise ValueError("replacement_not_allowed")
            else:
                definition = original["definition_snapshot"]
            row = {**original, "position": pos, "exercise_id": selected,
                   "removed": item["removed"], "skipped": item["skipped"],
                   "definition_snapshot": definition}
        else:
            exercise = item.get("exercise")
            if not isinstance(exercise, dict) or not isinstance(exercise.get("id"), str):
                raise ValueError("invalid_offline_exercise")
            selected = exercise["id"]
            card = catalog.get(selected)
            if card is None:
                if not selected.startswith("custom-"):
                    raise ValueError("exercise_not_found")
                _uuid(selected[7:])
                if not isinstance(exercise.get("name"), str) or not exercise["name"].strip():
                    raise ValueError("invalid_offline_exercise")
                if exercise.get("measurement_type") not in {"reps", "seconds", "weighted_reps", "reps_seconds"}:
                    raise ValueError("invalid_offline_exercise")
                card = {**exercise, "active": True, "review_status": "needs_review"}
                cards[selected] = card
            elif not card.get("active", True) or card.get("review_status") == "blocked":
                raise ValueError("exercise_unavailable")
            definition = {k: card.get(k, "") for k in ("id", "name", "measurement_type", "note")}
            row = {"id": entry_id, "workout_id": workout["id"],
                   "original_exercise_id": selected, "exercise_id": selected,
                   "position": pos, "planned_sets": None, "planned_reps": None,
                   "planned_seconds": None, "planned_weight_kg": None,
                   "is_ad_hoc": True, "removed": item["removed"], "skipped": item["skipped"],
                   "definition_snapshot": definition, "revision": 1}
        normalized.append(row)
    if not set(baseline).issubset(seen) or positions != set(range(1, len(entries) + 1)):
        raise ValueError("invalid_offline_entries")
    by_id = {row["id"]: row for row in normalized}
    seen_sets, set_numbers, normalized_sets = set(), set(), []
    for item in sets:
        if not isinstance(item, dict):
            raise ValueError("invalid_offline_set")
        set_id = _uuid(item.get("id"))
        entry_id = _uuid(item.get("workout_exercise_id"))
        row = by_id.get(entry_id)
        number = item.get("set_number")
        if (set_id in seen_sets or not row or row["removed"] or row["skipped"]
                or isinstance(number, bool) or not isinstance(number, int)
                or not 1 <= number <= 50 or (entry_id, number) in set_numbers):
            raise ValueError("invalid_offline_set")
        seen_sets.add(set_id)
        set_numbers.add((entry_id, number))
        actual = {k: item.get(k) for k in ("actual_reps", "actual_seconds", "actual_weight_kg")}
        for key, maximum in (("actual_reps", 1000), ("actual_seconds", 7200), ("actual_weight_kg", 400)):
            value = actual[key]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                      or value < 0 or value > maximum or (key != "actual_weight_kg" and not isinstance(value, int))):
                raise ValueError("invalid_offline_set")
        try:
            validate_set_fact(row["definition_snapshot"]["measurement_type"], actual)
        except Conflict:
            raise ValueError("measurement_mismatch") from None
        normalized_sets.append({"id": set_id, "workout_id": workout["id"],
                                "workout_exercise_id": entry_id, "set_number": number,
                                **actual, "completed_at": _timestamp(item.get("completed_at")), "revision": 1})
    if payload["status"] == "completed" and any(
        not row.get("is_ad_hoc") and not row["removed"] and
        (row["skipped"] or sum(s["workout_exercise_id"] == row["id"] for s in normalized_sets) < row["planned_sets"])
        for row in normalized
    ):
        raise ValueError("incomplete_workout")
    return {"entries": normalized, "sets": normalized_sets, "new_cards": cards}

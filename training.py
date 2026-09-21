"""Deterministic check-in evaluation and workout construction."""

from __future__ import annotations

from copy import deepcopy
from math import floor
from typing import Any
from uuid import uuid4


REQUIRED_CHECKIN_FIELDS = {
    "back_pain", "pain_change",
    "readiness", "location", "equipment",
}
PAIN_CHANGES = {"better", "same", "worse"}
LEG_TRENDS = {"none", "better", "same", "worse", "new"}
WEAKNESS_LEVELS = {"none", "mild", "severe"}
LOCATIONS = {"home", "outdoor", "gym"}


def _is_int(value: Any, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _valid_checkin(checkin: dict[str, Any]) -> tuple[bool, list[str]]:
    missing = sorted(REQUIRED_CHECKIN_FIELDS - set(checkin))
    errors = [f"missing:{field}" for field in missing]
    if missing:
        return False, errors
    leg = checkin.get("leg_symptoms")
    systemic = checkin.get("systemic_symptoms")
    if not _is_int(checkin.get("back_pain"), 0, 10):
        errors.append("invalid:back_pain")
    if checkin.get("pain_change") not in PAIN_CHANGES:
        errors.append("invalid:pain_change")
    if not _is_int(checkin.get("readiness"), 1, 5):
        errors.append("invalid:readiness")
    if checkin.get("location") not in LOCATIONS:
        errors.append("invalid:location")
    equipment = checkin.get("equipment")
    if not isinstance(equipment, list) or any(not isinstance(item, str) for item in equipment):
        errors.append("invalid:equipment")
    elif len(equipment) != len(set(equipment)):
        errors.append("invalid:equipment")
    if leg is not None and not isinstance(leg, dict):
        errors.append("invalid:leg_symptoms")
    elif leg is not None:
        if "trend" in leg and leg["trend"] not in LEG_TRENDS:
            errors.append("invalid:leg_symptoms.trend")
        if "weakness" in leg and leg["weakness"] not in WEAKNESS_LEVELS:
            errors.append("invalid:leg_symptoms.weakness")
        for field in ("bilateral", "saddle_numbness", "bladder_bowel_change"):
            if field in leg and not isinstance(leg[field], bool):
                errors.append(f"invalid:leg_symptoms.{field}")
    if systemic is not None and not isinstance(systemic, dict):
        errors.append("invalid:systemic_symptoms")
    elif systemic is not None:
        for field in (
            "unusual_weakness", "dizziness", "palpitations",
            "active_or_worsening_bleeding", "fainting", "severe_shortness_of_breath",
        ):
            if field in systemic and not isinstance(systemic[field], bool):
                errors.append(f"invalid:systemic_symptoms.{field}")
    return not errors, errors


def evaluate_checkin(checkin: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Return a versioned deterministic mode without making a medical inference."""
    if not isinstance(checkin, dict) or not isinstance(rules, dict):
        return {
            "mode": "yellow", "reasons": ["invalid:payload"], "blocks_workout": False,
            "complete": False, "rule_version": rules.get("version") if isinstance(rules, dict) else None,
            "demo_only": True, "pilot": False,
        }
    valid, validation_reasons = _valid_checkin(checkin)
    result = {
        "mode": "yellow", "reasons": validation_reasons, "blocks_workout": False,
        "complete": valid, "rule_version": rules.get("version"),
        "demo_only": bool(rules.get("demo_only", True)),
        "pilot": bool(rules.get("pilot", False)),
    }
    if not valid:
        return result
    leg = checkin.get("leg_symptoms") or {}
    systemic = checkin.get("systemic_symptoms") or {}
    red_reasons = []
    if leg.get("weakness") == "severe":
        red_reasons.append("red:severe_leg_weakness")
    if leg.get("bilateral") and leg.get("trend") in {"new", "worse"}:
        red_reasons.append("red:bilateral_leg_symptoms")
    if leg.get("saddle_numbness"):
        red_reasons.append("red:saddle_numbness")
    if leg.get("bladder_bowel_change"):
        red_reasons.append("red:bladder_bowel_change")
    if systemic.get("fainting"):
        red_reasons.append("red:fainting")
    if systemic.get("severe_shortness_of_breath"):
        red_reasons.append("red:severe_shortness_of_breath")
    if red_reasons:
        return {**result, "mode": "red", "reasons": red_reasons, "blocks_workout": True}
    yellow = rules.get("yellow", {})
    yellow_reasons = []
    if checkin["back_pain"] >= int(yellow.get("pain_at_least", 7)):
        yellow_reasons.append("yellow:elevated_back_pain")
    if checkin["pain_change"] == "worse":
        yellow_reasons.append("yellow:back_pain_worse")
    if leg.get("trend") in {"new", "worse"}:
        yellow_reasons.append("yellow:leg_symptoms_worse")
    if leg.get("weakness") == "mild":
        yellow_reasons.append("yellow:mild_leg_weakness")
    if checkin["readiness"] <= int(yellow.get("readiness_at_most", 2)):
        yellow_reasons.append("yellow:low_readiness")
    for field in ("unusual_weakness", "dizziness", "palpitations", "active_or_worsening_bleeding"):
        if systemic.get(field):
            yellow_reasons.append(f"yellow:{field}")
    if yellow_reasons:
        return {**result, "mode": "yellow", "reasons": yellow_reasons}
    return {**result, "mode": "green", "reasons": []}


def _available(exercise: dict[str, Any], equipment: set[str]) -> bool:
    return set(exercise.get("equipment", [])).issubset(equipment)


def is_program_eligible(exercise: dict[str, Any]) -> bool:
    """Only manually allowed, active cards may be selected by a program."""
    return bool(exercise.get("active", True)) and exercise.get("review_status") == "allowed"


def definition_snapshot(exercise_id: str, exercise: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": exercise_id,
        "name": exercise["name"],
        "measurement_type": exercise["measurement_type"],
        "note": exercise.get("note", ""),
    }


def build_direct_workout(program: dict[str, Any]) -> dict[str, Any]:
    library = program.get("exercise_library", {})
    plan = []
    for source in program.get("exercises", []):
        exercise_id = source["exercise_id"]
        definition = library.get(exercise_id)
        if not definition:
            raise ValueError(f"unknown_exercise:{exercise_id}")
        if not is_program_eligible(definition):
            raise ValueError(f"exercise_not_allowed:{exercise_id}")
        plan.append({
            "id": str(uuid4()), "original_exercise_id": exercise_id, "exercise_id": exercise_id,
            "name": definition["name"], "position": len(plan) + 1,
            "planned_sets": source["planned_sets"], "planned_reps": source.get("planned_reps"),
            "planned_seconds": source.get("planned_seconds"),
            "planned_weight_kg": source.get("planned_weight_kg"),
            "replacement_reason": None, "demo_only": bool(definition.get("demo_only", True)),
            "definition_snapshot": definition_snapshot(exercise_id, definition), "is_ad_hoc": False,
        })
    if not plan:
        raise ValueError("empty_plan")
    return {"program_version": program["version"], "program_version_id": program.get("id"),
            "program_session_id": program.get("session_id"), "rule_version": "manual-v1",
            "demo_only": bool(program.get("demo_only", True)), "mode": None,
            "adaptation_reasons": [], "exercises": plan, "omitted": [],
            "source_snapshot": deepcopy(program)}


def _yellow_value(value: Any, factor: float) -> Any:
    return None if value is None else max(1, floor(value * factor))


def build_workout(program: dict[str, Any], checkin_result: dict[str, Any], equipment: list[str]) -> dict[str, Any] | None:
    """Build a plan snapshot from one session and an exercise library."""
    if checkin_result.get("blocks_workout") or checkin_result.get("mode") == "red":
        return None
    if not checkin_result.get("complete"):
        raise ValueError("checkin_incomplete")
    if checkin_result.get("rule_version") != program.get("rule_version"):
        raise ValueError("rule_version_mismatch")
    library = program.get("exercise_library", {})
    allowed_equipment = set(equipment)
    omitted: list[dict[str, str]] = []
    plan: list[dict[str, Any]] = []
    for source in program.get("exercises", []):
        item = deepcopy(source)
        original_id = item["exercise_id"]
        selected_id = original_id
        definition = library.get(original_id)
        if not definition:
            raise ValueError(f"unknown_exercise:{original_id}")
        if not is_program_eligible(definition):
            raise ValueError(f"exercise_not_allowed:{original_id}")
        replacement_reason = None
        if not _available(definition, allowed_equipment):
            selected_id = ""
            for candidate_id in item.get("allowed_replacements", []):
                candidate = library.get(candidate_id)
                if candidate and is_program_eligible(candidate) and _available(candidate, allowed_equipment):
                    selected_id = candidate_id
                    definition = candidate
                    replacement_reason = "equipment_unavailable"
                    break
            if not selected_id:
                omitted.append({"exercise_id": original_id, "reason": "equipment_unavailable"})
                continue
        factor = float(item.get("yellow_factor", 0.7)) if checkin_result["mode"] == "yellow" else 1.0
        plan.append({
            "id": str(uuid4()), "original_exercise_id": original_id, "exercise_id": selected_id,
            "name": definition["name"], "position": len(plan) + 1,
            "planned_sets": _yellow_value(item["planned_sets"], factor),
            "planned_reps": _yellow_value(item.get("planned_reps"), factor),
            "planned_seconds": _yellow_value(item.get("planned_seconds"), factor),
            "planned_weight_kg": item.get("planned_weight_kg"),
            "replacement_reason": replacement_reason,
            "demo_only": bool(definition.get("demo_only", True)),
            "definition_snapshot": definition_snapshot(selected_id, definition),
            "is_ad_hoc": False,
        })
    return {
        "program_version": program["version"], "program_version_id": program.get("id"),
        "program_session_id": program.get("session_id"), "rule_version": program["rule_version"],
        "demo_only": bool(program.get("demo_only", True)), "mode": checkin_result["mode"],
        "adaptation_reasons": list(checkin_result.get("reasons", [])), "exercises": plan,
        "omitted": omitted, "source_snapshot": deepcopy(program),
    }

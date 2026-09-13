"""Deterministic demo check-in evaluation and workout construction."""

from __future__ import annotations

from copy import deepcopy
from math import floor
from typing import Any
from uuid import uuid4


REQUIRED_CHECKIN_FIELDS = {
    "back_pain", "pain_change", "leg_symptoms", "systemic_symptoms",
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
    if not isinstance(leg, dict):
        errors.append("invalid:leg_symptoms")
    else:
        if leg.get("trend") not in LEG_TRENDS:
            errors.append("invalid:leg_symptoms.trend")
        if leg.get("weakness") not in WEAKNESS_LEVELS:
            errors.append("invalid:leg_symptoms.weakness")
        for field in ("bilateral", "saddle_numbness", "bladder_bowel_change"):
            if not isinstance(leg.get(field), bool):
                errors.append(f"invalid:leg_symptoms.{field}")
    if not isinstance(systemic, dict):
        errors.append("invalid:systemic_symptoms")
    else:
        for field in (
            "unusual_weakness", "dizziness", "palpitations",
            "active_or_worsening_bleeding", "fainting", "severe_shortness_of_breath",
        ):
            if not isinstance(systemic.get(field), bool):
                errors.append(f"invalid:systemic_symptoms.{field}")
    return not errors, errors


def evaluate_checkin(checkin: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    """Return a versioned demo mode without making a medical inference."""
    if not isinstance(checkin, dict) or not isinstance(rules, dict):
        return {
            "mode": "yellow", "reasons": ["invalid:payload"], "blocks_workout": False,
            "complete": False, "rule_version": rules.get("version") if isinstance(rules, dict) else None,
            "demo_only": True,
        }
    valid, validation_reasons = _valid_checkin(checkin)
    result = {
        "mode": "yellow", "reasons": validation_reasons, "blocks_workout": False,
        "complete": valid, "rule_version": rules.get("version"),
        "demo_only": bool(rules.get("demo_only", True)),
    }
    if not valid:
        return result
    leg = checkin["leg_symptoms"]
    systemic = checkin["systemic_symptoms"]
    red_reasons = []
    if leg["weakness"] == "severe":
        red_reasons.append("red:severe_leg_weakness")
    if leg["bilateral"] and leg["trend"] in {"new", "worse"}:
        red_reasons.append("red:bilateral_leg_symptoms")
    if leg["saddle_numbness"]:
        red_reasons.append("red:saddle_numbness")
    if leg["bladder_bowel_change"]:
        red_reasons.append("red:bladder_bowel_change")
    if systemic["fainting"]:
        red_reasons.append("red:fainting")
    if systemic["severe_shortness_of_breath"]:
        red_reasons.append("red:severe_shortness_of_breath")
    if red_reasons:
        return {**result, "mode": "red", "reasons": red_reasons, "blocks_workout": True}
    yellow = rules.get("yellow", {})
    yellow_reasons = []
    if checkin["back_pain"] >= int(yellow.get("pain_at_least", 7)):
        yellow_reasons.append("yellow:elevated_back_pain")
    if checkin["pain_change"] == "worse":
        yellow_reasons.append("yellow:back_pain_worse")
    if leg["trend"] in {"new", "worse"}:
        yellow_reasons.append("yellow:leg_symptoms_worse")
    if leg["weakness"] == "mild":
        yellow_reasons.append("yellow:mild_leg_weakness")
    if checkin["readiness"] <= int(yellow.get("readiness_at_most", 2)):
        yellow_reasons.append("yellow:low_readiness")
    for field in ("unusual_weakness", "dizziness", "palpitations", "active_or_worsening_bleeding"):
        if systemic[field]:
            yellow_reasons.append(f"yellow:{field}")
    if yellow_reasons:
        return {**result, "mode": "yellow", "reasons": yellow_reasons}
    return {**result, "mode": "green", "reasons": []}


def _available(exercise: dict[str, Any], equipment: set[str]) -> bool:
    return set(exercise.get("equipment", [])).issubset(equipment)


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
        replacement_reason = None
        if not _available(definition, allowed_equipment):
            selected_id = ""
            for candidate_id in item.get("allowed_replacements", []):
                candidate = library.get(candidate_id)
                if candidate and _available(candidate, allowed_equipment):
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
        })
    return {
        "program_version": program["version"], "program_version_id": program.get("id"),
        "program_session_id": program.get("session_id"), "rule_version": program["rule_version"],
        "demo_only": bool(program.get("demo_only", True)), "mode": checkin_result["mode"],
        "adaptation_reasons": list(checkin_result.get("reasons", [])), "exercises": plan,
        "omitted": omitted, "source_snapshot": deepcopy(program),
    }

import json
from pathlib import Path

import pytest

from training import build_direct_workout, build_workout, evaluate_checkin
from db import demo_rules


FIXTURE = Path(__file__).parent / "fixtures" / "demo_program.json"


def base_checkin():
    return {
        "back_pain": 3,
        "pain_change": "same",
        "leg_symptoms": {
            "trend": "none", "weakness": "none", "bilateral": False,
            "saddle_numbness": False, "bladder_bowel_change": False,
        },
        "systemic_symptoms": {
            "unusual_weakness": False, "dizziness": False, "palpitations": False,
            "active_or_worsening_bleeding": False, "fainting": False,
            "severe_shortness_of_breath": False,
        },
        "readiness": 4,
        "location": "home",
        "equipment": ["mat", "bands"],
    }


@pytest.fixture
def program():
    return json.loads(FIXTURE.read_text())


@pytest.mark.parametrize(
    ("mutate", "mode", "blocked", "reason"),
    [
        (lambda value: value, "green", False, None),
        (lambda value: value.update(back_pain=7), "yellow", False, "yellow:elevated_back_pain"),
        (lambda value: value["leg_symptoms"].update(trend="worse"), "yellow", False, "yellow:leg_symptoms_worse"),
        (lambda value: value["leg_symptoms"].update(weakness="severe"), "red", True, "red:severe_leg_weakness"),
        (lambda value: value["systemic_symptoms"].update(fainting=True), "red", True, "red:fainting"),
    ],
)
def test_evaluate_checkin_modes(program, mutate, mode, blocked, reason):
    checkin = base_checkin()
    mutate(checkin)
    result = evaluate_checkin(checkin, program["rules"])
    assert result["mode"] == mode
    assert result["blocks_workout"] is blocked
    assert result["complete"] is True
    if reason:
        assert reason in result["reasons"]


def test_incomplete_or_unknown_value_never_returns_green(program):
    incomplete = base_checkin()
    incomplete.pop("readiness")
    invalid = base_checkin()
    invalid["pain_change"] = "unknown"
    first = evaluate_checkin(incomplete, program["rules"])
    second = evaluate_checkin(invalid, program["rules"])
    assert first["mode"] == second["mode"] == "yellow"
    assert first["complete"] is second["complete"] is False
    assert "missing:readiness" in first["reasons"]
    assert "invalid:pain_change" in second["reasons"]


def test_usual_pain_requires_no_extra_symptom_answers(program):
    checkin = base_checkin()
    checkin.pop("leg_symptoms")
    checkin.pop("systemic_symptoms")
    result = evaluate_checkin(checkin, program["rules"])
    assert result["complete"] is True
    assert result["mode"] == "green"


def test_optional_leg_answers_still_affect_evaluation(program):
    checkin = base_checkin()
    checkin.pop("systemic_symptoms")
    checkin["leg_symptoms"] = {"weakness": "severe"}
    result = evaluate_checkin(checkin, program["rules"])
    assert result["complete"] is True
    assert result["blocks_workout"] is True
    assert "red:severe_leg_weakness" in result["reasons"]


def test_pilot_rule_metadata_is_preserved_in_checkin_result():
    result = evaluate_checkin(base_checkin(), demo_rules("pilot-rules-v1"))

    assert result["rule_version"] == "pilot-rules-v1"
    assert result["demo_only"] is False
    assert result["pilot"] is True


def test_build_green_workout_keeps_dose_and_uses_allowed_equipment_replacement(program):
    result = evaluate_checkin(base_checkin(), program["rules"])
    workout = build_workout(program, result, ["mat", "bands"])
    assert workout["program_version"] == 1
    assert workout["rule_version"] == "demo-rules-v1"
    assert workout["source_snapshot"] == program
    assert [item["exercise_id"] for item in workout["exercises"]] == ["bird-dog", "band-row", "walk-easy"]
    assert workout["exercises"][0]["planned_sets"] == 3
    assert workout["exercises"][2]["replacement_reason"] == "equipment_unavailable"


def test_build_yellow_workout_reduces_sets_and_reps(program):
    checkin = base_checkin()
    checkin["back_pain"] = 7
    result = evaluate_checkin(checkin, program["rules"])
    workout = build_workout(program, result, ["mat", "bands", "stationary_bike"])
    first = workout["exercises"][0]
    assert workout["mode"] == "yellow"
    assert first["planned_sets"] == 2
    assert first["planned_reps"] == 4


def test_red_mode_builds_no_workout(program):
    checkin = base_checkin()
    checkin["leg_symptoms"]["saddle_numbness"] = True
    result = evaluate_checkin(checkin, program["rules"])
    assert build_workout(program, result, ["mat", "bands"]) is None


def test_direct_workout_keeps_published_dose_without_checkin_or_equipment_filter(program):
    result = build_direct_workout(program)

    assert result["mode"] is None
    assert result["rule_version"] == "manual-v1"
    assert [item["exercise_id"] for item in result["exercises"]] == ["bird-dog", "band-row", "bike-easy"]
    assert result["omitted"] == []


def test_build_rejects_unknown_exercise(program):
    result = evaluate_checkin(base_checkin(), program["rules"])
    program["exercises"][0]["exercise_id"] = "missing"
    with pytest.raises(ValueError, match="unknown_exercise"):
        build_workout(program, result, ["mat"])


def test_build_rejects_non_allowed_program_entry_and_skips_non_allowed_replacement(program):
    result = evaluate_checkin(base_checkin(), program["rules"])
    program["exercise_library"]["bird-dog"]["review_status"] = "needs_review"
    with pytest.raises(ValueError, match="exercise_not_allowed:bird-dog"):
        build_workout(program, result, ["mat"])

    program["exercise_library"]["bird-dog"]["review_status"] = "allowed"
    program["exercise_library"]["walk-easy"]["review_status"] = "blocked"
    workout = build_workout(program, result, ["mat", "bands"])
    assert [item["exercise_id"] for item in workout["exercises"]] == ["bird-dog", "band-row"]
    assert workout["exercises"][0]["definition_snapshot"]["name"] == "Bird dog"

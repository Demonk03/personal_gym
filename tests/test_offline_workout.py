from uuid import uuid4

from test_app import prepare, operation


def start(client, auth):
    prepared, _ = prepare(client, auth)
    workout_id = prepared.get_json()["workout"]["id"]
    started = client.post(
        f"/api/workouts/{workout_id}/start",
        json=operation(revision=1), headers=auth,
    ).get_json()
    return workout_id, started


def finish_body(bundle, *, status="stopped_early"):
    entries = [{
        "id": row["id"], "position": row["position"],
        "exercise_id": row["exercise_id"], "removed": False,
        "skipped": status == "stopped_early",
    } for row in bundle["exercises"]]
    return operation(
        revision=bundle["workout"]["revision"], status=status,
        finished_at="2026-09-13T12:00:00+00:00",
        stop_reason="time" if status == "stopped_early" else None,
        post_checkin={"overall_difficulty": 5, "back_pain": 3,
                      "leg_symptoms_change": "same", "comment": ""},
        entries=entries, sets=[],
    )


def test_offline_commit_is_atomic_and_idempotent(client, auth, repository):
    workout_id, bundle = start(client, auth)
    body = finish_body(bundle)
    path = f"/api/workouts/{workout_id}/commit-offline"

    first = client.post(path, json=body, headers=auth)
    repeated = client.post(path, json=body, headers=auth)
    assert first.status_code == repeated.status_code == 200
    assert first.get_json() == repeated.get_json()
    assert repository.workouts[workout_id]["status"] == "stopped_early"
    assert len([c for c in repository.checkins.values() if c.get("workout_id") == workout_id and c["kind"] == "post"]) == 1

    changed = {**body, "stop_reason": "pain"}
    conflict = client.post(path, json=changed, headers=auth)
    assert conflict.status_code == 409


def test_invalid_offline_set_leaves_server_workout_unchanged(client, auth, repository):
    workout_id, bundle = start(client, auth)
    body = finish_body(bundle)
    body["sets"] = [{"id": str(uuid4()), "workout_exercise_id": str(uuid4()),
                     "set_number": 1, "actual_reps": 8,
                     "completed_at": "2026-09-13T11:00:00+00:00"}]
    response = client.post(f"/api/workouts/{workout_id}/commit-offline", json=body, headers=auth)
    assert response.status_code in (400, 422)
    assert repository.workouts[workout_id]["status"] == "in_progress"
    assert not repository.sets


def test_offline_commit_preserves_sets_and_creates_one_custom_card(client, auth, repository):
    workout_id, bundle = start(client, auth)
    body = finish_body(bundle)
    custom_id = f"custom-{uuid4()}"
    entry_id, set_id = str(uuid4()), str(uuid4())
    body["entries"].append({
        "id": entry_id, "position": len(body["entries"]) + 1,
        "exercise_id": custom_id,
        "exercise": {"id": custom_id, "name": "Новый подъём", "measurement_type": "reps", "note": ""},
        "removed": False, "skipped": False,
    })
    body["sets"] = [{
        "id": set_id, "workout_exercise_id": entry_id, "set_number": 1,
        "actual_reps": 8, "completed_at": "2026-09-13T11:00:00+00:00",
    }]
    response = client.post(f"/api/workouts/{workout_id}/commit-offline", json=body, headers=auth)
    assert response.status_code == 200
    result = response.get_json()
    assert any(row["id"] == entry_id for row in result["exercises"])
    assert any(row["id"] == set_id for row in result["sets"])
    assert repository.catalog[custom_id]["review_status"] == "needs_review"


def test_invalid_value_rejects_complete_snapshot(client, auth, repository):
    workout_id, bundle = start(client, auth)
    body = finish_body(bundle)
    entry_id = bundle["exercises"][0]["id"]
    body["entries"][0]["skipped"] = False
    body["sets"] = [{
        "id": str(uuid4()), "workout_exercise_id": entry_id, "set_number": 1,
        "actual_reps": 0, "completed_at": "2026-09-13T11:00:00+00:00",
    }]
    response = client.post(f"/api/workouts/{workout_id}/commit-offline", json=body, headers=auth)
    assert response.status_code == 422
    assert repository.workouts[workout_id]["status"] == "in_progress"
    assert not repository.sets

from uuid import uuid4


def checkin(**changes):
    value = {
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
    value.update(changes)
    return value


def operation(**payload):
    return {"idempotency_key": str(uuid4()), **payload}


def prepare(client, auth, operation_id=None, **checkin_changes):
    body = {
        "idempotency_key": operation_id or str(uuid4()),
        "session_key": "full-body-a",
        "scheduled_date": "2026-09-13",
        "checkin": checkin(**checkin_changes),
    }
    return client.post("/api/workouts/prepare", json=body, headers=auth), body


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_personal_routes_require_key_and_disable_cache(client, auth):
    unauthorized = client.get("/api/bootstrap")
    allowed = client.get("/api/bootstrap", headers={**auth, "Origin": "https://gym.example"})

    assert unauthorized.status_code == 401
    assert unauthorized.get_json()["error"]["code"] == "unauthorized"
    assert allowed.status_code == 200
    assert allowed.headers["Cache-Control"] == "no-store"
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://gym.example"
    assert "Access-Control-Allow-Origin" not in client.get(
        "/api/bootstrap", headers={**auth, "Origin": "https://attacker.example"}
    ).headers


def test_prepare_is_idempotent_and_prevents_two_active_workouts(client, auth, repository):
    operation_id = str(uuid4())
    first, body = prepare(client, auth, operation_id)
    repeated = client.post("/api/workouts/prepare", json=body, headers=auth)
    second, _ = prepare(client, auth)

    assert first.status_code == repeated.status_code == 201
    assert first.get_json() == repeated.get_json()
    assert second.status_code == 409
    assert second.get_json()["error"]["code"] == "conflict"
    assert len(repository.workouts) == 1


def test_changed_body_with_same_operation_is_rejected(client, auth):
    operation_id = str(uuid4())
    first, body = prepare(client, auth, operation_id)
    body["checkin"]["back_pain"] = 4
    changed = client.post("/api/workouts/prepare", json=body, headers=auth)

    assert first.status_code == 201
    assert changed.status_code == 409


def test_incomplete_checkin_is_422_and_red_checkin_creates_no_workout(client, auth, repository):
    incomplete = checkin()
    incomplete.pop("readiness")
    invalid = client.post("/api/workouts/prepare", json=operation(checkin=incomplete), headers=auth)
    severe = checkin()
    severe["leg_symptoms"]["saddle_numbness"] = True
    blocked = client.post("/api/workouts/prepare", json=operation(checkin=severe), headers=auth)

    assert invalid.status_code == 422
    assert invalid.get_json()["error"]["code"] == "checkin_incomplete"
    assert blocked.status_code == 200
    assert blocked.get_json()["blocked"] is True
    assert repository.get_active_workout() is None


def test_invalid_date_and_fractional_reps_are_rejected(client, auth):
    invalid_date = client.post(
        "/api/workouts/prepare",
        json=operation(scheduled_date="13-09-2026", checkin=checkin()), headers=auth,
    )
    assert invalid_date.status_code == 400
    prepared, _ = prepare(client, auth)
    workout_id = prepared.get_json()["workout"]["id"]
    started = client.post(
        f"/api/workouts/{workout_id}/start", json=operation(revision=1), headers=auth,
    ).get_json()
    invalid_set = client.post(
        f"/api/workouts/{workout_id}/sets",
        json=operation(
            id=str(uuid4()), workout_exercise_id=started["exercises"][0]["id"],
            set_number=1, actual_reps=4.5,
        ), headers=auth,
    )
    assert invalid_set.status_code == 400


def test_full_workout_lifecycle_and_stale_revision(client, auth, repository):
    prepared, _ = prepare(client, auth)
    bundle = prepared.get_json()
    workout_id = bundle["workout"]["id"]
    initial_revision = bundle["workout"]["revision"]

    started = client.post(
        f"/api/workouts/{workout_id}/start",
        json=operation(revision=initial_revision), headers=auth,
    )
    assert started.status_code == 200
    assert started.get_json()["workout"]["status"] == "in_progress"
    assert started.get_json()["workout"]["revision"] == 2

    stale = client.put(
        f"/api/workouts/{workout_id}/exercises/order",
        json=operation(revision=1, order=[row["id"] for row in bundle["exercises"]]), headers=auth,
    )
    assert stale.status_code == 409
    assert stale.get_json()["error"]["code"] == "revision_conflict"

    current = started.get_json()
    reverse_order = [row["id"] for row in reversed(current["exercises"])]
    reordered = client.put(
        f"/api/workouts/{workout_id}/exercises/order",
        json=operation(revision=2, order=reverse_order), headers=auth,
    )
    assert reordered.status_code == 200
    assert [row["id"] for row in reordered.get_json()["exercises"]] == reverse_order

    bike = next(row for row in reordered.get_json()["exercises"] if row["original_exercise_id"] == "bike-easy")
    replaced = client.post(
        f"/api/workouts/{workout_id}/exercises/{bike['id']}/replace",
        json=operation(revision=3, replacement_id="walk-easy", reason="Нет велотренажёра"), headers=auth,
    )
    assert replaced.status_code == 200
    assert next(row for row in replaced.get_json()["exercises"] if row["id"] == bike["id"])["exercise_id"] == "walk-easy"

    first_exercise = replaced.get_json()["exercises"][0]
    set_operation = str(uuid4())
    set_body = {
        "idempotency_key": set_operation, "id": str(uuid4()),
        "workout_exercise_id": first_exercise["id"], "set_number": 1, "actual_reps": 6,
    }
    saved = client.post(f"/api/workouts/{workout_id}/sets", json=set_body, headers=auth)
    repeated = client.post(f"/api/workouts/{workout_id}/sets", json=set_body, headers=auth)
    assert saved.status_code == repeated.status_code == 201
    assert saved.get_json() == repeated.get_json()

    finished = client.post(
        f"/api/workouts/{workout_id}/finish",
        json=operation(
            revision=4, status="completed", finished_at="2026-09-13T12:00:00+00:00",
            post_checkin={"overall_difficulty": 5, "back_pain": 3, "leg_symptoms_change": "same", "comment": "Нормально"},
        ), headers=auth,
    )
    assert finished.status_code == 200
    assert finished.get_json()["workout"]["status"] == "completed"

    next_day = client.post(
        f"/api/workouts/{workout_id}/next-day-checkin",
        json=operation(
            revision=5,
            checkin={"pain_change": "same", "leg_symptoms_change": "better", "unusual_fatigue": False, "ready_for_similar_load": True},
        ), headers=auth,
    )
    assert next_day.status_code == 201
    assert {row["kind"] for row in repository.get_workout(workout_id)["checkins"]} == {"pre", "post", "next_day"}


def test_cancel_only_preparing_workout(client, auth):
    prepared, _ = prepare(client, auth)
    workout_id = prepared.get_json()["workout"]["id"]
    cancelled = client.post(
        f"/api/workouts/{workout_id}/cancel",
        json=operation(revision=1, reason="Планы изменились"), headers=auth,
    )
    restart = client.post(
        f"/api/workouts/{workout_id}/start",
        json=operation(revision=2), headers=auth,
    )
    assert cancelled.status_code == 200
    assert cancelled.get_json()["workout"]["status"] == "cancelled"
    assert restart.status_code == 409


def test_weight_history_progress_and_exports(client, auth, repository):
    repository.profile["target_weight_kg"] = 85
    create_body = operation(weight_kg=92.4, measured_at="2026-09-01T08:00:00+02:00")
    created = client.post("/api/weight", json=create_body, headers=auth)
    repeated = client.post("/api/weight", json=create_body, headers=auth)
    assert created.status_code == repeated.status_code == 201
    assert created.get_json() == repeated.get_json()

    entry = created.get_json()
    updated = client.put(
        f"/api/weight/{entry['id']}",
        json=operation(revision=1, weight_kg=92.0, measured_at="2026-09-01T08:00:00+02:00"), headers=auth,
    )
    stale = client.put(
        f"/api/weight/{entry['id']}",
        json=operation(revision=1, weight_kg=91.9, measured_at="2026-09-01T08:00:00+02:00"), headers=auth,
    )
    assert updated.status_code == 200
    assert updated.get_json()["revision"] == 2
    assert stale.status_code == 409

    progress = client.get("/api/progress?from=2026-09-01&to=2026-09-30", headers=auth)
    history = client.get("/api/history?from=2026-09-01&to=2026-09-30", headers=auth)
    json_export = client.get("/api/export.json", headers=auth)
    csv_export = client.get("/api/export.csv", headers=auth)

    assert progress.status_code == history.status_code == 200
    assert progress.get_json()["weight"]["current_kg"] == 92.0
    assert progress.get_json()["weight"]["to_target_kg"] == 7.0
    assert history.get_json() == {"workouts": []}
    exported = json_export.get_json()
    assert "gym_operations" not in exported["data"]
    assert "push_subscriptions" not in exported["data"]
    assert "record_type,id,measured_at" in csv_export.get_data(as_text=True)
    assert "weight" in csv_export.get_data(as_text=True)


def test_progress_rejects_invalid_period(client, auth):
    missing = client.get("/api/progress", headers=auth)
    backwards = client.get("/api/progress?from=2026-09-30&to=2026-09-01", headers=auth)
    assert missing.status_code == backwards.status_code == 400

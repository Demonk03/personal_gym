from metrics import build_progress, training_summary, weight_series


def test_weight_series_averages_each_local_day_before_smoothing():
    entries = [
        {"weight_kg": 92, "measured_at": "2026-09-01T20:00:00+00:00"},
        {"weight_kg": 94, "measured_at": "2026-09-01T22:30:00+00:00"},
        {"weight_kg": 91, "measured_at": "2026-09-08T07:00:00+00:00"},
        {"weight_kg": 90, "measured_at": "2026-10-08T07:00:00+00:00"},
    ]

    result = weight_series(entries, "Europe/Belgrade")

    assert result["raw"] == [
        {"date": "2026-09-01", "weight_kg": 92.0},
        {"date": "2026-09-02", "weight_kg": 94.0},
        {"date": "2026-09-08", "weight_kg": 91.0},
        {"date": "2026-10-08", "weight_kg": 90.0},
    ]
    assert result["week_change_kg"] == -1.0
    assert result["month_change_kg"] == -1.0
    assert result["smoothed"][2]["weight_kg"] == 92.5


def test_training_summary_keeps_load_types_and_extra_sessions_separate():
    workouts = [
        {"id": "one", "scheduled_date": "2026-09-01", "status": "completed", "is_extra": False},
        {"id": "two", "scheduled_date": "2026-09-03", "status": "stopped_early", "is_extra": False},
        {"id": "three", "scheduled_date": "2026-09-04", "status": "completed", "is_extra": True},
        {"id": "four", "scheduled_date": "2026-09-05", "status": "cancelled", "is_extra": False},
    ]
    sets = [
        {"load_category": "external_weight", "actual_reps": 10, "actual_weight_kg": 20},
        {"load_category": "bodyweight", "actual_reps": 8},
        {"load_category": "band", "actual_reps": 12},
        {"load_category": "time", "actual_seconds": 600},
    ]

    result = training_summary(workouts, sets, ["2026-09-01", "2026-09-03", "2026-09-05"])

    assert result["adherence_percent"] == 33
    assert result["completed_planned"] == 1
    assert result["extra_completed"] == 1
    assert result["stopped_early"] == 1
    assert result["cancelled"] == 1
    assert result["load"] == {
        "external_weight_kg": 200.0, "bodyweight_reps": 8, "band_reps": 12, "seconds": 600,
    }


def test_empty_progress_has_no_invented_values():
    result = build_progress({}, "Europe/Belgrade", 85)

    assert result["weight"]["current_kg"] is None
    assert result["weight"]["to_target_kg"] is None
    assert result["training"]["adherence_percent"] is None
    assert result["symptoms"] == []

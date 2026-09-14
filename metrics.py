"""Pure progress calculations; no AI or persistence dependencies."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp_requires_timezone")
    return parsed


def _date(value: str | date) -> date:
    return value if isinstance(value, date) else date.fromisoformat(value)


def _timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise ValueError("invalid_timezone") from error


def weight_series(entries: list[dict[str, Any]], timezone_name: str) -> dict[str, Any]:
    timezone = _timezone(timezone_name)
    by_day: dict[date, list[float]] = defaultdict(list)
    for entry in entries:
        day = _datetime(entry["measured_at"]).astimezone(timezone).date()
        by_day[day].append(float(entry["weight_kg"]))
    daily = [
        {"date": day.isoformat(), "weight_kg": round(sum(values) / len(values), 2)}
        for day, values in sorted(by_day.items())
    ]
    smoothed = []
    for point in daily:
        point_day = _date(point["date"])
        values = [item["weight_kg"] for item in daily if point_day - timedelta(days=6) <= _date(item["date"]) <= point_day]
        smoothed.append({"date": point["date"], "weight_kg": round(sum(values) / len(values), 2)})

    def change(days: int):
        if not daily:
            return None
        current_day = _date(daily[-1]["date"])
        candidates = [item for item in daily if _date(item["date"]) <= current_day - timedelta(days=days)]
        return round(daily[-1]["weight_kg"] - candidates[-1]["weight_kg"], 2) if candidates else None

    return {
        "raw": daily,
        "smoothed": smoothed,
        "current_kg": daily[-1]["weight_kg"] if daily else None,
        "week_change_kg": change(7),
        "month_change_kg": change(30),
    }


def training_summary(
    workouts: list[dict[str, Any]],
    sets: list[dict[str, Any]],
    planned_session_dates: list[str],
) -> dict[str, Any]:
    workouts = [w for w in workouts if w.get("checkin_mode") != "red"]
    planned = set(planned_session_dates)
    completed = [row for row in workouts if row.get("status") == "completed"]
    completed_planned = [
        row for row in completed
        if not row.get("is_extra", False) and row.get("scheduled_date") in planned
    ]
    extra = [row for row in completed if row.get("is_extra", False)]
    loads = {"external_weight_kg": 0.0, "bodyweight_reps": 0, "band_reps": 0, "seconds": 0}
    for item in sets:
        category = item.get("load_category")
        reps = int(item.get("actual_reps") or 0)
        if category == "external_weight":
            loads["external_weight_kg"] += reps * float(item.get("actual_weight_kg") or 0)
        elif category == "bodyweight":
            loads["bodyweight_reps"] += reps
        elif category == "band":
            loads["band_reps"] += reps
        if item.get("actual_seconds") is not None:
            loads["seconds"] += int(item["actual_seconds"])
    loads["external_weight_kg"] = round(loads["external_weight_kg"], 2)
    return {
        "planned": len(planned),
        "completed_planned": len(completed_planned),
        "adherence_percent": round(100 * len(completed_planned) / len(planned)) if planned else None,
        "completed_total": len(completed),
        "stopped_early": sum(row.get("status") == "stopped_early" for row in workouts),
        "cancelled": sum(row.get("status") == "cancelled" for row in workouts),
        "extra_completed": len(extra),
        "load": loads,
    }


def symptom_series(checkins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in sorted(checkins, key=lambda item: item.get("created_at", "")):
        payload = row.get("payload") or {}
        result.append({
            "workout_id": row.get("workout_id"), "kind": row.get("kind"),
            "created_at": row.get("created_at"), "back_pain": payload.get("back_pain"),
            "pain_change": payload.get("pain_change"),
            "leg_symptoms_change": payload.get("leg_symptoms_change") or (payload.get("leg_symptoms") or {}).get("trend"),
        })
    return result


def build_progress(data: dict[str, Any], timezone_name: str, target_weight_kg: float | None = None) -> dict[str, Any]:
    weight = weight_series(data.get("weight_entries", []), timezone_name)
    weight["target_kg"] = target_weight_kg
    weight["to_target_kg"] = (
        round(weight["current_kg"] - float(target_weight_kg), 2)
        if weight["current_kg"] is not None and target_weight_kg is not None else None
    )
    return {
        "weight": weight,
        "training": training_summary(data.get("workouts", []), data.get("sets", []), data.get("planned_session_dates", [])),
        "symptoms": symptom_series(data.get("checkins", [])),
    }

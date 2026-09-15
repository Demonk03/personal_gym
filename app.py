import hmac
import csv
import io
import os
import re
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

import db
import gpt
import operations
from metrics import build_progress
from training import build_workout, evaluate_checkin


EXERCISE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
MEASUREMENT_TYPES = {"reps", "seconds", "weighted_reps", "reps_seconds"}
REVIEW_STATUSES = {"allowed", "conditional", "needs_review", "blocked"}


class APIError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _json() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise APIError("Ожидается JSON-объект")
    return payload


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise APIError(f"Поле {field} должно быть UUID") from None


def _operation(payload: dict[str, Any]) -> str:
    return _uuid(payload.get("idempotency_key"), "idempotency_key")


def _exercise_id(value: Any, field="exercise_id") -> str:
    if not isinstance(value, str) or not EXERCISE_ID_RE.fullmatch(value):
        raise APIError(f"Поле {field} должно быть корректным ID упражнения")
    return value


def _integer(payload: dict[str, Any], field: str, minimum: int, maximum: int) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise APIError(f"Поле {field} должно быть числом от {minimum} до {maximum}")
    return value


def _optional_integer(payload: dict[str, Any], field: str, minimum: int, maximum: int):
    if payload.get(field) is None:
        return None
    return _integer(payload, field, minimum, maximum)


def _number(payload: dict[str, Any], field: str, minimum: float, maximum: float, required=False):
    value = payload.get(field)
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= value <= maximum:
        raise APIError(f"Поле {field} должно быть числом от {minimum} до {maximum}")
    return value


def _text(payload: dict[str, Any], field: str, required=False, max_length=500):
    value = payload.get(field, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise APIError(f"Поле {field} должно быть строкой")
    value = value.strip()
    if required and not value:
        raise APIError(f"Поле {field} обязательно")
    if len(value) > max_length:
        raise APIError(f"Поле {field} слишком длинное")
    return value


def _date(payload: dict[str, Any], field: str):
    value = _text(payload, field, max_length=10)
    if not value:
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise APIError(f"Поле {field} должно быть датой YYYY-MM-DD") from None


def _timestamp(payload: dict[str, Any], field: str) -> str:
    value = _text(payload, field, required=True, max_length=50)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise APIError(f"Поле {field} должно быть временем ISO 8601") from None
    if parsed.tzinfo is None:
        raise APIError(f"Поле {field} должно содержать часовой пояс")
    return parsed.isoformat()


def _post_checkin(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise APIError("Поле post_checkin должно быть объектом")
    result = {
        "overall_difficulty": _integer(payload, "overall_difficulty", 1, 10),
        "back_pain": _integer(payload, "back_pain", 0, 10),
        "leg_symptoms_change": _text(payload, "leg_symptoms_change", required=True, max_length=20),
        "comment": _text(payload, "comment", max_length=1000),
    }
    if result["leg_symptoms_change"] not in {"better", "same", "worse"}:
        raise APIError("Недопустимое значение поля leg_symptoms_change")
    return result


def _next_day_checkin(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise APIError("Поле checkin должно быть объектом")
    pain_change = _text(payload, "pain_change", required=True, max_length=20)
    leg_change = _text(payload, "leg_symptoms_change", required=True, max_length=20)
    if pain_change not in {"better", "same", "worse"} or leg_change not in {"better", "same", "worse"}:
        raise APIError("Некорректное изменение симптомов")
    unusual_fatigue = payload.get("unusual_fatigue")
    ready_similar = payload.get("ready_for_similar_load")
    if not isinstance(unusual_fatigue, bool) or not isinstance(ready_similar, bool):
        raise APIError("Поля усталости и готовности должны быть true или false")
    return {
        "pain_change": pain_change, "leg_symptoms_change": leg_change,
        "unusual_fatigue": unusual_fatigue, "ready_for_similar_load": ready_similar,
    }


def _allowed_origins() -> set[str]:
    configured = os.getenv("DASHBOARD_ORIGIN", "http://localhost:8000")
    return {value.strip().rstrip("/") for value in configured.split(",") if value.strip()}


def create_app(repository=None, weekly_review_service=None) -> Flask:
    app = Flask(__name__)
    active_repository = repository
    review_service = weekly_review_service

    def repo():
        nonlocal active_repository
        if active_repository is None:
            active_repository = db.SupabaseRepository()
        return active_repository

    def reviews():
        nonlocal review_service
        if review_service is None:
            review_service = gpt.WeeklyReviewService()
        return review_service

    def require_api_key(function):
        @wraps(function)
        def wrapper(*args, **kwargs):
            expected = os.getenv("API_KEY", "")
            header = request.headers.get("Authorization", "")
            provided = header[7:].strip() if header.startswith("Bearer ") else ""
            if not expected or not hmac.compare_digest(provided, expected):
                raise APIError("Неверный API-ключ", 401, "unauthorized")
            return function(*args, **kwargs)
        return wrapper

    @app.after_request
    def response_headers(response):
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") in _allowed_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(APIError)
    def api_error(error):
        return jsonify({"error": {"code": error.code, "message": error.message}}), error.status

    @app.errorhandler(db.NotFound)
    def not_found(error):
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 404

    @app.errorhandler(db.RevisionConflict)
    def revision_conflict(error):
        return jsonify({"error": {"code": error.code, "message": str(error)}}), 409

    def conflict(error):
        code = "operation_pending" if isinstance(error, operations.OperationPending) else getattr(error, "code", "operation_conflict")
        return jsonify({"error": {"code": code, "message": str(error) or code}}), 409

    for conflict_type in (db.Conflict, operations.OperationConflict, operations.OperationPending):
        app.register_error_handler(conflict_type, conflict)

    @app.errorhandler(Exception)
    def unexpected(error):
        if isinstance(error, HTTPException):
            return jsonify({"error": {"code": "http_error", "message": error.description}}), error.code
        app.logger.exception("Unhandled API error")
        return jsonify({"error": {"code": "internal_error", "message": "Временная ошибка сервиса"}}), 500

    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/bootstrap")
    @require_api_key
    def bootstrap():
        return jsonify(repo().bootstrap())

    @app.get("/api/exercises")
    @require_api_key
    def exercise_catalog():
        query = request.args.get("q", "").strip()
        if len(query) > 160:
            raise APIError("Параметр q слишком длинный")
        return jsonify({"exercises": repo().list_exercises(query)})

    @app.put("/api/exercises/<exercise_id>")
    @require_api_key
    def update_exercise(exercise_id):
        payload = _json()
        allowed = {"name", "measurement_type", "review_status", "note", "active", "revision"}
        if set(payload) - allowed:
            raise APIError("Переданы неизвестные поля")
        changes = {}
        if "name" in payload:
            changes["name"] = _text(payload, "name", required=True, max_length=160)
        if "note" in payload:
            changes["note"] = _text(payload, "note", max_length=2000)
        if "measurement_type" in payload:
            value = _text(payload, "measurement_type", required=True, max_length=30)
            if value not in MEASUREMENT_TYPES:
                raise APIError("Некорректный формат измерения")
            changes["measurement_type"] = value
        if "review_status" in payload:
            value = _text(payload, "review_status", required=True, max_length=30)
            if value not in REVIEW_STATUSES:
                raise APIError("Некорректный статус упражнения")
            changes["review_status"] = value
        if "active" in payload:
            if not isinstance(payload["active"], bool):
                raise APIError("Поле active должно быть true или false")
            changes["active"] = payload["active"]
        if not changes:
            raise APIError("Нет изменений упражнения")
        return jsonify(repo().update_exercise(
            _exercise_id(exercise_id), _integer(payload, "revision", 1, 1_000_000), changes,
        ))

    @app.get("/api/workouts/active")
    @require_api_key
    def active_workout():
        return jsonify({"workout": repo().get_active_workout()})

    @app.get("/api/workouts/<workout_id>")
    @require_api_key
    def get_workout(workout_id):
        return jsonify(repo().get_workout(_uuid(workout_id, "workout_id")))

    @app.get("/api/operations/<operation_id>")
    @require_api_key
    def operation_status(operation_id):
        return jsonify(repo().operation_status(_uuid(operation_id, "operation_id")))

    @app.post("/api/workouts/prepare")
    @require_api_key
    def prepare_workout():
        payload = _json()
        operation_id = _operation(payload)
        checkin = payload.get("checkin")
        if not isinstance(checkin, dict):
            raise APIError("Поле checkin должно быть объектом")
        session_key = _text(payload, "session_key", required=False, max_length=80) or None
        program = repo().get_program(session_key)
        evaluation = evaluate_checkin(checkin, program["rules"])
        if not evaluation["complete"]:
            raise APIError("Заполни обязательные поля check-in", 422, "checkin_incomplete")
        request_hash = operations.body_hash(payload)
        if evaluation["blocks_workout"]:
            result = repo().save_blocked_checkin(operation_id, request_hash, checkin, evaluation)
            return jsonify(result)
        if not isinstance(payload.get("is_extra", False), bool):
            raise APIError("is_extra должно быть true или false")
        plan = build_workout(program, evaluation, checkin["equipment"])
        workout_id = str(uuid5(NAMESPACE_URL, f"personal-gym:{operation_id}:workout"))
        exercises = []
        for position, item in enumerate(plan["exercises"], 1):
            exercises.append({**item, "id": str(uuid5(NAMESPACE_URL, f"personal-gym:{operation_id}:exercise:{position}"))})
        workout = {
            "id": workout_id, "program_version_id": plan["program_version_id"],
            "program_session_id": plan["program_session_id"],
            "scheduled_date": _date(payload, "scheduled_date") or datetime.now(ZoneInfo((repo().bootstrap().get("profile") or {}).get("timezone", "Europe/Belgrade"))).date().isoformat(),
            "is_extra": payload.get("is_extra", False), "omitted": plan["omitted"],
            "status": "preparing", "checkin_mode": evaluation["mode"],
            "checkin_reasons": evaluation["reasons"], "demo_only": plan["demo_only"],
            "rule_version": plan["rule_version"], "profile_snapshot": repo().bootstrap().get("profile") or {},
            "program_snapshot": {**plan["source_snapshot"], "omitted": plan["omitted"]}, "checkin_payload": checkin,
            "checkin_evaluation": evaluation, "revision": 1,
            "created_at": datetime.now(timezone.utc).isoformat(), "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return jsonify(repo().prepare_workout(operation_id, request_hash, workout, exercises)), 201

    def mutation_payload():
        payload = _json()
        return payload, _operation(payload), operations.body_hash(payload)

    @app.post("/api/workouts/<workout_id>/start")
    @require_api_key
    def start_workout(workout_id):
        payload, operation_id, digest = mutation_payload()
        result = repo().mutate_workout("start", operation_id, digest,
            p_workout_id=_uuid(workout_id, "workout_id"), p_revision=_integer(payload, "revision", 1, 1_000_000))
        return jsonify(result)

    @app.put("/api/workouts/<workout_id>/exercises/order")
    @require_api_key
    def reorder_workout(workout_id):
        payload, operation_id, digest = mutation_payload()
        order = payload.get("order")
        if not isinstance(order, list) or not order:
            raise APIError("Поле order должно быть непустым списком")
        clean_order = [_uuid(value, "order") for value in order]
        result = repo().mutate_workout("reorder", operation_id, digest,
            p_workout_id=_uuid(workout_id, "workout_id"), p_revision=_integer(payload, "revision", 1, 1_000_000), p_order=clean_order)
        return jsonify(result)

    @app.post("/api/workouts/<workout_id>/exercises/<entry_id>/replace")
    @require_api_key
    def replace_exercise(workout_id, entry_id):
        payload, operation_id, digest = mutation_payload()
        result = repo().mutate_workout("replace", operation_id, digest,
            p_workout_id=_uuid(workout_id, "workout_id"), p_revision=_integer(payload, "revision", 1, 1_000_000),
            p_entry_id=_uuid(entry_id, "entry_id"), p_replacement_id=_text(payload, "replacement_id", required=True, max_length=64),
            p_reason=_text(payload, "reason", max_length=300))
        return jsonify(result)

    @app.post("/api/workouts/<workout_id>/exercises")
    @require_api_key
    def add_workout_exercise(workout_id):
        payload, operation_id, digest = mutation_payload()
        raw = payload.get("exercise")
        if not isinstance(raw, dict):
            raise APIError("Поле exercise должно быть объектом")
        exercise_id = _exercise_id(raw.get("id"))
        exercise = {"id": exercise_id}
        if exercise_id.startswith("custom-"):
            _uuid(exercise_id.removeprefix("custom-"), "exercise.id")
            exercise["name"] = _text(raw, "name", required=True, max_length=160)
            measurement = _text(raw, "measurement_type", required=True, max_length=30)
            if measurement not in MEASUREMENT_TYPES:
                raise APIError("Некорректный формат измерения")
            exercise["measurement_type"] = measurement
            exercise["note"] = _text(raw, "note", max_length=2000)
        elif set(raw) != {"id"}:
            raise APIError("Для существующего упражнения передай только id")
        result = repo().add_workout_exercise(
            operation_id, digest, _uuid(workout_id, "workout_id"),
            _integer(payload, "revision", 1, 1_000_000),
            _uuid(payload.get("workout_entry_id"), "workout_entry_id"), exercise,
        )
        return jsonify(result), 201

    @app.post("/api/workouts/<workout_id>/sets")
    @require_api_key
    def save_set(workout_id):
        payload, operation_id, digest = mutation_payload()
        set_data = {
            "id": _uuid(payload.get("id"), "id"), "workout_id": _uuid(workout_id, "workout_id"),
            "workout_exercise_id": _uuid(payload.get("workout_exercise_id"), "workout_exercise_id"),
            "set_number": _integer(payload, "set_number", 1, 50),
            "completed_at": _timestamp(payload,"completed_at") if payload.get("completed_at") else datetime.now(timezone.utc).isoformat(),
            "actual_reps": _optional_integer(payload, "actual_reps", 1, 1000),
            "actual_seconds": _optional_integer(payload, "actual_seconds", 1, 7200),
            "actual_weight_kg": _number(payload, "actual_weight_kg", 0, 400),
            "difficulty": _optional_integer(payload, "difficulty", 1, 10),
            "effect": _text(payload, "effect", max_length=20) or None,
        }
        bundle = repo().get_workout(set_data["workout_id"])
        entry = next((row for row in bundle["exercises"] if row["id"] == set_data["workout_exercise_id"]), None)
        if not entry:
            raise db.NotFound("workout_exercise_not_found")
        try:
            db.validate_set_fact((entry.get("definition_snapshot") or {}).get("measurement_type"), set_data)
        except db.Conflict:
            raise APIError("Факт не соответствует формату упражнения", 422, "measurement_mismatch") from None
        if set_data["effect"] not in {None, "better", "same", "worse"}:
            raise APIError("Некорректное значение effect")
        return jsonify(repo().save_set(operation_id, digest, set_data)), 201

    @app.put("/api/workouts/<workout_id>/sets")
    @require_api_key
    def update_set(workout_id):
        payload, operation_id, digest = mutation_payload()
        clean_workout_id = _uuid(workout_id, "workout_id")
        clean_set_id = _uuid(payload.get("id"), "id")
        set_data = {
            key: value for key, value in {
                "actual_reps": _optional_integer(payload, "actual_reps", 1, 1000),
                "actual_seconds": _optional_integer(payload, "actual_seconds", 1, 7200),
                "actual_weight_kg": _number(payload, "actual_weight_kg", 0, 400),
                "difficulty": _optional_integer(payload, "difficulty", 1, 10),
                "effect": _text(payload, "effect", max_length=20) or None,
            }.items() if value is not None
        }
        if not set_data:
            raise APIError("Нет изменений подхода")
        bundle = repo().get_workout(clean_workout_id)
        current_set = next((row for row in bundle["sets"] if row["id"] == clean_set_id), None)
        if not current_set:
            raise db.NotFound("set_not_found")
        entry = next((row for row in bundle["exercises"] if row["id"] == current_set["workout_exercise_id"]), None)
        try:
            db.validate_set_fact(
                (entry.get("definition_snapshot") or {}).get("measurement_type") if entry else "",
                {**current_set, **set_data},
            )
        except db.Conflict:
            raise APIError("Факт не соответствует формату упражнения", 422, "measurement_mismatch") from None
        result = repo().mutate_workout("update_set", operation_id, digest,
            p_workout_id=clean_workout_id, p_revision=None,
            p_set_id=clean_set_id, p_set_revision=_integer(payload, "revision", 1, 1_000_000), p_set_data=set_data)
        return jsonify(result)

    @app.post("/api/workouts/<workout_id>/finish")
    @require_api_key
    def finish_workout(workout_id):
        payload, operation_id, digest = mutation_payload()
        status = _text(payload, "status", required=True, max_length=30)
        if status not in {"completed", "stopped_early"}:
            raise APIError("Некорректный статус завершения")
        stop_reason = _text(payload, "stop_reason", max_length=500) or None
        if status == "stopped_early" and not stop_reason:
            raise APIError("Укажи причину досрочного завершения")
        result = repo().finish_workout(
            operation_id, digest, _uuid(workout_id, "workout_id"),
            _integer(payload, "revision", 1, 1_000_000), status,
            _timestamp(payload, "finished_at") if payload.get("finished_at") else datetime.now(timezone.utc).isoformat(),
            stop_reason, _post_checkin(payload.get("post_checkin")),
        )
        return jsonify(result)

    @app.post("/api/workouts/<workout_id>/cancel")
    @require_api_key
    def cancel_workout(workout_id):
        payload, operation_id, digest = mutation_payload()
        result = repo().mutate_workout("cancel", operation_id, digest,
            p_workout_id=_uuid(workout_id, "workout_id"), p_revision=_integer(payload, "revision", 1, 1_000_000),
            p_reason=_text(payload, "reason", max_length=500))
        return jsonify(result)

    @app.post("/api/workouts/<workout_id>/next-day-checkin")
    @require_api_key
    def next_day(workout_id):
        payload, operation_id, digest = mutation_payload()
        result = repo().mutate_workout("next_day_checkin", operation_id, digest,
            p_workout_id=_uuid(workout_id, "workout_id"), p_revision=_integer(payload, "revision", 1, 1_000_000),
            p_payload=_next_day_checkin(payload.get("checkin")))
        return jsonify(result), 201

    @app.get("/api/history")
    @require_api_key
    def history():
        date_from = request.args.get("from")
        date_to = request.args.get("to")
        for name, value in (("from", date_from), ("to", date_to)):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    raise APIError(f"Параметр {name} должен быть датой YYYY-MM-DD") from None
        if date_from and date_to and date_from > date_to:
            raise APIError("Начало периода должно быть раньше конца")
        return jsonify({"workouts": repo().list_history(date_from, date_to)})

    @app.get("/api/history/<workout_id>")
    @require_api_key
    def history_item(workout_id):
        return jsonify(repo().get_workout(_uuid(workout_id, "workout_id")))

    @app.get("/api/progress")
    @require_api_key
    def progress():
        date_from = request.args.get("from")
        date_to = request.args.get("to")
        if not date_from or not date_to:
            raise APIError("Укажи параметры from и to")
        try:
            date.fromisoformat(date_from)
            date.fromisoformat(date_to)
        except ValueError:
            raise APIError("Период должен использовать даты YYYY-MM-DD") from None
        if date_from > date_to:
            raise APIError("Начало периода должно быть раньше конца")
        profile = repo().bootstrap().get("profile") or {}
        result = build_progress(
            repo().progress_data(date_from, date_to),
            profile.get("timezone", "Europe/Belgrade"), profile.get("target_weight_kg"),
        )
        return jsonify(result)

    @app.post("/api/weight")
    @require_api_key
    def create_weight():
        payload, operation_id, digest = mutation_payload()
        entry = {
            "id": str(uuid5(NAMESPACE_URL, f"personal-gym:{operation_id}:weight")),
            "weight_kg": _number(payload, "weight_kg", 25, 400, required=True),
            "measured_at": _timestamp(payload, "measured_at"),
        }
        return jsonify(repo().create_weight(operation_id, digest, entry)), 201

    @app.put("/api/weight/<entry_id>")
    @require_api_key
    def update_weight(entry_id):
        payload, operation_id, digest = mutation_payload()
        result = repo().update_weight(
            operation_id, digest, _uuid(entry_id, "entry_id"),
            _integer(payload, "revision", 1, 1_000_000),
            _number(payload, "weight_kg", 25, 400, required=True),
            _timestamp(payload, "measured_at"),
        )
        return jsonify(result)

    @app.get("/api/export.json")
    @require_api_key
    def export_json():
        return jsonify({"version": 1, "exported_at": datetime.now(timezone.utc).isoformat(), "data": repo().export_data()})

    @app.get("/api/export.csv")
    @require_api_key
    def export_csv():
        data = repo().export_data()
        buffer = io.StringIO()
        fields = [
            "record_type", "id", "measured_at", "weight_kg", "workout_id",
            "workout_exercise_id", "set_number", "actual_reps", "actual_seconds", "actual_weight_kg",
            "waist_cm", "chest_cm", "hips_cm", "thigh_cm",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for item in data.get("weight_entries", []):
            writer.writerow({
                "record_type": "weight", "id": item.get("id"),
                "measured_at": item.get("measured_at"), "weight_kg": item.get("weight_kg"),
            })
        for item in data.get("body_measurements", []):
            writer.writerow({key: value for key, value in {"record_type": "measurement", **item}.items() if key in fields})
        for item in data.get("workout_sets", []):
            writer.writerow({key: value for key, value in {"record_type": "set", **item}.items() if key in fields})
        return Response(
            buffer.getvalue(), content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=personal-gym-export.csv"},
        )

    def requested_week_start(value=None):
        if value:
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                raise APIError("week_start должен быть датой YYYY-MM-DD") from None
            if parsed.isoweekday() != 1:
                raise APIError("week_start должен быть понедельником")
            return parsed.isoformat()
        profile = repo().bootstrap().get("profile") or {}
        today = datetime.now(timezone.utc).astimezone(ZoneInfo(profile.get("timezone", "Europe/Belgrade"))).date()
        return (today - timedelta(days=today.isoweekday() - 1)).isoformat()

    @app.get("/api/weekly-reviews/current")
    @require_api_key
    def current_weekly_review():
        week_start = requested_week_start(request.args.get("week_start"))
        source = repo().weekly_source(week_start)
        review = repo().get_current_weekly_review(week_start)
        if review and review.get("source_hash") != gpt.source_hash(source) and review.get("status") == "ready":
            review = {**review, "status": "stale"}
        profile = repo().bootstrap().get("profile") or {}
        end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
        facts = build_progress(repo().progress_data(week_start, end), profile.get("timezone", "Europe/Belgrade"), profile.get("target_weight_kg"))
        completed = {w["id"] for w in source.get("workouts", []) if w["status"] in {"completed", "stopped_early"}}
        answered = {c.get("workout_id") for c in source.get("checkins", []) if c["kind"] == "next_day"}
        return jsonify({"week_start": week_start, "review": review, "facts": facts,
            "coverage": {"workouts": len(completed), "next_day_missing": len(completed - answered)}, "no_data": not completed})

    @app.post("/api/weekly-reviews/generate")
    @require_api_key
    def generate_weekly_review():
        payload = _json()
        operation_id = _operation(payload)
        week_start = requested_week_start(_text(payload, "week_start", required=True, max_length=10))
        source = repo().weekly_source(week_start)
        source_digest = gpt.source_hash(source)
        existing = repo().get_current_weekly_review(week_start)
        if existing and existing.get("source_hash") == source_digest and existing.get("status") == "ready":
            return jsonify(existing)
        request_digest = operations.body_hash(payload)
        review_id = str(uuid5(NAMESPACE_URL, f"personal-gym:weekly:{week_start}:{source_digest}"))
        claim = repo().claim_operation(operation_id, "weekly_review", review_id, request_digest)
        if claim["status"] == "conflict":
            raise operations.OperationConflict
        if claim["status"] == "pending":
            raise operations.OperationPending
        if claim["status"] == "succeeded":
            return jsonify(claim["result"])
        token = claim["token"]
        base_record = {
            "id": review_id, "week_start": week_start, "source_hash": source_digest,
            "source_workout_ids": [row["id"] for row in source.get("workouts", [])],
            "prompt_version": gpt.PROMPT_VERSION, "model": reviews().model,
        }
        try:
            result = reviews().generate(source, repo().approved_exercise_ids())
        except gpt.ReviewValidationError as error:
            repo().fail_weekly_review(operation_id, token, base_record, {"code": "invalid_ai_response", "message": str(error)})
            raise APIError("AI вернул некорректный разбор", 502, "invalid_ai_response") from error
        except Exception as error:
            repo().fail_weekly_review(operation_id, token, base_record, {"code": "ai_unavailable", "message": str(error)})
            raise APIError("AI временно недоступен", 503, "ai_unavailable") from error
        saved = repo().commit_weekly_review(operation_id, token, {**base_record, "result": result})
        return jsonify(saved), 201

    from integration import register_integration
    register_integration(app, repo, require_api_key)
    from notifications import register_notifications
    register_notifications(app, repo, require_api_key)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8001")))

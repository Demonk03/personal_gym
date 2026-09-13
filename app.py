import hmac
import csv
import io
import os
from datetime import date, datetime, timezone
from functools import wraps
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

import db
import operations
from metrics import build_progress
from training import build_workout, evaluate_checkin


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

    def repo():
        nonlocal active_repository
        if active_repository is None:
            active_repository = db.SupabaseRepository()
        return active_repository

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
        plan = build_workout(program, evaluation, checkin["equipment"])
        workout_id = str(uuid5(NAMESPACE_URL, f"personal-gym:{operation_id}:workout"))
        exercises = []
        for position, item in enumerate(plan["exercises"], 1):
            exercises.append({**item, "id": str(uuid5(NAMESPACE_URL, f"personal-gym:{operation_id}:exercise:{position}"))})
        workout = {
            "id": workout_id, "program_version_id": plan["program_version_id"],
            "program_session_id": plan["program_session_id"],
            "scheduled_date": _date(payload, "scheduled_date"),
            "status": "preparing", "checkin_mode": evaluation["mode"],
            "checkin_reasons": evaluation["reasons"], "demo_only": plan["demo_only"],
            "rule_version": plan["rule_version"], "profile_snapshot": repo().bootstrap().get("profile") or {},
            "program_snapshot": plan["source_snapshot"], "checkin_payload": checkin,
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

    @app.post("/api/workouts/<workout_id>/sets")
    @require_api_key
    def save_set(workout_id):
        payload, operation_id, digest = mutation_payload()
        set_data = {
            "id": _uuid(payload.get("id"), "id"), "workout_id": _uuid(workout_id, "workout_id"),
            "workout_exercise_id": _uuid(payload.get("workout_exercise_id"), "workout_exercise_id"),
            "set_number": _integer(payload, "set_number", 1, 50),
            "actual_reps": _optional_integer(payload, "actual_reps", 0, 1000),
            "actual_seconds": _optional_integer(payload, "actual_seconds", 0, 7200),
            "actual_weight_kg": _number(payload, "actual_weight_kg", 0, 400),
            "difficulty": _optional_integer(payload, "difficulty", 1, 10),
            "effect": _text(payload, "effect", max_length=20) or None,
        }
        if set_data["actual_reps"] is None and set_data["actual_seconds"] is None:
            raise APIError("Укажи повторы или секунды")
        if set_data["effect"] not in {None, "better", "same", "worse"}:
            raise APIError("Некорректное значение effect")
        return jsonify(repo().save_set(operation_id, digest, set_data)), 201

    @app.put("/api/workouts/<workout_id>/sets")
    @require_api_key
    def update_set(workout_id):
        payload, operation_id, digest = mutation_payload()
        set_data = {
            key: value for key, value in {
                "actual_reps": _optional_integer(payload, "actual_reps", 0, 1000),
                "actual_seconds": _optional_integer(payload, "actual_seconds", 0, 7200),
                "actual_weight_kg": _number(payload, "actual_weight_kg", 0, 400),
                "difficulty": _optional_integer(payload, "difficulty", 1, 10),
                "effect": _text(payload, "effect", max_length=20) or None,
            }.items() if value is not None
        }
        if not set_data:
            raise APIError("Нет изменений подхода")
        result = repo().mutate_workout("update_set", operation_id, digest,
            p_workout_id=_uuid(workout_id, "workout_id"), p_revision=None,
            p_set_id=_uuid(payload.get("id"), "id"), p_set_revision=_integer(payload, "revision", 1, 1_000_000), p_set_data=set_data)
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
            _text(payload, "finished_at", max_length=50) or datetime.now(timezone.utc).isoformat(),
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
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for item in data.get("weight_entries", []):
            writer.writerow({
                "record_type": "weight", "id": item.get("id"),
                "measured_at": item.get("measured_at"), "weight_kg": item.get("weight_kg"),
            })
        for item in data.get("workout_sets", []):
            writer.writerow({key: value for key, value in {"record_type": "set", **item}.items() if key in fields})
        return Response(
            buffer.getvalue(), content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=personal-gym-export.csv"},
        )

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8001")))

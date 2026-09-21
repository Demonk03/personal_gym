"""Persistence boundary for Personal Gym."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from operations import execute_operation


MEASUREMENT_TYPES = {"reps", "seconds", "weighted_reps", "reps_seconds"}
REVIEW_STATUSES = {"allowed", "conditional", "needs_review", "blocked"}


def validate_set_fact(measurement_type: str, values: dict[str, Any]) -> None:
    """Validate facts against the immutable definition selected for this workout."""
    reps, seconds, weight = (values.get("actual_reps"), values.get("actual_seconds"), values.get("actual_weight_kg"))
    valid = {
        "reps": reps is not None and reps > 0 and seconds is None and weight is None,
        "seconds": reps is None and seconds is not None and seconds > 0 and weight is None,
        "weighted_reps": reps is not None and reps > 0 and seconds is None and weight is not None and weight >= 0,
        "reps_seconds": reps is not None and reps > 0 and seconds is not None and seconds > 0 and weight is None,
    }
    if measurement_type not in MEASUREMENT_TYPES or not valid.get(measurement_type, False):
        raise Conflict("measurement_mismatch")


class RepositoryError(Exception):
    code = "repository_error"


class NotFound(RepositoryError):
    code = "not_found"


class Conflict(RepositoryError):
    code = "conflict"


class RevisionConflict(Conflict):
    code = "revision_conflict"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_client():
    """Create Supabase lazily so domain tests need no credentials or SDK."""
    try:
        import httpx
        from supabase import ClientOptions, create_client
    except ImportError as error:
        raise RuntimeError("Install requirements.txt to use Supabase") from error
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_KEY are required")
    # PostgREST enables HTTP/2 by default. Some managed network paths send a
    # GOAWAY between sequential requests, so use stable HTTP/1.1 for this API.
    http_client = httpx.Client(http2=False, timeout=30.0, follow_redirects=True)
    return create_client(url, key, options=ClientOptions(httpx_client=http_client))


class SupabaseRepository:
    """Thin server-only adapter. Browser clients never receive this key."""

    def __init__(self, client=None):
        self.client = client or get_client()

    def bootstrap(self) -> dict[str, Any]:
        profile = self.client.table("player_profile").select("*").eq("id", True).limit(1).execute().data
        try:
            program = self.get_program()
        except NotFound:
            return {"contract_version": 2, "profile": profile[0] if profile else None, "program": None,
                    "sessions": [], "programs": self.list_programs(), "day_choices": self.list_day_choices()}
        sessions = self.client.table("program_sessions").select("session_key").eq("program_version_id", program["id"]).order("position").execute().data
        return {"contract_version": 2, "profile": profile[0] if profile else None, "program": program,
                "sessions": [self.get_program(row["session_key"]) for row in sessions],
                "programs": self.list_programs(), "day_choices": self.list_day_choices()}

    def list_programs(self):
        versions = self.client.table("program_versions").select("*").eq("published", True).order("version").execute().data
        result = []
        for version in versions:
            sessions = self.client.table("program_sessions").select("*").eq("program_version_id", version["id"]).order("position").execute().data
            result.append({**version, "sessions": [self.get_program_by_session_id(row["id"]) for row in sessions]})
        return result

    def list_day_choices(self):
        return self.client.table("gym_day_choices").select("*").order("scheduled_date").execute().data

    def select_program(self, program_version_id):
        version = self.client.table("program_versions").select("id").eq("id", program_version_id).eq("published", True).limit(1).execute().data
        if not version:
            raise NotFound("program_not_found")
        row = self.client.table("gym_program_selection").upsert({"id": True, "program_version_id": program_version_id, "updated_at": utc_now()}).execute().data
        if not row:
            raise NotFound("program_selection_not_found")
        return row[0]

    def set_session_weekday(self, session_id, weekday):
        self.get_program_by_session_id(session_id)
        self.client.table("gym_session_weekdays").upsert({"session_id": session_id, "weekday": weekday}).execute()
        return {"session_id": session_id, "weekday": weekday}

    def set_day_choice(self, scheduled_date, choice, session_id=None, assigned_session_id=None):
        if self.client.table("workouts").select("id").eq("scheduled_date", scheduled_date).neq("status", "cancelled").limit(1).execute().data:
            raise Conflict("workout_already_exists")
        row = {"scheduled_date": scheduled_date, "choice": choice, "session_id": session_id,
               "assigned_session_id": assigned_session_id, "updated_at": utc_now()}
        return self.client.table("gym_day_choices").upsert(row).execute().data[0]

    def clear_day_choice(self, scheduled_date):
        self.client.table("gym_day_choices").delete().eq("scheduled_date", scheduled_date).execute()
        return {"scheduled_date": scheduled_date, "restored": True}

    def resolve_session(self, scheduled_date):
        choice = self.client.table("gym_day_choices").select("*").eq("scheduled_date", scheduled_date).limit(1).execute().data
        if choice:
            if choice[0]["choice"] == "skipped":
                raise Conflict("scheduled_day_skipped")
            return {"program": self.get_program_by_session_id(choice[0]["session_id"]),
                    "assigned_session_id": choice[0].get("assigned_session_id") or choice[0]["session_id"]}
        selection = self.client.table("gym_program_selection").select("program_version_id").eq("id", True).limit(1).execute().data
        if not selection:
            raise NotFound("program_selection_not_found")
        sessions = self.client.table("program_sessions").select("*").eq("program_version_id", selection[0]["program_version_id"]).order("position").execute().data
        weekday = date.fromisoformat(scheduled_date).isoweekday()
        for session in sessions:
            override = self.client.table("gym_session_weekdays").select("weekday").eq("session_id", session["id"]).limit(1).execute().data
            if (override[0]["weekday"] if override else session.get("weekday")) == weekday:
                return {"program": self.get_program_by_session_id(session["id"]), "assigned_session_id": session["id"]}
        raise NotFound("scheduled_session_not_found")

    def list_exercises(self, query=""):
        request = self.client.table("exercise_library").select("*").eq("active", True).order("name")
        if query:
            request = request.ilike("name", f"%{query}%")
        return request.limit(200).execute().data

    def update_exercise(self, exercise_id, revision, changes):
        payload = {**changes, "revision": revision + 1, "updated_at": utc_now()}
        rows = self.client.table("exercise_library").update(payload).eq("id", exercise_id).eq("revision", revision).execute().data
        if rows:
            return rows[0]
        if not self.client.table("exercise_library").select("id").eq("id", exercise_id).limit(1).execute().data:
            raise NotFound("exercise_not_found")
        raise RevisionConflict("revision_conflict")

    def add_workout_exercise(self, operation_id, payload_hash, workout_id, revision, entry_id, exercise):
        result = self._rpc("gym_add_workout_exercise", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash,
            "p_workout_id": workout_id, "p_revision": revision,
            "p_entry_id": entry_id, "p_exercise": exercise,
        })
        return self.get_workout(result["workout_id"])

    def get_program(self, session_key: str | None = None) -> dict[str, Any]:
        selection = self.client.table("gym_program_selection").select("program_version_id").eq("id", True).limit(1).execute().data
        versions = (self.client.table("program_versions").select("*").eq("id", selection[0]["program_version_id"]).limit(1).execute().data
                    if selection else self.client.table("program_versions").select("*").eq("active", True).limit(1).execute().data)
        if not versions:
            raise NotFound("active_program_not_found")
        version = versions[0]
        if not version.get("published", False):
            raise NotFound("active_program_not_found")
        query = self.client.table("program_sessions").select("*").eq("program_version_id", version["id"])
        if session_key:
            query = query.eq("session_key", session_key)
        sessions = query.order("position").limit(1).execute().data
        if not sessions:
            raise NotFound("program_session_not_found")
        session = sessions[0]
        return self._program_session(version, session)

    def get_program_by_session_id(self, session_id):
        sessions = self.client.table("program_sessions").select("*").eq("id", session_id).limit(1).execute().data
        if not sessions:
            raise NotFound("program_session_not_found")
        session = sessions[0]
        versions = self.client.table("program_versions").select("*").eq("id", session["program_version_id"]).eq("published", True).limit(1).execute().data
        if not versions:
            raise Conflict("program_not_published")
        return self._program_session(versions[0], session)

    def _program_session(self, version, session):
        overrides = self.client.table("gym_session_weekdays").select("weekday").eq("session_id", session["id"]).limit(1).execute().data
        if overrides:
            session = {**session, "weekday": overrides[0]["weekday"]}
        entries = self.client.table("program_session_exercises").select("*").eq("session_id", session["id"]).order("position").execute().data
        ids = [entry["exercise_id"] for entry in entries]
        exercises = self.client.table("exercise_library").select("*").in_("id", ids).execute().data
        replacements = self.client.table("gym_session_replacements").select("*").in_("session_exercise_id", [e["id"] for e in entries]).execute().data if entries else []
        if entries and not replacements:
            legacy = self.client.table("exercise_replacements").select("*").in_("exercise_id", ids).execute().data
            replacements = [{"session_exercise_id": e["id"], "replacement_id": row["replacement_id"],
                             "reason": row["reason"]} for e in entries for row in legacy if e["exercise_id"] == row["exercise_id"]]
        replacement_map: dict[str, list[str]] = {}
        replacement_ids = []
        for row in replacements:
            replacement_map.setdefault(row["session_exercise_id"], []).append(row["replacement_id"])
            replacement_ids.append(row["replacement_id"])
        if replacement_ids:
            exercises += self.client.table("exercise_library").select("*").in_("id", replacement_ids).execute().data
        library = {item["id"]: item for item in exercises}
        return {
            "id": version["id"], "session_id": session["id"], "session_key": session["session_key"],
            "name": session["name"], "session_type": session["session_type"], "weekday": session["weekday"],
            "estimated_minutes": session["estimated_minutes"], "created_at": version["created_at"],
            "replacement_reasons": {f'{next((e["exercise_id"] for e in entries if e["id"] == r["session_exercise_id"]), "")}:{r["replacement_id"]}': r["reason"] for r in replacements},
            "version": version["version"], "rule_version": version["rule_version"],
            "program_code": version.get("program_code"), "stage_code": version.get("stage_code"),
            "demo_only": version["demo_only"], "rules": demo_rules(version["rule_version"]),
            "exercise_library": library,
            "exercises": [{**entry, "allowed_replacements": replacement_map.get(entry["id"], [])} for entry in entries],
        }

    def get_active_workout(self):
        rows = self.client.table("workouts").select("*").in_("status", ["preparing", "in_progress"]).limit(1).execute().data
        return self.get_workout(rows[0]["id"]) if rows else None

    def get_workout(self, workout_id: str):
        rows = self.client.table("workouts").select("*").eq("id", workout_id).limit(1).execute().data
        if not rows:
            raise NotFound("workout_not_found")
        exercises = self.client.table("workout_exercises").select("*").eq("workout_id", workout_id).order("position").execute().data
        sets = self.client.table("workout_sets").select("*").eq("workout_id", workout_id).order("completed_at").execute().data
        checkins = self.client.table("checkins").select("*").eq("workout_id", workout_id).order("created_at").execute().data
        return {"workout": rows[0], "exercises": exercises, "sets": sets, "checkins": checkins}

    def operation_status(self, operation_id: str):
        rows = self.client.table("gym_operations").select("status,result,error").eq("id", operation_id).limit(1).execute().data
        if not rows:
            raise NotFound("operation_not_found")
        return rows[0]

    def claim_operation(self, operation_id, kind, resource_id, payload_hash):
        try:
            value = self.client.rpc("gym_claim_operation", {
                "p_id": operation_id, "p_kind": kind, "p_resource_id": resource_id, "p_hash": payload_hash,
            }).execute().data
        except Exception as error:
            code = str(getattr(error, "code", ""))
            if code == "23505" or '"code":"23505"' in str(error).replace(" ", ""):
                return {"status": "pending"}
            raise
        return value[0] if isinstance(value, list) and value else value

    def commit_operation(self, operation_id, token, result):
        return self.client.rpc("gym_commit_operation", {
            "p_id": operation_id, "p_token": token, "p_result": result,
        }).execute().data

    def fail_operation(self, operation_id, token, error):
        return self.client.rpc("gym_fail_operation", {
            "p_id": operation_id, "p_token": token, "p_error": error,
        }).execute().data

    def _rpc(self, name: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            value = self.client.rpc(name, params).execute().data
        except Exception as error:
            message = str(error)
            code = str(getattr(error, "code", ""))
            if code == "23505" or '"code":"23505"' in message.replace(" ", ""):
                raise Conflict("unique_conflict") from error
            if "revision_conflict" in message:
                raise RevisionConflict("revision_conflict") from error
            if name == "gym_commit_offline_workout" and any(code_name in message for code_name in (
                "invalid_offline_snapshot", "invalid_offline_entry", "invalid_offline_entries",
                "invalid_offline_exercise", "invalid_offline_set", "invalid_terminal_status",
                "stop_reason_required", "measurement_mismatch", "incomplete_workout",
                "exercise_not_found", "replacement_not_allowed", "exercise_unavailable",
            )):
                raise ValueError(message) from error
            if any(code in message for code in (
                "active_workout_exists", "invalid_workout_state", "invalid_exercise_order",
                "replacement_not_allowed", "checkin_already_exists", "set_already_exists", "exercise_has_sets", "exercise_unavailable", "empty_plan", "invalid_edit", "incomplete_workout",
                "measurement_mismatch", "workout_exercise_exists", "program_has_unapproved_exercises",
            )):
                raise Conflict(message) from error
            if "not_found" in message:
                raise NotFound(message) from error
            raise
        if isinstance(value, list) and value:
            value = value[0]
        if not isinstance(value, dict):
            raise RepositoryError("invalid_rpc_response")
        if value.get("status") == "conflict":
            raise Conflict("operation_conflict")
        if value.get("status") == "pending":
            raise Conflict("operation_pending")
        return value.get("result", value)

    def prepare_workout(self, operation_id, payload_hash, workout, exercises):
        result = self._rpc("gym_create_prepared_workout", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash,
            "p_workout": workout, "p_exercises": exercises,
        })
        return self.get_workout(result["workout_id"])

    def save_blocked_checkin(self, operation_id, payload_hash, payload, evaluation):
        return self._rpc("gym_save_blocked_checkin", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash,
            "p_payload": payload, "p_evaluation": evaluation,
        })

    def mutate_workout(self, action, operation_id, payload_hash, **params):
        names = {
            "start": "gym_start_workout", "reorder": "gym_reorder_workout",
            "replace": "gym_replace_workout_exercise", "cancel": "gym_cancel_workout",
            "next_day_checkin": "gym_save_next_day_checkin", "update_set": "gym_update_set",
        }
        result = self._rpc(names[action], {"p_operation_id": operation_id, "p_body_hash": payload_hash, **params})
        return self.get_workout(result["workout_id"]) if result.get("workout_id") else result

    def save_set(self, operation_id, payload_hash, set_data):
        bundle = self.get_workout(set_data["workout_id"])
        entry = next((row for row in bundle["exercises"] if row["id"] == set_data["workout_exercise_id"]), None)
        if not entry:
            raise NotFound("workout_exercise_not_found")
        validate_set_fact((entry.get("definition_snapshot") or {}).get("measurement_type"), set_data)
        return self._rpc("gym_save_set", {"p_operation_id": operation_id, "p_body_hash": payload_hash, "p_set": set_data})

    def finish_workout(self, operation_id, payload_hash, workout_id, revision, status, finished_at, stop_reason, post_checkin):
        result = self._rpc("gym_finish_workout", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash, "p_workout_id": workout_id,
            "p_revision": revision, "p_status": status, "p_finished_at": finished_at,
            "p_stop_reason": stop_reason, "p_post_checkin": post_checkin,
        })
        return self.get_workout(result["workout_id"])

    def commit_offline_workout(self, operation_id, payload_hash, workout_id, payload):
        result = self._rpc("gym_commit_offline_workout", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash,
            "p_workout_id": workout_id, "p_payload": payload,
        })
        return self.get_workout(result["workout_id"])

    def list_history(self, date_from=None, date_to=None):
        query = self.client.table("workouts").select("*").order("scheduled_date", desc=True).order("created_at", desc=True)
        if date_from:
            query = query.gte("scheduled_date", date_from)
        if date_to:
            query = query.lte("scheduled_date", date_to)
        return query.execute().data

    def _planned_dates(self, date_from, date_to):
        if not date_from or not date_to:
            return []
        versions = self.client.table("program_versions").select("id").eq("active", True).limit(1).execute().data
        if not versions:
            return []
        sessions = self.client.table("program_sessions").select("weekday").eq("program_version_id", versions[0]["id"]).execute().data
        weekdays = {row["weekday"] for row in sessions if row.get("weekday")}
        cursor, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
        values = []
        while cursor <= end:
            if cursor.isoweekday() in weekdays:
                values.append(cursor.isoformat())
            cursor += timedelta(days=1)
        return values

    def progress_data(self, date_from=None, date_to=None):
        workouts = self.list_history(date_from, date_to)
        workout_ids = [row["id"] for row in workouts]
        if not workout_ids:
            sets, checkins = [], []
        else:
            sets = self.client.table("workout_sets").select("*").in_("workout_id", workout_ids).execute().data
            checkins = self.client.table("checkins").select("*").in_("workout_id", workout_ids).execute().data
        weight_query = self.client.table("weight_entries").select("*").order("measured_at")
        if date_from:
            weight_query = weight_query.gte("measured_at", local_boundary(date_from, self.bootstrap()["profile"]))
        if date_to:
            weight_query = weight_query.lt("measured_at", local_boundary((date.fromisoformat(date_to) + timedelta(days=1)).isoformat(), self.bootstrap()["profile"]))
        weights = weight_query.execute().data
        entries = self.client.table("workout_exercises").select("id,exercise_id,workout_id").in_("workout_id", workout_ids).execute().data if workout_ids else []
        entry_map = {row["id"]: row for row in entries}
        snapshots = {row["id"]: row.get("program_snapshot", {}).get("exercise_library", {}) for row in workouts}
        for item in sets:
            entry = entry_map.get(item["workout_exercise_id"], {})
            definition = entry.get("definition_snapshot") or snapshots.get(entry.get("workout_id"), {}).get(entry.get("exercise_id"), {})
            item["measurement_type"] = definition.get("measurement_type")
            if definition.get("measurement_type") == "weighted_reps":
                item["load_category"] = "external_weight"
            elif "bands" in definition.get("equipment", []):
                item["load_category"] = "band"
            elif definition.get("measurement_type") == "seconds":
                item["load_category"] = "time"
            else:
                item["load_category"] = "bodyweight"
        return {
            "workouts": workouts, "sets": sets, "checkins": checkins,
            "weight_entries": weights, "planned_session_dates": self._planned_dates(date_from, date_to),
        }

    def create_weight(self, operation_id, payload_hash, entry):
        return self._rpc("gym_create_weight", {"p_operation_id": operation_id, "p_body_hash": payload_hash, "p_entry": entry})

    def update_weight(self, operation_id, payload_hash, entry_id, revision, weight_kg, measured_at):
        return self._rpc("gym_update_weight", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash, "p_entry_id": entry_id,
            "p_revision": revision, "p_weight_kg": weight_kg, "p_measured_at": measured_at,
        })

    def export_data(self):
        tables = (
            "player_profile", "exercise_library", "exercise_replacements", "program_versions",
            "program_sessions", "program_session_exercises", "workouts", "workout_exercises",
            "workout_sets", "checkins", "weight_entries", "weekly_reviews", "body_measurements", "workout_edits",
        )
        return {table: self.client.table(table).select("*").execute().data for table in tables}

    def weekly_source(self, week_start):
        end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
        workouts = self.client.table("workouts").select("*").gte("scheduled_date", week_start).lte("scheduled_date", end).in_("status", ["completed", "stopped_early", "cancelled"]).order("scheduled_date").order("id").execute().data
        ids = [row["id"] for row in workouts]
        sets = self.client.table("workout_sets").select("*").in_("workout_id", ids).order("completed_at").order("id").execute().data if ids else []
        checkins = self.client.table("checkins").select("*").in_("workout_id", ids).order("created_at").order("id").execute().data if ids else []
        return {"week_start": week_start, "workouts": workouts, "sets": sets, "checkins": checkins}

    def approved_exercise_ids(self):
        rows = self.client.table("exercise_library").select("id").eq("review_status", "allowed").eq("active", True).execute().data
        return {row["id"] for row in rows}

    def get_current_weekly_review(self, week_start):
        rows = self.client.table("weekly_reviews").select("*").eq("week_start", week_start).order("created_at", desc=True).limit(1).execute().data
        return rows[0] if rows else None

    def commit_weekly_review(self, operation_id, token, review):
        value = self.client.rpc("gym_commit_weekly_review", {
            "p_operation_id": operation_id, "p_token": token, "p_review": review,
        }).execute().data
        return value[0] if isinstance(value, list) and value else value

    def fail_weekly_review(self, operation_id, token, review, error):
        value = self.client.rpc("gym_fail_weekly_review", {
            "p_operation_id": operation_id, "p_token": token, "p_review": review, "p_error": error,
        }).execute().data
        return value[0] if isinstance(value, list) and value else value


def demo_rules(version: str = "demo-rules-v1") -> dict[str, Any]:
    pilot = version == "pilot-rules-v1"
    return {
        "version": version,
        "demo_only": not pilot,
        "pilot": pilot,
        "yellow": {"pain_at_least": 7, "readiness_at_most": 2},
    }


class MemoryRepository:
    """Deterministic repository used by API and domain tests."""

    def __init__(self, program: dict[str, Any] | None = None):
        self.program = deepcopy(program) if program else None
        self.programs = [deepcopy(program)] if program else []
        self.selected_program_id = program.get("id") if program else None
        self.day_choices = {}
        self.weekdays = {}
        self.profile = {"id": True, "timezone": "Europe/Belgrade", "demo_only": True, "revision": 1}
        self.workouts: dict[str, dict[str, Any]] = {}
        self.exercises: dict[str, dict[str, Any]] = {}
        self.sets: dict[str, dict[str, Any]] = {}
        self.checkins: dict[str, dict[str, Any]] = {}
        self.operations: dict[str, dict[str, Any]] = {}
        self.weights: dict[str, dict[str, Any]] = {}
        self.measurements = {}
        self.edits = []
        self.reviews: dict[str, dict[str, Any]] = {}
        self.catalog: dict[str, dict[str, Any]] = deepcopy((program or {}).get("exercise_library", {}))
        for exercise_id, item in self.catalog.items():
            item.setdefault("id", exercise_id)
            item.setdefault("review_status", "needs_review")
            item.setdefault("active", True)
            item.setdefault("note", "")
            item.setdefault("source", "base_catalog")
            item.setdefault("revision", 1)

    def list_exercises(self, query=""):
        needle = query.casefold().strip()
        return sorted((deepcopy(row) for row in self.catalog.values() if row.get("active", True) and needle in row["name"].casefold()), key=lambda row: row["name"].casefold())

    def update_exercise(self, exercise_id, revision, changes):
        row = self.catalog.get(exercise_id)
        if not row:
            raise NotFound("exercise_not_found")
        if row["revision"] != revision:
            raise RevisionConflict("revision_conflict")
        row.update(deepcopy(changes), revision=revision + 1, updated_at=utc_now())
        row["approved"] = bool(row.get("active", True) and row.get("review_status") == "allowed")
        return deepcopy(row)

    def bootstrap(self):
        return {"contract_version": 2, "profile": deepcopy(self.profile), "program": deepcopy(self.program),
                "sessions": [deepcopy(item) for item in self.programs if item.get("id") == self.selected_program_id],
                "programs": self.list_programs(),
                "day_choices": list(deepcopy(self.day_choices).values())}

    def get_program(self, session_key=None):
        sessions = [item for item in self.programs if item.get("id") == self.selected_program_id]
        program = next((item for item in sessions if not session_key or item.get("session_key") == session_key), None)
        if not program:
            raise NotFound("program_session_not_found")
        return deepcopy(program)

    def get_program_by_session_id(self, session_id):
        for program in self.programs:
            if program.get("session_id") == session_id:
                return deepcopy(program)
        raise NotFound("program_session_not_found")

    def list_programs(self):
        result = []
        for program_id in dict.fromkeys(item.get("id") for item in self.programs):
            sessions = [deepcopy(item) for item in self.programs if item.get("id") == program_id]
            if not sessions:
                continue
            first = sessions[0]
            result.append({key: deepcopy(first.get(key)) for key in (
                "id", "name", "version", "program_code", "stage_code", "rule_version", "demo_only"
            )} | {"published": True, "sessions": sessions})
        return result

    def list_day_choices(self):
        return list(deepcopy(self.day_choices).values())

    def select_program(self, program_version_id):
        for program in self.programs:
            if program.get("id") == program_version_id:
                self.selected_program_id = program_version_id
                self.program = deepcopy(program)
                return {"program_version_id": program_version_id}
        raise NotFound("program_not_found")

    def set_session_weekday(self, session_id, weekday):
        self.weekdays[session_id] = weekday
        for program in self.programs:
            if program.get("session_id") == session_id:
                program["weekday"] = weekday
        if self.program and self.program.get("session_id") == session_id:
            self.program["weekday"] = weekday
        return {"session_id": session_id, "weekday": weekday}

    def set_day_choice(self, scheduled_date, choice, session_id=None, assigned_session_id=None):
        if any(w.get("scheduled_date") == scheduled_date and w.get("status") != "cancelled" for w in self.workouts.values()):
            raise Conflict("workout_already_exists")
        row = {"scheduled_date": scheduled_date, "choice": choice, "session_id": session_id,
               "assigned_session_id": assigned_session_id}
        self.day_choices[scheduled_date] = row
        return deepcopy(row)

    def clear_day_choice(self, scheduled_date):
        self.day_choices.pop(scheduled_date, None)
        return {"scheduled_date": scheduled_date, "restored": True}

    def resolve_session(self, scheduled_date):
        choice = self.day_choices.get(scheduled_date)
        if choice:
            if choice["choice"] == "skipped":
                raise Conflict("scheduled_day_skipped")
            return {"program": self.get_program_by_session_id(choice["session_id"]),
                    "assigned_session_id": choice.get("assigned_session_id") or choice["session_id"]}
        weekday = date.fromisoformat(scheduled_date).isoweekday()
        candidates = [program for program in self.programs if program.get("id") == self.selected_program_id]
        program = next((item for item in candidates if self.weekdays.get(item.get("session_id"), item.get("weekday")) == weekday), None)
        if not program:
            raise NotFound("scheduled_session_not_found")
        return {"program": deepcopy(program), "assigned_session_id": program["session_id"]}

    def claim_operation(self, operation_id, kind, resource_id, payload_hash):
        existing = self.operations.get(operation_id)
        if existing:
            if (existing["kind"], existing["resource_id"], existing["body_hash"]) != (kind, resource_id, payload_hash):
                return {"status": "conflict"}
            if existing["status"] == "succeeded":
                return {"status": "succeeded", "result": deepcopy(existing["result"])}
            if existing["status"] == "pending":
                return {"status": "pending"}
            token = str(uuid4())
            existing.update(status="pending", token=token, error=None)
            return {"status": "claimed", "token": token}
        token = str(uuid4())
        self.operations[operation_id] = {
            "kind": kind, "resource_id": resource_id, "body_hash": payload_hash,
            "status": "pending", "token": token, "result": None, "error": None,
        }
        return {"status": "claimed", "token": token}

    def commit_operation(self, operation_id, token, result):
        op = self.operations[operation_id]
        if op["token"] != token or op["status"] != "pending":
            return False
        op.update(status="succeeded", result=deepcopy(result), error=None)
        return True

    def fail_operation(self, operation_id, token, error):
        op = self.operations[operation_id]
        if op["token"] != token or op["status"] != "pending":
            return False
        op.update(status="failed", error=deepcopy(error))
        return True

    def operation_status(self, operation_id):
        if operation_id not in self.operations:
            raise NotFound("operation_not_found")
        op = self.operations[operation_id]
        return {key: deepcopy(op[key]) for key in ("status", "result", "error")}

    def _active(self):
        return [row for row in self.workouts.values() if row["status"] in {"preparing", "in_progress"}]

    def get_active_workout(self):
        active = self._active()
        return self.get_workout(active[0]["id"]) if active else None

    def get_workout(self, workout_id):
        if workout_id not in self.workouts:
            raise NotFound("workout_not_found")
        return {
            "workout": deepcopy(self.workouts[workout_id]),
            "exercises": sorted((deepcopy(row) for row in self.exercises.values() if row["workout_id"] == workout_id), key=lambda row: row["position"]),
            "sets": sorted((deepcopy(row) for row in self.sets.values() if row["workout_id"] == workout_id), key=lambda row: (row["completed_at"], row["id"])),
            "checkins": [deepcopy(row) for row in self.checkins.values() if row.get("workout_id") == workout_id],
        }

    def save_blocked_checkin(self, operation_id, payload_hash, payload, evaluation):
        def save():
            checkin_id = str(uuid4())
            self.checkins[checkin_id] = {
                "id": checkin_id, "workout_id": None, "kind": "pre",
                "payload": deepcopy(payload), "evaluation": deepcopy(evaluation), "created_at": utc_now(),
            }
            return {"blocked": True, "evaluation": deepcopy(evaluation), "checkin_id": checkin_id}
        return execute_operation(self, operation_id, "blocked_checkin", None, {"payload": payload, "evaluation": evaluation}, save, payload_hash)

    def prepare_workout(self, operation_id, payload_hash, workout, exercises):
        def save():
            if self._active():
                raise Conflict("active_workout_exists")
            self.workouts[workout["id"]] = deepcopy(workout)
            for item in exercises:
                self.exercises[item["id"]] = {**deepcopy(item), "workout_id": workout["id"], "revision": 1, "skipped": False}
            if "checkin_payload" in workout:
                checkin_id = str(uuid4())
                self.checkins[checkin_id] = {
                    "id": checkin_id, "workout_id": workout["id"], "kind": "pre",
                    "payload": deepcopy(workout["checkin_payload"]),
                    "evaluation": deepcopy(workout["checkin_evaluation"]), "revision": 1,
                    "created_at": utc_now(), "updated_at": utc_now(),
                }
            return self.get_workout(workout["id"])
        payload = {"workout": workout, "exercises": exercises}
        return execute_operation(self, operation_id, "prepare_workout", workout["id"], payload, save, payload_hash)

    def mutate_workout(self, action, operation_id, payload_hash, **params):
        workout_id = params["p_workout_id"]
        payload = {"action": action, **params}
        def mutate():
            workout = self.workouts.get(workout_id)
            if not workout:
                raise NotFound("workout_not_found")
            revision = params.get("p_revision")
            if revision is not None and workout["revision"] != revision:
                raise RevisionConflict("revision_conflict")
            if action == "start":
                if workout["status"] != "preparing":
                    raise Conflict("invalid_workout_state")
                if not any(e["workout_id"] == workout_id and not e.get("removed") for e in self.exercises.values()):
                    raise Conflict("empty_plan")
                workout.update(status="in_progress", started_at=utc_now())
            elif action == "cancel":
                if workout["status"] != "preparing":
                    raise Conflict("invalid_workout_state")
                workout.update(status="cancelled", finished_at=utc_now())
            elif action == "reorder":
                if workout["status"] not in {"preparing", "in_progress"}:
                    raise Conflict("invalid_workout_state")
                order = params["p_order"]
                current = [row["id"] for row in self.exercises.values() if row["workout_id"] == workout_id]
                if len(order) != len(set(order)) or set(order) != set(current):
                    raise Conflict("invalid_exercise_order")
                for position, entry_id in enumerate(order, 1):
                    self.exercises[entry_id]["position"] = position
            elif action == "replace":
                if workout["status"] not in {"preparing", "in_progress"}:
                    raise Conflict("invalid_workout_state")
                entry = self.exercises.get(params["p_entry_id"])
                if not entry or entry["workout_id"] != workout_id:
                    raise NotFound("workout_exercise_not_found")
                snapshot = workout.get("program_snapshot", {})
                allowed = snapshot.get("exercise_library", {})
                source = next((item for item in snapshot.get("exercises", []) if item["exercise_id"] == entry["original_exercise_id"]), None)
                if not source:
                    raise NotFound("workout_exercise_not_found")
                if params["p_replacement_id"] not in source.get("allowed_replacements", []) or params["p_replacement_id"] not in allowed:
                    raise Conflict("replacement_not_allowed")
                if any(r["workout_exercise_id"] == entry["id"] for r in self.sets.values()):
                    raise Conflict("exercise_has_sets")
                definition = allowed[params["p_replacement_id"]]
                if not definition.get("active", True) or definition.get("review_status") != "allowed":
                    raise Conflict("replacement_not_allowed")
                if definition.get("measurement_type") != allowed[entry["exercise_id"]].get("measurement_type"):
                    raise Conflict("exercise_unavailable")
                entry.update(
                    exercise_id=params["p_replacement_id"], replacement_reason=params.get("p_reason"),
                    definition_snapshot={key: deepcopy(definition.get(key, "")) for key in ("id", "name", "measurement_type", "note")},
                    revision=entry["revision"] + 1,
                )
            elif action == "next_day_checkin":
                if workout["status"] not in {"completed", "stopped_early"}:
                    raise Conflict("invalid_workout_state")
                if any(row.get("workout_id") == workout_id and row["kind"] == "next_day" for row in self.checkins.values()):
                    raise Conflict("checkin_already_exists")
                checkin_id = str(uuid4())
                self.checkins[checkin_id] = {
                    "id": checkin_id, "workout_id": workout_id, "kind": "next_day",
                    "payload": deepcopy(params["p_payload"]), "revision": 1,
                    "created_at": utc_now(), "updated_at": utc_now(),
                }
            elif action == "update_set":
                item = self.sets.get(params["p_set_id"])
                if not item or item["workout_id"] != workout_id:
                    raise NotFound("set_not_found")
                if item["revision"] != params["p_set_revision"]:
                    raise RevisionConflict("revision_conflict")
                entry = self.exercises[item["workout_exercise_id"]]
                validate_set_fact((entry.get("definition_snapshot") or {}).get("measurement_type"), {**item, **params["p_set_data"]})
                item.update(**deepcopy(params["p_set_data"]), revision=item["revision"] + 1)
                workout["edited_at"] = utc_now()
                self.edits.append({"workout_id": workout_id, "action": "update_set", "created_at": utc_now()})
            else:
                raise RepositoryError("unknown_mutation")
            if action != "update_set":
                workout["revision"] += 1
                workout["updated_at"] = utc_now()
            return self.get_workout(workout_id)
        return execute_operation(self, operation_id, action, workout_id, payload, mutate, payload_hash)

    def add_workout_exercise(self, operation_id, payload_hash, workout_id, revision, entry_id, exercise):
        payload = {"workout_id": workout_id, "revision": revision, "entry_id": entry_id, "exercise": exercise}
        def add():
            workout = self.workouts.get(workout_id)
            if not workout:
                raise NotFound("workout_not_found")
            if workout["status"] not in {"preparing", "in_progress"}:
                raise Conflict("invalid_workout_state")
            if workout["revision"] != revision:
                raise RevisionConflict("revision_conflict")
            exercise_id = exercise["id"]
            existing = self.catalog.get(exercise_id)
            if existing:
                if not existing.get("active", True) or existing.get("review_status") == "blocked":
                    raise Conflict("exercise_unavailable")
                definition = existing
            else:
                if not exercise_id.startswith("custom-"):
                    raise NotFound("exercise_not_found")
                definition = {
                    **deepcopy(exercise), "instructions": "", "media_url": None, "equipment": [],
                    "source": "quick_user_entry", "review_status": "needs_review", "active": True,
                    "approved": False, "demo_only": False, "revision": 1,
                }
                self.catalog[exercise_id] = definition
            if entry_id in self.exercises:
                raise Conflict("workout_exercise_exists")
            position = max((row["position"] for row in self.exercises.values() if row["workout_id"] == workout_id), default=0) + 1
            self.exercises[entry_id] = {
                "id": entry_id, "workout_id": workout_id, "original_exercise_id": exercise_id,
                "exercise_id": exercise_id, "position": position, "planned_sets": None,
                "planned_reps": None, "planned_seconds": None, "planned_weight_kg": None,
                "definition_snapshot": {key: deepcopy(definition.get(key, "")) for key in ("id", "name", "measurement_type", "note")},
                "is_ad_hoc": True, "replacement_reason": None, "revision": 1,
                "skipped": False, "removed": False,
            }
            workout.update(revision=revision + 1, updated_at=utc_now())
            return self.get_workout(workout_id)
        return execute_operation(self, operation_id, "add_workout_exercise", workout_id, payload, add, payload_hash)

    def save_set(self, operation_id, payload_hash, set_data):
        workout_id = set_data["workout_id"]
        def save():
            workout = self.workouts.get(workout_id)
            entry = self.exercises.get(set_data["workout_exercise_id"])
            if not workout or workout["status"] != "in_progress":
                raise Conflict("invalid_workout_state")
            if not entry or entry["workout_id"] != workout_id:
                raise NotFound("workout_exercise_not_found")
            if entry.get("removed") or entry.get("skipped"):
                raise Conflict("exercise_unavailable")
            validate_set_fact((entry.get("definition_snapshot") or {}).get("measurement_type"), set_data)
            if set_data["id"] in self.sets or any(
                row["workout_exercise_id"] == entry["id"] and row["set_number"] == set_data["set_number"]
                for row in self.sets.values()
            ):
                raise Conflict("set_already_exists")
            self.sets[set_data["id"]] = {**deepcopy(set_data), "revision": 1, "completed_at": set_data.get("completed_at") or utc_now()}
            return deepcopy(self.sets[set_data["id"]])
        return execute_operation(self, operation_id, "save_set", workout_id, set_data, save, payload_hash)

    def finish_workout(self, operation_id, payload_hash, workout_id, revision, status, finished_at, stop_reason, post_checkin):
        payload = {"workout_id": workout_id, "revision": revision, "status": status, "finished_at": finished_at, "stop_reason": stop_reason, "post_checkin": post_checkin}
        def finish():
            workout = self.workouts.get(workout_id)
            if not workout:
                raise NotFound("workout_not_found")
            if workout["status"] != "in_progress":
                raise Conflict("invalid_workout_state")
            if workout["revision"] != revision:
                raise RevisionConflict("revision_conflict")
            if status == "completed" and any(e.get("skipped") or sum(s["workout_exercise_id"] == e["id"] for s in self.sets.values()) < e["planned_sets"] for e in self.exercises.values() if e["workout_id"] == workout_id and not e.get("removed") and not e.get("is_ad_hoc")):
                raise Conflict("incomplete_workout")
            workout.update(status=status, finished_at=finished_at, stop_reason=stop_reason, revision=revision + 1, updated_at=utc_now())
            checkin_id = str(uuid4())
            self.checkins[checkin_id] = {
                "id": checkin_id, "workout_id": workout_id, "kind": "post",
                "payload": deepcopy(post_checkin), "revision": 1,
                "created_at": utc_now(), "updated_at": utc_now(),
            }
            return self.get_workout(workout_id)
        return execute_operation(self, operation_id, "finish_workout", workout_id, payload, finish, payload_hash)

    def commit_offline_workout(self, operation_id, payload_hash, workout_id, payload):
        from offline_workout import validate_snapshot

        def commit():
            bundle = self.get_workout(workout_id)
            if bundle["sets"] or any(c["kind"] == "post" for c in bundle["checkins"]):
                raise Conflict("offline_server_facts_exist")
            normalized = validate_snapshot(bundle, payload, self.catalog)
            now = utc_now()
            next_catalog = deepcopy(self.catalog)
            next_exercises = deepcopy(self.exercises)
            next_sets = deepcopy(self.sets)
            next_workouts = deepcopy(self.workouts)
            next_checkins = deepcopy(self.checkins)
            for card_id, card in normalized["new_cards"].items():
                next_catalog[card_id] = {
                    **deepcopy(card), "source": "quick_user_entry", "revision": 1,
                    "created_at": now, "updated_at": now,
                }
            for row in normalized["entries"]:
                next_exercises[row["id"]] = deepcopy(row)
            for row in normalized["sets"]:
                next_sets[row["id"]] = deepcopy(row)
            workout = next_workouts[workout_id]
            workout.update(status=payload["status"], finished_at=payload["finished_at"],
                           stop_reason=payload.get("stop_reason"), revision=workout["revision"] + 1,
                           updated_at=now)
            checkin_id = str(uuid4())
            next_checkins[checkin_id] = {
                "id": checkin_id, "workout_id": workout_id, "kind": "post",
                "payload": deepcopy(payload["post_checkin"]), "revision": 1,
                "created_at": now, "updated_at": now,
            }
            self.catalog = next_catalog
            self.exercises = next_exercises
            self.sets = next_sets
            self.workouts = next_workouts
            self.checkins = next_checkins
            return self.get_workout(workout_id)

        return execute_operation(self, operation_id, "commit_offline_workout", workout_id,
                                 payload, commit, payload_hash)

    def list_history(self, date_from=None, date_to=None):
        rows = list(self.workouts.values())
        if date_from:
            rows = [row for row in rows if row.get("scheduled_date") and row["scheduled_date"] >= date_from]
        if date_to:
            rows = [row for row in rows if row.get("scheduled_date") and row["scheduled_date"] <= date_to]
        return sorted((deepcopy(row) for row in rows), key=lambda row: (row.get("scheduled_date") or "", row["created_at"]), reverse=True)

    def progress_data(self, date_from=None, date_to=None):
        workouts = self.list_history(date_from, date_to)
        ids = {row["id"] for row in workouts}
        sets = []
        for row in self.sets.values():
            if row["workout_id"] not in ids:
                continue
            item = deepcopy(row)
            entry = self.exercises[item["workout_exercise_id"]]
            definition = entry.get("definition_snapshot") or self.workouts[row["workout_id"]]["program_snapshot"].get("exercise_library", {}).get(entry["exercise_id"], {})
            item["measurement_type"] = definition.get("measurement_type")
            if definition.get("measurement_type") == "weighted_reps":
                item["load_category"] = "external_weight"
            elif "bands" in definition.get("equipment", []):
                item["load_category"] = "band"
            elif definition.get("measurement_type") == "seconds":
                item["load_category"] = "time"
            else:
                item["load_category"] = "bodyweight"
            sets.append(item)
        checkins = [deepcopy(row) for row in self.checkins.values() if row.get("workout_id") in ids]
        weights = [deepcopy(row) for row in self.weights.values()]
        if date_from:
            weights = [row for row in weights if datetime.fromisoformat(row["measured_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(local_boundary(date_from, self.profile))]
        if date_to:
            weights = [row for row in weights if datetime.fromisoformat(row["measured_at"].replace("Z", "+00:00")) < datetime.fromisoformat(local_boundary((date.fromisoformat(date_to)+timedelta(days=1)).isoformat(), self.profile))]
        planned = []
        if date_from and date_to and self.program and self.program.get("weekday"):
            cursor, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
            while cursor <= end:
                if cursor.isoweekday() == self.program["weekday"]: planned.append(cursor.isoformat())
                cursor += timedelta(days=1)
        return {"workouts": workouts, "sets": sets, "checkins": checkins, "weight_entries": weights, "planned_session_dates": planned}

    def create_weight(self, operation_id, payload_hash, entry):
        def save():
            if entry["id"] in self.weights:
                raise Conflict("weight_entry_exists")
            self.weights[entry["id"]] = {**deepcopy(entry), "revision": 1, "created_at": utc_now(), "updated_at": utc_now()}
            return deepcopy(self.weights[entry["id"]])
        return execute_operation(self, operation_id, "create_weight", entry["id"], entry, save, payload_hash)

    def update_weight(self, operation_id, payload_hash, entry_id, revision, weight_kg, measured_at):
        payload = {"id": entry_id, "revision": revision, "weight_kg": weight_kg, "measured_at": measured_at}
        def save():
            entry = self.weights.get(entry_id)
            if not entry:
                raise NotFound("weight_entry_not_found")
            if entry["revision"] != revision:
                raise RevisionConflict("revision_conflict")
            entry.update(weight_kg=weight_kg, measured_at=measured_at, revision=revision + 1, updated_at=utc_now())
            return deepcopy(entry)
        return execute_operation(self, operation_id, "update_weight", entry_id, payload, save, payload_hash)

    def export_data(self):
        return {
            "player_profile": [deepcopy(self.profile)],
            "exercise_library": list(deepcopy(self.catalog).values()),
            "exercise_replacements": [],
            "program_versions": [deepcopy(self.program)] if self.program else [],
            "program_sessions": [], "program_session_exercises": [],
            "workouts": list(deepcopy(self.workouts).values()),
            "workout_exercises": list(deepcopy(self.exercises).values()),
            "workout_sets": list(deepcopy(self.sets).values()),
            "checkins": list(deepcopy(self.checkins).values()),
            "weight_entries": list(deepcopy(self.weights).values()),
            "body_measurements": list(deepcopy(self.measurements).values()), "workout_edits": deepcopy(self.edits),
            "weekly_reviews": list(deepcopy(self.reviews).values()),
        }

    def weekly_source(self, week_start):
        end = (date.fromisoformat(week_start) + timedelta(days=6)).isoformat()
        workouts = sorted(
            (deepcopy(row) for row in self.workouts.values()
             if week_start <= (row.get("scheduled_date") or "") <= end
             and row["status"] in {"completed", "stopped_early", "cancelled"}),
            key=lambda row: ((row.get("scheduled_date") or ""), row["id"]),
        )
        ids = {row["id"] for row in workouts}
        sets = sorted((deepcopy(row) for row in self.sets.values() if row["workout_id"] in ids), key=lambda row: (row["completed_at"], row["id"]))
        checkins = sorted((deepcopy(row) for row in self.checkins.values() if row.get("workout_id") in ids), key=lambda row: (row["created_at"], row["id"]))
        return {"week_start": week_start, "workouts": workouts, "sets": sets, "checkins": checkins}

    def approved_exercise_ids(self):
        return {
            key for key, value in self.catalog.items()
            if value.get("review_status") == "allowed" and value.get("active", True)
        }

    def get_current_weekly_review(self, week_start):
        rows = [row for row in self.reviews.values() if row["week_start"] == week_start]
        return deepcopy(sorted(rows, key=lambda row: row["created_at"], reverse=True)[0]) if rows else None

    def commit_weekly_review(self, operation_id, token, review):
        for row in self.reviews.values():
            if row["week_start"] == review["week_start"] and row["status"] == "ready":
                row["status"] = "stale"
        saved = {**deepcopy(review), "status": "ready", "revision": 1, "error": None, "created_at": utc_now(), "updated_at": utc_now()}
        self.reviews[saved["id"]] = saved
        self.commit_operation(operation_id, token, saved)
        return deepcopy(saved)

    def fail_weekly_review(self, operation_id, token, review, error):
        saved = {**deepcopy(review), "status": "failed", "revision": 1, "result": None, "error": deepcopy(error), "created_at": utc_now(), "updated_at": utc_now()}
        self.reviews[saved["id"]] = saved
        self.fail_operation(operation_id, token, error)
        return deepcopy(saved)


def local_boundary(day, profile):
    from zoneinfo import ZoneInfo
    return datetime.fromisoformat(day).replace(tzinfo=ZoneInfo((profile or {}).get("timezone", "Europe/Belgrade"))).astimezone(timezone.utc).isoformat()

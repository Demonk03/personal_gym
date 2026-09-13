"""Persistence boundary for Personal Gym."""

from __future__ import annotations

import os
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from operations import execute_operation


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
        return {"profile": profile[0] if profile else None, "program": self.get_program()}

    def get_program(self, session_key: str | None = None) -> dict[str, Any]:
        versions = self.client.table("program_versions").select("*").eq("active", True).limit(1).execute().data
        if not versions:
            raise NotFound("active_program_not_found")
        version = versions[0]
        query = self.client.table("program_sessions").select("*").eq("program_version_id", version["id"])
        if session_key:
            query = query.eq("session_key", session_key)
        sessions = query.order("position").limit(1).execute().data
        if not sessions:
            raise NotFound("program_session_not_found")
        session = sessions[0]
        entries = self.client.table("program_session_exercises").select("*").eq("session_id", session["id"]).order("position").execute().data
        ids = [entry["exercise_id"] for entry in entries]
        exercises = self.client.table("exercise_library").select("*").in_("id", ids).execute().data
        replacements = self.client.table("exercise_replacements").select("*").in_("exercise_id", ids).execute().data
        replacement_map: dict[str, list[str]] = {}
        replacement_ids = []
        for row in replacements:
            replacement_map.setdefault(row["exercise_id"], []).append(row["replacement_id"])
            replacement_ids.append(row["replacement_id"])
        if replacement_ids:
            exercises += self.client.table("exercise_library").select("*").in_("id", replacement_ids).execute().data
        library = {item["id"]: item for item in exercises}
        return {
            "id": version["id"], "session_id": session["id"], "session_key": session["session_key"],
            "version": version["version"], "rule_version": version["rule_version"],
            "demo_only": version["demo_only"], "rules": demo_rules(version["rule_version"]),
            "exercise_library": library,
            "exercises": [{**entry, "allowed_replacements": replacement_map.get(entry["exercise_id"], [])} for entry in entries],
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
            if any(code in message for code in (
                "active_workout_exists", "invalid_workout_state", "invalid_exercise_order",
                "replacement_not_allowed", "checkin_already_exists", "set_already_exists",
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
        return self._rpc("gym_create_prepared_workout", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash,
            "p_workout": workout, "p_exercises": exercises,
        })

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
        return self._rpc("gym_save_set", {"p_operation_id": operation_id, "p_body_hash": payload_hash, "p_set": set_data})

    def finish_workout(self, operation_id, payload_hash, workout_id, revision, status, finished_at, stop_reason, post_checkin):
        result = self._rpc("gym_finish_workout", {
            "p_operation_id": operation_id, "p_body_hash": payload_hash, "p_workout_id": workout_id,
            "p_revision": revision, "p_status": status, "p_finished_at": finished_at,
            "p_stop_reason": stop_reason, "p_post_checkin": post_checkin,
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
            weight_query = weight_query.gte("measured_at", f"{date_from}T00:00:00Z")
        if date_to:
            weight_query = weight_query.lt("measured_at", f"{(date.fromisoformat(date_to) + timedelta(days=1)).isoformat()}T00:00:00Z")
        weights = weight_query.execute().data
        entries = self.client.table("workout_exercises").select("id,exercise_id").in_("workout_id", workout_ids).execute().data if workout_ids else []
        entry_map = {row["id"]: row["exercise_id"] for row in entries}
        exercise_ids = list(set(entry_map.values()))
        library_rows = self.client.table("exercise_library").select("id,equipment,measurement_type").in_("id", exercise_ids).execute().data if exercise_ids else []
        library = {row["id"]: row for row in library_rows}
        for item in sets:
            definition = library.get(entry_map.get(item["workout_exercise_id"]), {})
            if float(item.get("actual_weight_kg") or 0) > 0:
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
            "workout_sets", "checkins", "weight_entries", "weekly_reviews",
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
        rows = self.client.table("exercise_library").select("id").eq("approved", True).eq("active", True).execute().data
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
    return {"version": version, "demo_only": True, "yellow": {"pain_at_least": 7, "readiness_at_most": 2}}


class MemoryRepository:
    """Deterministic repository used by API and domain tests."""

    def __init__(self, program: dict[str, Any] | None = None):
        self.program = deepcopy(program) if program else None
        self.profile = {"id": True, "timezone": "Europe/Belgrade", "demo_only": True, "revision": 1}
        self.workouts: dict[str, dict[str, Any]] = {}
        self.exercises: dict[str, dict[str, Any]] = {}
        self.sets: dict[str, dict[str, Any]] = {}
        self.checkins: dict[str, dict[str, Any]] = {}
        self.operations: dict[str, dict[str, Any]] = {}
        self.weights: dict[str, dict[str, Any]] = {}
        self.reviews: dict[str, dict[str, Any]] = {}

    def bootstrap(self):
        return {"profile": deepcopy(self.profile), "program": deepcopy(self.program)}

    def get_program(self, session_key=None):
        if not self.program or session_key and self.program.get("session_key") != session_key:
            raise NotFound("program_session_not_found")
        return deepcopy(self.program)

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
                entry.update(exercise_id=params["p_replacement_id"], replacement_reason=params.get("p_reason"), revision=entry["revision"] + 1)
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
                item.update(**deepcopy(params["p_set_data"]), revision=item["revision"] + 1)
            else:
                raise RepositoryError("unknown_mutation")
            if action != "update_set":
                workout["revision"] += 1
                workout["updated_at"] = utc_now()
            return self.get_workout(workout_id)
        return execute_operation(self, operation_id, action, workout_id, payload, mutate, payload_hash)

    def save_set(self, operation_id, payload_hash, set_data):
        workout_id = set_data["workout_id"]
        def save():
            workout = self.workouts.get(workout_id)
            entry = self.exercises.get(set_data["workout_exercise_id"])
            if not workout or workout["status"] != "in_progress":
                raise Conflict("invalid_workout_state")
            if not entry or entry["workout_id"] != workout_id:
                raise NotFound("workout_exercise_not_found")
            if set_data["id"] in self.sets or any(
                row["workout_exercise_id"] == entry["id"] and row["set_number"] == set_data["set_number"]
                for row in self.sets.values()
            ):
                raise Conflict("set_already_exists")
            self.sets[set_data["id"]] = {**deepcopy(set_data), "revision": 1, "completed_at": utc_now()}
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
            workout.update(status=status, finished_at=finished_at, stop_reason=stop_reason, revision=revision + 1, updated_at=utc_now())
            checkin_id = str(uuid4())
            self.checkins[checkin_id] = {
                "id": checkin_id, "workout_id": workout_id, "kind": "post",
                "payload": deepcopy(post_checkin), "revision": 1,
                "created_at": utc_now(), "updated_at": utc_now(),
            }
            return self.get_workout(workout_id)
        return execute_operation(self, operation_id, "finish_workout", workout_id, payload, finish, payload_hash)

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
            definition = self.workouts[row["workout_id"]]["program_snapshot"].get("exercise_library", {}).get(entry["exercise_id"], {})
            if float(item.get("actual_weight_kg") or 0) > 0:
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
            weights = [row for row in weights if row["measured_at"][:10] >= date_from]
        if date_to:
            weights = [row for row in weights if row["measured_at"][:10] <= date_to]
        return {"workouts": workouts, "sets": sets, "checkins": checkins, "weight_entries": weights, "planned_session_dates": []}

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
            "exercise_library": list(deepcopy((self.program or {}).get("exercise_library", {})).values()),
            "exercise_replacements": [],
            "program_versions": [deepcopy(self.program)] if self.program else [],
            "program_sessions": [], "program_session_exercises": [],
            "workouts": list(deepcopy(self.workouts).values()),
            "workout_exercises": list(deepcopy(self.exercises).values()),
            "workout_sets": list(deepcopy(self.sets).values()),
            "checkins": list(deepcopy(self.checkins).values()),
            "weight_entries": list(deepcopy(self.weights).values()),
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
            key for key, value in (self.program or {}).get("exercise_library", {}).items()
            if value.get("approved") and value.get("active", True)
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

begin;

create table if not exists player_profile (
  id boolean primary key default true check (id),
  timezone text not null default 'Europe/Belgrade',
  target_weight_kg numeric(5,2) check (target_weight_kg > 0),
  equipment text[] not null default '{}',
  goals jsonb not null default '[]',
  limitations jsonb not null default '[]',
  limitations_reviewed_at timestamptz,
  demo_only boolean not null default true,
  revision integer not null default 1 check (revision >= 1),
  updated_at timestamptz not null default now()
);

create table if not exists exercise_library (
  id text primary key check (id ~ '^[a-z0-9][a-z0-9-]{1,63}$'),
  name text not null check (length(name) between 1 and 160),
  instructions text not null default '',
  media_url text,
  equipment text[] not null default '{}',
  measurement_type text not null check (measurement_type in ('reps','seconds','weighted_reps')),
  demo_only boolean not null default true,
  approved boolean not null default false,
  active boolean not null default true,
  revision integer not null default 1 check (revision >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists exercise_replacements (
  exercise_id text not null references exercise_library(id),
  replacement_id text not null references exercise_library(id),
  reason text not null default '',
  primary key (exercise_id, replacement_id),
  check (exercise_id <> replacement_id)
);

create table if not exists program_versions (
  id uuid primary key,
  version integer not null unique check (version >= 1),
  name text not null,
  rule_version text not null,
  demo_only boolean not null default true,
  approved boolean not null default false,
  active boolean not null default false,
  created_at timestamptz not null default now()
);

create unique index if not exists one_active_program_idx
  on program_versions (active) where active;

create table if not exists program_sessions (
  id uuid primary key,
  program_version_id uuid not null references program_versions(id),
  session_key text not null,
  name text not null,
  session_type text not null check (session_type in ('back_control','full_body','cardio')),
  weekday smallint check (weekday between 1 and 7),
  estimated_minutes integer not null check (estimated_minutes between 1 and 180),
  position integer not null check (position >= 1),
  unique (program_version_id, session_key),
  unique (program_version_id, position)
);

create table if not exists program_session_exercises (
  id uuid primary key,
  session_id uuid not null references program_sessions(id) on delete cascade,
  exercise_id text not null references exercise_library(id),
  position integer not null check (position >= 1),
  planned_sets integer not null check (planned_sets between 1 and 20),
  planned_reps integer check (planned_reps between 1 and 1000),
  planned_seconds integer check (planned_seconds between 1 and 7200),
  planned_weight_kg numeric(6,2) check (planned_weight_kg >= 0),
  yellow_factor numeric(4,3) not null default 0.7 check (yellow_factor > 0 and yellow_factor <= 1),
  unique (session_id, position),
  check (planned_reps is not null or planned_seconds is not null)
);

create table if not exists workouts (
  id uuid primary key,
  program_version_id uuid references program_versions(id),
  program_session_id uuid references program_sessions(id),
  scheduled_date date,
  status text not null check (status in ('preparing','in_progress','completed','stopped_early','cancelled')),
  checkin_mode text not null check (checkin_mode in ('green','yellow','red')),
  checkin_reasons text[] not null default '{}',
  demo_only boolean not null default true,
  is_extra boolean not null default false,
  rule_version text not null,
  profile_snapshot jsonb not null default '{}',
  program_snapshot jsonb not null,
  revision integer not null default 1 check (revision >= 1),
  started_at timestamptz,
  finished_at timestamptz,
  stop_reason text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists one_active_workout_idx
  on workouts ((true)) where status in ('preparing','in_progress');

create index if not exists workouts_date_idx on workouts (scheduled_date desc, created_at desc);

create table if not exists workout_exercises (
  id uuid primary key,
  workout_id uuid not null references workouts(id) on delete cascade,
  original_exercise_id text not null references exercise_library(id),
  exercise_id text not null references exercise_library(id),
  position integer not null check (position >= 1),
  planned_sets integer not null check (planned_sets between 1 and 20),
  planned_reps integer check (planned_reps between 1 and 1000),
  planned_seconds integer check (planned_seconds between 1 and 7200),
  planned_weight_kg numeric(6,2) check (planned_weight_kg >= 0),
  replacement_reason text,
  skipped boolean not null default false,
  skip_reason text,
  revision integer not null default 1 check (revision >= 1),
  unique (workout_id, position)
);

create table if not exists workout_sets (
  id uuid primary key,
  workout_id uuid not null references workouts(id) on delete cascade,
  workout_exercise_id uuid not null references workout_exercises(id) on delete cascade,
  set_number integer not null check (set_number between 1 and 50),
  actual_reps integer check (actual_reps between 0 and 1000),
  actual_seconds integer check (actual_seconds between 0 and 7200),
  actual_weight_kg numeric(6,2) check (actual_weight_kg >= 0),
  difficulty integer check (difficulty between 1 and 10),
  effect text check (effect in ('better','same','worse')),
  completed_at timestamptz not null default now(),
  revision integer not null default 1 check (revision >= 1),
  unique (workout_exercise_id, set_number),
  check (actual_reps is not null or actual_seconds is not null)
);

create table if not exists checkins (
  id uuid primary key,
  workout_id uuid references workouts(id) on delete cascade,
  kind text not null check (kind in ('pre','post','next_day')),
  checkin_date date not null default current_date,
  payload jsonb not null,
  evaluation jsonb,
  rule_version text,
  revision integer not null default 1 check (revision >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (workout_id, kind)
);

create table if not exists weight_entries (
  id uuid primary key,
  weight_kg numeric(5,2) not null check (weight_kg between 25 and 400),
  measured_at timestamptz not null,
  revision integer not null default 1 check (revision >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists weight_entries_measured_idx on weight_entries (measured_at desc, id);

create table if not exists weekly_reviews (
  id uuid primary key,
  week_start date not null,
  source_hash text not null,
  source_workout_ids uuid[] not null default '{}',
  prompt_version text not null,
  model text not null,
  status text not null check (status in ('pending','running','ready','failed','stale')),
  result jsonb,
  error jsonb,
  revision integer not null default 1 check (revision >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (week_start, source_hash)
);

create table if not exists gym_operations (
  id uuid primary key,
  kind text not null,
  resource_id uuid,
  body_hash text not null,
  status text not null check (status in ('pending','succeeded','failed')),
  token uuid not null,
  lease_until timestamptz not null,
  result jsonb,
  error jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists one_pending_resource_operation_idx
  on gym_operations (kind, resource_id) where status='pending' and resource_id is not null;

create table if not exists push_subscriptions (
  id uuid primary key,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists scheduled_jobs (
  id uuid primary key,
  logical_key text not null unique,
  kind text not null check (kind in ('next_day_checkin','weekly_review','workout_reminder')),
  due_at timestamptz not null,
  status text not null check (status in ('pending','running','succeeded','failed','cancelled')),
  attempts integer not null default 0 check (attempts >= 0),
  payload jsonb not null default '{}',
  last_error text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table workouts add column if not exists edited_at timestamptz;
alter table workout_exercises add column if not exists removed boolean not null default false;
create table if not exists workout_edits (
 id uuid primary key default gen_random_uuid(), workout_id uuid references workouts(id),
 action text not null, data jsonb not null default '{}', created_at timestamptz not null default now()
);
create table if not exists body_measurements (
 id uuid primary key, measured_at timestamptz not null,
 waist_cm numeric not null check (waist_cm between 10 and 300),
 chest_cm numeric not null check (chest_cm between 10 and 300),
 hips_cm numeric not null check (hips_cm between 10 and 300),
 thigh_cm numeric not null check (thigh_cm between 10 and 300),
 revision integer not null default 1, created_at timestamptz not null default now()
);

create or replace function gym_claim_operation(
  p_id uuid, p_kind text, p_resource_id uuid, p_hash text
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  op gym_operations;
  fresh uuid := gen_random_uuid();
begin
  insert into gym_operations (id, kind, resource_id, body_hash, status, token, lease_until)
  values (p_id, p_kind, p_resource_id, p_hash, 'pending', fresh, now() + interval '4 minutes')
  on conflict (id) do nothing;

  select * into op from gym_operations where id = p_id for update;
  if op.kind <> p_kind or op.resource_id is distinct from p_resource_id or op.body_hash <> p_hash then
    return jsonb_build_object('status', 'conflict');
  end if;
  if op.status = 'succeeded' then
    return jsonb_build_object('status', 'succeeded', 'result', op.result);
  end if;
  if op.status = 'pending' and op.token <> fresh and op.lease_until > now() then
    return jsonb_build_object('status', 'pending');
  end if;

  update gym_operations
     set status = 'pending', token = fresh, lease_until = now() + interval '4 minutes',
         error = null, updated_at = now()
   where id = p_id;
  return jsonb_build_object('status', 'claimed', 'token', fresh);
end $$;

create or replace function gym_fail_operation(
  p_id uuid, p_token uuid, p_error jsonb
) returns boolean language plpgsql security definer set search_path = public as $$
begin
  update gym_operations
     set status = 'failed', error = p_error, updated_at = now()
   where id = p_id and token = p_token and status = 'pending';
  return found;
end $$;

create or replace function gym_commit_operation(
  p_id uuid, p_token uuid, p_result jsonb
) returns boolean language plpgsql security definer set search_path = public as $$
begin
  update gym_operations
     set status = 'succeeded', result = p_result, error = null, updated_at = now()
   where id = p_id and token = p_token and status = 'pending';
  return found;
end $$;

create or replace function gym_create_prepared_workout(
  p_operation_id uuid, p_body_hash text, p_workout jsonb, p_exercises jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  claim jsonb;
  token uuid;
  workout_id uuid := (p_workout->>'id')::uuid;
  item jsonb;
  result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'prepare_workout', workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;

  insert into workouts (
    id, program_version_id, program_session_id, scheduled_date, status,
    checkin_mode, checkin_reasons, demo_only, rule_version,
    profile_snapshot, program_snapshot, is_extra
  ) values (
    workout_id, nullif(p_workout->>'program_version_id','')::uuid,
    nullif(p_workout->>'program_session_id','')::uuid,
    nullif(p_workout->>'scheduled_date','')::date, 'preparing',
    p_workout->>'checkin_mode', coalesce(array(select jsonb_array_elements_text(p_workout->'checkin_reasons')), '{}'),
    coalesce((p_workout->>'demo_only')::boolean, true), p_workout->>'rule_version',
    coalesce(p_workout->'profile_snapshot', '{}'), p_workout->'program_snapshot', coalesce((p_workout->>'is_extra')::boolean,false)
  );

  if p_workout ? 'checkin_payload' then
    insert into checkins (id, workout_id, kind, checkin_date, payload, evaluation, rule_version)
    values (
      gen_random_uuid(), workout_id, 'pre', coalesce(nullif(p_workout->>'scheduled_date','')::date, current_date),
      p_workout->'checkin_payload', p_workout->'checkin_evaluation', p_workout->>'rule_version'
    );
  end if;

  for item in select * from jsonb_array_elements(p_exercises) loop
    insert into workout_exercises (
      id, workout_id, original_exercise_id, exercise_id, position,
      planned_sets, planned_reps, planned_seconds, planned_weight_kg, replacement_reason
    ) values (
      (item->>'id')::uuid, workout_id, item->>'original_exercise_id', item->>'exercise_id',
      (item->>'position')::integer, (item->>'planned_sets')::integer,
      nullif(item->>'planned_reps','')::integer, nullif(item->>'planned_seconds','')::integer,
      nullif(item->>'planned_weight_kg','')::numeric, item->>'replacement_reason'
    );
  end loop;

  result := jsonb_build_object('workout_id', workout_id, 'revision', 1, 'status', 'preparing');
  perform gym_commit_operation(p_operation_id, token, result);
  return jsonb_build_object('status', 'succeeded', 'result', result);
exception when others then
  perform gym_fail_operation(p_operation_id, token, jsonb_build_object('message', sqlerrm));
  raise;
end $$;

create or replace function gym_save_set(
  p_operation_id uuid, p_body_hash text, p_set jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  claim jsonb;
  token uuid;
  result jsonb;
begin
  claim := gym_claim_operation(
    p_operation_id, 'save_set', (p_set->>'workout_id')::uuid, p_body_hash
  );
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;

  perform 1 from workouts where id=(p_set->>'workout_id')::uuid and status='in_progress' for update;
  if not found then raise exception 'invalid_workout_state'; end if;
  perform 1 from workout_exercises where id=(p_set->>'workout_exercise_id')::uuid
    and workout_id=(p_set->>'workout_id')::uuid and not removed and not skipped for update;
  if not found then raise exception 'exercise_unavailable'; end if;
  insert into workout_sets (
    id, workout_id, workout_exercise_id, set_number, actual_reps,
    actual_seconds, actual_weight_kg, difficulty, effect, completed_at
  ) values (
    (p_set->>'id')::uuid, (p_set->>'workout_id')::uuid,
    (p_set->>'workout_exercise_id')::uuid, (p_set->>'set_number')::integer,
    nullif(p_set->>'actual_reps','')::integer, nullif(p_set->>'actual_seconds','')::integer,
    nullif(p_set->>'actual_weight_kg','')::numeric, nullif(p_set->>'difficulty','')::integer,
    nullif(p_set->>'effect',''), coalesce((p_set->>'completed_at')::timestamptz,now())
  );

  result := jsonb_build_object('set_id', p_set->>'id', 'revision', 1);
  perform gym_commit_operation(p_operation_id, token, result);
  return jsonb_build_object('status', 'succeeded', 'result', result);
exception when others then
  perform gym_fail_operation(p_operation_id, token, jsonb_build_object('message', sqlerrm));
  raise;
end $$;

create or replace function gym_finish_workout(
  p_operation_id uuid, p_body_hash text, p_workout_id uuid, p_revision integer,
  p_status text, p_finished_at timestamptz, p_stop_reason text default null,
  p_post_checkin jsonb default null
) returns jsonb language plpgsql security definer set search_path = public as $$
declare
  claim jsonb;
  token uuid;
  changed workouts;
  result jsonb;
begin
  if p_status not in ('completed','stopped_early') then raise exception 'invalid_terminal_status'; end if;
  claim := gym_claim_operation(p_operation_id, 'finish_workout', p_workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;

  perform 1 from workouts where id=p_workout_id for update;
  if p_status='completed' and exists(select 1 from workout_exercises e where e.workout_id=p_workout_id and not e.removed
    and (e.skipped or (select count(*) from workout_sets s where s.workout_exercise_id=e.id)<e.planned_sets)) then raise exception 'incomplete_workout'; end if;
  update workouts set status = p_status, finished_at = p_finished_at,
    stop_reason = p_stop_reason, revision = revision + 1, updated_at = now()
  where id = p_workout_id and status = 'in_progress' and revision = p_revision
  returning * into changed;
  if changed.id is null then raise exception 'revision_conflict'; end if;

  if p_post_checkin is not null then
    insert into checkins (id, workout_id, kind, checkin_date, payload)
    values (gen_random_uuid(), p_workout_id, 'post', (p_finished_at at time zone 'UTC')::date, p_post_checkin);
  end if;

  result := jsonb_build_object('workout_id', changed.id, 'status', changed.status, 'revision', changed.revision);
  perform gym_commit_operation(p_operation_id, token, result);
  return jsonb_build_object('status', 'succeeded', 'result', result);
exception when others then
  perform gym_fail_operation(p_operation_id, token, jsonb_build_object('message', sqlerrm));
  raise;
end $$;

create or replace function gym_save_blocked_checkin(
  p_operation_id uuid, p_body_hash text, p_payload jsonb, p_evaluation jsonb,
  p_checkin_date date default current_date
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'blocked_checkin', null, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  insert into checkins (id, workout_id, kind, checkin_date, payload, evaluation, rule_version)
  values (p_operation_id, null, 'pre', p_checkin_date, p_payload, p_evaluation, p_evaluation->>'rule_version');
  result := jsonb_build_object('blocked', true, 'checkin_id', p_operation_id, 'evaluation', p_evaluation);
  perform gym_commit_operation(p_operation_id, token, result);
  return jsonb_build_object('status', 'succeeded', 'result', result);
end $$;

create or replace function gym_start_workout(
  p_operation_id uuid, p_body_hash text, p_workout_id uuid, p_revision integer
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; changed workouts; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'start', p_workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  if not exists(select 1 from workout_exercises where workout_id=p_workout_id and not removed) then raise exception 'empty_plan'; end if;
  update workouts set status='in_progress', started_at=now(), revision=revision+1, updated_at=now()
  where id=p_workout_id and status='preparing' and revision=p_revision returning * into changed;
  if changed.id is null then raise exception 'revision_conflict'; end if;
  result := jsonb_build_object('workout_id', changed.id, 'status', changed.status, 'revision', changed.revision);
  perform gym_commit_operation(p_operation_id, token, result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_reorder_workout(
  p_operation_id uuid, p_body_hash text, p_workout_id uuid, p_revision integer, p_order uuid[]
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; current_ids uuid[]; changed workouts; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'reorder', p_workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  select array_agg(id order by id) into current_ids from workout_exercises where workout_id=p_workout_id;
  if cardinality(p_order) <> cardinality(array(select distinct unnest(p_order)))
     or current_ids is distinct from array(select unnest(p_order) order by 1) then
    raise exception 'invalid_exercise_order';
  end if;
  if not exists(select 1 from workouts where id=p_workout_id and status in ('preparing','in_progress') and revision=p_revision) then
    raise exception 'revision_conflict';
  end if;
  update workout_exercises e set position=o.position
  from unnest(p_order) with ordinality as o(id,position)
  where e.id=o.id and e.workout_id=p_workout_id;
  update workouts set revision=revision+1,updated_at=now() where id=p_workout_id returning * into changed;
  result := jsonb_build_object('workout_id',changed.id,'status',changed.status,'revision',changed.revision);
  perform gym_commit_operation(p_operation_id,token,result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_replace_workout_exercise(
  p_operation_id uuid, p_body_hash text, p_workout_id uuid, p_revision integer,
  p_entry_id uuid, p_replacement_id text, p_reason text default ''
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; entry workout_exercises; changed workouts; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'replace', p_workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  perform 1 from workouts where id=p_workout_id for update;
  select * into entry from workout_exercises where id=p_entry_id and workout_id=p_workout_id for update;
  if entry.id is null then raise exception 'workout_exercise_not_found'; end if;
  if not exists(
    select 1 from workouts w, jsonb_array_elements(w.program_snapshot->'exercises') source
    where w.id=p_workout_id and source->>'exercise_id'=entry.original_exercise_id
      and coalesce(source->'allowed_replacements','[]') ? p_replacement_id
  ) or not exists(select 1 from exercise_library where id=p_replacement_id) then
    raise exception 'replacement_not_allowed';
  end if;
  if not exists(select 1 from workouts where id=p_workout_id and status in ('preparing','in_progress') and revision=p_revision) then
    raise exception 'revision_conflict';
  end if;
  perform 1 from workouts where id=p_workout_id for update;
  if exists(select 1 from workout_sets where workout_exercise_id=p_entry_id) then raise exception 'exercise_has_sets'; end if;
  if exists(select 1 from exercise_library r join exercise_library original on original.id=entry.exercise_id
     where r.id=p_replacement_id and r.measurement_type <> original.measurement_type) then raise exception 'exercise_unavailable'; end if;
  if exists(select 1 from checkins c join exercise_library r on r.id=p_replacement_id where c.workout_id=p_workout_id and c.kind='pre'
     and not (coalesce(c.payload->'equipment','[]') @> to_jsonb(r.equipment))) then raise exception 'exercise_unavailable'; end if;
  update workout_exercises set exercise_id=p_replacement_id,replacement_reason=p_reason,revision=revision+1 where id=p_entry_id;
  update workouts set revision=revision+1,updated_at=now() where id=p_workout_id returning * into changed;
  result := jsonb_build_object('workout_id',changed.id,'status',changed.status,'revision',changed.revision);
  perform gym_commit_operation(p_operation_id,token,result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_cancel_workout(
  p_operation_id uuid, p_body_hash text, p_workout_id uuid, p_revision integer, p_reason text default ''
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; changed workouts; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'cancel', p_workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  update workouts set status='cancelled',finished_at=now(),stop_reason=p_reason,revision=revision+1,updated_at=now()
  where id=p_workout_id and status='preparing' and revision=p_revision returning * into changed;
  if changed.id is null then raise exception 'revision_conflict'; end if;
  result := jsonb_build_object('workout_id',changed.id,'status',changed.status,'revision',changed.revision);
  perform gym_commit_operation(p_operation_id,token,result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_save_next_day_checkin(
  p_operation_id uuid, p_body_hash text, p_workout_id uuid, p_revision integer, p_payload jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; changed workouts; checkin_id uuid := gen_random_uuid(); result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'next_day_checkin', p_workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  if not exists(select 1 from workouts where id=p_workout_id and status in ('completed','stopped_early') and revision=p_revision) then
    raise exception 'revision_conflict';
  end if;
  insert into checkins(id,workout_id,kind,payload) values(checkin_id,p_workout_id,'next_day',p_payload);
  update workouts set revision=revision+1,updated_at=now() where id=p_workout_id returning * into changed;
  result := jsonb_build_object('workout_id',changed.id,'status',changed.status,'revision',changed.revision,'checkin_id',checkin_id);
  perform gym_commit_operation(p_operation_id,token,result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_update_set(
  p_operation_id uuid, p_body_hash text, p_workout_id uuid, p_revision integer,
  p_set_id uuid, p_set_revision integer, p_set_data jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; changed workout_sets; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'update_set', p_workout_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  update workout_sets set
    actual_reps=coalesce((p_set_data->>'actual_reps')::integer,actual_reps),
    actual_seconds=coalesce((p_set_data->>'actual_seconds')::integer,actual_seconds),
    actual_weight_kg=coalesce((p_set_data->>'actual_weight_kg')::numeric,actual_weight_kg),
    difficulty=coalesce((p_set_data->>'difficulty')::integer,difficulty),
    effect=coalesce(p_set_data->>'effect',effect), revision=revision+1
  where id=p_set_id and workout_id=p_workout_id and revision=p_set_revision returning * into changed;
  if changed.id is null then raise exception 'revision_conflict'; end if;
  update workouts set edited_at=now() where id=p_workout_id;
  insert into workout_edits(workout_id,action,data) values(p_workout_id,'update_set',p_set_data);
  result := jsonb_build_object('set_id',changed.id,'revision',changed.revision);
  perform gym_commit_operation(p_operation_id,token,result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_create_weight(
  p_operation_id uuid, p_body_hash text, p_entry jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'create_weight', (p_entry->>'id')::uuid, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  insert into weight_entries(id,weight_kg,measured_at)
  values((p_entry->>'id')::uuid,(p_entry->>'weight_kg')::numeric,(p_entry->>'measured_at')::timestamptz);
  result := jsonb_build_object('id',p_entry->>'id','weight_kg',(p_entry->>'weight_kg')::numeric,
    'measured_at',p_entry->>'measured_at','revision',1);
  perform gym_commit_operation(p_operation_id,token,result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_update_weight(
  p_operation_id uuid, p_body_hash text, p_entry_id uuid, p_revision integer,
  p_weight_kg numeric, p_measured_at timestamptz
) returns jsonb language plpgsql security definer set search_path = public as $$
declare claim jsonb; token uuid; changed weight_entries; result jsonb;
begin
  claim := gym_claim_operation(p_operation_id, 'update_weight', p_entry_id, p_body_hash);
  if claim->>'status' <> 'claimed' then return claim; end if;
  token := (claim->>'token')::uuid;
  update weight_entries set weight_kg=p_weight_kg,measured_at=p_measured_at,
    revision=revision+1,updated_at=now()
  where id=p_entry_id and revision=p_revision returning * into changed;
  if changed.id is null then raise exception 'revision_conflict'; end if;
  result := jsonb_build_object('id',changed.id,'weight_kg',changed.weight_kg,
    'measured_at',changed.measured_at,'revision',changed.revision);
  perform gym_commit_operation(p_operation_id,token,result);
  return jsonb_build_object('status','succeeded','result',result);
end $$;

create or replace function gym_commit_weekly_review(
  p_operation_id uuid, p_token uuid, p_review jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare saved weekly_reviews;
begin
  if not exists(select 1 from gym_operations where id=p_operation_id and token=p_token and status='pending') then
    raise exception 'operation_fenced';
  end if;
  insert into weekly_reviews(
    id,week_start,source_hash,source_workout_ids,prompt_version,model,status,result,error
  ) values (
    (p_review->>'id')::uuid,(p_review->>'week_start')::date,p_review->>'source_hash',
    coalesce(array(select jsonb_array_elements_text(p_review->'source_workout_ids'))::uuid[],'{}'),
    p_review->>'prompt_version',p_review->>'model','ready',p_review->'result',null
  ) on conflict (week_start,source_hash) do update set
    source_workout_ids=excluded.source_workout_ids,prompt_version=excluded.prompt_version,
    model=excluded.model,status='ready',result=excluded.result,error=null,
    revision=weekly_reviews.revision+1,updated_at=now()
  returning * into saved;
  update weekly_reviews set status='stale',updated_at=now()
  where week_start=saved.week_start and id<>saved.id and status='ready';
  perform gym_commit_operation(p_operation_id,p_token,to_jsonb(saved));
  return to_jsonb(saved);
end $$;

create or replace function gym_fail_weekly_review(
  p_operation_id uuid, p_token uuid, p_review jsonb, p_error jsonb
) returns jsonb language plpgsql security definer set search_path = public as $$
declare saved weekly_reviews;
begin
  if not exists(select 1 from gym_operations where id=p_operation_id and token=p_token and status='pending') then
    raise exception 'operation_fenced';
  end if;
  insert into weekly_reviews(
    id,week_start,source_hash,source_workout_ids,prompt_version,model,status,result,error
  ) values (
    (p_review->>'id')::uuid,(p_review->>'week_start')::date,p_review->>'source_hash',
    coalesce(array(select jsonb_array_elements_text(p_review->'source_workout_ids'))::uuid[],'{}'),
    p_review->>'prompt_version',p_review->>'model','failed',null,p_error
  ) on conflict (week_start,source_hash) do update set
    status='failed',result=null,error=excluded.error,revision=weekly_reviews.revision+1,updated_at=now()
  returning * into saved;
  perform gym_fail_operation(p_operation_id,p_token,p_error);
  return to_jsonb(saved);
end $$;

alter table player_profile enable row level security;
alter table exercise_library enable row level security;
alter table exercise_replacements enable row level security;
alter table program_versions enable row level security;
alter table program_sessions enable row level security;
alter table program_session_exercises enable row level security;
alter table workouts enable row level security;
alter table workout_exercises enable row level security;
alter table workout_sets enable row level security;
alter table checkins enable row level security;
alter table weight_entries enable row level security;
alter table weekly_reviews enable row level security;
alter table gym_operations enable row level security;
alter table push_subscriptions enable row level security;
alter table scheduled_jobs enable row level security;

revoke all on all tables in schema public from public;
revoke all on function gym_claim_operation(uuid,text,uuid,text) from public;
revoke all on function gym_fail_operation(uuid,uuid,jsonb) from public;
revoke all on function gym_commit_operation(uuid,uuid,jsonb) from public;
revoke all on function gym_create_prepared_workout(uuid,text,jsonb,jsonb) from public;
revoke all on function gym_save_set(uuid,text,jsonb) from public;
revoke all on function gym_finish_workout(uuid,text,uuid,integer,text,timestamptz,text,jsonb) from public;
revoke all on function gym_save_blocked_checkin(uuid,text,jsonb,jsonb,date) from public;
revoke all on function gym_start_workout(uuid,text,uuid,integer) from public;
revoke all on function gym_reorder_workout(uuid,text,uuid,integer,uuid[]) from public;
revoke all on function gym_replace_workout_exercise(uuid,text,uuid,integer,uuid,text,text) from public;
revoke all on function gym_cancel_workout(uuid,text,uuid,integer,text) from public;
revoke all on function gym_save_next_day_checkin(uuid,text,uuid,integer,jsonb) from public;
revoke all on function gym_update_set(uuid,text,uuid,integer,uuid,integer,jsonb) from public;
revoke all on function gym_create_weight(uuid,text,jsonb) from public;
revoke all on function gym_update_weight(uuid,text,uuid,integer,numeric,timestamptz) from public;
revoke all on function gym_commit_weekly_review(uuid,uuid,jsonb) from public;
revoke all on function gym_fail_weekly_review(uuid,uuid,jsonb,jsonb) from public;

create or replace function gym_edit(p_operation_id uuid,p_body_hash text,p_workout_id uuid,p_revision integer,p_action text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path=public as $$
declare claim jsonb; token uuid; w workouts; e workout_exercises; item jsonb; result jsonb;
begin
 claim:=gym_claim_operation(p_operation_id,p_action,p_workout_id,p_body_hash);
 if claim->>'status'<>'claimed' then return claim; end if;
 token:=(claim->>'token')::uuid;
 select * into w from workouts where id=p_workout_id for update;
 if w.id is null then raise exception 'workout_not_found'; end if;
 if w.revision<>p_revision then raise exception 'revision_conflict'; end if;
 if p_action='reprepare' then
   if w.status<>'preparing' then raise exception 'invalid_workout_state'; end if;
   delete from workout_exercises where workout_id=w.id;
   for item in select * from jsonb_array_elements(p_data->'exercises') loop
     insert into workout_exercises(id,workout_id,original_exercise_id,exercise_id,position,planned_sets,planned_reps,planned_seconds,planned_weight_kg,replacement_reason)
     values((item->>'id')::uuid,w.id,item->>'original_exercise_id',item->>'exercise_id',(item->>'position')::integer,(item->>'planned_sets')::integer,
       (item->>'planned_reps')::integer,(item->>'planned_seconds')::integer,(item->>'planned_weight_kg')::numeric,item->>'replacement_reason');
   end loop;
   update workouts set checkin_mode=p_data->'evaluation'->>'mode', checkin_reasons=array(select jsonb_array_elements_text(p_data->'evaluation'->'reasons')),
     program_snapshot=p_data->'snapshot', status=case when (p_data->'evaluation'->>'blocks_workout')::boolean then 'cancelled' else 'preparing' end,
     finished_at=case when (p_data->'evaluation'->>'blocks_workout')::boolean then now() else null end where id=w.id;
   update checkins set payload=p_data->'checkin',evaluation=p_data->'evaluation',revision=revision+1,updated_at=now(),created_at=now() where workout_id=w.id and kind='pre';
 elsif p_action in ('remove','restore','skip','unskip') then
   if w.status not in ('preparing','in_progress') then raise exception 'invalid_workout_state'; end if;
   select * into e from workout_exercises where id=(p_data->>'entry_id')::uuid and workout_id=w.id for update;
   if e.id is null then raise exception 'workout_exercise_not_found'; end if;
   if p_action='remove' and exists(select 1 from workout_sets where workout_exercise_id=e.id) then raise exception 'exercise_has_sets'; end if;
   update workout_exercises set removed=case when p_action in ('remove','restore') then p_action='remove' else removed end,
     skipped=case when p_action in ('skip','unskip') then p_action='skip' else skipped end, revision=revision+1 where id=e.id;
 elsif p_action='undo_set' then
   if w.status<>'in_progress' then raise exception 'invalid_workout_state'; end if;
   delete from workout_sets where id=(p_data->>'set_id')::uuid and workout_id=w.id and revision=(p_data->>'set_revision')::integer;
   if not found then raise exception 'revision_conflict'; end if;
 elsif p_action='edit_post' then
   if w.status not in ('completed','stopped_early') then raise exception 'invalid_workout_state'; end if;
   update checkins set payload=p_data->'post_checkin',revision=revision+1,updated_at=now() where workout_id=w.id and kind='post';
   if not found then raise exception 'checkin_not_found'; end if;
   update workouts set edited_at=now() where id=w.id;
 else raise exception 'invalid_edit'; end if;
 update workouts set revision=revision+1,updated_at=now() where id=w.id;
 insert into workout_edits(workout_id,action,data) values(w.id,p_action,p_data);
 result:=jsonb_build_object('workout_id',w.id,'revision',w.revision+1);
 perform gym_commit_operation(p_operation_id,token,result);
 return jsonb_build_object('status','succeeded','result',result);
end $$;
create or replace function gym_measurement(p_operation_id uuid,p_body_hash text,p_data jsonb)
returns jsonb language plpgsql security definer set search_path=public as $$
declare claim jsonb; entry body_measurements;
begin
 claim:=gym_claim_operation(p_operation_id,'measurement',p_operation_id,p_body_hash);
 if claim->>'status'<>'claimed' then return claim; end if;
 insert into body_measurements(id,measured_at,waist_cm,chest_cm,hips_cm,thigh_cm)
 values(p_operation_id,(p_data->>'measured_at')::timestamptz,(p_data->>'waist_cm')::numeric,(p_data->>'chest_cm')::numeric,(p_data->>'hips_cm')::numeric,(p_data->>'thigh_cm')::numeric) returning * into entry;
 perform gym_commit_operation(p_operation_id,(claim->>'token')::uuid,to_jsonb(entry));
 return jsonb_build_object('status','succeeded','result',to_jsonb(entry));
end $$;
alter table body_measurements enable row level security;
alter table workout_edits enable row level security;
revoke all on body_measurements,workout_edits from public;
revoke all on function gym_edit(uuid,text,uuid,integer,text,jsonb) from public;
revoke all on function gym_measurement(uuid,text,jsonb) from public;

alter table push_subscriptions add column if not exists preferences jsonb not null default '{}';
create or replace function gym_claim_notification(p_key text,p_kind text)
returns jsonb language plpgsql security definer set search_path=public as $$
declare job scheduled_jobs;
begin
 insert into scheduled_jobs(id,logical_key,kind,due_at,status) values(gen_random_uuid(),p_key,p_kind,now(),'pending') on conflict(logical_key) do nothing;
 select * into job from scheduled_jobs where logical_key=p_key for update;
 if job.status='succeeded' or (job.status='running' and job.updated_at>now()-interval '5 minutes') then return jsonb_build_object('claimed',false); end if;
 update scheduled_jobs set status='running',attempts=attempts+1,updated_at=now() where id=job.id;
 return jsonb_build_object('claimed',true,'id',job.id,'attempts',job.attempts+1);
end $$;
revoke all on function gym_claim_notification(text,text) from public;

commit;

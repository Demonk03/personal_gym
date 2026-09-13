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
  workout_id uuid not null references workouts(id) on delete cascade,
  kind text not null check (kind in ('pre','post','next_day')),
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
    profile_snapshot, program_snapshot
  ) values (
    workout_id, nullif(p_workout->>'program_version_id','')::uuid,
    nullif(p_workout->>'program_session_id','')::uuid,
    nullif(p_workout->>'scheduled_date','')::date, 'preparing',
    p_workout->>'checkin_mode', coalesce(array(select jsonb_array_elements_text(p_workout->'checkin_reasons')), '{}'),
    coalesce((p_workout->>'demo_only')::boolean, true), p_workout->>'rule_version',
    coalesce(p_workout->'profile_snapshot', '{}'), p_workout->'program_snapshot'
  );

  for item in select * from jsonb_array_elements(p_exercises) loop
    insert into workout_exercises (
      id, workout_id, original_exercise_id, exercise_id, position,
      planned_sets, planned_reps, planned_seconds, planned_weight_kg
    ) values (
      (item->>'id')::uuid, workout_id, item->>'original_exercise_id', item->>'exercise_id',
      (item->>'position')::integer, (item->>'planned_sets')::integer,
      nullif(item->>'planned_reps','')::integer, nullif(item->>'planned_seconds','')::integer,
      nullif(item->>'planned_weight_kg','')::numeric
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

  insert into workout_sets (
    id, workout_id, workout_exercise_id, set_number, actual_reps,
    actual_seconds, actual_weight_kg, difficulty, effect
  ) values (
    (p_set->>'id')::uuid, (p_set->>'workout_id')::uuid,
    (p_set->>'workout_exercise_id')::uuid, (p_set->>'set_number')::integer,
    nullif(p_set->>'actual_reps','')::integer, nullif(p_set->>'actual_seconds','')::integer,
    nullif(p_set->>'actual_weight_kg','')::numeric, nullif(p_set->>'difficulty','')::integer,
    nullif(p_set->>'effect','')
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
  p_status text, p_finished_at timestamptz, p_stop_reason text default null
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

  update workouts set status = p_status, finished_at = p_finished_at,
    stop_reason = p_stop_reason, revision = revision + 1, updated_at = now()
  where id = p_workout_id and status = 'in_progress' and revision = p_revision
  returning * into changed;
  if changed.id is null then raise exception 'revision_conflict'; end if;

  result := jsonb_build_object('workout_id', changed.id, 'status', changed.status, 'revision', changed.revision);
  perform gym_commit_operation(p_operation_id, token, result);
  return jsonb_build_object('status', 'succeeded', 'result', result);
exception when others then
  perform gym_fail_operation(p_operation_id, token, jsonb_build_object('message', sqlerrm));
  raise;
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
revoke all on function gym_finish_workout(uuid,text,uuid,integer,text,timestamptz,text) from public;

commit;

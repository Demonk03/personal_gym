begin;

alter table exercise_library add column if not exists body_areas text[] not null default '{}';

alter table program_versions add column if not exists program_code text;
alter table program_versions add column if not exists stage_code text;
alter table program_versions add column if not exists published boolean not null default false;
update program_versions
set program_code = 'pilot', stage_code = 'pilot', published = (approved and not demo_only)
where program_code is null;
alter table program_versions alter column program_code set not null;
alter table program_versions alter column stage_code set not null;

create table if not exists gym_program_selection (
  id boolean primary key default true check (id),
  program_version_id uuid not null references program_versions(id),
  revision integer not null default 1 check (revision > 0),
  updated_at timestamptz not null default now()
);

insert into gym_program_selection(id,program_version_id)
select true,id from program_versions where active
on conflict (id) do nothing;

create table if not exists gym_session_weekdays (
  session_id uuid primary key references program_sessions(id) on delete cascade,
  weekday smallint not null check (weekday between 1 and 7)
);

create table if not exists gym_day_choices (
  scheduled_date date primary key,
  choice text not null check (choice in ('session','skipped')),
  session_id uuid references program_sessions(id),
  assigned_session_id uuid references program_sessions(id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check ((choice='session' and session_id is not null) or
         (choice='skipped' and session_id is null))
);

create table if not exists gym_session_replacements (
  session_exercise_id uuid not null references program_session_exercises(id) on delete cascade,
  replacement_id text not null references exercise_library(id),
  reason text not null default '',
  primary key(session_exercise_id,replacement_id)
);

alter table workouts alter column checkin_mode drop not null;
alter table workouts add column if not exists assigned_session_id uuid references program_sessions(id);

create or replace function gym_assert_published_program_eligible(p_program_id uuid) returns void
language plpgsql set search_path=public as $$
begin
  perform gym_assert_program_eligible(p_program_id);
  if not exists(select 1 from program_sessions where program_version_id=p_program_id) then
    raise exception 'program_has_no_sessions';
  end if;
end $$;

create or replace function gym_guard_program_selection() returns trigger
language plpgsql set search_path=public as $$
begin
  if not exists(select 1 from program_versions where id=new.program_version_id and published and approved) then
    raise exception 'program_not_published';
  end if;
  perform gym_assert_published_program_eligible(new.program_version_id);
  return new;
end $$;
drop trigger if exists gym_program_selection_guard on gym_program_selection;
create trigger gym_program_selection_guard before insert or update of program_version_id
on gym_program_selection for each row execute function gym_guard_program_selection();

create or replace function gym_unpublish_programs_for_exercise() returns trigger
language plpgsql set search_path=public as $$
begin
  if not new.active or new.review_status<>'allowed' then
    update program_versions p set published=false
    where p.published and exists(
      select 1 from program_session_exercises pse
      join program_sessions ps on ps.id=pse.session_id
      where ps.program_version_id=p.id and pse.exercise_id=new.id
    );
  end if;
  return new;
end $$;
drop trigger if exists gym_program_unpublish_on_exercise on exercise_library;
create trigger gym_program_unpublish_on_exercise after update of active,review_status
on exercise_library for each row execute function gym_unpublish_programs_for_exercise();

alter table gym_program_selection enable row level security;
alter table gym_session_weekdays enable row level security;
alter table gym_day_choices enable row level security;
alter table gym_session_replacements enable row level security;
revoke all on gym_program_selection,gym_session_weekdays,gym_day_choices,gym_session_replacements
from public,anon,authenticated;

commit;

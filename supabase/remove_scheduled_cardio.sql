-- Apply to an existing three-session pilot in Supabase SQL Editor.
-- Copies the two strength sessions into a new active version; preserves the old
-- version, workout history, exercise-library statuses, and all workout facts.
-- Repeatable. For a fresh database, use activate_pilot_program.sql instead.
begin;

do $remove_scheduled_cardio$
declare
  old_id constant uuid := '71000000-0000-4000-8000-000000000001';
  new_id constant uuid := '71000000-0000-4000-8000-000000000002';
  old_program program_versions;
begin
  select * into old_program from program_versions where id=old_id for update;
  if old_program.id is null then
    raise exception 'previous_pilot_not_found';
  end if;

  if not exists (select 1 from program_versions where id=new_id) then
    if (select count(*) from program_sessions where program_version_id=old_id
        and session_key in ('full-body-a-pilot','full-body-b-pilot')) <> 2 then
      raise exception 'previous_strength_sessions_missing';
    end if;

    insert into program_versions(id,version,name,rule_version,demo_only,approved,active)
    values(new_id,(select coalesce(max(version),0)+1 from program_versions),
      old_program.name,old_program.rule_version,old_program.demo_only,
      old_program.approved,false);

    insert into program_sessions(id,program_version_id,session_key,name,
      session_type,weekday,estimated_minutes,position)
    select case session_key
        when 'full-body-a-pilot' then '72000000-0000-4000-8000-000000000004'::uuid
        else '72000000-0000-4000-8000-000000000005'::uuid end,
      new_id,session_key,name,session_type,weekday,estimated_minutes,position
    from program_sessions
    where program_version_id=old_id
      and session_key in ('full-body-a-pilot','full-body-b-pilot');

    insert into program_session_exercises(id,session_id,exercise_id,position,
      planned_sets,planned_reps,planned_seconds,planned_weight_kg,yellow_factor)
    select gen_random_uuid(),
      case ps.session_key
        when 'full-body-a-pilot' then '72000000-0000-4000-8000-000000000004'::uuid
        else '72000000-0000-4000-8000-000000000005'::uuid end,
      pse.exercise_id,pse.position,pse.planned_sets,pse.planned_reps,
      pse.planned_seconds,pse.planned_weight_kg,pse.yellow_factor
    from program_session_exercises pse
    join program_sessions ps on ps.id=pse.session_id
    where ps.program_version_id=old_id
      and ps.session_key in ('full-body-a-pilot','full-body-b-pilot');
  end if;

  if (select count(*) from program_sessions where program_version_id=new_id) <> 2
      or exists (select 1 from program_sessions where program_version_id=new_id
          and session_type='cardio') then
    raise exception 'two_session_pilot_invalid';
  end if;
  perform gym_assert_program_eligible(new_id);
  update program_versions set active=false where active and id<>new_id;
  update program_versions set active=true where id=new_id;
end
$remove_scheduled_cardio$;

commit;

select ps.weekday,ps.name,ps.session_key
from program_sessions ps
where ps.program_version_id='71000000-0000-4000-8000-000000000002'
order by ps.position;

-- Activate the user-approved 3-week pilot after schema.sql + seed_production.sql.
-- Re-run this file after any later production seed. Safe to execute repeatedly.
begin;

do $pilot_catalog$
declare
  expected_ids text[] := array[
    'light-general-warmup', 'bird-dog', 'glute-bridge', 'dead-bug',
    'band-pallof-press', 'band-row', 'knee-pushup', 'band-chest-press',
    'band-lateral-walk', 'walk-easy'
  ];
  found_count integer;
begin
  select count(*) into found_count
  from exercise_library
  where active and id = any(expected_ids);

  if found_count <> cardinality(expected_ids) then
    raise exception 'pilot_exercises_missing: expected %, found %', cardinality(expected_ids), found_count;
  end if;

  update exercise_library
  set review_status = case
        when id = any(expected_ids) then 'allowed'
        when id = any(array['running','jump-rope','tennis','padel','free-handstand']) then 'blocked'
        else 'needs_review'
      end,
      updated_at = now()
  where active;
end
$pilot_catalog$;

do $pilot_version$
declare
  pilot_id constant uuid := '71000000-0000-4000-8000-000000000001';
  next_version integer;
begin
  if not exists (select 1 from program_versions where id=pilot_id) then
    select coalesce(max(version),0)+1 into next_version from program_versions;
    insert into program_versions (
      id, version, name, rule_version, demo_only, approved, active
    ) values (
      pilot_id, next_version, 'Осторожный пилот · 3 недели',
      'pilot-rules-v1', false, true, false
    );
  else
    update program_versions set
      name='Осторожный пилот · 3 недели',
      rule_version='pilot-rules-v1', demo_only=false, approved=true, active=false
    where id=pilot_id;
  end if;
end
$pilot_version$;

insert into program_sessions (
  id, program_version_id, session_key, name, session_type,
  weekday, estimated_minutes, position
) values
  ('72000000-0000-4000-8000-000000000001','71000000-0000-4000-8000-000000000001','full-body-a-pilot','Всё тело A','full_body',1,30,1),
  ('72000000-0000-4000-8000-000000000002','71000000-0000-4000-8000-000000000001','full-body-b-pilot','Всё тело B + спина','full_body',3,30,2),
  ('72000000-0000-4000-8000-000000000003','71000000-0000-4000-8000-000000000001','easy-cardio-pilot','Спокойное кардио','cardio',6,20,3)
on conflict (id) do update set
  session_key=excluded.session_key, name=excluded.name,
  session_type=excluded.session_type, weekday=excluded.weekday,
  estimated_minutes=excluded.estimated_minutes, position=excluded.position;

delete from program_session_exercises
where session_id in (
  '72000000-0000-4000-8000-000000000001',
  '72000000-0000-4000-8000-000000000002',
  '72000000-0000-4000-8000-000000000003'
);

insert into program_session_exercises (
  id, session_id, exercise_id, position,
  planned_sets, planned_reps, planned_seconds, yellow_factor
) values
  ('73000000-0000-4000-8000-000000000001','72000000-0000-4000-8000-000000000001','light-general-warmup',1,1,null,300,0.67),
  ('73000000-0000-4000-8000-000000000002','72000000-0000-4000-8000-000000000001','bird-dog',2,2,6,null,0.67),
  ('73000000-0000-4000-8000-000000000003','72000000-0000-4000-8000-000000000001','glute-bridge',3,2,10,null,0.67),
  ('73000000-0000-4000-8000-000000000004','72000000-0000-4000-8000-000000000001','band-row',4,2,12,null,0.67),
  ('73000000-0000-4000-8000-000000000005','72000000-0000-4000-8000-000000000001','knee-pushup',5,2,8,null,0.67),
  ('73000000-0000-4000-8000-000000000006','72000000-0000-4000-8000-000000000001','band-lateral-walk',6,2,10,null,0.67),
  ('73000000-0000-4000-8000-000000000007','72000000-0000-4000-8000-000000000001','band-pallof-press',7,2,8,null,0.67),
  ('73000000-0000-4000-8000-000000000008','72000000-0000-4000-8000-000000000002','light-general-warmup',1,1,null,300,0.67),
  ('73000000-0000-4000-8000-000000000009','72000000-0000-4000-8000-000000000002','dead-bug',2,2,6,null,0.67),
  ('73000000-0000-4000-8000-000000000010','72000000-0000-4000-8000-000000000002','band-lateral-walk',3,2,10,null,0.67),
  ('73000000-0000-4000-8000-000000000011','72000000-0000-4000-8000-000000000002','band-row',4,2,12,null,0.67),
  ('73000000-0000-4000-8000-000000000012','72000000-0000-4000-8000-000000000002','band-chest-press',5,2,10,null,0.67),
  ('73000000-0000-4000-8000-000000000013','72000000-0000-4000-8000-000000000002','glute-bridge',6,2,10,null,0.67),
  ('73000000-0000-4000-8000-000000000014','72000000-0000-4000-8000-000000000002','band-pallof-press',7,2,8,null,0.67),
  ('73000000-0000-4000-8000-000000000015','72000000-0000-4000-8000-000000000003','walk-easy',1,1,null,1200,0.60);

do $pilot_assertions$
declare
  pilot_id constant uuid := '71000000-0000-4000-8000-000000000001';
begin
  if (select count(*) from program_sessions where program_version_id=pilot_id) <> 3 then
    raise exception 'pilot_session_count_mismatch';
  end if;
  if (select count(*) from program_session_exercises pse join program_sessions ps on ps.id=pse.session_id where ps.program_version_id=pilot_id) <> 15 then
    raise exception 'pilot_exercise_count_mismatch';
  end if;
  perform gym_assert_program_eligible(pilot_id);

  update program_versions set active=false where active and id<>pilot_id;
  update program_versions set active=true where id=pilot_id;
end
$pilot_assertions$;

commit;

select review_status, count(*) as exercises
from exercise_library where active
group by review_status order by review_status;

select version, name, rule_version, demo_only, approved, active
from program_versions where active;

select ps.position, ps.weekday, ps.name, ps.session_key, count(pse.id) as exercises
from program_sessions ps
join program_session_exercises pse on pse.session_id=ps.id
where ps.program_version_id='71000000-0000-4000-8000-000000000001'
group by ps.id order by ps.position;

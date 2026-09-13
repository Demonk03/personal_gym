begin;

insert into player_profile (
  id, timezone, target_weight_kg, equipment, goals, limitations, demo_only
) values (
  true, 'Europe/Belgrade', 85, array['mat','bands','pullup_bar'],
  '["Общая сила", "Выносливость", "Регулярность"]',
  '["Демонстрационные ограничения — заменить после согласования"]', true
) on conflict (id) do update set
  timezone = excluded.timezone, target_weight_kg = excluded.target_weight_kg,
  equipment = excluded.equipment, goals = excluded.goals,
  limitations = excluded.limitations, demo_only = true, updated_at = now();

insert into exercise_library (id, name, instructions, equipment, measurement_type, demo_only, approved)
values
  ('bird-dog', 'Bird dog', 'Демонстрационная техника — требует проверки.', array['mat'], 'reps', true, false),
  ('glute-bridge', 'Ягодичный мост без веса', 'Демонстрационная техника — требует проверки.', array['mat'], 'reps', true, false),
  ('incline-pushup', 'Отжимания от высокой опоры', 'Демонстрационная техника — требует проверки.', '{}', 'reps', true, false),
  ('band-row', 'Тяга резинки сидя', 'Демонстрационная техника — требует проверки.', array['bands'], 'reps', true, false),
  ('bike-easy', 'Велотренажёр в спокойном темпе', 'Демонстрационная техника — требует проверки.', array['stationary_bike'], 'seconds', true, false),
  ('walk-easy', 'Спокойная ходьба', 'Демонстрационная техника — требует проверки.', '{}', 'seconds', true, false),
  ('wall-pushup', 'Отжимания от стены', 'Демонстрационная техника — требует проверки.', '{}', 'reps', true, false)
on conflict (id) do update set
  name = excluded.name, instructions = excluded.instructions,
  equipment = excluded.equipment, measurement_type = excluded.measurement_type,
  demo_only = true, approved = false, updated_at = now();

insert into exercise_replacements (exercise_id, replacement_id, reason)
values
  ('incline-pushup', 'wall-pushup', 'Демонстрационный облегчённый вариант'),
  ('bike-easy', 'walk-easy', 'Демонстрационная замена по оборудованию')
on conflict (exercise_id, replacement_id) do update set reason = excluded.reason;

insert into program_versions (id, version, name, rule_version, demo_only, approved, active)
values ('10000000-0000-4000-8000-000000000001', 1, 'Демонстрационная программа', 'demo-rules-v1', true, false, true)
on conflict (id) do update set name = excluded.name, rule_version = excluded.rule_version,
  demo_only = true, approved = false, active = true;

insert into program_sessions (id, program_version_id, session_key, name, session_type, weekday, estimated_minutes, position)
values
  ('20000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000001', 'back-a', 'Спина и контроль', 'back_control', 1, 15, 1),
  ('20000000-0000-4000-8000-000000000002', '10000000-0000-4000-8000-000000000001', 'full-body-a', 'Всё тело', 'full_body', 3, 35, 2),
  ('20000000-0000-4000-8000-000000000003', '10000000-0000-4000-8000-000000000001', 'cardio-a', 'Спокойное кардио', 'cardio', 6, 20, 3)
on conflict (id) do update set name = excluded.name, weekday = excluded.weekday,
  estimated_minutes = excluded.estimated_minutes, position = excluded.position;

insert into program_session_exercises (
  id, session_id, exercise_id, position, planned_sets, planned_reps, planned_seconds, yellow_factor
) values
  ('30000000-0000-4000-8000-000000000001', '20000000-0000-4000-8000-000000000001', 'bird-dog', 1, 3, 6, null, 0.67),
  ('30000000-0000-4000-8000-000000000002', '20000000-0000-4000-8000-000000000001', 'glute-bridge', 2, 3, 10, null, 0.67),
  ('30000000-0000-4000-8000-000000000003', '20000000-0000-4000-8000-000000000002', 'bird-dog', 1, 3, 6, null, 0.67),
  ('30000000-0000-4000-8000-000000000004', '20000000-0000-4000-8000-000000000002', 'glute-bridge', 2, 3, 10, null, 0.67),
  ('30000000-0000-4000-8000-000000000005', '20000000-0000-4000-8000-000000000002', 'incline-pushup', 3, 3, 8, null, 0.67),
  ('30000000-0000-4000-8000-000000000006', '20000000-0000-4000-8000-000000000002', 'band-row', 4, 3, 12, null, 0.67),
  ('30000000-0000-4000-8000-000000000007', '20000000-0000-4000-8000-000000000003', 'bike-easy', 1, 1, null, 1200, 0.60)
on conflict (id) do update set planned_sets = excluded.planned_sets,
  planned_reps = excluded.planned_reps, planned_seconds = excluded.planned_seconds,
  yellow_factor = excluded.yellow_factor;

commit;

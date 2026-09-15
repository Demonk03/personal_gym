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

insert into exercise_library (
  id, name, instructions, equipment, measurement_type, demo_only, review_status, source
)
values
  ('prone-lying', 'Лежание на животе', '', string_to_array('mat',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('mckenzie-press-up', 'Разгибания Маккензи', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('glute-bridge', 'Ягодичный мост', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'calisthenics_history'),
  ('bird-dog', 'Bird dog', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('prone-opposite-arm-leg-raise', 'Попеременный подъём руки и ноги лёжа на животе', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('dead-bug', 'Dead bug', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('modified-curl-up', 'Модифицированный curl-up', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('forearm-plank', 'Планка на предплечьях', '', string_to_array('mat',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('side-plank', 'Боковая планка', '', string_to_array('mat',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('plank-shoulder-protraction', 'Планка с проекцией плеч вперёд', '', string_to_array('mat',','), 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('hollow-body-hold', 'Hollow body hold', '', string_to_array('mat',','), 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('band-pallof-press', 'Pallof press с резинкой', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('band-row', 'Тяга резинки к поясу', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('band-lateral-walk', 'Шаги в сторону с резинкой', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('pushup', 'Отжимания классические', '', array[]::text[], 'reps', false, 'needs_review', 'history_2023_2025'),
  ('paused-pushup', 'Отжимания с паузой внизу', '', array[]::text[], 'reps', false, 'needs_review', 'calisthenics_history'),
  ('incline-pushup', 'Отжимания от наклонной поверхности', '', string_to_array('bench',','), 'reps', false, 'needs_review', 'calisthenics_history'),
  ('close-grip-pushup', 'Отжимания узким хватом', '', array[]::text[], 'reps', false, 'needs_review', 'calisthenics_history'),
  ('knee-pushup', 'Отжимания с колен', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('wall-scap-pushup', 'Wall scap push-ups', '', string_to_array('wall',','), 'reps', false, 'needs_review', 'calisthenics_history'),
  ('dumbbell-bench-press', 'Жим гантелей лёжа', '', string_to_array('dumbbells,bench',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('barbell-bench-press', 'Жим штанги лёжа', '', string_to_array('barbell,bench,rack',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('incline-barbell-bench-press', 'Жим штанги на наклонной скамье', '', string_to_array('barbell,incline_bench,rack',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('seated-dumbbell-shoulder-press', 'Жим гантелей сидя', '', string_to_array('dumbbells,bench',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('machine-chest-press', 'Жим в тренажёре от груди', '', string_to_array('chest_press_machine',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('band-chest-press', 'Жим резинки от груди', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('pike-pushup', 'Pike push-ups', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'calisthenics_history'),
  ('cable-triceps-pushdown', 'Разгибание рук на верхнем блоке', '', string_to_array('cable_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('dumbbell-overhead-triceps-extension', 'Разгибание руки с гантелью', '', string_to_array('dumbbell',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('band-triceps-extension', 'Разгибание рук с резинкой', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('pullup-overhand', 'Подтягивания прямым хватом', '', string_to_array('pullup_bar',','), 'reps', false, 'needs_review', 'history_2023_2025'),
  ('pullup-neutral', 'Подтягивания нейтральным хватом', '', string_to_array('neutral_pullup_bar',','), 'reps', false, 'needs_review', 'calisthenics_history'),
  ('band-assisted-pullup', 'Подтягивания с резинкой', '', string_to_array('pullup_bar,bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('lat-pulldown', 'Тяга верхнего блока', '', string_to_array('lat_pulldown_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('seated-cable-row', 'Горизонтальная тяга сидя', '', string_to_array('cable_row_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('bent-over-barbell-row', 'Тяга штанги в наклоне', '', string_to_array('barbell',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('one-arm-dumbbell-row', 'Тяга гантели одной рукой', '', string_to_array('dumbbell,bench',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('chest-supported-dumbbell-row', 'Тяга с опорой грудью', '', string_to_array('dumbbells,incline_bench',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('band-row-to-chest', 'Тяга резинки к груди', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('cable-face-pull', 'Face pull на блоке', '', string_to_array('cable_machine',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('band-face-pull', 'Face pull с резинкой', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('scap-pullup', 'Scap pull-ups', '', string_to_array('pullup_bar',','), 'reps', false, 'needs_review', 'calisthenics_history'),
  ('dumbbell-shrug', 'Шраги с гантелями', '', string_to_array('dumbbells',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('barbell-shrug', 'Шраги со штангой', '', string_to_array('barbell',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('dumbbell-fly', 'Разведение гантелей лёжа', '', string_to_array('dumbbells,bench',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('machine-chest-fly', 'Сведение рук в тренажёре', '', string_to_array('pec_deck_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('dumbbell-lateral-raise', 'Подъём гантелей через стороны', '', string_to_array('dumbbells',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('dumbbell-front-raise', 'Подъём гантелей перед собой', '', string_to_array('dumbbells',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('barbell-curl', 'Сгибание рук с прямой штангой', '', string_to_array('barbell',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('ez-bar-curl', 'Сгибание рук с EZ-штангой', '', string_to_array('ez_bar',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('preacher-curl', 'Сгибание рук на скамье Скотта', '', string_to_array('preacher_bench',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('hammer-curl', 'Молотковые сгибания', '', string_to_array('dumbbells',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('band-biceps-curl', 'Сгибание рук с резинкой', '', string_to_array('bands',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('prone-ytwl', 'YTWL лёжа на животе', '', string_to_array('mat',','), 'reps', false, 'needs_review', 'calisthenics_history'),
  ('scapula-cars', 'Scapula CARs', '', array[]::text[], 'reps', false, 'needs_review', 'calisthenics_history'),
  ('leg-press', 'Жим ногами', '', string_to_array('leg_press_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('box-squat', 'Приседание до бокса', '', string_to_array('box',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('sit-to-stand', 'Вставание со стула', '', string_to_array('chair',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('bulgarian-split-squat', 'Болгарские выпады', '', string_to_array('bench',','), 'weighted_reps', false, 'needs_review', 'calisthenics_history'),
  ('reverse-lunge', 'Обратные выпады', '', array[]::text[], 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('step-up', 'Зашагивания на платформу', '', string_to_array('box',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('romanian-deadlift', 'Румынская тяга', '', string_to_array('barbell',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('machine-leg-curl', 'Сгибание ног в тренажёре', '', string_to_array('leg_curl_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('machine-leg-extension', 'Разгибание ног в тренажёре', '', string_to_array('leg_extension_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('calf-raise', 'Подъём на носки', '', string_to_array('calf_machine',','), 'weighted_reps', false, 'needs_review', 'history_2023_2025'),
  ('machine-hip-abduction', 'Разведение ног в тренажёре', '', string_to_array('hip_abduction_machine',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('machine-hip-adduction', 'Сведение ног в тренажёре', '', string_to_array('hip_adduction_machine',','), 'weighted_reps', false, 'needs_review', 'base_catalog'),
  ('wall-facing-handstand', 'Стойка на руках лицом к стене', '', string_to_array('wall',','), 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('free-handstand', 'Свободная стойка на руках', '', array[]::text[], 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('box-pike-hold', 'Box pike hold', '', string_to_array('box',','), 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('walk-easy', 'Ходьба на улице', '', array[]::text[], 'seconds', false, 'allowed', 'base_catalog'),
  ('treadmill-walk', 'Ходьба на дорожке', '', string_to_array('treadmill',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('bike-easy', 'Велотренажёр', '', string_to_array('stationary_bike',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('elliptical', 'Эллиптический тренажёр', '', string_to_array('elliptical',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('stepper', 'Степпер', '', string_to_array('stepper',','), 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('rowing-machine', 'Гребной тренажёр', '', string_to_array('rower',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('swimming', 'Плавание', '', string_to_array('pool',','), 'seconds', false, 'needs_review', 'base_catalog'),
  ('light-general-warmup', 'Лёгкая общая разминка', '', array[]::text[], 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('jump-rope', 'Скакалка', '', string_to_array('jump_rope',','), 'seconds', false, 'blocked', 'calisthenics_history'),
  ('running', 'Бег', '', array[]::text[], 'seconds', false, 'blocked', 'base_catalog'),
  ('tennis', 'Теннис', '', string_to_array('tennis_court',','), 'seconds', false, 'blocked', 'base_catalog'),
  ('padel', 'Падл', '', string_to_array('padel_court',','), 'seconds', false, 'blocked', 'base_catalog'),
  ('wall-pushup', 'Отжимания от стены', '', string_to_array('wall',','), 'reps', false, 'needs_review', 'base_catalog'),
  ('shoulder-circles', 'Круги плечами', '', array[]::text[], 'reps', false, 'needs_review', 'calisthenics_history'),
  ('elbow-circles', 'Круги локтями', '', array[]::text[], 'reps', false, 'needs_review', 'calisthenics_history'),
  ('wrist-prep', 'Подготовка запястий', '', array[]::text[], 'seconds', false, 'needs_review', 'calisthenics_history'),
  ('shoulder-mobility-light', 'Лёгкая мобилизация плеч', '', array[]::text[], 'seconds', false, 'needs_review', 'calisthenics_history')
on conflict (id) do update set
  name=excluded.name, instructions=excluded.instructions, equipment=excluded.equipment,
  measurement_type=excluded.measurement_type, demo_only=false,
  review_status=excluded.review_status, source=excluded.source, active=true, updated_at=now();

update exercise_library set
  note='Элемент калистеники выполнялся до появления боли в спине; временная последовательность не доказывает причинность.'
where source='calisthenics_history';
update exercise_library set
  note='Во время выполнения появилась боль в правом плече 4/10, после чего упражнение было прекращено.'
where id='free-handstand';

insert into exercise_replacements (exercise_id, replacement_id, reason)
values
  ('incline-pushup', 'wall-pushup', 'Демонстрационный облегчённый вариант'),
  ('bike-easy', 'walk-easy', 'Демонстрационная замена по оборудованию')
on conflict (exercise_id, replacement_id) do update set reason = excluded.reason;

insert into program_versions (id, version, name, rule_version, demo_only, approved, active)
values ('10000000-0000-4000-8000-000000000001', 1, 'Демонстрационная программа', 'demo-rules-v1', true, false, false)
on conflict (id) do update set name = excluded.name, rule_version = excluded.rule_version,
  demo_only = true, approved = false, active = false;

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

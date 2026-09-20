-- Run in Supabase SQL Editor after deploying the new check-in UI and API.
-- Back up checkins first: this removes historical answers from pre-workout JSON payloads.
-- There are no separate columns to drop: checkins.payload is a JSONB column.
begin;

update public.checkins
set payload = (payload - 'systemic_symptoms')
              #- '{leg_symptoms,saddle_numbness}'
              #- '{leg_symptoms,bladder_bowel_change}',
    updated_at = now()
where kind = 'pre'
  and (payload ? 'systemic_symptoms'
       or payload #> '{leg_symptoms,saddle_numbness}' is not null
       or payload #> '{leg_symptoms,bladder_bowel_change}' is not null);

commit;

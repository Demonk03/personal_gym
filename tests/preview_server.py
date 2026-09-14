"""Local synthetic preview, no Supabase or real user data. Run from repository root."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import os
os.environ['API_KEY']='preview-key'
os.environ['DASHBOARD_ORIGIN']='http://127.0.0.1:8774'
from flask import send_from_directory
from app import create_app
from db import MemoryRepository
root=Path(__file__).resolve().parents[1]
program=json.loads((root/'tests/fixtures/demo_program.json').read_text())
program.update(name='Всё тело',session_type='full_body',weekday=7,estimated_minutes=45,created_at='2026-09-01T10:00:00Z')
program['exercise_library']['bird-dog'].update(name='Bird dog',instructions='Из положения на четвереньках вытяните противоположные руку и ногу. Сохраняйте спокойное дыхание.')
repository=MemoryRepository(program)
repository.profile.update(equipment=['mat','bands'],target_weight_kg=85)
for i,value in enumerate([92.4,92.0,91.8,92.2,91.5,91.3]):
 repository.weights[str(i)]={'id':str(i),'measured_at':f'2026-09-{i*2+1:02}T08:00:00Z','weight_kg':value,'revision':1}
app=create_app(repository=repository)
@app.get('/')
def home():return send_from_directory(root/'docs','index.html')
@app.get('/<path:filename>')
def static_file(filename):return send_from_directory(root/'docs',filename)
app.run(host='127.0.0.1',port=8774)

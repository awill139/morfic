import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio, json, tempfile
from pathlib import Path

from morfic.llm import llm
from morfic.localization import detect_localization_request, propose_localization, extract_candidates
from morfic.models import AppManifest

HTML='''<!doctype html><html><body>
<header><h1>LifePulse</h1><p>Your daily life dashboard</p></header>
<label for="sleep">Sleep time</label><input id="sleep" placeholder="When did you go to bed?">
<label for="water">Water intake</label><input id="water" placeholder="How many glasses of water?">
<button title="Save today's entry">Save day</button><section><h2>Weekly trends</h2><p>See how your habits change over time.</p></section>
<script src="app.js"></script></body></html>'''
JS='''const labels = {mood: "Mood", exercise: "Exercise", meals: "Meals", screen: "Screen time"};
function message(){ return "Great job staying consistent!"; }
localStorage.setItem("lifepulse_entries", "[]");'''

TRANSLATIONS={
'Your daily life dashboard':'每日生活仪表盘','Sleep time':'睡眠时间','When did you go to bed?':'你几点睡觉？',
'Water intake':'饮水量','How many glasses of water?':'你喝了多少杯水？',"Save today's entry":'保存今天的记录',
'Save day':'保存今日','Weekly trends':'每周趋势','See how your habits change over time.':'查看你的习惯如何随时间变化。',
'Mood':'心情','Exercise':'运动','Meals':'饮食','Screen time':'屏幕时间','Great job staying consistent!':'坚持得很好！'
}

async def fake(system,user,json_mode):
    assert 'localization engine' in system
    payload=json.loads(user)
    rows=[]
    for c in payload['candidates']:
        if c['text'] in TRANSLATIONS:
            rows.append({'id':c['id'],'text':TRANSLATIONS[c['text']]})
    return json.dumps({'translations':rows},ensure_ascii=False)

async def main():
    assert detect_localization_request('now make it all in chinese') == 'Simplified Chinese'
    with tempfile.TemporaryDirectory() as td:
        root=Path(td); (root/'index.html').write_text(HTML); (root/'app.js').write_text(JS)
        files,candidates=extract_candidates(root)
        assert len(candidates)>=10, len(candidates)
        llm.set_test_handler(fake)
        manifest=AppManifest(name='LifePulse',description='x',requested_intent='track my life',capabilities=[],source_type='generated',entry_file='index.html')
        action=await propose_localization(root,manifest,'now make it all in chinese','Simplified Chinese')
        assert len(action.file_writes)==2
        out={x['path']:x['content'] for x in action.file_writes}
        assert '每日生活仪表盘' in out['index.html']
        assert '睡眠时间' in out['index.html']
        assert '每周趋势' in out['index.html']
        assert '心情' in out['app.js'] and '运动' in out['app.js']
        assert 'lifepulse_entries' in out['app.js'], 'storage key must not be translated'
        assert 'function message()' in out['app.js']
        print('LOCALIZATION FAST PATH PASS:',len(candidates),'candidates,',len(action.file_writes),'files patched')
    llm.set_test_handler(None)

asyncio.run(main())

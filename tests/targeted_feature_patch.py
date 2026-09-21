import os as _os; _os.environ.setdefault("MORFIC_SECRET_STORE", "file")  # never touch the real keychain
import asyncio, json, tempfile
from pathlib import Path

from morfic.generator import modify_generated, validate_static_app
from morfic.llm import llm
from morfic.models import AppManifest
from morfic.repair import apply_patch

# Deliberately large existing app: a feature addition must not rewrite this whole source.
FILLER = "\n".join(f"function existingFeature{i}(){{ return {i}; }}" for i in range(900))
HTML = '''<!doctype html><html><head><link rel="stylesheet" href="styles.css"></head><body>
<nav id="main-nav"><button id="dashboard-tab">Dashboard</button></nav>
<main id="app"><section id="dashboard"><h1>LifePulse</h1><p>Track sleep, water, mood and trends.</p></section></main>
<script src="app.js"></script></body></html>'''
JS = '''const state = JSON.parse(localStorage.getItem("lifepulse_entries") || "[]");
function saveState(){localStorage.setItem("lifepulse_entries", JSON.stringify(state));}
''' + FILLER
CSS = 'body{font-family:system-ui}.card{padding:16px}'
NEW_FEATURE = '''(() => {
  const app = document.getElementById('app');
  if (!app || document.getElementById('caffeine-tracker')) return;
  const section = document.createElement('section');
  section.id = 'caffeine-tracker';
  section.className = 'card';
  section.innerHTML = `<h2>Caffeine tracker</h2><label>Amount (mg)<input id="caffeine-mg" type="number" min="0"></label><button id="caffeine-add">Add</button><p id="caffeine-estimate">No caffeine logged yet.</p>`;
  app.appendChild(section);
  const KEY='lifepulse_caffeine';
  document.getElementById('caffeine-add').addEventListener('click', () => {
    const mg=Number(document.getElementById('caffeine-mg').value||0);
    localStorage.setItem(KEY, JSON.stringify({mg,at:Date.now()}));
    document.getElementById('caffeine-estimate').textContent=`Logged ${mg} mg.`;
  });
})();'''

calls=[]
async def fake(system,user,json_mode):
    calls.append((system,user,json_mode))
    if 'impact-analysis step' in system:
        payload=json.loads(user)
        # Planner should only receive compact structural map, not the 900-function body.
        assert 'existingFeature450' not in user
        return json.dumps({
            'summary':'Add a caffeine tracker as an isolated LifePulse feature',
            'existing_file_changes':[
                {'path':'index.html','instruction':'Load the new caffeine tracker after the existing app script.','hints':['<script src="app.js"></script>','</body>']}
            ],
            'new_files':[{'path':'caffeine-tracker.js','purpose':'Self-contained caffeine logging UI and local persistence mounted into #app.'}],
            'file_deletes':[]
        })
    if 'implementing ONE new file' in system:
        return NEW_FEATURE
    if 'surgical change to ONE existing application file' in system:
        payload=json.loads(user)
        assert payload['target_file']=='index.html'
        return json.dumps({'operations':[{
            'op':'insert_after',
            'anchor':'<script src="app.js"></script>',
            'content':'\n<script src="caffeine-tracker.js"></script>',
            'occurrence':1
        }]})
    raise AssertionError('unexpected prompt: '+system[:100])

async def main():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)
        (root/'index.html').write_text(HTML,encoding='utf-8')
        (root/'app.js').write_text(JS,encoding='utf-8')
        (root/'styles.css').write_text(CSS,encoding='utf-8')
        manifest=AppManifest(name='LifePulse',description='life simulator',requested_intent='track my life',capabilities=['habit tracking'],source_type='generated',entry_file='index.html')
        llm.set_test_handler(fake)
        action=await modify_generated(root,manifest,'add a caffeine tracker')
        # Existing app.js must not be touched at all.
        assert all(x['path']!='app.js' for x in action.file_writes)
        assert {x['path'] for x in action.file_writes}=={'index.html','caffeine-tracker.js'}
        original_js=(root/'app.js').read_text(encoding='utf-8')
        apply_patch(root,None,action)
        assert (root/'app.js').read_text(encoding='utf-8')==original_js
        assert 'caffeine-tracker.js' in (root/'index.html').read_text(encoding='utf-8')
        assert 'Caffeine tracker' in (root/'caffeine-tracker.js').read_text(encoding='utf-8')
        validate_static_app(root,'index.html')
        total_model_output = len(NEW_FEATURE) + len(json.dumps({'operations':[{'op':'insert_after','anchor':'<script src="app.js"></script>','content':'\n<script src="caffeine-tracker.js"></script>','occurrence':1}]}))
        print('TARGETED FEATURE PASS: large app unchanged; new feature isolated; model output chars',total_model_output,'existing JS chars',len(JS))
    llm.set_test_handler(None)

asyncio.run(main())

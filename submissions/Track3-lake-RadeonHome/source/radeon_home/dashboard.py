"""Dependency-free local web console for the RadeonHome task preview.

Run ``python -m radeon_home.dashboard`` and open http://127.0.0.1:8080.
It is intentionally local only and never sends task text to a third party.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import live_runner
from .language import DEFAULT_INSTRUCTION
from .local_llm import local_qwen_status
from .orchestrator import preview_task
from .semantic_world import observe_room


DASHBOARD_INSTRUCTION = "把垃圾扔进垃圾桶"


PAGE = """<!doctype html><html lang='zh-CN'><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>RadeonHome | Language to Verified Physical Delivery</title>
<link rel='icon' href='data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="%23101c31"/><path d="M15 45V18h18c10 0 16 5 16 14s-6 13-16 13zm10-8h8c4 0 6-2 6-5s-2-6-6-6h-8z" fill="%237fdbca"/></svg>'>
<style>
:root{--bg:#07101d;--panel:#101c31;--line:#29415f;--text:#f5f8fc;--muted:#9db0c8;--teal:#7fdbca;--orange:#f28a35;--blue:#4385df}
*{box-sizing:border-box}body{font:15px/1.5 Inter,system-ui,sans-serif;margin:0;background:radial-gradient(circle at 75% 0,#17375a 0,transparent 34%),var(--bg);color:var(--text)}
header{max-width:1240px;margin:auto;padding:22px 28px;display:flex;align-items:center;justify-content:space-between}.brand{font-size:19px;font-weight:850;letter-spacing:.2px}.brand span{color:var(--teal)}.badges{display:flex;gap:8px}.badge,.step{border:1px solid var(--line);border-radius:999px;padding:6px 11px;color:var(--muted);font-size:12px;background:#0c1728}
.hero{max-width:1180px;margin:16px auto 24px;padding:38px;border:1px solid var(--line);border-radius:24px;background:linear-gradient(135deg,#12233c,#0d192b 72%);box-shadow:0 24px 70px #02081280}.eyebrow{color:var(--teal);font-weight:800;letter-spacing:1.7px;font-size:12px}.hero h1{font-size:clamp(34px,5vw,62px);line-height:1.04;max-width:980px;margin:14px 0 18px;letter-spacing:-2px}.hero p{font-size:18px;color:#c3d1e2;max-width:850px}.flow{display:flex;gap:9px;flex-wrap:wrap;margin-top:26px}.step{font-size:13px;color:#e9f1fa;padding:9px 14px}.step b{color:var(--orange);margin-right:5px}.proof{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:24px}.proof div{background:#091524;border-left:3px solid var(--teal);padding:12px 14px;border-radius:8px}.proof strong{display:block}.proof small{color:var(--muted)}
main{max-width:1180px;margin:0 auto 48px;padding:0;display:grid;grid-template-columns:1.05fr .95fr;gap:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:22px;min-width:0}.section-label{color:var(--orange);font-size:12px;font-weight:850;letter-spacing:1px}.card h2{margin:4px 0 14px;font-size:24px}textarea{width:100%;height:84px;background:#07101d;color:white;border:1px solid #42607f;border-radius:10px;padding:13px;font:inherit}button{background:var(--orange);border:0;border-radius:9px;padding:11px 15px;font-weight:800;margin-top:10px;cursor:pointer}button.secondary{background:var(--blue);margin-left:8px}.hint{color:var(--muted);font-size:13px}.sim-stage{margin-top:20px;background:#06101c;border:1px solid #2b4665;border-radius:14px;min-height:330px;padding:12px}.sim-placeholder{min-height:300px;display:grid;place-content:center;text-align:center;color:var(--muted)}.sim-placeholder strong{display:block;color:var(--text);font-size:19px;margin-bottom:6px}.map-title{display:flex;justify-content:space-between;align-items:center;margin-top:12px}details{margin-top:12px;color:var(--muted)}summary{cursor:pointer;color:#bed0e4;font-weight:700}canvas,video{width:100%;background:#07101d;border-radius:10px;border:1px solid #263d59}pre{white-space:pre-wrap;max-height:420px;overflow:auto;color:#b8ccdf;background:#091524;padding:14px;border-radius:10px;font-size:12px}.tag{color:var(--teal);font-weight:850;font-size:12px;border:1px solid #37776d;border-radius:999px;padding:5px 9px}.media{display:grid;grid-template-columns:1fr 1fr;gap:8px}.media h3{grid-column:1/-1}.media img{width:100%;border-radius:8px;border:1px solid var(--line)}.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.metric{background:#091524;border:1px solid #29415f;border-radius:10px;padding:13px}.metric b{display:block;font-size:21px;color:var(--teal)}.metric small{color:var(--muted)}.verdict{margin:12px 0;padding:14px;border-radius:10px;background:#0d2927;border:1px solid #37776d;color:#c8fff4}.verdict strong{display:block;font-size:18px;color:#7fdbca}.phase{color:#c7d6e8;background:#091524;border-radius:10px;padding:13px;margin-bottom:10px}
@media(max-width:800px){header{padding:16px}.badges{display:none}.hero{margin:8px 14px 18px;padding:25px}.hero h1{letter-spacing:-1px}.proof{grid-template-columns:1fr 1fr}main{grid-template-columns:1fr;padding:0 14px}.media{grid-template-columns:1fr}}
</style>
<header><div class='brand'>Radeon<span>Home</span></div><div class='badges'><span class='badge'>Team lake</span><span class='badge'>AMD Radeon / ROCm</span><span class='badge'>Genesis Physical AI</span></div></header>
<section class='hero'><div class='eyebrow'>HOUSEHOLD MOBILE MANIPULATION</div><h1>Tell the robot what belongs where. It navigates, grasps, delivers, and proves the result.</h1><p>RadeonHome turns a household instruction into a collision-aware mobile manipulation task, executes physical contact in Genesis on an AMD Radeon GPU, and records auditable RGB-D, contact, video, and JSON evidence.</p><div class='flow'><span class='step'><b>01</b>Understand</span><span class='step'><b>02</b>Navigate</span><span class='step'><b>03</b>Physical grasp</span><span class='step'><b>04</b>Verify placement</span></div><div class='proof'><div><strong>Local Qwen</strong><small>Intent only, no joint commands</small></div><div><strong>Mobile Franka</strong><small>Collision-aware asset migration</small></div><div><strong>Failure-aware</strong><small>Contact, drift, and retry checks</small></div><div><strong>Reproducible proof</strong><small>RGB-D + MP4 + JSON</small></div></div></section>
<main><section class='card'><div class='section-label'>STEP 1 · REQUEST AND LIVE SIMULATION</div><h2>Give the robot a household task</h2><textarea id='instruction'></textarea><br><button onclick='plan()'>Plan task / 生成计划</button><button class='secondary' onclick='execute()'>Run physical experiment / 执行</button><p class='hint'>Local Qwen explains intent. A validated deterministic controller executes one experiment and never accepts free-form joint commands.</p><div class='map-title'><h3>Real Genesis execution</h3><span class='badge'>Live RGB + metric depth</span></div><div class='sim-stage' id='media'><div class='sim-placeholder'><strong>Plan, then run the physical experiment</strong>Live Genesis RGB and depth refresh here every second.<br>The completed MP4 replaces the stream automatically.</div></div><details><summary>Show collision-aware A* route evidence</summary><canvas id='map' width='640' height='640'></canvas></details></section><section class='card'><div class='section-label'>STEP 2 · EXECUTION EVIDENCE</div><h2>Physical checks <span class='tag' id='status'>READY</span></h2><div id='summary'><div class='phase'>Waiting for a task. The run will report contact, payload retention, placement accuracy, and reproducible artifacts here.</div></div><details><summary>Inspect raw machine-readable evidence</summary><pre id='out'>Loading semantic map…</pre></details></section></main>
<script>const out=document.getElementById('out'),input=document.getElementById('instruction');input.value=__DEFAULT_INSTRUCTION__;
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function draw(s,routes=[]){const c=document.getElementById('map'),x=c.getContext('2d'),g=s.grid,sc=c.width/g.width;x.clearRect(0,0,c.width,c.height);x.strokeStyle='#1b2e48';for(let i=0;i<=g.width;i++){x.beginPath();x.moveTo(i*sc,0);x.lineTo(i*sc,c.height);x.stroke()}x.fillStyle='#58677a';s.occupied_cells.forEach(a=>x.fillRect(a[0]*sc,c.height-(a[1]+1)*sc,sc,sc));x.fillStyle='#7fdbca';Object.entries(s.semantic_docks).forEach(([n,a])=>{let px=(a[0]-g.origin_xy_m[0])/g.resolution_m,py=(a[1]-g.origin_xy_m[1])/g.resolution_m;x.fillRect(px*sc-4,c.height-py*sc-4,8,8);x.fillText(n,px*sc+6,c.height-py*sc)});x.strokeStyle='#ec7a2d';x.lineWidth=3;routes.forEach(r=>{let p=r.pickup_path.concat(r.delivery_path);x.beginPath();p.forEach((a,i)=>{let px=(a[0]+.5)*sc,py=c.height-(a[1]+.5)*sc;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke()});}
function renderSummary(d){let s=document.getElementById('summary');if(d.status==='running'){let l=d.live_status||{};s.innerHTML='<div class="phase"><strong>Genesis is executing now</strong><br>Phase: '+(l.latest_event||'initializing')+'<br>Control steps: '+(l.control_steps||0)+'</div>';return}if(d.status!=='completed'||!d.result){s.innerHTML='<div class="phase">Run '+(d.run_id||'')+' is '+(d.status||'queued')+'.</div>';return}let r=d.result,m=r.manipulation||{},p=m.placement_metrics||{},ok=r.grasp_success&&r.transport_success&&r.place_success;s.innerHTML='<div class="verdict"><strong>'+(ok?'✓ VERIFIED PHYSICAL DELIVERY':'✕ RUN NEEDS REVIEW')+'</strong>'+(ok?'Bilateral grasp, payload retention, and placement checks all passed.':'At least one physical verification check failed.')+'</div><div class="evidence-grid"><div class="metric"><b>'+(r.grasp_success?'PASS':'FAIL')+'</b><small>Bilateral physical grasp</small></div><div class="metric"><b>'+(r.payload_lost_during_transport?'FAIL':'PASS')+'</b><small>Payload retained in transport</small></div><div class="metric"><b>'+((p.horizontal_error_m||0)*1000).toFixed(1)+' mm</b><small>Placement error</small></div><div class="metric"><b>'+(r.recorded_control_steps||0)+'</b><small>Recorded control steps</small></div><div class="metric"><b>'+(r.recorded_video_frames||0)+'</b><small>Real video frames</small></div><div class="metric"><b>AMD GPU</b><small>Genesis backend: '+(r.backend||'unknown').toUpperCase()+'</small></div></div>'}
async function plan(){document.getElementById('status').textContent='PLANNING';let q=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({instruction:input.value,use_local_llm:true})});let d=await q.json();if(!q.ok){out.textContent=d.error;document.getElementById('status').textContent='REJECTED';return}draw(d.observation,d.routes);out.textContent=JSON.stringify({language_backend:d.language_backend,task_plan:d.task_plan,mode:d.mode,disclosure:d.disclosure,events:d.events,routes:d.routes},null,2);let l=d.language_backend||{},steps=(d.task_plan.steps||[]).map(x=>x.object_id+' → '+(x.target_id||x.reference_id)).join('<br>');document.getElementById('summary').innerHTML='<div class="verdict"><strong>Qwen semantic plan validated</strong>'+esc(l.explanation||'Constrained task plan accepted.')+'</div><div class="phase"><strong>'+esc(l.model||'Deterministic fallback')+'</strong><br>Source: '+esc(l.plan_source||l.backend)+'<br><br>'+steps+'<br><br>Qwen selects semantic tasks only. Deterministic validation, A* planning, and physical control remain authoritative.</div>';document.getElementById('status').textContent='PREVIEW READY'}
let activeRun=null;async function execute(){document.getElementById('media').innerHTML='';document.getElementById('status').textContent='GENESIS RUNNING';let q=await fetch('/api/execute',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({instruction:input.value})}),d=await q.json();if(!q.ok){out.textContent=d.error;document.getElementById('status').textContent='READY';return}activeRun=d.run_id;out.textContent=JSON.stringify(d,null,2);renderSummary(d);pollRun()}async function pollRun(){if(!activeRun)return;let q=await fetch('/api/runs/'+activeRun),d=await q.json();out.textContent=JSON.stringify(d,null,2);renderSummary(d);document.getElementById('status').textContent=d.status.toUpperCase();if(d.status==='running'){let media=document.getElementById('media'),stamp=Date.now(),rgb=d.live_rgb_url?'<img alt="live Genesis RGB" src="'+d.live_rgb_url+'?t='+stamp+'">':'<p>Genesis 正在初始化相机…</p>',depth=d.live_depth_url?'<img alt="live Genesis depth" src="'+d.live_depth_url+'?t='+stamp+'">':'';media.innerHTML='<h3>实时 Genesis 画面 / Live simulator</h3><div class="media">'+rgb+depth+'</div><small>阶段：'+(d.live_status.latest_event||'initializing')+'；控制步：'+(d.live_status.control_steps||0)+'</small>';setTimeout(pollRun,1000);return}if(d.status==='completed'){let a=d.artifacts,imgs=(a.rgb_key_frame_urls||[]).slice(-2).map(x=>'<img alt="RGB" src="'+x+'">').join('')+(a.depth_key_frame_urls||[]).slice(-2).map(x=>'<img alt="depth" src="'+x+'">').join('');document.getElementById('media').innerHTML='<h3>真实实验视频 / Physical run</h3><video controls src="'+a.video_url+'"></video><div class="media">'+imgs+'</div>'}}
Promise.all([fetch('/api/scene').then(x=>x.json()),fetch('/api/llm-status').then(x=>x.json())]).then(([s,l])=>{draw(s);out.textContent='语义地图已加载。Local Qwen: '+(l.available?'ONLINE':'OFFLINE (deterministic fallback)')});</script></html>""".replace(
    "__DEFAULT_INSTRUCTION__", json.dumps(DASHBOARD_INSTRUCTION)
)


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, value: dict) -> None:
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/scene":
            self._json(HTTPStatus.OK, observe_room())
        elif path == "/api/llm-status":
            self._json(HTTPStatus.OK, local_qwen_status())
        elif path.startswith("/api/runs/"):
            try:
                self._json(HTTPStatus.OK, live_runner.describe_run(path.rsplit("/", 1)[-1]))
            except KeyError:
                self._json(HTTPStatus.NOT_FOUND, {"error": "unknown run"})
        elif path.startswith("/runs/"):
            parts = path.split("/")
            if len(parts) != 4:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            try:
                artifact = live_runner.resolve_artifact(parts[2], parts[3])
            except (KeyError, FileNotFoundError):
                self._json(HTTPStatus.NOT_FOUND, {"error": "artifact not found"})
                return
            body = artifact.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mimetypes.guess_type(artifact.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/execute":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                self._json(
                    HTTPStatus.ACCEPTED,
                    live_runner.start_physical_run(instruction=payload["instruction"]),
                )
            except (RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        if path != "/api/preview":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            self._json(
                HTTPStatus.OK,
                preview_task(
                    payload["instruction"],
                    use_local_llm=bool(payload.get("use_local_llm", False)),
                ),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def log_message(self, _format: str, *_args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local RadeonHome dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"RadeonHome dashboard: http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()

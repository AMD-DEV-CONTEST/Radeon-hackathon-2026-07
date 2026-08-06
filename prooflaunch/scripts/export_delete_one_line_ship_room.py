from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path

from prooflaunch_remix.files import atomic_write_text, sha256_file
from prooflaunch_remix.visual_release_gate import seal


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-ship-room-v1"
CAROUSEL = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-carousel-v2/receipt.json"
SCHEDULE = ROOT / "artifacts/gtm-last-mile-pk-v1/content-scheduling-super-challenger-v2/content-calendar.json"
RESPONSE = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-response-loop-v1/response-learning-contract.json"
LIFECYCLE = ROOT / "artifacts/gtm-last-mile-pk-v1/gtm-lifecycle-super-challenger-v2/gtm-lifecycle-execution-dossier.json"
PORTFOLIO = ROOT / "evidence/v10/delete-one-line-six-lane-named-pk-portfolio-v4.json"
IMAGE_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-qwen-image-ab-v1/packet-receipt.json"
AUDIO_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-qwen3-tts-v1/review-packet/packet-receipt.json"
MEMORY_PACKET = ROOT / "artifacts/gtm-last-mile-pk-v1/named-product-pk-mem0-v2/review-packet/packet-receipt.json"
EXPERIENCE = ROOT / "artifacts/gtm-last-mile-pk-v1/delete-one-line-experience-v1/index.html"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def rel(path: Path) -> str:
    return os.path.relpath(path, OUTPUT).replace(os.sep, "/")


def main() -> None:
    carousel = load(CAROUSEL)
    schedule = load(SCHEDULE)
    response = load(RESPONSE)
    lifecycle = load(LIFECYCLE)
    portfolio = load(PORTFOLIO)
    packet = load(IMAGE_PACKET)
    audio_packet = load(AUDIO_PACKET)
    memory_packet = load(MEMORY_PACKET)
    if any((schedule["external_activation_executed"], lifecycle["external_action_executed"], portfolio["production_effect_observed"])):
        raise SystemExit("ship room cannot render an overclaimed external state")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    slides = "".join(
        f'<figure><img src="{esc(rel(CAROUSEL.parent / row["png"]["path"]))}" alt="Delete One Line slide {row["slide_id"]}"><figcaption>{row["slide_id"]} · {row["png"]["sha256"][:10]}</figcaption></figure>'
        for row in carousel["files"]
    )
    queue = "".join(
        f'''<article class="queue-card"><div class="row"><span class="channel">{esc(slot['channel'].replace('_', ' '))}</span><span class="pending">HOLD</span></div><h3>{esc(slot['hook'])}</h3><p>{esc(slot['creative_move'])}</p><dl><dt>Format</dt><dd>{esc(slot['format'])}</dd><dt>Learning</dt><dd>{esc(slot['intended_learning'])}</dd><dt>Kill</dt><dd>{esc(slot['decision_rule'])}</dd><dt>Review due</dt><dd>{esc(slot['review_due_at_utc'])}</dd></dl></article>'''
        for slot in schedule["slots"]
    )
    image_reviewers = "".join(
        f'<a class="review" href="{esc(rel(IMAGE_PACKET.parent / "public" / f"reviewer-{slot:02d}.html"))}"><b>Reviewer {slot:02d}</b><span>source hidden · independent · empty</span></a>'
        for slot in range(1, 6)
    )
    audio_reviewers = "".join(
        f'<a class="review audio" href="{esc(rel(AUDIO_PACKET.parent / "public" / f"reviewer-{slot:02d}.html"))}"><b>Listener {slot:02d}</b><span>source hidden · same script · empty</span></a>'
        for slot in range(1, 6)
    )
    memory_reviewers = "".join(
        f'<a class="review memory" href="{esc(rel(MEMORY_PACKET.parent / "public" / f"reviewer-{slot:02d}.html"))}"><b>Auditor {slot:02d}</b><span>source hidden · same task · empty</span></a>'
        for slot in range(1, 6)
    )
    signals = "".join(
        f'''<article><div class="row"><span class="channel">{esc(row['id'].replace('_', ' '))}</span><span class="{('learn' if row['learning_eligible'] else 'ignore')}">{'LEARN' if row['learning_eligible'] else 'NO LEARNING'}</span></div><p>{esc(row['meaning'])}</p><small>{esc(row['reply_job'])}</small></article>'''
        for row in response["signal_classes"]
    )
    team_cells = lifecycle["team_cells"]
    cells = "".join(
        f'''<article><span>{index:02d}</span><h3>{esc(row.get('cell_name', row.get('name', row.get('cell_id', 'specialist'))))}</h3><p>{esc(row['failure_signature'])}</p><small>Gate: {esc(row['quality_gate'])}</small></article>'''
        for index, row in enumerate(team_cells, 1)
    )
    executable_rows = [row for row in portfolio["rows"] if row["category_id"] in {"image_generation_editing", "audio_voice_music", "cross_device_memory"}]
    pk_rows = "".join(
        f'''<tr><td>{esc({'image_generation_editing': 'image', 'audio_voice_music': 'audio', 'cross_device_memory': 'memory'}[row['category_id']])}</td><td>{esc(row['reference_product'])}</td><td>{'YES' if row['authorized_named_product_baseline_present'] else 'NO'}</td><td>{'READY' if row['source_hidden_five_human_packet_present'] else 'MISSING'}</td><td>{row['qualified_human_review_count']}/5</td><td>0</td><td>{esc(row['comparison_status'].replace('_', ' '))}</td></tr>'''
        for row in executable_rows
    )
    if any(item["submitted_review_count"] != 0 for item in (packet, audio_packet, memory_packet)):
        raise SystemExit("ship room review counts must be regenerated from compiled human results")
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>ProofLaunch · Delete One Line Ship Room</title><style>
:root{{--ink:#0a0b09;--paper:#f2eee4;--acid:#dcff2f;--red:#ff4e38;--blue:#334cff;--violet:#7b2cff;--line:#b8b3a8;--muted:#69665f}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.45 Arial,Helvetica,sans-serif}}a{{color:inherit}}.wrap{{width:min(1520px,calc(100% - 36px));margin:auto}}nav{{position:sticky;top:0;z-index:9;background:rgba(242,238,228,.94);backdrop-filter:blur(16px);border-bottom:2px solid var(--ink)}}nav .wrap{{height:62px;display:flex;align-items:center;justify-content:space-between}}nav strong,.mono,.channel,.pending,.learn,.ignore,dt,figcaption{{font:900 12px/1.15 ui-monospace,SFMono-Regular,monospace;letter-spacing:.08em;text-transform:uppercase}}nav div{{display:flex;gap:18px}}nav a{{text-decoration:none}}header{{padding:70px 0 42px;border-bottom:2px solid var(--ink)}}h1{{font-size:clamp(60px,10vw,148px);line-height:.82;letter-spacing:-.08em;margin:22px 0;max-width:1300px}}.lede{{font-size:clamp(20px,2.4vw,38px);line-height:1.08;max-width:1060px}}.score{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--ink);border:1px solid var(--ink);margin-top:40px}}.score div{{background:var(--paper);padding:20px}}.score b{{display:block;font-size:42px;letter-spacing:-.06em}}.score small{{color:var(--muted)}}section{{padding:58px 0;border-bottom:1px solid var(--line)}}.section-head{{display:grid;grid-template-columns:1fr 1.4fr;gap:28px;margin-bottom:28px}}h2{{font-size:clamp(38px,5vw,78px);line-height:.9;letter-spacing:-.06em;margin:0}}.section-head p{{font-size:20px;margin:0;max-width:760px}}.action{{display:inline-block;background:var(--ink);color:var(--paper);padding:14px 18px;text-decoration:none;font-weight:900;margin-top:18px}}.filmstrip{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;overflow:auto}}figure{{margin:0;min-width:190px}}figure img{{width:100%;display:block;border:2px solid var(--ink)}}figcaption{{padding:8px 0}}.reviews{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.review{{border:2px solid var(--ink);padding:22px;text-decoration:none;background:var(--acid)}}.review.audio{{background:var(--blue);color:white}}.review.memory{{background:var(--violet);color:white}}.review b,.review span{{display:block}}.review span{{margin-top:7px;color:#333;font-size:12px}}.review.audio span,.review.memory span{{color:#e1e5ff}}.queue{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}}.queue-card,.signals article,.cells article{{border:1px solid var(--ink);padding:22px;background:#f8f5ed}}.row{{display:flex;justify-content:space-between;gap:12px}}.pending{{background:var(--red);padding:5px 8px}}.learn{{background:var(--acid);padding:5px 8px}}.ignore{{background:#d0ccc2;padding:5px 8px}}h3{{font-size:28px;line-height:1;margin:18px 0 12px;letter-spacing:-.04em}}dl{{display:grid;grid-template-columns:84px 1fr;gap:8px;margin:20px 0 0}}dd{{margin:0;color:var(--muted)}}.signals{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.signals small,.cells small{{color:var(--muted)}}.cells{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.cells article>span{{font-size:34px;font-weight:900;color:var(--red)}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:11px;text-transform:uppercase}}.boundary{{background:var(--ink);color:var(--paper);padding:26px;font-size:22px}}footer{{padding:42px 0 70px;color:var(--muted)}}@media(max-width:900px){{nav div{{display:none}}.score,.reviews{{grid-template-columns:repeat(2,1fr)}}.queue,.signals,.section-head{{grid-template-columns:1fr}}.cells{{grid-template-columns:repeat(2,1fr)}}.filmstrip{{grid-template-columns:repeat(5,60vw)}}}}
</style></head><body><nav><div class="wrap"><strong>PROOFLAUNCH / SHIP ROOM 01</strong><div><a href="#creative">Creative</a><a href="#review">Blind review</a><a href="#queue">Queue</a><a href="#learning">Learning</a><a href="#pk">PK</a></div></div></nav><header><div class="wrap"><div class="mono">DELETE ONE LINE · B2B ORGANIC LAUNCH · HUMAN RELEASE REQUIRED</div><h1>0 SHIPPED.<br>3 REAL FIGHTS.</h1><p class="lede">This is not a gallery of forty things an agent made. It is the room where one campaign earns—or loses—the right to leave the building.</p><div class="score"><div><b>5</b><small>finished 4:5 frames</small></div><div><b>7</b><small>channel decisions on hold</small></div><div><b>3</b><small>same-task named baselines</small></div><div><b>0/15</b><small>independent reviews</small></div><div><b>0</b><small>observed market effects</small></div></div></div></header><main>
<section id="creative"><div class="wrap"><div class="section-head"><h2>The work,<br>not the promise.</h2><div><p>Five frames turn one forbidden outcome claim into a visible sacrifice, evidence docket, verdict and reusable operator test.</p><a class="action" href="{esc(rel(EXPERIENCE))}">RUN THE LOCAL CLAIM TRIAL →</a></div></div><div class="filmstrip">{slides}</div></div></section>
<section id="review"><div class="wrap"><div class="section-head"><h2>Qwen-Image<br>versus this.</h2><p>Same task. Original local Qwen-family export. No hidden repair. Left/right placement varies by reviewer. Product identity is absent from public review files. A packet is not a win.</p></div><div class="reviews">{image_reviewers}</div></div></section>
<section><div class="wrap"><div class="section-head"><h2>Qwen3‑TTS<br>versus this.</h2><p>Identical frozen script. The raw local VoiceDesign output faces the mastered cross-examiner direction. Five source-hidden listeners judge intelligibility, prosody, emotion, consistency, mix and consent provenance.</p></div><div class="reviews">{audio_reviewers}</div></div></section>
<section><div class="wrap"><div class="section-head"><h2>Mem0<br>versus this.</h2><p>Same approved insight, desktop-to-mobile handoff, newer contradictory fact, provenance test and exact deletion. Five source-hidden auditors judge the JSON evidence—not vendor identity or framework popularity.</p></div><div class="reviews">{memory_reviewers}</div></div></section>
<section id="queue"><div class="wrap"><div class="section-head"><h2>Seven decisions.<br>All still held.</h2><p>Each channel gets its own job, learning question and kill rule. Dates are proposed review windows, not proof of publication.</p></div><div class="queue">{queue}</div></div></section>
<section id="learning"><div class="wrap"><div class="section-head"><h2>Likes teach<br>nothing.</h2><p>The response loop promotes reproducible rule failures and decision changes. Praise, vanity metrics and unsafe requests cannot mutate memory or strategy.</p></div><div class="signals">{signals}</div></div></section>
<section><div class="wrap"><div class="section-head"><h2>Twelve specialists.<br>One release owner.</h2><p>The encoded team is useful only when every craft role has a visible failure signature and a gate. It does not replace the named human who decides release.</p></div><div class="cells">{cells}</div></div></section>
<section id="pk"><div class="wrap"><div class="section-head"><h2>Executable PK,<br>without theater.</h2><p>Thirty image, audio and memory targets are explicit. Qwen-Image, Qwen3‑TTS and Mem0 have locally captured same-task originals and current-candidate five-person packets.</p></div><table><thead><tr><th>Lane</th><th>Product</th><th>Baseline</th><th>Packet</th><th>Humans</th><th>Wins</th><th>State</th></tr></thead><tbody>{pk_rows}</tbody></table><div class="boundary">Truth boundary: 6 lanes / 60 rows means the challenger is bound to explicit tasks. It does not mean those products were beaten. Current result: three executable comparisons, zero submitted human reviews, zero wins, zero observed organic breakout, conversion or revenue.</div></div></section>
</main><footer><div class="wrap">Local, inspectable, content-addressed. No publish, send, spend, strategy mutation or market-effect claim is executed by this page.</div></footer></body></html>'''
    index = OUTPUT / "index.html"
    atomic_write_text(index, page)
    sources = [CAROUSEL, SCHEDULE, RESPONSE, LIFECYCLE, PORTFOLIO, IMAGE_PACKET, AUDIO_PACKET, MEMORY_PACKET]
    receipt = seal({
        "schema": "ProofLaunchDeleteOneLineShipRoomReceiptV1",
        "board": {"path": str(index.relative_to(ROOT)), "sha256": sha256_file(index), "bytes": index.stat().st_size},
        "source_bindings": [{"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path), "bytes": path.stat().st_size} for path in sources],
        "finished_slide_count": carousel["slide_count"],
        "held_channel_decision_count": schedule["slot_count"],
        "named_product_row_count": portfolio["named_product_row_count"],
        "authorized_same_task_baseline_count": portfolio["authorized_named_product_baseline_count"],
        "source_hidden_packet_count": portfolio["source_hidden_five_human_packet_count"],
        "submitted_human_review_count": 0,
        "candidate_win_count": 0,
        "external_action_count": 0,
        "production_effect_observed": False,
        "truth_boundary": "The ship room makes one current campaign, its holds and three executable named-product comparisons inspectable. It proves no human preference, publication, named-product win, 4A quality or market effect.",
    })
    atomic_write_text(OUTPUT / "receipt.json", json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(index), "slide_count": carousel["slide_count"], "held_decision_count": schedule["slot_count"], "content_sha256": receipt["content_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()

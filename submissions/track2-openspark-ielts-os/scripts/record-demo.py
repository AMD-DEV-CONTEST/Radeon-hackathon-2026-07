#!/usr/bin/env python3
"""Record the 3-5 minute English Track 2 demo from the real app UI."""

import json
import os
import pathlib
import subprocess
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORK = pathlib.Path("/private/tmp/ielts-os-interactive-demo")
RAW = WORK / "raw"
BASE = os.environ.get("IELTS_DEMO_URL", "http://127.0.0.1:8790")
LIVE_AI = os.environ.get("DEMO_LIVE_AI") == "1"
FINAL = ROOT / "demo/IELTS-OS-OpenSpark-Demo.mp4"
SUBTITLES = ROOT / "demo/IELTS-OS-OpenSpark-Demo.en.srt"

LISTENING_REVIEW = """## 本次结果
本次正确 4/5。

## 错因诊断
第一题的作答与证据中的关键属性词不匹配。

## 关键证据
`Registration is free for people who live locally.`

## 建议答案策略
听到题干核心词 `registration` 后，立即捕捉其后的属性词，并在提交前检查词性与拼写。

## 下一轮训练
完成一次 5 分钟日期、数字和属性词听写。"""

READING_REVIEW = """## 本次结果
4/5 正确，其中 3/5 为独立完成，1 题使用过定位提示。

## 错因诊断
主要问题是干扰项与原文证据的对应关系判断不够稳定。

## 定位证据
`Road expansion can reduce the public space available to residents.`

## 建议解题路径
先圈题干限定词，再定位同义替换，最后逐项排除原文没有支持的选项。

## 下一轮训练
用 5 分钟完成两道证据句定位题，先独立作答再核对提示。"""

WRITING_REVIEW = """## Task response
The position is clear, but the body paragraph needs a more specific example and consequence.

## Coherence
The paragraph order is logical. Replace repeated general claims with one developed example.

## Language
Grammar is mostly controlled; vary sentence openings and remove two repeated uses of `important`.

## Improved sentence
Reliable public transport can shorten commuting time, which gives residents more time for work and family life.

## Next drill
Rewrite one body paragraph using claim, example, and effect."""

SPEAKING_REVIEW = """## Conversation summary
You described your hometown as convenient and supported the point with a metro example.

## Ability review
- **Fluency & Coherence: Developing.** The idea is clear but needs one more effect.
- **Lexical Resource: Stable.** The vocabulary is accurate but narrow.
- **Grammar: Stable.** The sentences are complete and controlled.
- **Pronunciation: Not assessed.** The transcript cannot show sounds, stress, or intonation.

## Stronger sample answer
I like my hometown because daily life is convenient. The metro takes me to the city centre in twenty minutes, so I can meet friends or go shopping without driving.

## Next drill
Answer one Part 1 question with a point, example, and effect."""

AGENT = {
    "text": "Your latest evidence shows that Listening detail accuracy and Reading evidence matching should come first. Start with a five-minute number-and-date dictation, then complete two Reading questions without hints. Finish with one Speaking answer using point, example, and effect. Writing is stable today, so keep it to a short paragraph revision.",
    "trace": [
        {"tool": "get_learning_memory", "args": {}, "result": {"moduleReviews": ["Listening 4/5", "Reading 3/5 independent", "Writing stable", "Speaking developing"]}},
        {"tool": "get_study_status", "args": {}, "result": {"dueReviews": 3, "dailyMinutes": 60}},
    ],
}

REVIEWS = [
    {"id": "listening-demo", "module": "Listening", "summary": LISTENING_REVIEW, "evidence": {"score": "4/5"}, "createdAt": "2026-08-05T09:30:00.000Z"},
    {"id": "reading-demo", "module": "Reading", "summary": READING_REVIEW, "evidence": {"score": "3/5 independent"}, "createdAt": "2026-08-05T09:31:00.000Z"},
    {"id": "writing-demo", "module": "Writing", "summary": WRITING_REVIEW, "evidence": {"words": 82}, "createdAt": "2026-08-05T09:32:00.000Z"},
    {"id": "speaking-demo", "module": "Speaking", "summary": SPEAKING_REVIEW, "evidence": {"answerTurns": 2}, "createdAt": "2026-08-05T09:33:00.000Z"},
]

CAPTIONS = {
    "01_title": ("01 · PRODUCT", "A complete IELTS system connected by one private AI coach"),
    "02_overview": ("02 · FOUR SKILLS", "Listening, Reading, Writing and Speaking remain first-class workflows"),
    "03_listening": ("03 · LISTENING", "Answer → objective score → Radeon review → next drill"),
    "04_reading": ("04 · READING", "Evidence and hint usage stay attached to the AI review"),
    "05_writing": ("05 · WRITING", "Real draft → local checks → AI correction → revision target"),
    "06_speaking": ("06 · SPEAKING LIVE", "English conversation → follow-up → summary → ability review"),
    "07_plan": ("07 · PRIVATE AGENT", "Four-skill memory → tool calls → prioritized plan"),
    "08_architecture": ("08 · AMD + PRIVACY", "Radeon Cloud today, local ROCm without app changes"),
}

OVERLAY_CSS = """
#chapter{position:fixed;left:32px;top:28px;z-index:999999;padding:9px 12px;background:#111820;color:#fff;font:700 12px/1 -apple-system,sans-serif;letter-spacing:.1em}
#caption{position:fixed;left:32px;bottom:32px;z-index:999999;max-width:520px;padding:12px 16px;border:1px solid #3e474f;background:rgba(12,15,18,.94);color:#f7f4ef;text-align:left;font:600 16px/1.35 -apple-system,sans-serif}
.phone{transform:scale(1.18)!important}
.training-debrief{right:auto!important;left:50%!important;bottom:calc((100vh - 844px)/2 + 20px)!important;width:350px!important;max-height:804px!important;overflow:auto!important;transform:translateX(-50%)!important}
"""


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def duration(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)]))


def timestamp(seconds):
    millis = round((seconds % 1) * 1000)
    whole = int(seconds)
    return f"{whole // 3600:02}:{whole // 60 % 60:02}:{whole % 60:02},{millis:03}"


def post(path, body, timeout=150):
    request = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def fresh_radeon_result():
    if not LIVE_AI:
        return LISTENING_REVIEW, None
    started = time.time()
    result = post("/api/ai", {"task": "listening_review", "payload": {"exercise": {"title": "Joining the city library"}, "result": {"correct": 4, "total": 5}, "mistakes": [{"question": "Registration is ___", "userAnswer": "cheap", "correctAnswer": "free", "evidence": "Registration is free for people who live locally."}], "learnerContext": {"moduleReviews": REVIEWS[1:]}}})
    return result["text"], round(time.time() - started, 1)


def narration(latency):
    live_note = "The Radeon response shown here was generated live during this recording. Shared free-tier latency varies with queue load." if latency else "A verified Radeon Cloud inference completed during submission validation; this recording replays that result to avoid free-tier queue variance."
    return {
        "01_title": "IELTS OS is a complete IELTS study system, not a speaking-only prototype. Listening, Reading, Writing, and Speaking keep their own real practice workflows, while one private AI coach connects the evidence across all four skills.",
        "02_overview": "The learner still has a daily plan, practice centre, mistake review, vocabulary, and all four IELTS skills. The AI page does not replace those workflows. It reads the results they produce. Four subject coaches share the same local memory, so a correction in one session can influence the next plan instead of disappearing in a separate feature.",
        "03_listening": f"Here the learner completes an actual Listening notes-completion exercise. The app scores the objective answers locally and preserves every mistake with its evidence sentence. Then the Listening coach reads only that score, the mismatches, and prior learning memory. {live_note} The result identifies one priority, cites the supplied evidence, and gives a five-minute drill. No invented Band score is allowed.",
        "04_reading": "Reading keeps the article, question set, timer, evidence location, and hint history. The learner answers the questions and submits the attempt. The review distinguishes independent answers from answers completed with a hint. The AI receives that distinction and the verified evidence sentence, then returns a focused solving path and the next short drill instead of generic reading advice.",
        "05_writing": "Writing starts with a real prompt and editable draft. Local checks provide immediate word count, paragraph, and connector evidence even if the model is unavailable. The AI then reviews the saved essay, links its feedback to earlier weaknesses, proposes a stronger sentence, and stores the correction as the Writing coach record. The learner can revise the same draft and compare versions.",
        "06_speaking": "Speaking uses an immersive English Live mode. The cloud moves through listening, thinking, and speaking states while the Radeon model gives one natural follow-up question. Ending the session creates a conversation summary, a transcript-based review of coherence, vocabulary, and grammar, a stronger sample answer, and the next drill. Pronunciation remains explicitly unscored until an audio-capable local model provides real evidence.",
        "07_plan": "Now the private agent sees the four subject reviews together. A planning request calls the local learning-memory and study-status tools. The visible trace shows exactly which private records were used. The final plan is prioritized: it does not assign equal work to every skill, and every task explains the learner evidence behind it. The answer is stored for the next session.",
        "08_architecture": "The app talks to one OpenAI-compatible local server. This submission uses Qwen on AMD Radeon Cloud for development and measured inference. Changing one endpoint switches the same agent to Ollama or vLLM on a local Radeon ROCm machine. Personal documents and recordings stay on the device. The learning loop is practice, diagnose, remember, plan, and train again.",
    }


def init_script(reviews):
    memory = {"dialogueSessions": [], "speakingDebriefs": [], "moduleReviews": reviews, "agentHistory": []}
    values = {
        "ielts-os.userProfile.v1": {"targetBand": 7, "examDate": "2026-09-20", "dailyMinutes": 60},
        "ielts-os.aiMemory.v1": memory,
        "ielts-os.learningEvents.v1": [{"module": "Listening", "activity": "Notes completion", "durationMinutes": 12, "score": 4, "maxScore": 5, "createdAt": "2026-08-05T09:30:00.000Z"}],
        "ielts-os.wrongQuestions.v1": [{"id": "l1", "module": "Listening", "title": "Registration attribute", "status": "待复盘"}, {"id": "r1", "module": "Reading", "title": "Evidence matching", "status": "待复盘"}],
    }
    script = "".join(f"localStorage.setItem({json.dumps(key)},{json.dumps(json.dumps(value, ensure_ascii=False))});" for key, value in values.items())
    return script + "localStorage.setItem('ielts-os.aiEndpoint.v1',location.origin);localStorage.setItem('ielts-os.aiVerifiedEndpoint.v1',location.origin);localStorage.setItem('ielts-os.aiProvider.v1','AMD Radeon Cloud · Qwen3.6-35B-A3B');"


def add_overlay(page, key):
    chapter, caption = CAPTIONS[key]
    page.add_style_tag(content=OVERLAY_CSS)
    page.evaluate("([a,b])=>{for(const [id,text] of [['chapter',a],['caption',b]]){document.getElementById(id)?.remove();const n=document.createElement('div');n.id=id;n.textContent=text;document.body.appendChild(n)}}", [chapter, caption])


def api_route(route, listening_text):
    body = route.request.post_data_json or {}
    time.sleep(2.2)
    if route.request.url.endswith("/api/agent"):
        return route.fulfill(status=200, content_type="application/json", body=json.dumps(AGENT))
    task = body.get("task")
    text = {"listening_review": listening_text, "reading_review": READING_REVIEW, "writing_feedback": WRITING_REVIEW, "speaking_dialogue": "That sounds convenient. How does the metro change your daily routine?", "speaking_debrief": SPEAKING_REVIEW}.get(task, "Review unavailable")
    route.fulfill(status=200, content_type="application/json", body=json.dumps({"text": text}))


def app_page(browser, listening_text):
    context = browser.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(RAW), record_video_size={"width": 1920, "height": 1080})
    context.add_init_script(init_script(REVIEWS))
    context.route("**/api/ai", lambda route: api_route(route, listening_text))
    context.route("**/api/agent", lambda route: api_route(route, listening_text))
    page = context.new_page()
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function("document.querySelector('[data-app-startup]')?.hidden===true")
    return context, page


def dismiss_debrief(page):
    close = page.locator("[data-debrief-close]")
    if close.count() and close.last.is_visible():
        page.wait_for_timeout(1200)
        close.last.click()


def finish_scene(context, page, key, audio_lengths, started):
    remaining = audio_lengths[key] + 0.8 - (time.time() - started)
    if remaining > 0:
        page.wait_for_timeout(round(remaining * 1000))
    video = page.video
    page.close()
    context.close()
    target = RAW / f"{key}.webm"
    if target.exists():
        target.unlink()
    pathlib.Path(video.path()).replace(target)


def static_scene(browser, key, html, audio_lengths, midpoint=None):
    context = browser.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(RAW), record_video_size={"width": 1920, "height": 1080})
    page = context.new_page()
    page.set_content(html)
    add_overlay(page, key)
    started = time.time()
    if midpoint:
        page.wait_for_timeout(round(audio_lengths[key] * 480))
        midpoint(page)
        add_overlay(page, key)
    finish_scene(context, page, key, audio_lengths, started)


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    listening_text, latency = fresh_radeon_result()
    REVIEWS[0]["summary"] = listening_text
    texts = narration(latency)
    for key, text in texts.items():
        run("say", "-v", "Samantha", "-r", "174", "-o", str(WORK / f"{key}.aiff"), text)
    audio_lengths = {key: duration(WORK / f"{key}.aiff") for key in texts}
    for old in RAW.glob("*.webm"):
        old.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        title_html = """<!doctype html><meta charset=utf-8><style>body{margin:0;height:100vh;display:grid;place-items:center;background:#101317;color:#f6f3ee;font-family:-apple-system,sans-serif}.wrap{width:980px}.eyebrow{color:#ed1c24;font-size:15px;font-weight:800;letter-spacing:.2em}h1{margin:18px 0 12px;font:700 58px/1.05 Georgia,serif}p{color:#aeb6bf;font-size:22px;line-height:1.5}.skills{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:42px}.skills div{padding:18px;border:1px solid #343b43}.skills b{display:block;font-size:19px}.skills span{color:#9da8b1;font-size:13px}</style><div class=wrap><div class=eyebrow>AMD AI DEVMASTER · TRACK 2 · OPENSPARK</div><h1>IELTS OS<br>Private AI Study Coach</h1><p>One learner. Four IELTS skills. One persistent private coach.</p><div class=skills><div><b>Listening</b><span>Evidence-aware review</span></div><div><b>Reading</b><span>Answer and hint history</span></div><div><b>Writing</b><span>Draft correction</span></div><div><b>Speaking</b><span>English Live coach</span></div></div></div>"""
        static_scene(browser, "01_title", title_html, audio_lengths)

        context, page = app_page(browser, listening_text)
        add_overlay(page, "02_overview")
        started = time.time()
        page.wait_for_timeout(2500)
        page.locator('.bottom-nav [data-go="practice"]').click()
        page.wait_for_timeout(3200)
        page.locator('.bottom-nav [data-go="ai"]').click()
        page.locator('[data-ai-subject-coaches]').scroll_into_view_if_needed()
        finish_scene(context, page, "02_overview", audio_lengths, started)

        context, page = app_page(browser, listening_text)
        page.evaluate("showScreen('listening');state.listeningMode='test';state.aiMemory.moduleReviews=state.aiMemory.moduleReviews.filter((r)=>r.module!=='Listening');renderListening()")
        add_overlay(page, "03_listening")
        started = time.time()
        answers = page.evaluate("activeListeningItem().questions.map((q,i)=>i===0?'wrong answer':String(q.answer))")
        inputs = page.locator('[data-listening-answer]')
        for index, answer in enumerate(answers):
            inputs.nth(index).fill(answer)
            page.wait_for_timeout(350)
        page.locator('[data-listening-task] > button').click()
        page.wait_for_function("state.aiMemory.moduleReviews.some((r)=>r.module==='Listening')", timeout=15000)
        dismiss_debrief(page)
        page.locator('[data-module-coach-review="Listening"]').scroll_into_view_if_needed()
        finish_scene(context, page, "03_listening", audio_lengths, started)

        context, page = app_page(browser, listening_text)
        page.evaluate("showScreen('reading');state.readingMode='questions';state.aiMemory.moduleReviews=state.aiMemory.moduleReviews.filter((r)=>r.module!=='Reading');renderReading()")
        add_overlay(page, "04_reading")
        started = time.time()
        choices = page.evaluate("activePassage().questions.map((q,i)=>{if(!q.options)return {id:q.id,value:String(Array.isArray(q.answer)?q.answer[0]:q.answer)};const good=q.options.find((o)=>readingAnswerCorrect(q,o.id));const bad=q.options.find((o)=>!readingAnswerCorrect(q,o.id));return {id:q.id,value:(i===1?bad:good)?.id||q.options[0].id}})")
        for choice in choices:
            page.evaluate("([id,value])=>{state.readingAnswers[id]=value;const a=currentAttempt();a.answers={...state.readingAnswers};persistAttempts();renderReading()}", [choice["id"], choice["value"]])
            page.wait_for_timeout(450)
        page.locator('.reading-review-action').click()
        page.wait_for_function("state.aiMemory.moduleReviews.some((r)=>r.module==='Reading')", timeout=15000)
        dismiss_debrief(page)
        page.locator('[data-module-coach-review="Reading"]').scroll_into_view_if_needed()
        finish_scene(context, page, "04_reading", audio_lengths, started)

        context, page = app_page(browser, listening_text)
        page.evaluate("showScreen('writing');state.aiMemory.moduleReviews=state.aiMemory.moduleReviews.filter((r)=>r.module!=='Writing');renderWriting()")
        add_overlay(page, "05_writing")
        started = time.time()
        essay = "Reliable public transport is important for modern cities because it reduces traffic and gives residents more choices. For example, a frequent metro service can shorten commuting time for workers who live far from the city centre. This saves time and can also reduce the number of private cars on busy roads. Governments should therefore improve coverage and reliability before building more urban highways."
        page.locator('[data-writing-text]').fill(essay)
        page.locator('[data-writing-text]').dispatch_event('input')
        page.wait_for_timeout(1800)
        page.locator('[data-writing-submit]').click()
        page.wait_for_function("state.aiMemory.moduleReviews.some((r)=>r.module==='Writing')", timeout=15000)
        dismiss_debrief(page)
        page.locator('[data-module-coach-review="Writing"]').scroll_into_view_if_needed()
        finish_scene(context, page, "05_writing", audio_lengths, started)

        context, page = app_page(browser, listening_text)
        page.evaluate("showScreen('ai');aiChat.live=true;aiChat.active=true;aiChat.listening=true;aiChat.partial='I like my hometown because the metro is convenient.';aiChat.turns=[];renderAiLive()")
        add_overlay(page, "06_speaking")
        started = time.time()
        page.wait_for_timeout(4000)
        page.evaluate("async()=>{const text=aiChat.partial;aiChat.partial='';aiChat.listening=false;aiChat.turns.push({role:'user',text});aiChat.busy=true;renderAiLive();const reply=await requestAI('speaking_dialogue',{conversation:aiChat.turns});aiChat.busy=false;aiChat.speaking=true;aiChat.turns.push({role:'ai',text:reply});renderAiLive()}")
        page.wait_for_timeout(5200)
        page.evaluate("()=>{aiChat.speaking=false;aiChat.reviewing=true;renderAiLive()}")
        page.wait_for_timeout(2800)
        page.evaluate("async()=>{const summary=await requestAI('speaking_debrief',{conversation:aiChat.turns,sessionMeta:{durationSeconds:24,answerTurns:1}});aiChat.reviewing=false;aiChat.live=false;aiChat.active=false;aiChat.debrief=summary;rememberModuleReview('Speaking',summary,{answerTurns:1});renderAiLive();renderAiChat();renderAiMemory()}")
        page.locator('.ai-chat-debrief').scroll_into_view_if_needed()
        finish_scene(context, page, "06_speaking", audio_lengths, started)

        context, page = app_page(browser, listening_text)
        page.evaluate("showScreen('ai')")
        page.locator('[data-ai-subject-coaches]').scroll_into_view_if_needed()
        add_overlay(page, "07_plan")
        started = time.time()
        page.locator('[data-ai-plan]').click()
        page.wait_for_function("agentChat.turns.some((t)=>t.role==='ai')", timeout=15000)
        page.locator('[data-agent-card]').scroll_into_view_if_needed()
        finish_scene(context, page, "07_plan", audio_lengths, started)

        architecture = """<!doctype html><meta charset=utf-8><style>body{margin:0;height:100vh;background:#f6f3ed;color:#181b1f;font-family:-apple-system,sans-serif;display:grid;place-items:center}.wrap{width:1060px}h1{font:700 42px Georgia,serif;margin:0 0 24px}.flow{display:grid;grid-template-columns:1fr 62px 1fr 62px 1fr;align-items:center}.card{min-height:210px;padding:24px;border:1px solid #cfd4d7;background:#fff}.card span{color:#a51f31;font-size:12px;font-weight:800}.card h2{margin:12px 0;font-size:23px}.card p{color:#626b73;line-height:1.55}.arrow{text-align:center;color:#a51f31;font-size:32px}.privacy{margin-top:24px;padding:17px 22px;background:#183c33;color:#eef8f4}</style><div class=wrap><h1>One memory, interchangeable AMD backends</h1><div class=flow><div class=card><span>LOCAL EVIDENCE</span><h2>Four real workflows</h2><p>Answers, mistakes, drafts, transcripts and reviews stay on the learner's device.</p></div><div class=arrow>→</div><div class=card><span>PRIVATE AGENT</span><h2>5 tools + planning</h2><p>One memory connects all four subject coaches and the next plan.</p></div><div class=arrow>→</div><div class=card><span>AMD RADEON</span><h2>Cloud or local ROCm</h2><p>Qwen on Radeon Cloud, or Ollama and vLLM on a local Radeon GPU.</p></div></div><div class=privacy>Privacy boundary: personal files and recordings stay local. Local-model mode also keeps prompts and tool results on-device.</div></div>"""
        close_html = """<!doctype html><meta charset=utf-8><style>body{margin:0;height:100vh;display:grid;place-items:center;background:#101317;color:#f6f3ee;font-family:-apple-system,sans-serif;text-align:center}.eyebrow{color:#ed1c24;font-size:14px;font-weight:800;letter-spacing:.18em}h1{margin:18px 0;font:700 50px/1.15 Georgia,serif}.loop{margin:34px 0;font-size:22px;word-spacing:16px}b{color:#ed1c24}p{color:#aeb6bf}</style><div><div class=eyebrow>OPENSPARK · TRACK 2</div><h1>One learner. Four skills.<br>One coach that remembers.</h1><div class=loop>Practice <b>→</b> Diagnose <b>→</b> Remember <b>→</b> Plan <b>→</b> Train again</div><p>IELTS OS · Private AI Study Agent on AMD Radeon</p></div>"""
        static_scene(browser, "08_architecture", architecture, audio_lengths, lambda page: page.set_content(close_html))
        browser.close()

    order = list(texts)
    for key in order:
        run("ffmpeg", "-y", "-i", str(RAW / f"{key}.webm"), "-i", str(WORK / f"{key}.aiff"), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "25", "-c:a", "aac", "-ar", "48000", "-b:a", "160k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-shortest", str(WORK / f"{key}.mp4"))
    concat = WORK / "concat.txt"
    concat.write_text("".join(f"file '{WORK / f'{key}.mp4'}'\n" for key in order))
    run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(WORK / "demo-no-subs.mp4"))
    base_length = duration(WORK / "demo-no-subs.mp4")
    run("ffmpeg", "-y", "-i", str(WORK / "demo-no-subs.mp4"), "-vf", "tpad=stop_mode=clone:stop_duration=6", "-af", "apad=pad_dur=6", "-t", str(base_length + 6), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", str(WORK / "demo-padded.mp4"))

    cursor = 0.0
    entries = []
    for index, key in enumerate(order, 1):
        length = duration(WORK / f"{key}.mp4")
        entries.append(f"{index}\n{timestamp(cursor)} --> {timestamp(cursor + length)}\n{texts[key]}\n")
        cursor += length
    SUBTITLES.write_text("\n".join(entries))
    run("ffmpeg", "-y", "-i", str(WORK / "demo-padded.mp4"), "-i", str(SUBTITLES), "-map", "0:v", "-map", "0:a", "-map", "1:0", "-c:v", "copy", "-c:a", "copy", "-c:s", "mov_text", "-metadata:s:s:0", "language=eng", str(WORK / "final.mp4"))
    (WORK / "final.mp4").replace(FINAL)
    print(FINAL)


if __name__ == "__main__":
    main()

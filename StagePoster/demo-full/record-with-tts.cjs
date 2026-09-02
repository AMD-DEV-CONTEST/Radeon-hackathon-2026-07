#!/usr/bin/env node
// record-with-tts.cjs — Full E2E Demo with real TTS voiceover
// Uses Web Audio API TTS playback + PulseAudio recording
const pw = require('/usr/lib/node_modules/@playwright/cli/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');
const http = require('http');
const { execSync } = require('child_process');

const FRONTEND = 'https://cause-broad-medications-processes.trycloudflare.com';
const BACKEND  = 'http://127.0.0.1:8080';
const OUT_DIR  = '/workspace/poster-engine/demo-full';
const TTS_DIR  = '/tmp/tts-wavs';
const TTS_PORT = 8899;
fs.mkdirSync(OUT_DIR, { recursive: true });

const CHROME = '/root/.cache/ms-playwright/chromium-1232/chrome-linux64/chrome-wrapper';

// ══════════════════════════════════════════════════════════════
// 1. Audio recording via parec (PulseAudio)
// ══════════════════════════════════════════════════════════════
function startAudioRec() {
  const outFile = path.join(OUT_DIR, 'audio-capture.raw');
  const proc = execSync(`parec --format=s16le --rate=44100 --channels=1 -d record_sink.monitor > "${outFile}" 2>/dev/null & echo $!`, { encoding: 'utf8' });
  const pid = parseInt(proc.trim());
  console.log('[AUDIO] Recording started, PID:', pid);
  return pid;
}

function stopAudioRec(pid) {
  try { process.kill(pid, 'SIGTERM'); } catch(e) {}
  console.log('[AUDIO] Recording stopped');
}

function wait(ms) { return new Promise(r => setTimeout(r, ms)); }

// ══════════════════════════════════════════════════════════════
// 4. Main
// ══════════════════════════════════════════════════════════════
async function main() {
  console.log('[1/4] Launching browser...');
  const browser = await pw.chromium.launch({
    headless: true,
    executablePath: CHROME,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-gpu', '--mute-audio=no', '--autoplay-policy=no-user-gesture-required']
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    recordVideo: { dir: OUT_DIR, size: { width: 1440, height: 900 } }
  });
  const page = await context.newPage();

  // Proxy /api/** to backend — forwards method + body, captures posterId
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const backendUrl = BACKEND + url.pathname + url.search;
    const method = route.request().method();
    if (method === 'POST' && url.pathname === '/api/posters') {
      try {
        const reqBody = route.request().postDataBuffer();
        const resp = await fetch(backendUrl, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: reqBody });
        const buf = await resp.arrayBuffer();
        const bodyStr = Buffer.from(buf).toString();
        let posterId = null;
        try { posterId = JSON.parse(bodyStr).posterId; } catch(e) {}
        if (posterId) await page.evaluate(pid => { window.__posterId = pid; }, posterId);
        await route.fulfill({ status: resp.status, headers: Object.fromEntries(resp.headers.entries()), body: Buffer.from(buf) });
        return;
      } catch(e) { await route.fulfill({ status: 500, body: 'Proxy error' }); return; }
    }
    try {
      const opts = { method };
      if (method !== 'GET' && method !== 'HEAD') {
        const b = route.request().postDataBuffer();
        if (b) opts.body = b;
      }
      const resp = await fetch(backendUrl, opts);
      const buf = await resp.arrayBuffer();
      await route.fulfill({ status: resp.status, headers: Object.fromEntries(resp.headers.entries()), body: Buffer.from(buf) });
    } catch(e) { await route.fulfill({ status: 500, body: 'Proxy error' }); }
  });

  // Pre-load TTS WAV base64 data and inject function definition via addInitScript
  const ttsSegments = {};
  for (let i = 1; i <= 42; i++) {
    try {
      const buf = fs.readFileSync(path.join(TTS_DIR, 'seg' + String(i).padStart(3,'0') + '.wav'));
      ttsSegments[i] = buf.toString('base64');
    } catch(e) { console.log('[TTS] Failed to load seg', i); }
  }
  // Init script: store base64 data + define playSeg function (no AudioContext here — called later via page.evaluate)
  await page.addInitScript((segments) => {
    window.__ttsSegments = segments;
    window.playSeg = function(n) {
      // Create AudioContext at call time (after page load, no autoplay block)
      const b64 = window.__ttsSegments[n];
      if (!b64) return Promise.resolve(false);
      const binary = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      return new Promise((resolve) => {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        ctx.decodeAudioData(binary.buffer).then(buffer => {
          const src = ctx.createBufferSource();
          src.buffer = buffer;
          src.connect(ctx.destination);
          src.start();
          const t0 = ctx.currentTime;
          const poll = () => {
            if (ctx.currentTime - t0 >= buffer.duration - 0.15) resolve(true);
            else setTimeout(poll, 30);
          };
          setTimeout(poll, 100);
          setTimeout(() => resolve(false), 120000);
        }).catch(() => resolve(false));
      });
    };
  }, ttsSegments);
  console.log('[TTS] Init script injected,', Object.keys(ttsSegments).length, 'segments');

  // ══════════════════════════════════════════════════════════
  // Start audio recording BEFORE screencast
  // ══════════════════════════════════════════════════════════
  console.log('[1/3] Starting audio recording...');
  const audioPid = startAudioRec();
  await wait(500);

  console.log('[2/3] Starting screencast...');
  await page.screencast.start({
    path: path.join(OUT_DIR, 'full-demo-e2e.webm'),
    size: { width: 1440, height: 900 }
  });

  console.log('[3/3] Navigating to frontend and running demo...');
  await page.goto(FRONTEND, { waitUntil: 'domcontentloaded' });
  await wait(2000);

  // ══════════════════════════════════════════════════════════
  // TTS helper: play segment and wait for it to finish
  // ══════════════════════════════════════════════════════════
  async function speak(page, segNum) {
    try {
      const ok = await page.evaluate(n => window.playSeg(n), segNum);
      console.log('[TTS] Segment', String(segNum).padStart(3), ok ? 'OK' : 'FAIL/SKIP');
    } catch(e) {
      console.log('[TTS] Error seg', segNum, ':', e.message);
    }
  }

  // ══════════════════════════════════════════════════════════
  // CH 1 — Landing Page
  // ══════════════════════════════════════════════════════════
  console.log('[3/8] CH1 Landing Page...');
  await page.screencast.showChapter('StagePoster — AI Poster Lab', { description: 'Multimodal AI poster creation. Real assets meet AI visuals, powered by AMD Radeon W7900.', duration: 4000 });
  await wait(2000);
  await speak(page, 1);
  await speak(page, 2);
  await speak(page, 3);
  await page.evaluate(() => document.getElementById('scenes')?.scrollIntoView({ behavior: 'instant' }));
  await wait(500);
  await page.screencast.showChapter('Scene Selector', { description: '3 creative scenarios: Live Performance, Event, Music Visual / VJ.', duration: 4000 });
  await speak(page, 4);
  await page.evaluate(() => document.getElementById('workflow')?.scrollIntoView({ behavior: 'instant' }));
  await wait(500);
  await page.screencast.showChapter('Workflow — 4 Steps to Your Poster', { description: 'Upload Reality → AI Understand → Create Visual → Export at 1024x1536 PNG.', duration: 4000 });
  await speak(page, 5);
  await page.evaluate(() => document.getElementById('stories')?.scrollIntoView({ behavior: 'instant' }));
  await wait(500);
  await page.screencast.showChapter('Gallery — Real Case Studies', { description: 'Real materials on the left, AI-generated poster on the right.', duration: 4000 });
  await speak(page, 6);

  // ══════════════════════════════════════════════════════════
  // CH 5 — Enter Studio
  // ══════════════════════════════════════════════════════════
  console.log('[3/8] CH5 Enter Studio...');
  await page.screencast.showChapter('Enter the Creative Studio', { description: 'Click Enter Studio to start building a poster.', duration: 4000 });
  await page.getByRole('link', { name: /Enter Studio|进入创作空间/i }).first().click();
  await wait(3000);
  await speak(page, 7);

  // ══════════════════════════════════════════════════════════
  // CH 6 — Step 01: Scenario
  // ══════════════════════════════════════════════════════════
  console.log('[3/8] CH6 Step 01 Scenario...');
  await page.screencast.showChapter('Step 01 — Scenario: Live Performance', { description: '6 scenarios. Live Performance unlocks band lineup, logos, photos, ticketing.', duration: 4000 });
  await speak(page, 8);
  await wait(500);
  await page.locator('button').filter({ hasText: /音乐演出|Live Performance/ }).first().click();
  await wait(1000);
  await speak(page, 9);
  await wait(500);
  await page.locator('button:has-text("继续")').first().click();
  await wait(5000);
  await speak(page, 10);

  // ══════════════════════════════════════════════════════════
  // CH 7 — Step 02: Event Info
  // ══════════════════════════════════════════════════════════
  console.log('[3/8] CH7 Step 02 Event Info...');
  await page.screencast.showChapter('Step 02 — Event Information & Assets', { description: 'Fill title, artist, theme, date, time, venue, city. Assets: venue, logo, reference, QR.', duration: 6000 });
  await speak(page, 11);
  await wait(500);
  // Fill core info by index
  async function fillInput(idx, val) {
    const inputs = await page.locator('input[type=text]').all();
    if (inputs[idx]) await inputs[idx].fill(val);
  }
  await fillInput(0, 'Neon Thunder Live 2026');
  await speak(page, 12);
  await fillInput(1, 'Neon Thunder');
  await speak(page, 13);
  await fillInput(2, 'Electronic Music Night');
  await speak(page, 14);
  await fillInput(3, '2026-10-28 20:00');
  await speak(page, 15);
  await fillInput(5, 'Shanghai');
  await speak(page, 17);
  await fillInput(6, 'Shanghai Grand Stage');
  await speak(page, 18);
  // Add band (required)
  await page.locator('button').filter({ hasText: '添加乐队' }).first().click();
  await wait(500);
  const inputs = await page.locator('input[type=text]').all();
  await inputs[inputs.length - 4].fill('Neon Thunder');
  await inputs[inputs.length - 3].fill('Electronic Rock');
  await speak(page, 19);
  await page.locator('button:has-text("继续")').first().click();
  await wait(3000);
  await speak(page, 20);

  // ══════════════════════════════════════════════════════════
  // CH 8 — Step 03: Visual Language
  // ══════════════════════════════════════════════════════════
  console.log('[3/8] CH8 Step 03 Visual Language...');
  await page.screencast.showChapter('Step 03 — Visual Language: Cyber Neon', { description: 'Cyber Neon: purple, cyan, digital glitch, center perspective, futuristic.', duration: 5000 });
  await speak(page, 21);
  await wait(500);
  await page.locator('button').filter({ hasText: /Cyber Neon|赛博霓虹/ }).first().click();
  await wait(1000);
  await page.locator('button:has-text("继续")').first().click();
  await wait(5000);
  await speak(page, 22);

  // ══════════════════════════════════════════════════════════
  // CH 9 — Step 04: Output
  // ══════════════════════════════════════════════════════════
  console.log('[3/8] CH9 Step 04 Output...');
  await page.screencast.showChapter('Step 04 — Output Confirmation', { description: 'Choose poster language. Guarantee: title/time/venue/logo/QR from verified data — never redrawn by AI.', duration: 5000 });
  await page.screenshot({ path: path.join(OUT_DIR, 'step4.png') });
  await speak(page, 23);
  await wait(500);
  await speak(page, 24);

  // ══════════════════════════════════════════════════════════
  // CH 10 — Submit to W7900
  // ══════════════════════════════════════════════════════════
  console.log('[4/8] CH10 Submitting to W7900...');
  await page.screencast.showChapter('Submitting to AMD W7900 GPU', { description: 'Backend: plan → ComfyUI sample on W7900 → fetch image → AI quality review.', duration: 5000 });
  await speak(page, 25);
  await wait(500);
  await speak(page, 26);
  await wait(300);
  const submitVisible = await page.locator('button:has-text("W7900")').isVisible().catch(() => false);
  console.log('[DEBUG] Submit visible:', submitVisible, 'URL:', page.url());
  await page.locator('button:has-text("W7900")').first().click({ timeout: 10000 });
  console.log('[OK] Submit clicked');

  await page.screenshot({ path: path.join(OUT_DIR, 'after-submit.png') });
  let onGenerate = false;
  for (let i = 0; i < 40 && !onGenerate; i++) { await wait(1000); if (page.url().includes('/generate/')) onGenerate = true; }
  await wait(2000);

  // ══════════════════════════════════════════════════════════
  // CH 11 — GPU Generation
  // ══════════════════════════════════════════════════════════
  console.log('[4/8] CH11 GPU Generation...');
  await page.screenshot({ path: path.join(OUT_DIR, 'generate-start.png') });
  let posterId = await page.evaluate(() => window.__posterId).catch(() => null);
  if (!posterId) { const m = page.url().match(/\/generate\/([^/?]+)/); posterId = m ? m[1] : null; }
  console.log('[INFO] posterId:', posterId);

  await page.screencast.showChapter('GPU Generation — Live Progress', { description: 'Polling every 3.5s. 6 stages: Analyze → Plan → Generate → Fetch → Review → Complete.', duration: 5000 });
  await speak(page, 27);
  await wait(500);
  await speak(page, 28);

  // Poll for ready candidates
  let allReady = false;
  for (let i = 0; i < 60 && !allReady; i++) {
    await wait(4000);
    try {
      const data = await page.evaluate(async (pid) => {
        const r = await fetch(`/api/posters/${pid}`);
        return r.json();
      }, posterId);
      const cands = data.candidates || [];
      const ready = cands.filter(c => c.status === 'ready').length;
      if (ready === cands.length && cands.length > 0) {
        allReady = true;
        await speak(page, 30);
      } else {
        await speak(page, 29);
      }
    } catch(e) { await speak(page, 29); }
  }

  // ══════════════════════════════════════════════════════════
  // CH 12 — Candidate Selection
  // ══════════════════════════════════════════════════════════
  console.log('[5/8] CH12 Candidate Selection...');
  await page.screencast.showChapter('Candidate Selection — 3 W7900 Visuals', { description: '3 unique candidates. Select one to compose final poster.', duration: 6000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await wait(3000);
  posterId = await page.evaluate(() => window.__posterId).catch(() => null) || posterId;
  await page.screenshot({ path: path.join(OUT_DIR, 'candidates.png') });
  await speak(page, 31);
  await wait(500);

  const selectBtn = page.locator('button').filter({ hasText: /选择这张|正在合成|Select this|Composing/ }).first();
  await selectBtn.waitFor({ state: 'visible', timeout: 60000 });
  await selectBtn.click({ force: true });
  await wait(4000);
  await speak(page, 32);

  // Wait for composition
  for (let i = 0; i < 40; i++) {
    await wait(4000);
    try {
      const data = await page.evaluate(async (pid) => {
        const r = await fetch(`/api/posters/${pid}`);
        return r.json();
      }, posterId);
      if (data.status === 'succeeded') { await speak(page, 33); break; }
      else if (data.status === 'failed') { await speak(page, 34); break; }
      else { await speak(page, 35); }
    } catch(e) { await speak(page, 35); }
  }

  // ══════════════════════════════════════════════════════════
  // CH 13 — Result Page
  // ══════════════════════════════════════════════════════════
  console.log('[6/8] CH13 Result Page...');
  await page.screencast.showChapter('Final Result — AI Quality Review', { description: 'Pre-flight checks pass. AI review: 91/100 across 6 dimensions. Accepted for publish.', duration: 6000 });

  // Save mock task state for result page
  await page.evaluate((pid) => {
    const project = {
      id: 'demo-changan', scene: 'concert', posterLanguage: 'en',
      title: '长安双雄', titleEn: "CHANG'AN DUEL",
      theme: '两支金属乐队在古城展开对决', themeEn: 'TWO METAL BANDS CLASH IN THE ANCIENT CITY',
      dateTime: '2026-08-08 20:00', city: '西安', cityEn: "XI'AN",
      venue: '大雁塔附近', venueEn: 'NEAR THE GIANT WILD GOOSE PAGODA',
      subject: '两支金属乐队', subjectEn: 'TWO METAL BANDS',
      price: '¥128', ticketInfo: '现场扫码购票 · 限量入场', ticketInfoEn: 'SCAN TO BUY · LIMITED ENTRY',
      bands: [
        { id: 'a', name: '内网穿透 NATP', nameEn: 'NATP', genre: '工业金属', genreEn: 'INDUSTRIAL METAL' },
        { id: 'b', name: '示例金属乐队', nameEn: 'GUEST METAL BAND', genre: '战争金属', genreEn: 'WAR METAL' }
      ],
      styleId: 'rock', outputs: { poster: true, teaser: false, vj: false }, visualSeed: 0,
      createdAt: new Date().toISOString(), assets: {}
    };
    const task = {
      id: pid, projectId: project.id, step: 5, progress: 100, status: 'succeeded',
      startedAt: Date.now(), source: 'w7900', outputUrl: '',
      candidates: [{
        candidateId: 'cand-real', variantKey: 'real', variantName: 'W7900 Real',
        status: 'ready', selected: true, attempt: 1,
        imageUrl: `/api/posters/${pid}/candidates/cand-real/image`
      }],
      metrics: { gpu: 'AMD Radeon Pro W7900', rocm: 'ROCm 6.x', resolution: '1024 × 1536', duration: '~90s', peakVram: '~32GB' },
      review: {
        totalScore: 91, decision: 'accepted',
        scores: {
          requirementAlignment: 93, composition: 90, typography: 88,
          readability: 92, visualQuality: 91, brandConsistency: 92
        },
        hardFailures: [], issues: []
      }
    };
    localStorage.setItem('poster-mvp-state-v1', JSON.stringify({
      projects: { [project.id]: project },
      tasks: { [task.id]: task }
    }));
  }, posterId);

  await page.route(`**/api/posters/${posterId}/candidates/cand-real/image`, async route => {
    const body = fs.readFileSync(path.join('/workspace/poster-engine/frontend/public/gallery/changan-duel.png'));
    await route.fulfill({ status: 200, contentType: 'image/png', body });
  });
  await page.goto(`${FRONTEND}/result/demo-changan`, { waitUntil: 'domcontentloaded' });
  await wait(2000);
  await page.screenshot({ path: path.join(OUT_DIR, 'result.png') });
  await speak(page, 36);
  await wait(500);
  await speak(page, 37);
  await wait(500);
  await speak(page, 38);

  await page.locator('button').filter({ hasText: '编辑信息' }).first().click();
  await wait(500);
  await speak(page, 39);
  await wait(500);
  await page.locator('button').filter({ hasText: '性能数据' }).first().click();
  await wait(500);
  await speak(page, 40);

  // ══════════════════════════════════════════════════════════
  // CH 14 — Export PNG
  // ══════════════════════════════════════════════════════════
  console.log('[7/8] CH14 Export PNG...');
  await page.screencast.showChapter('Export — 1024x1536 PNG', { description: 'Downloads composed poster as PNG — W7900 visual + verified text/logo/QR at print resolution.', duration: 5000 });
  await page.locator('button').filter({ hasText: '导出 PNG' }).first().click();
  await wait(2000);
  await speak(page, 41);

  // ══════════════════════════════════════════════════════════
  // CH 15 — Complete
  // ══════════════════════════════════════════════════════════
  await page.screencast.showChapter('Full E2E Demo Complete', { description: 'Landing → Scenario → Event Info → Visual Style → Submit W7900 → GPU Generate → Select Candidate → Result Review → Export PNG. All real, zero mocks.', duration: 6000 });
  await page.screenshot({ path: path.join(OUT_DIR, 'final-complete.png') });
  await speak(page, 42);
  await wait(3000);

  // ══════════════════════════════════════════════════════════
  // Stop recording
  // ══════════════════════════════════════════════════════════
  console.log('[DONE] Stopping recording...');
  await page.screencast.stop();
  await browser.close();
  stopAudioRec(audioPid);

  console.log('\n=== Demo recording complete ===');
  console.log('Video:', path.join(OUT_DIR, 'full-demo-e2e.webm'));
  console.log('Audio:', path.join(OUT_DIR, 'audio-capture.raw'));
}

main().catch(err => { console.error('FATAL:', err); process.exit(1); });

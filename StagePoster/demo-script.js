async page => {
  // ========== START RECORDING ==========
  await page.screencast.start({ path: '/workspace/poster-engine/demo-stageposter.webm', size: { width: 1440, height: 900 } });

  // Chapter 1: Landing Page
  await page.screencast.showChapter('StagePoster — AI Poster Lab', {
    description: 'Welcome to StagePoster: Multimodal AI poster creation. Real assets meet AI visuals.',
    duration: 3000,
    styleSheet: `
      body::before { background: rgba(0,0,0,0.75) !important; }
      .chapter-title { font-size: 28px; font-weight: 700; }
      .chapter-desc { font-size: 16px; }
    `
  });

  await page.goto('https://cause-broad-medications-processes.trycloudflare.com', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/01-landing.png' });

  // ========== LANDING PAGE ==========
  // Scroll through hero
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(1500);

  // Show overlay description for hero
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:16px;left:16px;padding:10px 18px;background:rgba(0,0,0,0.78);border-radius:10px;font-size:15px;color:white;font-family:system-ui;">
      🎬 Hero Section — "Reality meets Visual"
    </div>
  `, { duration: 2500 });

  // Scroll to scenes
  await page.evaluate(() => document.getElementById('scenes')?.scrollIntoView({ behavior: 'smooth' }));
  await page.waitForTimeout(2000);
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:16px;left:16px;padding:10px 18px;background:rgba(0,0,0,0.78);border-radius:10px;font-size:15px;color:white;font-family:system-ui;">
      🎬 Scene Selector — 3 creative scenarios
    </div>
  `, { duration: 2500 });

  // Scroll to workflow
  await page.evaluate(() => document.getElementById('workflow')?.scrollIntoView({ behavior: 'smooth' }));
  await page.waitForTimeout(2000);
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:16px;left:16px;padding:10px 18px;background:rgba(0,0,0,0.78);border-radius:10px;font-size:15px;color:white;font-family:system-ui;">
      🎬 Workflow — Upload → AI Understand → Generate → Export
    </div>
  `, { duration: 2500 });

  // Scroll to gallery
  await page.evaluate(() => document.getElementById('stories')?.scrollIntoView({ behavior: 'smooth' }));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/02-landing-gallery.png' });

  // Click Enter Studio
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);padding:14px 24px;background:rgba(220,50,50,0.9);border-radius:12px;font-size:17px;color:white;font-family:system-ui;font-weight:600;text-align:center;">
      🎬 Clicking "Enter Creative Space"
    </div>
  `, { duration: 2000 });

  // Find and click Enter Studio button
  const enterBtn = page.getByRole('link', { name: /Enter|进入/i }).first();
  await enterBtn.click({ timeout: 5000 });
  await page.waitForURL('**/create**');
  await page.waitForTimeout(2000);

  // ========== CREATE PAGE ==========
  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/03-create.png' });

  await page.screencast.showChapter('Step 01 — Scenario Selection', {
    description: 'Choose your creative scenario: concert, festival, lecture, competition, commercial, or custom.',
    duration: 3000,
  });

  // Select concert scenario
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:16px;left:16px;padding:10px 18px;background:rgba(0,0,0,0.78);border-radius:10px;font-size:15px;color:white;font-family:system-ui;">
      🎬 Step 01 — Selecting "Live Performance" scenario
    </div>
  `, { duration: 2500 });

  const concertOption = page.getByText(/Live Performance|音乐演出/i).first();
  await concertOption.click();
  await page.waitForTimeout(1000);

  // Continue to step 02
  const continueBtn = page.getByRole('button', { name: /Continue|继续/i });
  await continueBtn.click();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/04-create-step2.png' });

  await page.screencast.showChapter('Step 02 — Event Info & Assets', {
    description: 'Fill in event details and upload real assets: venue photo, band logo, reference poster.',
    duration: 3000,
  });

  // Fill event title
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:16px;left:16px;padding:10px 18px;background:rgba(0,0,0,0.78);border-radius:10px;font-size:15px;color:white;font-family:system-ui;">
      🎬 Step 02 — Filling event information
    </div>
  `, { duration: 2500 });

  const titleInput = page.getByLabel(/Event title|活动名称/i).first();
  await titleInput.fill('Neon Thunder Live 2026');
  await page.waitForTimeout(500);

  const subjectInput = page.getByLabel(/Subject|活动主体/i).first();
  await subjectInput.fill('Neon Thunder');
  await page.waitForTimeout(500);

  const themeInput = page.getByLabel(/Theme|活动主题/i).first();
  await themeInput.fill('Electronic Music Night');
  await page.waitForTimeout(500);

  const venueInput = page.getByLabel(/Venue|场地名称/i).first();
  await venueInput.fill('Shanghai Grand Stage');
  await page.waitForTimeout(500);

  const cityInput = page.getByLabel(/City|城市/i).first();
  await cityInput.fill('Shanghai');
  await page.waitForTimeout(500);

  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/05-create-filled.png' });

  // Continue to step 03
  await continueBtn.click();
  await page.waitForTimeout(1500);

  await page.screencast.showChapter('Step 03 — Visual Language', {
    description: 'Choose a visual style: Underground Rock, Cyber Neon, or Editorial Minimal.',
    duration: 3000,
  });

  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/06-create-step3.png' });

  // Select Cyber Neon
  const cyberOption = page.getByText(/Cyber Neon/i).first();
  await cyberOption.click();
  await page.waitForTimeout(1000);

  // Continue to step 04
  await continueBtn.click();
  await page.waitForTimeout(1500);

  await page.screencast.showChapter('Step 04 — Output Confirmation', {
    description: 'Choose poster language and confirm deliverables. Ready to submit to AMD W7900 GPU!',
    duration: 3000,
  });

  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/07-create-step4.png' });

  // ========== SUBMIT ==========
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);padding:14px 28px;background:rgba(220,50,50,0.92);border-radius:12px;font-size:18px;color:white;font-family:system-ui;font-weight:700;text-align:center;">
      🎬 Submitting to AMD W7900 GPU
    </div>
  `, { duration: 2000 });

  const submitBtn = page.getByRole('button', { name: /Submit|提交/i }).last();
  await submitBtn.click();
  await page.waitForURL('**/generate**');
  await page.waitForTimeout(3000);

  // ========== GENERATE PAGE ==========
  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/08-generate.png' });

  await page.screencast.showChapter('GPU Generation — Live Progress', {
    description: 'W7900 is generating your poster. 6 stages: analyze → plan → generate → fetch → review → complete.',
    duration: 4000,
  });

  // Wait for some progress (polling happens automatically)
  await page.waitForTimeout(5000);
  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/09-generate-progress.png' });

  // ========== RESULT PAGE (use demo poster if available) ==========
  // Navigate to result page directly via demo project
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);padding:14px 28px;background:rgba(220,50,50,0.92);border-radius:12px;font-size:18px;color:white;font-family:system-ui;font-weight:700;text-align:center;">
      🎬 Showing Result Page — Final Poster Review
    </div>
  `, { duration: 2000 });

  // Go back and try with demo mode which has pre-loaded results
  await page.goto('https://cause-broad-medications-processes.trycloudflare.com/create?demo=1', { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);

  // Look for a way to access result - check if demo has a result link
  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/10-demo-create.png' });

  // Try navigating to result via a known poster ID from localStorage or API
  // First try the generate page to submit and see if we get results quickly
  await page.screencast.showOverlay(`
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);padding:16px 30px;background:rgba(0,0,0,0.85);border-radius:12px;font-size:16px;color:white;font-family:system-ui;text-align:center;max-width:500px;">
      <b>🎬 StagePoster Demo Complete</b><br><br>
      ✅ Landing Page — Hero, Scenes, Workflow, Gallery<br>
      ✅ Step 01 — Scenario Selection<br>
      ✅ Step 02 — Event Info & Asset Upload<br>
      ✅ Step 03 — Visual Language<br>
       →  Step 04 — Submit to W7900 GPU<br>
       →  Generate Progress Page<br>
       →  Candidate Selection<br>
       →  Final Result & Quality Review<br>
       →  Export PNG<br><br>
      <i>GPU generation takes 60-90s — submit now!</i>
    </div>
  `, { duration: 5000 });

  await page.screenshot({ path: '/workspace/poster-engine/demo-screenshots/11-demo-complete.png' });

  // ========== STOP RECORDING ==========
  await page.screencast.stop();
  return 'Demo recording complete!';
}

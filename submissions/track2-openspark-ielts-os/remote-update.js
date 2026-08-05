(() => {
  const IELTSLearning = window.IELTSLearning;
  const persistValue = (key, value) => window.IELTSReliability.writeValue(localStorage, key, value);
  const removePersistedValue = (key) => window.IELTSReliability.removeValue(localStorage, key);
  const manifestUrl = "https://francischi-ark.github.io/ielts-os-updates/manifest.json";
  const cacheName = "ielts-os-remote-content-v1";
  const key = "ielts-os.remote-manifest.v1";
  const bundledVersion = "2026.07.22.3";
  let manifest = {};
  try { manifest = JSON.parse(localStorage.getItem(key) || "{}"); } catch (_) {}
  const hasNewerRemote = () => Boolean(manifest.version) && String(manifest.version).localeCompare(bundledVersion, undefined, { numeric: true }) > 0;
  const status = () => ({
    version: hasNewerRemote() ? manifest.version : bundledVersion,
    assetCount: hasNewerRemote() ? Object.keys(manifest.assets || {}).length : 12,
    updatedAt: hasNewerRemote() ? manifest.updatedAt || null : null,
    lastError: manifest.lastError || null,
    bundled: !hasNewerRemote(),
  });
  const renderStatus = () => {
    const current = status();
    const updatedAt = current.updatedAt ? new Date(current.updatedAt) : null;
    const write = (selector, value) => { const node = document.querySelector(selector); if (node) node.textContent = value; };
    write("[data-remote-version]", current.version ? `版本 ${current.version}` : "本机内置版");
    write("[data-remote-updated]", current.bundled ? "随 App 安装" : updatedAt && !Number.isNaN(updatedAt.getTime()) ? updatedAt.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "等待联网");
    write("[data-remote-assets]", current.assetCount ? `${current.assetCount} 份数据` : "内置内容");
    write("[data-remote-status]", current.bundled ? "当前使用随 App 安装的最新内容；有更高版本时会自动切换。" : current.lastError ? "暂未连接更新服务，当前仍可使用内置内容；联网后会自动重试。" : current.updatedAt ? "最新内容已缓存。手动检查成功后，App 会重新打开以使用新内容。" : "首次联网后会在后台准备最新内容，下次打开 App 就能用。");
  };
  const mountUpdateCard = () => {
    const anchor = document.querySelector('[data-settings-group="content"]') || document.querySelector(".settings-intro");
    if (!anchor || document.querySelector("[data-remote-version]")) return;
    anchor.insertAdjacentHTML("afterend", `<article class="sync-card content-update-card"><span>CONTENT UPDATE</span><h2>题库与词库更新</h2><p>练习题、词库和学习路径在联网时后台更新；原始 PDF、音视频不会自动下载到手机。</p><section class="content-update-status" aria-label="内容更新状态"><p><span>当前内容</span><strong data-remote-version>本机内置版</strong></p><p><span>上次同步</span><strong data-remote-updated>等待联网</strong></p><p><span>可用数据</span><strong data-remote-assets>内置内容</strong></p></section><div><button data-refresh-remote-content>检查内容更新</button></div><small data-remote-status>首次联网后会在后台准备最新内容，下次打开 App 就能用。</small></article>`);
    const style = document.createElement("style");
    style.textContent = `.phone .content-update-card{border:1px solid #e5ded4;background:linear-gradient(135deg,#f8f5ef,#f2eee7)}.phone .content-update-status{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:1px;margin-top:14px;overflow:hidden;border:1px solid var(--line);border-radius:12px;background:var(--line)}.phone .content-update-status p{display:grid;gap:4px;min-width:0;margin:0;padding:10px 8px;background:#fffdfa}.phone .content-update-status span{color:var(--muted);font-size:10px}.phone .content-update-status strong{overflow:hidden;color:var(--ink);font-size:11px;font-weight:600;text-overflow:ellipsis;white-space:nowrap}.phone .content-update-card>div{grid-template-columns:1fr}.phone .library-import-center{margin:0 0 14px;padding:14px;border:1px solid #e3ddd3;border-radius:16px;background:#fbf9f4}.phone .library-import-head>span,.phone .library-pack-map>div>span{color:var(--accent);font-size:10px;font-weight:600;letter-spacing:.11em}.phone .library-import-head>strong,.phone .library-pack-map>div>strong{display:block;margin:5px 0;font-size:17px}.phone .library-import-head p{margin:0;color:var(--muted);font-size:11px;line-height:1.45}.phone .library-import-modules{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:12px}.phone .library-import-modules button,.phone .library-pack-map button{display:grid;gap:3px;padding:9px;border:1px solid var(--line);border-radius:10px;background:#fffdfa;text-align:left}.phone .library-import-modules span,.phone .library-pack-map em{color:var(--muted);font-size:10px;font-style:normal}.phone .library-import-modules strong{font-size:15px}.phone .library-import-modules em{overflow:hidden;font-size:10px;font-style:normal;text-overflow:ellipsis;white-space:nowrap}.phone .library-pack-map{display:grid;gap:5px;margin-top:14px;padding-top:12px;border-top:1px solid var(--line)}.phone .library-pack-map>div{margin-bottom:2px}.phone .library-pack-map button{grid-template-columns:38px 1fr;align-items:center}.phone .library-pack-map b{grid-row:span 2;color:var(--accent);font-size:16px}.phone .library-pack-map span{font-size:11px}.phone .library-import-actions{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:12px}.phone .library-import-actions button{min-height:32px;padding:0 10px;border:1px solid var(--line);border-radius:9px;color:var(--accent);background:#fff;font-size:11px}.phone .library-import-actions small{color:var(--muted);font-size:10px;text-align:right}`;
    style.textContent += `.phone .today-resource-pack{display:grid;grid-template-columns:1fr auto;gap:8px 14px;align-items:center;margin:0 0 13px;padding:13px 14px;border:1px solid #e2d8ca;border-radius:16px;background:#fffdf9}.phone .today-resource-pack span{color:var(--accent);font-size:9px;font-weight:650;letter-spacing:.08em}.phone .today-resource-pack strong{display:block;margin-top:3px;color:var(--ink);font-size:13px}.phone .today-resource-pack p{margin:3px 0 0;color:var(--muted);font-size:10px;line-height:1.35}.phone .today-resource-pack button{min-height:34px;padding:0 10px;border:1px solid var(--accent);border-radius:9px;color:#fff;background:var(--accent);font-size:10px}`;
    style.textContent += `.phone .app-feedback{position:absolute;right:22px;bottom:82px;left:22px;z-index:40;padding:11px 14px;border:1px solid var(--line);border-radius:14px;color:var(--ink);background:#faf9f6f5;box-shadow:0 10px 28px #1c191523;font-size:12px;line-height:1.4;pointer-events:none}.phone .app-feedback[data-tone=success]{color:#285f3d}.phone .app-feedback[data-tone=error]{color:#8b342f}.phone .app-feedback[hidden]{display:none}.training-debrief{position:fixed;right:max(18px,calc((100vw - 430px)/2 + 18px));bottom:20px;left:max(18px,calc((100vw - 430px)/2 + 18px));z-index:1000;padding:18px;border:1px solid #d9cec0;border-radius:20px;background:#fffdf9;box-shadow:0 18px 60px #20181038;color:#211d19}.training-debrief>[data-debrief-close]{position:absolute;top:4px;right:4px;width:44px;height:44px;border:0;background:none;font-size:22px}.training-debrief>span{color:#8e2633;font-size:9px;letter-spacing:.12em}.training-debrief header{display:flex;align-items:end;gap:12px;margin:8px 0 12px}.training-debrief header>strong{font:500 42px Georgia,serif}.training-debrief header div{display:grid}.training-debrief header em{color:#7c736a;font-size:10px;font-style:normal}.training-debrief p{display:grid;grid-template-columns:70px 1fr;margin:7px 0;font-size:11px;line-height:1.45}.training-debrief footer{display:grid;gap:7px;margin-top:14px}.training-debrief footer button{min-height:44px;border:1px solid #d9cec0;border-radius:10px;background:#faf6ef;font-size:10px}.training-debrief footer>[data-debrief-primary]{color:#fff;background:#8e2633;font-size:12px}.debrief-alternatives{display:grid;grid-template-columns:repeat(2,1fr);gap:7px}.debrief-alternatives button{color:#665c54;background:transparent}.output-debrief header{display:grid;gap:3px;padding-bottom:11px;border-bottom:1px solid #e5ddd3}.output-debrief header>strong{font:500 25px Georgia,serif}.output-debrief header>em{color:#6f665e;font-size:11px;font-style:normal}.output-debrief .output-facts{display:grid;grid-template-columns:repeat(2,1fr);gap:1px;margin:11px 0;background:#e5ddd3}.output-debrief .output-facts span{display:grid;gap:2px;padding:9px;background:#fffdf9;color:#756b62;font-size:9px}.output-debrief .output-facts b{color:#211d19;font-size:14px}.output-debrief>small{display:block;color:#7c736a;font-size:9px;line-height:1.4}.output-debrief footer button{color:#fff;background:#8e2633;font-size:12px}.speaking-round-review{margin-bottom:12px;padding:14px;border:1px solid var(--line);border-radius:16px;background:#fff}.speaking-round-review audio{width:100%;margin:10px 0 7px}.speaking-round-review>p{margin:0;color:var(--ink);font-size:12px;line-height:1.55}.speaking-round-review>small{display:block;margin-top:8px;color:var(--muted);font-size:10px;line-height:1.4}`;
    style.textContent += `.phone .bottom-nav button{height:44px;border-radius:0;color:var(--muted);background:transparent}.phone .bottom-nav button.active{border-top:2px solid var(--accent);color:var(--accent)}.phone .screen[data-screen=today]{padding-inline:20px;background:#fff}.phone .growth-brief small{overflow:hidden;padding-top:5px;border-top:1px solid #ded5c9;color:#685f56;font-size:9px;text-overflow:ellipsis;white-space:nowrap}@media(max-width:860px){.phone .bottom-nav{bottom:0;padding-bottom:calc(7px + env(safe-area-inset-bottom))}}`;
    style.textContent += `.phone .growth-roadmap{display:grid;gap:5px;margin:12px 0;padding:11px;border:1px solid #dfd5c7;border-radius:12px;background:#fffdfa}.phone .growth-roadmap>span{color:var(--accent);font-size:9px;letter-spacing:.1em}.phone .growth-roadmap>strong{font-size:13px}.phone .growth-roadmap p{margin:0;color:#655c53;font-size:10px;line-height:1.4}.phone .growth-roadmap ul{display:grid;gap:3px;margin:3px 0 0;padding-left:16px;color:var(--muted);font-size:10px}`;
    style.textContent += `.phone .content-course{display:grid;gap:4px;margin:10px 0;padding:11px;border:1px solid #ded5c9;border-radius:12px;background:#fffdfa}.phone .content-course span{color:var(--accent);font-size:9px;letter-spacing:.1em}.phone .content-course strong{font-size:15px}.phone .content-course p,.phone .content-course small{margin:0;color:var(--muted);font-size:10px;line-height:1.4}.phone .luma-header>div:nth-child(2){min-width:0}.phone .luma-header h1{margin-top:1px;font-size:28px;line-height:1}`;
    document.head.append(style);
    document.querySelector("[data-refresh-remote-content]")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = "检查中…";
      try { await refresh(); button.textContent = "正在重新打开…"; setTimeout(() => window.location.reload(), 600); }
      catch (_) { renderStatus(); button.disabled = false; button.textContent = "检查内容更新"; }
    });
    renderStatus();
  };
  const growthStages = [
    { id: "foundation", roman: "I", max: 5, title: "基础建立", milestone: 5, brief: "先补词汇、句子和听辨，建立四科最低可用能力。", mix: [["词汇", 20], ["听力", 22], ["阅读", 18], ["写作", 18], ["口语", 12], ["复盘", 10]], goals: { Vocabulary: 84, Listening: 92, Reading: 76, Writing: 76, Speaking: 50, Review: 42 } },
    { id: "method", roman: "II", max: 5.5, title: "技能成型", milestone: 5.5, brief: "把基础能力转成题型方法，减少无效刷题。", mix: [["词汇", 10], ["听力", 23], ["阅读", 23], ["写作", 17], ["口语", 17], ["复盘", 10]], goals: { Vocabulary: 42, Listening: 97, Reading: 97, Writing: 71, Speaking: 71, Review: 42 } },
    { id: "accuracy", roman: "III", max: 6, title: "答题稳定", milestone: 6, brief: "按错误类型专项修复，让客观题正确率稳定。", mix: [["词汇", 8], ["听力", 24], ["阅读", 24], ["写作", 17], ["口语", 17], ["复盘", 10]], goals: { Vocabulary: 34, Listening: 101, Reading: 101, Writing: 71, Speaking: 71, Review: 42 } },
    { id: "feedback", roman: "IV", max: 6.5, title: "输出纠偏", milestone: 6.5, brief: "通过重写和复说修复写作、口语的评分项短板。", mix: [["词汇", 5], ["听力", 18], ["阅读", 18], ["写作", 24], ["口语", 25], ["复盘", 10]], goals: { Vocabulary: 21, Listening: 76, Reading: 76, Writing: 101, Speaking: 104, Review: 42 } },
    { id: "stability", roman: "V", max: Infinity, title: "7 分稳定", milestone: 7, brief: "用完整模考、时间管理和弱项回炉降低分数波动。", mix: [["词汇", 5], ["听力", 20], ["阅读", 20], ["写作", 22], ["口语", 23], ["复盘", 10]], goals: { Vocabulary: 21, Listening: 84, Reading: 84, Writing: 92, Speaking: 97, Review: 42 } },
  ];
  const moduleNames = { Listening: "听力", Reading: "阅读", Writing: "写作", Speaking: "口语" };
  const moduleTargets = { Listening: "listening", Reading: "reading", Writing: "writing", Speaking: "speaking" };
  const moduleFocus = {
    Listening: ["数字拼写、连读和场景词听辨", "同义替换、干扰项与 Section 3/4 稳定性"],
    Reading: ["核心词汇、长难句和证据定位", "限时节奏、主旨判断与同义替换"],
    Writing: ["句子准确度、段落结构和基本回应", "论证展开、衔接与四项标准重写"],
    Speaking: ["连续表达、基础发音和答案展开", "追问稳定性、词汇精度与复说修正"],
  };
  let libraryContext;
  const renderGrowthCoach = () => {
    const { state, goals, bandOf } = libraryContext || {};
    if (!state) return;
    const signalSummary = IELTSLearning.learningSignals(state.learningEvents, state.baselineResult?.scores);
    const scores = signalSummary.scores;
    const modules = signalSummary.modules.map((item) => ({ module: item.module, score: scores[item.module], samples: item.events.length, required: item.required, ready: item.ready }));
    const band = signalSummary.band ?? IELTSLearning.explicitAverage(state.baselineResult?.scores);
    const planningBand = band ?? 4.5;
    const suggestedStage = growthStages.find((item) => planningBand < item.max) || growthStages[growthStages.length - 1];
    const weakest = modules.slice().sort((a, b) => a.score - b.score || a.samples - b.samples)[0];
    const readyModules = signalSummary.readyModules;
    const confidence = readyModules < 4 ? state.baselineResult ? "低可信度自评" : "尚未校准" : "高可信度";
    const coachStageKey = "ielts-os.coach-stage.v1";
    const suggestedIndex = growthStages.indexOf(suggestedStage);
    let stageIndex = Math.max(0, growthStages.findIndex((item) => item.id === localStorage.getItem(coachStageKey)));
    if (!localStorage.getItem(coachStageKey)) stageIndex = suggestedIndex;
    if (suggestedIndex > stageIndex && readyModules === 4 && modules.every((item) => item.score >= growthStages[stageIndex].milestone - .5)) stageIndex += 1;
    const stage = growthStages[stageIndex];
    persistValue(coachStageKey, stage.id);
    const average = (values) => values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
    const wrongs = (state.userWrongQuestions || []).filter((item) => item.status !== "已掌握");
    const signals = modules.map((item) => {
      const bands = (state.learningEvents || []).filter((event) => event.module === item.module).slice(0, 6).map((event) => bandOf?.(event)).filter((value) => value !== null && value !== undefined);
      const decline = bands.length >= 6 ? average(bands.slice(0, 3)) - average(bands.slice(3, 6)) : 0;
      const repeat = wrongs.filter((wrong) => wrong.module === item.module).length;
      return { module: item.module, repeat, decline, weight: repeat + Math.max(0, -decline * 4) };
    }).filter((item) => item.repeat >= 3 || item.decline <= -.5).sort((a, b) => b.weight - a.weight);
    const recoveryKey = "ielts-os.recovery-focus.v1";
    let recovery;
    try { recovery = JSON.parse(localStorage.getItem(recoveryKey) || "null"); } catch (_) {}
    if (recovery && new Date(recovery.until).getTime() <= Date.now()) recovery = null;
    if (signals[0] && (!recovery || recovery.module !== signals[0].module)) recovery = { module: signals[0].module, reason: signals[0].decline <= -.5 ? `近期下降 ${Math.abs(signals[0].decline).toFixed(1)}` : `${signals[0].repeat} 项重复错题`, until: new Date(Date.now() + 5 * 86400000).toISOString() };
    if (!recovery && suggestedIndex < stageIndex) recovery = { module: weakest.module, reason: "近期估分低于当前阶段", until: new Date(Date.now() + 5 * 86400000).toISOString() };
    if (recovery) persistValue(recoveryKey, JSON.stringify(recovery)); else removePersistedValue(recoveryKey);
    if (goals) {
      Object.assign(goals, stage.goals);
      if (recovery) Object.keys(goals).forEach((module) => { goals[module] += module === recovery.module ? 40 : -8; });
    }
    const stageSignature = `${stage.id}:${recovery?.module || "steady"}`;
    const stageKey = "ielts-os.growth-stage.v1";
    if (localStorage.getItem(stageKey) !== stageSignature) {
      const now = new Date();
      const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
      delete state.planModules?.[date];
      persistValue("ielts-os.planModules.v1", JSON.stringify(state.planModules || {}));
      persistValue(stageKey, stageSignature);
    }
    const milestone = Math.max(stage.milestone, Math.min(7, Math.ceil((planningBand + .01) * 2) / 2));
    const priorityModule = recovery?.module || weakest.module;
    const focus = moduleFocus[priorityModule][planningBand < 5.5 ? 0 : 1];
    const missingSamples = modules.reduce((sum, item) => sum + Math.max(0, item.required - item.samples), 0);
    const practiceUnits = missingSamples + Math.max(3, Math.ceil(Math.max(0, milestone - planningBand) * 8)) + (recovery ? 3 : 0);
    const estimatedMinutes = practiceUnits * 20;
    const examDays = state.userProfile?.examDate ? Math.max(0, Math.ceil((new Date(`${state.userProfile.examDate}T12:00:00`) - new Date()) / 86400000)) : 90;
    const availableMinutes = examDays * Number(state.userProfile?.dailyMinutes || 60);
    const risk = availableMinutes < estimatedMinutes ? "时间偏紧：优先完成有效样本与回补，不再扩展新材料。" : examDays <= 14 ? "已进入考前窗口：以完整模考和稳定性为主。" : "时间可控：保持当前日计划即可。";
    const conditions = modules.filter((item) => !item.ready).map((item) => `${moduleNames[item.module]}再完成 ${item.required - item.samples} 个有效样本`);
    if (recovery) conditions.unshift(`${moduleNames[recovery.module]}完成 3 次回补并复测`);
    if (!conditions.length) conditions.push(`四科维持 ≥ ${(stage.milestone - .5).toFixed(1)}，完成下一次阶段测评`);
    const profileAnchor = document.querySelector(".learner-profile");
    let profile = document.querySelector("[data-growth-coach]");
    if (profileAnchor && !profile) {
      profile = document.createElement("article");
      profile.className = "growth-coach";
      profile.dataset.growthCoach = "";
      profileAnchor.after(profile);
    }
    if (profile) {
      profile.innerHTML = `<header><div><span>ROAD TO BAND 7 / VOLUME ${stage.roman}</span><h2>${stage.title}</h2></div><strong>${band === null ? "未校准" : band.toFixed(1)} → ${milestone.toFixed(1)}</strong></header><p>${stage.brief}</p><div class="growth-route">${growthStages.map((item, index) => `<i class="${index === stageIndex ? "active" : index < stageIndex ? "done" : ""}"><b>${item.roman}</b><span>${item.milestone.toFixed(1)}</span></i>`).join("")}</div><section class="growth-diagnosis">${modules.map((item) => `<div class="${item.module === priorityModule ? "weak" : ""}"><span>${moduleNames[item.module]}</span><strong>${item.ready || state.baselineResult ? item.score.toFixed(1) : "—"}</strong><em>${item.samples}/${item.required} 有效样本${item.ready ? " · 已达门槛" : ""}</em><small>${moduleFocus[item.module][item.score < 5.5 ? 0 : 1]}</small></div>`).join("")}</section><section class="growth-prescription"><div><span>${recovery ? "RECOVERY MODE" : "NEXT PRESCRIPTION"} · ${confidence}</span><strong>第一优先：${moduleNames[priorityModule]}</strong><p>${recovery ? `${recovery.reason}，执行 5 天回补。` : `${focus}。达到 ${milestone.toFixed(1)} 前，本周至少完成 3 次针对训练。`}</p></div><button data-growth-train>开始训练</button></section><section class="growth-mix">${stage.mix.map(([name, value]) => `<span><b style="width:${value}%"></b><em>${name} ${value}%</em></span>`).join("")}</section><button class="growth-assessment" data-growth-assessment>重新校准四科</button>`;
      const roadmap = document.createElement("section");
      roadmap.className = "growth-roadmap";
      roadmap.innerHTML = `<span>NEXT MILESTONE / ${milestone.toFixed(1)}</span><strong>约 ${practiceUnits} 次有效训练 · ${estimatedMinutes} 分钟</strong><p>${risk}</p><ul>${conditions.slice(0, 3).map((item) => `<li>${item}</li>`).join("")}</ul>`;
      profile.querySelector("[data-growth-assessment]").before(roadmap);
    }
    const todayAnchor = document.querySelector(".today-word-card");
    let today = document.querySelector("[data-growth-brief]");
    if (todayAnchor && !today) {
      today = document.createElement("button");
      today.className = "growth-brief";
      today.dataset.growthBrief = "";
      todayAnchor.after(today);
    }
    if (today) today.innerHTML = `<span>COACH / STAGE ${stage.roman}${recovery ? " · 回补中" : ""}</span><strong>${stage.title} · 下一站 ${milestone.toFixed(1)}</strong><em>${moduleNames[priorityModule]}优先：${recovery?.reason || focus}</em>`;
    profile?.querySelector("[data-growth-train]")?.addEventListener("click", () => document.querySelector(`[data-go="${moduleTargets[priorityModule]}"]`)?.click());
    profile?.querySelector("[data-growth-assessment]")?.addEventListener("click", () => document.querySelector('[data-go="assessment"]')?.click());
    if (today) today.onclick = () => document.querySelector('[data-go="assessment"]')?.click();
    renderEvidenceDashboard();
  };
  const mountGrowthCoach = () => {
    if (!document.querySelector("style[data-growth-style]")) {
      const style = document.createElement("style");
      style.dataset.growthStyle = "";
      style.textContent = `.phone .growth-coach{margin:14px 0;padding:16px;border:1px solid #dfd5c7;border-radius:18px;background:#f8f3ea}.phone .growth-coach header{display:flex;align-items:end;justify-content:space-between;gap:12px}.phone .growth-coach header span,.phone .growth-prescription span,.phone .growth-brief span{color:var(--accent);font-size:9px;font-weight:600;letter-spacing:.12em}.phone .growth-coach h2{margin:5px 0 0;font-family:var(--font-serif,Georgia,serif);font-size:24px;font-weight:500}.phone .growth-coach header>strong{color:var(--accent);font:500 20px var(--font-serif,Georgia,serif)}.phone .growth-coach>p{margin:9px 0 12px;color:var(--muted);font-size:12px;line-height:1.5}.phone .growth-route{display:grid;grid-template-columns:repeat(5,1fr);gap:3px;margin:10px 0 14px}.phone .growth-route i{display:grid;gap:2px;padding:7px 3px;border-top:2px solid #d7cec2;color:#91877c;font-style:normal;text-align:center}.phone .growth-route i.active{border-color:var(--accent);color:var(--accent)}.phone .growth-route i.done{border-color:#698779;color:#4d6b5d}.phone .growth-route b{font-size:10px}.phone .growth-route span{font-size:9px}.phone .growth-diagnosis{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}.phone .growth-diagnosis>div{display:grid;grid-template-columns:1fr auto;gap:2px 6px;padding:10px;border:1px solid #e6ddd2;border-radius:11px;background:#fffdfa}.phone .growth-diagnosis>div.weak{border-color:#a8323e}.phone .growth-diagnosis span{font-size:11px}.phone .growth-diagnosis strong{color:var(--accent);font-size:15px}.phone .growth-diagnosis em,.phone .growth-diagnosis small{grid-column:1/-1;color:var(--muted);font-size:9px;font-style:normal}.phone .growth-diagnosis small{font-size:10px;line-height:1.35}.phone .growth-prescription{display:grid;grid-template-columns:1fr 72px;gap:10px;margin-top:10px;padding:11px;border-radius:12px;background:#efe5d6}.phone .growth-prescription strong{display:block;margin:4px 0;font-size:13px}.phone .growth-prescription p{margin:0;color:#5d554c;font-size:10px;line-height:1.4}.phone .growth-prescription button,.phone .growth-assessment{border-radius:9px;color:#fff;background:var(--accent);font-size:10px}.phone .growth-mix{display:grid;gap:4px;margin:12px 0}.phone .growth-mix span{position:relative;height:18px;overflow:hidden;border-radius:5px;background:#ebe4db}.phone .growth-mix b{display:block;height:100%;background:#d9c1a3}.phone .growth-mix em{position:absolute;inset:2px 6px;color:#4e463f;font-size:9px;font-style:normal}.phone .growth-assessment{width:100%;min-height:36px;background:#8e2633}.phone .screen[data-screen=today] .growth-brief{order:3}.phone .growth-brief{display:grid;gap:3px;width:100%;margin:0 0 12px;padding:10px 12px;border:1px solid #ded5c9;border-radius:13px;background:#faf7f1;text-align:left}.phone .growth-brief strong{font:500 14px var(--font-serif,Georgia,serif)}.phone .growth-brief em{overflow:hidden;color:var(--muted);font-size:10px;font-style:normal;text-overflow:ellipsis;white-space:nowrap}`;
      document.head.append(style);
    }
    renderGrowthCoach();
    ["[data-profile-band]", "[data-profile-target]", "[data-tutor-note]"].forEach((selector) => {
      const node = document.querySelector(selector);
      if (node) new MutationObserver(renderGrowthCoach).observe(node, { childList: true, subtree: true });
    });
  };
  const renderLibraryCenter = () => {
    const { state, render } = libraryContext || {};
    const anchor = document.querySelector("[data-guided-paths]");
    if (!state || !anchor) return;
    let center = document.querySelector("[data-library-center]");
    if (!center) {
      center = document.createElement("section");
      center.className = "library-import-center";
      center.dataset.libraryCenter = "";
      anchor.before(center);
    }
    const groups = state.libraryCatalog?.modules || [];
    const label = { listening: "听力", reading: "阅读", writing: "写作", speaking: "口语", vocabulary: "词汇", general: "通用" };
    const resources = groups.flatMap((group) => group.resources || []);
    const progress = Object.entries(state.resourceProgress || {});
    const opened = progress.filter(([, value]) => value.openedAt).length;
    const completed = progress.filter(([, value]) => value.completedAt).length;
    center.hidden = state.practiceTab !== "资料库";
    if (center.hidden) return;
    center.innerHTML = `<div class="library-import-head"><span>MY MATERIALS / INDEX</span><strong>${resources.length} 份资料已索引</strong><p>已打开 ${opened} · 已完成 ${completed}。资料原件始终留在 iCloud，打开时才按需读取。</p></div><div class="library-import-modules">${groups.map((group) => { const list = group.resources || []; const done = list.filter((item) => state.resourceProgress?.[`library:${item.id}`]?.completedAt).length; const audio = list.filter((item) => /^(mp3|m4a|wav|aac)$/i.test(item.format || "") || item.kind === "audio").length; const video = list.filter((item) => /^(mp4|mov|m4v)$/i.test(item.format || "") || item.kind === "video").length; return `<button data-library-focus="${group.title}"><span>${label[group.title] || group.title}</span><strong>${done}/${list.length}</strong><em>${audio ? `${audio} 音频` : video ? `${video} 视频` : "文档资料"}</em></button>`; }).join("")}</div><div class="library-import-actions"><button data-library-show-all>查看全部资料</button><small>个人资料不会随公开仓库分发。</small></div>`;
    center.querySelectorAll("[data-library-focus]").forEach((button) => button.addEventListener("click", () => {
      state.practiceSearch = button.dataset.libraryFocus || "";
      state.practiceStatus = "未完成";
      state.practiceResourceFormat = "全部";
      state.practiceResourceAvailability = "全部";
      state.libraryLimit = 40;
      render();
    }));
    center.querySelector("[data-library-show-all]")?.addEventListener("click", () => {
      state.practiceSearch = "";
      state.practiceStatus = "全部";
      state.practiceResourceFormat = "全部";
      state.practiceResourceAvailability = "全部";
      state.libraryLimit = 40;
      render();
    });
  };
  const mountLibraryCenter = (state, render, goals, bandOf) => {
    libraryContext = { state, render, goals, bandOf };
    renderLibraryCenter();
    mountGrowthCoach();
  };
  const debriefPrimaryAction = (rate, repeat) => repeat >= 2 || rate < 70 ? "review" : "next";
  const showDebrief = (detail) => {
    document.querySelector("[data-training-debrief]")?.remove();
    const rate = detail.total ? Math.round(detail.score / detail.total * 100) : 0;
    const repeat = Number(detail.pack?.count || 0);
    const decision = repeat >= 2 ? `同类错误已出现 ${repeat} 次，先做 ${detail.pack.title}。` : rate < 70 ? "先复盘本次错题，再继续同科训练。" : "本次表现稳定，可以进入下一项计划。";
    const actions = {
      retry: { label: "再练同类", run: (event) => window.startPlanTask?.({ module: detail.moduleCode, target: detail.target }, event.currentTarget) },
      review: { label: repeat >= 2 ? `开始 ${detail.pack.minutes} 分钟微练` : "复盘本次错题", run: () => repeat >= 2 ? window.openWeakDrill?.(detail.pack) : document.querySelector('[data-go="graph"]')?.click() },
      next: { label: "进入下一任务", run: (event) => window.startPlanTask?.(detail.next, event.currentTarget) },
    };
    const primaryId = debriefPrimaryAction(rate, repeat);
    const alternatives = Object.keys(actions).filter((id) => id !== primaryId);
    const card = document.createElement("section");
    card.className = "training-debrief";
    card.dataset.trainingDebrief = "";
    card.setAttribute("aria-label", `${detail.module}本轮结果`);
    card.innerHTML = `<button data-debrief-close aria-label="关闭">×</button><span>SESSION REVIEW / ${detail.module}</span><header><strong>${rate}%</strong><div><b>${detail.score}/${detail.total}</b><em>${detail.minutes} 分钟</em></div></header><p><b>主要错因</b>${detail.error}</p><p><b>教练建议</b>${decision}</p><footer><button data-debrief-primary data-debrief-action="${primaryId}">${actions[primaryId].label}</button><div class="debrief-alternatives" aria-label="其他选择">${alternatives.map((id) => `<button data-debrief-action="${id}">${actions[id].label}</button>`).join("")}</div></footer>`;
    document.body.append(card);
    const close = () => card.remove();
    card.querySelector("[data-debrief-close]").onclick = close;
    card.querySelectorAll("[data-debrief-action]").forEach((button) => button.onclick = (event) => { actions[button.dataset.debriefAction].run(event); close(); });
    card.querySelector("[data-debrief-primary]").focus();
  };
  const mountSpeakingRoundReview = (detail) => {
    const panel = document.querySelector('[data-speaking-panel="review"]');
    if (!panel) return;
    const previous = panel.querySelector("[data-speaking-round-review]");
    if (previous?.dataset.audioUrl) URL.revokeObjectURL(previous.dataset.audioUrl);
    previous?.remove();
    const review = document.createElement("section");
    review.className = "speaking-round-review";
    review.dataset.speakingRoundReview = "";
    review.innerHTML = `<div class="section-title"><h2>本轮回听</h2><span>${detail.meta}</span></div><audio controls preload="metadata"></audio><p></p><small>时长与转写词数只用于复盘，不等于雅思分数。</small>`;
    review.querySelector("p").textContent = detail.transcript || "本轮暂无转写，请先回听录音。";
    if (detail.audio instanceof Blob) {
      const url = URL.createObjectURL(detail.audio);
      review.dataset.audioUrl = url;
      review.querySelector("audio").src = url;
    }
    panel.prepend(review);
  };
  const showOutputDebrief = (detail) => {
    document.querySelector("[data-training-debrief]")?.remove();
    const card = document.createElement("section");
    card.className = "training-debrief output-debrief";
    card.dataset.trainingDebrief = "";
    card.setAttribute("aria-label", `${detail.module}本轮总结`);
    card.innerHTML = `<button data-debrief-close aria-label="关闭">×</button><span>SESSION COMPLETE / ${detail.module}</span><header><strong>${detail.headline}</strong><em>${detail.meta}</em></header><div class="output-facts">${detail.facts.map(([label, value]) => `<span>${label}<b>${value}</b></span>`).join("")}</div><p><b>本轮重点</b>${detail.focus}</p><small>摘要只来自本轮可观察记录，不生成雅思分数。</small><footer><button data-output-next>${detail.actionLabel}</button></footer>`;
    document.body.append(card);
    const close = () => card.remove();
    card.querySelector("[data-debrief-close]").onclick = close;
    card.querySelector("[data-output-next]").onclick = () => {
      if (detail.target === "writing") {
        document.querySelector('[data-writing-mode="write"]')?.click();
        requestAnimationFrame(() => document.querySelector("[data-writing-text]")?.focus({ preventScroll: true }));
      } else {
        mountSpeakingRoundReview(detail);
        document.querySelector('[data-speaking-mode="review"]')?.click();
        requestAnimationFrame(() => document.querySelector("[data-speaking-round-review]")?.scrollIntoView({ behavior: "smooth", block: "start" }));
      }
      close();
    };
    card.querySelector("[data-output-next]").focus();
  };
  const renderEvidenceDashboard = () => {
    const { state, bandOf } = libraryContext || {};
    if (!state) return;
    const signalSummary = IELTSLearning.learningSignals(state.learningEvents, state.baselineResult?.scores);
    const scored = (state.learningEvents || []).filter((event) => bandOf?.(event) != null);
    const latest = scored[0];
    const brief = document.querySelector("[data-growth-brief]");
    if (brief) {
      brief.querySelector("[data-evidence-brief]")?.remove();
      const line = document.createElement("small");
      line.dataset.evidenceBrief = "";
      if (!latest) line.textContent = "上次变化：完成一次带分数训练后显示；学习时长不会自动推高估分。";
      else {
        const history = scored.filter((event) => event.module === latest.module).slice(1, 5).map(bandOf).filter((value) => value !== null);
        const current = bandOf(latest);
        const prior = history.length ? history.reduce((sum, value) => sum + value, 0) / history.length : null;
        const delta = prior === null ? "新增有效样本" : `${current >= prior ? "↑" : "↓"} ${Math.abs(current - prior).toFixed(1)} vs 同科历史`;
        const source = ["Listening", "Reading"].includes(latest.module) ? "客观题" : latest.module === "Writing" ? "本地写作分析" : "口语自评";
        line.textContent = `上次变化 · ${source}：${latest.activity} ${current.toFixed(1)} · ${delta} · ${latest.durationMinutes} 分钟`;
      }
      brief.append(line);
    }
    const report = document.querySelector("[data-weekly-report]");
    if (!report) return;
    const now = Date.now();
    const recent = (state.learningEvents || []).filter((event) => now - new Date(event.createdAt).getTime() < 14 * 86400000);
    const previous = (state.learningEvents || []).filter((event) => { const age = now - new Date(event.createdAt).getTime(); return age >= 14 * 86400000 && age < 28 * 86400000; });
    const minutes = (events) => events.reduce((sum, event) => sum + Number(event.durationMinutes || 0), 0);
    const activeDays = new Set(recent.map((event) => new Date(event.createdAt).toDateString())).size;
    const wrongs = (state.userWrongQuestions || []).filter((item) => item.status !== "已掌握");
    const topWrong = Object.entries(wrongs.reduce((all, item) => { const name = item.category || item.mistakeType || "理解与策略"; all[name] = (all[name] || 0) + 1; return all; }, {})).sort((a, b) => b[1] - a[1])[0];
    const scores = signalSummary.scores;
    const weakest = Object.entries(scores).sort((a, b) => a[1] - b[1])[0];
    const ready = signalSummary.readyModules;
    const delta = minutes(recent) - minutes(previous);
    report.innerHTML = `<span>14 DAY REVIEW / 本机学习记录</span><h3>${recent.length ? `下一周期主攻：${moduleNames[weakest[0]]}` : "完成第一项训练，开始积累进步证据"}</h3><div class="weekly-report-metrics"><span><strong>${minutes(recent)}</strong> 分钟</span><span><strong>${activeDays}</strong> 天学习</span><span><strong>${ready}/4</strong> 科达门槛</span><span><strong>${wrongs.length}</strong> 题待掌握</span></div><ul><li>投入：较前 14 天${delta >= 0 ? "增加" : "减少"} ${Math.abs(delta)} 分钟</li><li>估分：${ready === 4 ? "四科样本已达到高可信度门槛" : `仍需补齐 ${4 - ready} 科有效样本`}</li><li>重复错因：${topWrong ? `${topWrong[0]} · ${topWrong[1]} 项` : "暂无重复错误"}</li><li>行动：先完成${moduleNames[weakest[0]]}训练，再处理${topWrong?.[0] || "到期错题"}</li></ul><button>打开下一周期计划</button>`;
    report.querySelector("button").onclick = () => document.querySelector('[data-go="plan"]')?.click();
  };
  const refresh = async () => {
    const response = await fetch(manifestUrl, { cache: "no-store", signal: AbortSignal.timeout?.(5000) });
    const next = await response.json();
    const assets = Object.fromEntries(Object.entries(next.assets || {}).filter(([path, url]) => /^(data\/|content-packs\/library-catalog\.json$)/.test(path) && /^https:\/\//.test(url)));
    if (!response.ok || !Object.keys(assets).length) throw new Error("remote manifest unavailable");
    const cache = await caches.open(cacheName);
    await Promise.all(Object.values(assets).map(async (url) => {
      const asset = await fetch(url, { cache: "no-store", signal: AbortSignal.timeout?.(10000) });
      if (!asset.ok) throw new Error("remote asset unavailable");
      await cache.put(url, asset);
    }));
    const previous = manifest;
    manifest = { version: next.version || "remote", assets, updatedAt: new Date().toISOString(), lastError: null };
    if (!persistValue(key, JSON.stringify(manifest))) {
      manifest = previous;
      throw new Error("remote manifest save failed");
    }
    window.dispatchEvent(new CustomEvent("ieltsremoteupdate", { detail: status() }));
    renderStatus();
    return status();
  };
  window.IELTSRemote = {
    async get(path) {
      if (!hasNewerRemote()) return null;
      const url = manifest.assets?.[String(path).replace(/^\.\//, "")];
      return url && "caches" in window ? (await caches.open(cacheName)).match(url) : null;
    },
    status,
    refresh,
    mountLibraryCenter,
    renderLibraryCenter,
    renderGrowthCoach,
    renderEvidenceDashboard,
    showDebrief,
    showOutputDebrief,
  };
  mountUpdateCard();
  refresh().catch((error) => {
    manifest = { ...manifest, lastError: error.message || "network unavailable" };
    persistValue(key, JSON.stringify(manifest));
    window.dispatchEvent(new CustomEvent("ieltsremoteupdate", { detail: status() }));
    renderStatus();
  });
})();

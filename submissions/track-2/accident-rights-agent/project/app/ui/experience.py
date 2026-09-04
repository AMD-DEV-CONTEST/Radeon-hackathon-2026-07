"""Self-contained local experience page for the three business agents."""

from __future__ import annotations


def experience_page() -> str:
    return EXPERIENCE_HTML


EXPERIENCE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>路权智鉴 · 三 Agent 体验</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17221f;
      --muted: #61706a;
      --paper: #f4f1e9;
      --card: rgba(255, 255, 255, .88);
      --line: rgba(31, 54, 46, .13);
      --green: #116a4b;
      --green-2: #2d8a67;
      --mint: #dceee5;
      --amber: #c8791c;
      --amber-bg: #fff0d9;
      --red: #a64335;
      --red-bg: #fbe6e1;
      --blue: #315e8e;
      --shadow: 0 18px 60px rgba(38, 48, 43, .09);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at 12% -6%, rgba(121, 172, 145, .24), transparent 34rem),
        linear-gradient(180deg, #f8f6ef 0, var(--paper) 42%, #ece9e1 100%);
      font: 15px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
        "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      min-height: 100vh;
    }
    button { font: inherit; }
    .shell { width: min(1240px, calc(100% - 36px)); margin: 0 auto; }
    .topbar {
      display: flex; align-items: center; justify-content: space-between;
      padding: 24px 0 14px;
    }
    .brand { display: flex; gap: 12px; align-items: center; font-weight: 760; }
    .brand-mark {
      width: 38px; height: 38px; display: grid; place-items: center;
      border-radius: 12px; color: white; background: var(--green);
      box-shadow: 0 8px 24px rgba(17, 106, 75, .25);
    }
    .chips { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .chip, .pill {
      display: inline-flex; align-items: center; gap: 6px;
      padding: 5px 10px; border: 1px solid var(--line);
      border-radius: 999px; background: rgba(255,255,255,.62);
      color: var(--muted); font-size: 12px;
    }
    .chip::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: var(--green-2); }
    .hero {
      display: grid; grid-template-columns: 1.35fr .65fr; gap: 28px;
      align-items: end; padding: 54px 0 38px;
    }
    .eyebrow {
      text-transform: uppercase; letter-spacing: .16em; font-size: 12px;
      font-weight: 760; color: var(--green);
    }
    h1 { font-size: clamp(38px, 5.3vw, 70px); line-height: 1.02; margin: 14px 0 20px; letter-spacing: -.05em; }
    .hero p { max-width: 720px; font-size: 17px; color: var(--muted); margin: 0; }
    .hero-note {
      padding: 19px 20px; border-left: 3px solid var(--green);
      background: rgba(255,255,255,.54); color: var(--muted);
      border-radius: 0 16px 16px 0;
    }
    .hero-note strong { display: block; color: var(--ink); margin-bottom: 4px; }
    .control-panel {
      border: 1px solid var(--line); border-radius: 24px; padding: 22px;
      background: var(--card); box-shadow: var(--shadow); backdrop-filter: blur(18px);
    }
    .control-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
    .control-head h2, .section-title h2 { margin: 0; font-size: 20px; }
    .control-head p, .section-title p { color: var(--muted); margin: 3px 0 0; font-size: 13px; }
    .scenario-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .scenario {
      text-align: left; border: 1px solid var(--line); border-radius: 16px;
      background: rgba(248,247,242,.7); padding: 15px; color: inherit; cursor: pointer;
      transition: .18s ease;
    }
    .scenario:hover { transform: translateY(-2px); border-color: rgba(17,106,75,.34); }
    .scenario.active { background: var(--mint); border-color: rgba(17,106,75,.48); box-shadow: inset 0 0 0 1px rgba(17,106,75,.08); }
    .scenario-top { display: flex; align-items: center; gap: 9px; font-weight: 720; }
    .scenario-letter {
      width: 27px; height: 27px; display: grid; place-items: center;
      border-radius: 8px; color: white; background: var(--green);
    }
    .scenario p { margin: 8px 0 0; font-size: 12px; line-height: 1.55; color: var(--muted); }
    .run-row { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 18px; }
    .expectation { color: var(--muted); font-size: 13px; }
    .primary {
      border: 0; border-radius: 13px; padding: 12px 20px; min-width: 158px;
      background: var(--green); color: white; font-weight: 740; cursor: pointer;
      box-shadow: 0 10px 24px rgba(17,106,75,.22); transition: .18s ease;
    }
    .primary:hover { background: #0d593f; transform: translateY(-1px); }
    .primary:disabled { opacity: .62; cursor: wait; transform: none; }
    .progress {
      display: none; grid-template-columns: repeat(3, 1fr); gap: 1px;
      margin: 22px 0 0; overflow: hidden; border: 1px solid var(--line); border-radius: 16px;
      background: var(--line);
    }
    .progress.visible { display: grid; }
    .step { background: #fff; padding: 14px 16px; display: flex; align-items: center; gap: 10px; }
    .step-num { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; background: #edf0ed; color: var(--muted); font-size: 12px; font-weight: 760; }
    .step.done .step-num { color: white; background: var(--green); }
    .step.running .step-num { animation: pulse 1s infinite alternate; color: white; background: var(--amber); }
    .step small { display: block; color: var(--muted); }
    @keyframes pulse { to { transform: scale(1.08); box-shadow: 0 0 0 6px rgba(200,121,28,.12); } }
    .results { display: none; padding: 28px 0 80px; }
    .results.visible { display: block; }
    .summary-grid { display: grid; grid-template-columns: 1.2fr .8fr .8fr .8fr; gap: 12px; margin-bottom: 24px; }
    .metric {
      border: 1px solid var(--line); border-radius: 18px; padding: 18px;
      background: var(--card); min-height: 122px;
    }
    .metric.lead { background: var(--green); color: white; }
    .metric-label { font-size: 12px; color: var(--muted); margin-bottom: 11px; }
    .metric.lead .metric-label { color: rgba(255,255,255,.72); }
    .metric-value { font-size: 23px; line-height: 1.2; font-weight: 780; letter-spacing: -.025em; }
    .metric-sub { color: var(--muted); font-size: 12px; margin-top: 9px; }
    .metric.lead .metric-sub { color: rgba(255,255,255,.7); }
    .agent-section {
      border: 1px solid var(--line); border-radius: 24px; padding: 22px;
      background: var(--card); margin-top: 16px; box-shadow: 0 12px 36px rgba(38,48,43,.055);
    }
    .section-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
    .agent-no {
      display: inline-grid; place-items: center; width: 34px; height: 34px;
      border-radius: 11px; color: white; background: var(--green); margin-right: 9px;
    }
    .status-ok { color: var(--green); background: var(--mint); border-color: transparent; }
    .status-warn { color: #86510f; background: var(--amber-bg); border-color: transparent; }
    .status-block { color: var(--red); background: var(--red-bg); border-color: transparent; }
    .columns-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .columns-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
    .subcard { border: 1px solid var(--line); border-radius: 16px; padding: 16px; background: rgba(255,255,255,.58); }
    .subcard h3 { font-size: 14px; margin: 0 0 11px; }
    .empty { color: var(--muted); font-size: 13px; padding: 10px 0; }
    .list { display: grid; gap: 8px; }
    .list-item { border-top: 1px solid rgba(31,54,46,.09); padding-top: 8px; }
    .list-item:first-child { border-top: 0; padding-top: 0; }
    .list-item strong { font-size: 13px; }
    .list-item p { color: var(--muted); font-size: 12px; margin: 2px 0 0; }
    .tag { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 11px; background: #edf0ed; color: var(--muted); margin: 2px 4px 2px 0; }
    .tag.good { color: var(--green); background: var(--mint); }
    .tag.warn { color: #86510f; background: var(--amber-bg); }
    .tag.bad { color: var(--red); background: var(--red-bg); }
    .bar-row { display: grid; grid-template-columns: minmax(120px, 1.2fr) 2fr 48px; gap: 10px; align-items: center; margin: 11px 0; }
    .bar-label { font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .bar-track { height: 9px; border-radius: 99px; background: #e8ebe8; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--green), #73b08e); }
    .bar-value { text-align: right; font-size: 12px; font-variant-numeric: tabular-nums; }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 14px; }
    table { width: 100%; border-collapse: collapse; min-width: 650px; }
    th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--line); font-size: 12px; vertical-align: top; }
    th { background: #f0f2ef; color: var(--muted); font-weight: 690; }
    tr:last-child td { border-bottom: 0; }
    details { margin-top: 14px; }
    summary { cursor: pointer; color: var(--green); font-size: 13px; font-weight: 680; }
    .warning {
      margin-top: 14px; padding: 12px 14px; border-radius: 13px;
      background: var(--amber-bg); color: #75470f; font-size: 12px;
    }
    .error {
      display: none; margin-top: 18px; padding: 14px; border-radius: 14px;
      color: var(--red); background: var(--red-bg); border: 1px solid rgba(166,67,53,.18);
    }
    .error.visible { display: block; }
    footer { padding: 0 0 38px; color: var(--muted); font-size: 12px; text-align: center; }
    @media (max-width: 900px) {
      .hero { grid-template-columns: 1fr; padding-top: 34px; }
      .summary-grid { grid-template-columns: 1fr 1fr; }
      .scenario-grid, .columns-3 { grid-template-columns: 1fr; }
      .columns-2 { grid-template-columns: 1fr; }
    }
    @media (max-width: 560px) {
      .shell { width: min(100% - 22px, 1240px); }
      .topbar { align-items: flex-start; }
      .chips .chip:nth-child(n+2) { display: none; }
      .hero { padding-top: 24px; }
      h1 { font-size: 39px; }
      .control-panel, .agent-section { padding: 15px; border-radius: 19px; }
      .control-head, .run-row, .section-title { align-items: stretch; flex-direction: column; }
      .primary { width: 100%; }
      .progress { grid-template-columns: 1fr; }
      .summary-grid { grid-template-columns: 1fr; }
      .metric { min-height: auto; }
    }
  </style>
</head>
<body>
  <header class="shell topbar">
    <div class="brand"><span class="brand-mark">路</span><span>路权智鉴</span></div>
    <div class="chips">
      <span class="chip">本地运行</span>
      <span class="chip">合成案件</span>
      <span class="chip">人工审批</span>
    </div>
  </header>

  <main class="shell">
    <section class="hero">
      <div>
        <div class="eyebrow">Traffic accident rights agent</div>
        <h1>从散乱材料，<br>到可追溯的责任判断。</h1>
        <p>选择一种案件状态，一次体验材料完整性检查、两轮车辆法律属性分析，以及违法行为、原因力与责任多假设推理。</p>
      </div>
      <aside class="hero-note">
        <strong>这是真实业务逻辑，不是录制动画</strong>
        每次点击都会创建新的合成案件，经过当前 CaseState、法律 RAG、三个 Agent、Verifier 和人工审批节点。
      </aside>
    </section>

    <section class="control-panel" aria-labelledby="scenario-title">
      <div class="control-head">
        <div><h2 id="scenario-title">选择体验案件</h2><p>三种情况分别验证“可判断、应保留不确定、材料冲突”。</p></div>
        <span class="pill">不使用公网模型 API</span>
      </div>
      <div id="scenarioGrid" class="scenario-grid" aria-live="polite"></div>
      <div class="run-row">
        <div id="expectation" class="expectation">正在加载体验案件……</div>
        <button id="runButton" class="primary" type="button">运行三个 Agent</button>
      </div>
      <div id="progress" class="progress" aria-live="polite">
        <div class="step" data-step="1"><span class="step-num">1</span><div><strong>材料接收</strong><small>完整性与缺口</small></div></div>
        <div class="step" data-step="2"><span class="step-num">2</span><div><strong>车辆属性</strong><small>规则、登记与鉴定</small></div></div>
        <div class="step" data-step="3"><span class="step-num">3</span><div><strong>责任分析</strong><small>违法、原因力与概率</small></div></div>
      </div>
      <div id="errorBox" class="error"></div>
    </section>

    <section id="results" class="results" aria-live="polite">
      <div id="summary" class="summary-grid"></div>

      <article class="agent-section">
        <div class="section-title">
          <div><h2><span class="agent-no">1</span>Case Intake Agent</h2><p>只检查既有证据成果，不重复解析原始文件。</p></div>
          <span id="intakeStatus" class="pill"></span>
        </div>
        <div class="columns-3">
          <div class="subcard"><h3>已上传材料</h3><div id="uploaded"></div></div>
          <div class="subcard"><h3>关键缺失材料</h3><div id="missing"></div></div>
          <div class="subcard"><h3>下一步收集动作</h3><div id="actions"></div></div>
        </div>
      </article>

      <article class="agent-section">
        <div class="section-title">
          <div><h2><span class="agent-no">2</span>Vehicle Nature Agent</h2><p>技术符合性只是一项因素，不自动替代车辆法律属性认定。</p></div>
          <span id="vehicleStatus" class="pill"></span>
        </div>
        <div class="columns-2">
          <div class="subcard"><h3>属性结论与替代假设</h3><div id="vehicleHypotheses"></div></div>
          <div class="subcard"><h3>关键参数逐项比较</h3><div id="parameters"></div></div>
        </div>
        <div id="vehicleWarning" class="warning"></div>
        <details><summary>查看法律引用</summary><div id="vehicleCitations" class="list" style="margin-top:12px"></div></details>
      </article>

      <article class="agent-section">
        <div class="section-title">
          <div><h2><span class="agent-no">3</span>Liability Agent</h2><p>事故责任、民事赔偿责任和保险支付保持为三个独立对象。</p></div>
          <span id="liabilityStatus" class="pill"></span>
        </div>
        <div class="columns-2">
          <div class="subcard"><h3>责任假设置信分布</h3><div id="probabilities"></div></div>
          <div class="subcard"><h3>三个独立责任对象</h3><div id="threeObjects" class="list"></div></div>
        </div>
        <details open><summary>违法行为与原因力矩阵</summary><div id="violationTable" style="margin-top:12px"></div></details>
        <details><summary>缺失证据的反事实影响</summary><div id="counterfactuals" class="columns-2" style="margin-top:12px"></div></details>
      </article>
    </section>
  </main>
  <footer class="shell">仅用于产品体验与工程验证；结论不是交警、法院或保险理赔的最终决定。</footer>

  <script>
    const categoryNames = {
      accident_determination: "事故认定书", delivery_information: "送达信息",
      dashcam_video: "行车记录仪", scene_photos: "现场照片",
      road_signal_evidence: "道路/信号证据", vehicle_registration_plate: "车辆登记/号牌",
      vehicle_certificate_ccc: "合格证/CCC", vehicle_technical_parameters: "车辆技术参数",
      vehicle_nature_appraisal: "车辆属性鉴定", inquiry_record: "询问笔录",
      medical_repair_materials: "医疗/维修材料", insurance_policy_terms: "保险单与条款"
    };
    const classificationNames = {
      non_motor_vehicle: "非机动车", suspected_motor_vehicle: "疑似机动车",
      motor_vehicle: "机动车", insufficient_evidence: "证据不足"
    };
    const regimeNames = {
      motor_vs_motor: "机动车与机动车", motor_vs_non_motor_or_pedestrian: "机动车与非机动车/行人",
      pending_vehicle_classification: "等待车辆属性确认", insufficient_evidence: "证据不足"
    };
    const statusNames = {
      compliant: "符合", non_compliant: "不符合", unknown: "未知",
      conflicting: "冲突", not_applicable: "不适用", confirmed: "已确认",
      possible: "待确认", refuted: "已排除"
    };
    const evidenceNames = {
      intersection_surveillance: "路口监控", original_dashcam: "原始行车记录仪",
      vehicle_nature_appraisal: "车辆属性鉴定", signal_phase: "信号灯相位",
      collision_point_and_brake_marks: "碰撞点/刹车痕迹"
    };

    let scenarios = [];
    let selected = "demo_a";
    const $ = (id) => document.getElementById(id);
    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    })[ch]);
    const pct = (value) => `${Math.round(Number(value || 0) * 100)}%`;
    const empty = (text = "暂无") => `<div class="empty">${esc(text)}</div>`;
    const tagClass = (status) => ["compliant", "confirmed", "qualified", "available"].includes(status)
      ? "good" : ["non_compliant", "conflicting", "disputed", "blocked"].includes(status) ? "bad" : "warn";
    const tags = (values, klass = "") => values.length
      ? values.map(value => `<span class="tag ${klass}">${esc(value)}</span>`).join("")
      : empty();

    function renderScenarios() {
      $("scenarioGrid").innerHTML = scenarios.map(item => `
        <button class="scenario ${item.scenario_id === selected ? "active" : ""}"
          type="button" data-id="${esc(item.scenario_id)}" aria-pressed="${item.scenario_id === selected}">
          <span class="scenario-top"><span class="scenario-letter">${esc(item.short_label)}</span>${esc(item.title)}</span>
          <p>${esc(item.description)}</p>
        </button>`).join("");
      document.querySelectorAll(".scenario").forEach(button => {
        button.addEventListener("click", () => {
          selected = button.dataset.id;
          renderScenarios();
          const item = scenarios.find(row => row.scenario_id === selected);
          $("expectation").textContent = item.expected_effect;
        });
      });
      const item = scenarios.find(row => row.scenario_id === selected);
      if (item) $("expectation").textContent = item.expected_effect;
    }

    function setProgress(stage) {
      $("progress").classList.add("visible");
      document.querySelectorAll(".step").forEach((step, index) => {
        step.classList.toggle("done", index < stage);
        step.classList.toggle("running", index === stage);
      });
    }

    function renderList(target, items, formatter, noData) {
      $(target).innerHTML = items?.length
        ? `<div class="list">${items.map(formatter).join("")}</div>`
        : empty(noData);
    }

    function renderResult(state) {
      const intake = state.intake_assessment || {};
      const vehicle = state.vehicle_nature_result || {};
      const liability = state.liability_result || {};
      const blocked = Boolean(liability.uncertainty?.unique_conclusion_blocked);
      const verifier = Boolean(state.verifier_results?.passed);
      const uploadedCount = intake.uploaded_materials?.length || 0;
      const missingCount = intake.missing_required_materials?.length || 0;

      $("summary").innerHTML = `
        <div class="metric lead"><div class="metric-label">当前案件</div><div class="metric-value">${esc(state.experience?.title)}</div><div class="metric-sub">${esc(state.case_id)} · 合成体验数据</div></div>
        <div class="metric"><div class="metric-label">材料状态</div><div class="metric-value">${uploadedCount} 类已就绪</div><div class="metric-sub">${missingCount} 类关键缺失</div></div>
        <div class="metric"><div class="metric-label">车辆属性</div><div class="metric-value">${esc(classificationNames[vehicle.classification] || vehicle.classification)}</div><div class="metric-sub">置信度 ${pct(vehicle.confidence)}</div></div>
        <div class="metric"><div class="metric-label">结论状态</div><div class="metric-value">${blocked ? "保留多假设" : "受限定排序"}</div><div class="metric-sub">Verifier ${verifier ? "通过" : "需复核"}</div></div>`;

      $("intakeStatus").className = `pill ${intake.route_hint === "evidence_ready" ? "status-ok" : "status-warn"}`;
      $("intakeStatus").textContent = intake.route_hint === "evidence_ready" ? "可以继续分析" : "缺失证据分支";
      renderList("uploaded", intake.uploaded_materials, item => `
        <div class="list-item"><strong>${esc(categoryNames[item.category] || item.category)}</strong>
        <p>${esc(item.description)} · ${item.source_ids?.length || 0} 份来源</p></div>`, "没有识别到已上传材料");
      renderList("missing", intake.missing_required_materials, item => `
        <div class="list-item"><strong>${esc(categoryNames[item.category] || item.category)}</strong>
        <p>${esc(item.reason)}</p><span class="tag ${item.priority === "P0" ? "bad" : "warn"}">${esc(item.priority)}</span></div>`,
        "关键材料齐备");
      renderList("actions", intake.next_collection_actions, item => `
        <div class="list-item"><strong>${esc(categoryNames[item.category] || item.category)}</strong>
        <p>${esc(item.collection_method)}</p></div>`, "暂无补证动作");

      const vehicleClass = vehicle.conclusion_status === "qualified" ? "status-ok"
        : vehicle.conclusion_status === "disputed" ? "status-block" : "status-warn";
      $("vehicleStatus").className = `pill ${vehicleClass}`;
      $("vehicleStatus").textContent = `${classificationNames[vehicle.classification] || vehicle.classification} · ${pct(vehicle.confidence)}`;
      $("vehicleHypotheses").innerHTML = `
        <div class="list-item"><strong>当前分类：${esc(classificationNames[vehicle.classification] || vehicle.classification)}</strong>
        <p>结论状态 ${esc(vehicle.conclusion_status)}；支持事实 ${vehicle.supporting_facts?.length || 0} 项，反证 ${vehicle.contradicting_facts?.length || 0} 项。</p></div>
        ${(vehicle.alternative_hypotheses || []).map(item => `
          <div class="list-item"><strong>${esc(classificationNames[item.classification] || item.classification)} · ${pct(item.probability)}</strong>
          <p>${esc(item.explanation)}</p></div>`).join("")}`;
      const knownParameters = (vehicle.parameter_comparison || []).filter(item => item.status !== "unknown");
      renderList("parameters", knownParameters, item => `
        <div class="list-item"><strong>${esc(item.display_name)}</strong>
        <span class="tag ${tagClass(item.status)}">${esc(statusNames[item.status] || item.status)}</span>
        <p>观测：${esc(item.observed_value ?? "—")}；要求：${esc(item.standard_requirement)}</p></div>`, "当前材料中没有可比较的技术参数");
      $("vehicleWarning").textContent = vehicle.warning || "技术参数不直接替代法律属性判断。";
      renderList("vehicleCitations", vehicle.legal_basis, item => `
        <div class="list-item"><strong>${esc(item.title)} ${esc(item.article_no || "")}</strong>
        <p>${esc(item.quote)}</p><span class="tag">${esc(item.source_id)}</span></div>`, "没有可用法律引用");

      $("liabilityStatus").className = `pill ${blocked ? "status-warn" : "status-ok"}`;
      $("liabilityStatus").textContent = blocked ? "唯一结论已阻断" : "可形成受限定排序";
      const probabilities = liability.responsibility_probabilities || {};
      $("probabilities").innerHTML = Object.entries(probabilities).map(([label, value]) => `
        <div class="bar-row"><div class="bar-label" title="${esc(label)}">${esc(label)}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${pct(value)}"></div></div>
        <div class="bar-value">${pct(value)}</div></div>`).join("") || empty("没有责任概率");
      const civil = liability.civil_compensation_allocation || {};
      const insurance = liability.insurance_payment_estimate || {};
      $("threeObjects").innerHTML = `
        <div class="list-item"><strong>① 事故责任</strong><p>${blocked ? "不选择唯一方案，仅展示多假设分布。" : "当前证据允许形成受限定的责任排序。"}</p></div>
        <div class="list-item"><strong>② 民事赔偿责任</strong><p>${esc(regimeNames[liability.compensation_regime] || liability.compensation_regime)} · ${esc(civil.status || "—")}</p></div>
        <div class="list-item"><strong>③ 保险支付</strong><p>${insurance.status === "insufficient_data" ? "数据不足，不估算具体金额。" : esc(insurance.status)}</p></div>`;

      const activeViolations = (liability.violation_matrix || []).filter(item => item.status !== "unknown");
      $("violationTable").innerHTML = activeViolations.length ? `
        <div class="table-wrap"><table><thead><tr><th>当事方</th><th>行为</th><th>状态</th><th>置信度</th><th>法律引用</th></tr></thead><tbody>
        ${activeViolations.map(item => `<tr>
          <td>${item.party === "motor_vehicle" ? "机动车" : "两轮车辆"}</td>
          <td>${esc(item.behavior)}</td>
          <td><span class="tag ${tagClass(item.status)}">${esc(statusNames[item.status] || item.status)}</span></td>
          <td>${pct(item.confidence)}</td><td>${item.law_citations?.length || 0} 条</td></tr>`).join("")}
        </tbody></table></div>` : empty("没有可进入矩阵的行为事实");

      $("counterfactuals").innerHTML = (liability.counterfactual_analysis || []).map(item => `
        <div class="subcard"><h3>${esc(evidenceNames[item.evidence_type] || item.evidence_type)}
          <span class="tag ${item.current_status === "available" ? "good" : "warn"}">${item.current_status === "available" ? "已有" : "缺失"}</span></h3>
          <p style="font-size:12px;color:var(--muted)">${esc(item.collection_action)}</p>
          ${(item.branches || []).map(branch => `<div class="list-item"><strong>${esc(branch.condition)}</strong><p>${esc(branch.explanation)}</p></div>`).join("")}
        </div>`).join("") || empty("没有反事实分析");

      $("results").classList.add("visible");
      $("results").scrollIntoView({behavior: "smooth", block: "start"});
    }

    async function runExperience() {
      const button = $("runButton");
      button.disabled = true;
      button.textContent = "分析中…";
      $("errorBox").classList.remove("visible");
      $("results").classList.remove("visible");
      setProgress(0);
      const timer1 = setTimeout(() => setProgress(1), 380);
      const timer2 = setTimeout(() => setProgress(2), 800);
      try {
        const response = await fetch(`/experience/run/${encodeURIComponent(selected)}`, {method: "POST"});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "运行失败");
        setProgress(3);
        renderResult(payload);
      } catch (error) {
        $("errorBox").textContent = `体验运行失败：${error.message}`;
        $("errorBox").classList.add("visible");
      } finally {
        clearTimeout(timer1); clearTimeout(timer2);
        button.disabled = false;
        button.textContent = "再次运行三个 Agent";
      }
    }

    async function init() {
      try {
        const response = await fetch("/experience/scenarios");
        scenarios = await response.json();
        renderScenarios();
      } catch (error) {
        $("errorBox").textContent = `体验案件加载失败：${error.message}`;
        $("errorBox").classList.add("visible");
      }
      $("runButton").addEventListener("click", runExperience);
    }
    init();
  </script>
</body>
</html>
"""

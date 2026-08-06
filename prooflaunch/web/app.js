(() => {
  "use strict";

  const routeMetadata = new Map([
    ["/", { title: "ProofLaunch · GTM Mission Control", stage: null }],
    ["/workspace/evidence", { title: "Evidence intake · ProofLaunch", stage: "evidence" }],
    ["/workspace/brief", { title: "Campaign brief · ProofLaunch", stage: "brief" }],
    ["/workspace/create", { title: "Create candidates · ProofLaunch", stage: "create" }],
    ["/workspace/verify", { title: "Verify and repair · ProofLaunch", stage: "verify" }],
    ["/workspace/export", { title: "Export review · ProofLaunch", stage: "export" }],
    ["/front/channels", { title: "Channel system · ProofLaunch", stage: null }],
    ["/front/experiments", { title: "Experiment lab · ProofLaunch", stage: null }],
    ["/front/learning", { title: "Learning room · ProofLaunch", stage: null }],
    ["/front/visuals", { title: "Visual studio · ProofLaunch", stage: null }],
    ["/control/gtm-cockpit", { title: "GTM cockpit · ProofLaunch", stage: null }],
    ["/control/frontier-gtm", { title: "Frontier GTM studio · ProofLaunch", stage: null }],
    ["/control/world-state", { title: "World State · ProofLaunch", stage: null }],
    ["/control/trajectory", { title: "Future trajectory · ProofLaunch", stage: null }],
    ["/control/topology", { title: "Agent topology · ProofLaunch", stage: null }],
    ["/control/memory", { title: "Memory inspector · ProofLaunch", stage: null }],
    ["/control/distillation", { title: "Distillation registry · ProofLaunch", stage: null }],
    ["/control/training", { title: "Training control · ProofLaunch", stage: null }],
    ["/control/audit", { title: "Audit control · ProofLaunch", stage: null }],
    ["/control/repair", { title: "Repair control · ProofLaunch", stage: null }],
    ["/control/human-gate", { title: "Human Gate · ProofLaunch", stage: null }],
    ["/control/images", { title: "Twelve-image browser · ProofLaunch", stage: null }],
    ["/control/videos", { title: "Three-video preview · ProofLaunch", stage: null }],
    ["/control/landing", { title: "Landing preview · ProofLaunch", stage: null }],
    ["/control/email", { title: "Email preview · ProofLaunch", stage: null }],
    ["/control/ledger", { title: "Evidence Ledger · ProofLaunch", stage: null }],
    ["/control/performance", { title: "Performance · ProofLaunch", stage: null }],
    ["/admin/tenants", { title: "Tenants and access · ProofLaunch", stage: null }],
    ["/admin/policies", { title: "Policy center · ProofLaunch", stage: null }],
    ["/admin/connectors", { title: "Connector registry · ProofLaunch", stage: null }],
    ["/admin/runtime", { title: "Runtime health · ProofLaunch", stage: null }],
    ["/admin/data", { title: "Data governance · ProofLaunch", stage: null }],
    ["/datasets", { title: "Dataset records · ProofLaunch", stage: null }],
    ["/datasets/AI-ModelScope/emotion", { title: "AI-ModelScope/emotion · ProofLaunch", stage: null }],
    ["/gemma4-it-emotion-lora-ms-single-gpu", { title: "LoRA output directory · ProofLaunch", stage: null }],
    ["/github", { title: "GitHub boundary · ProofLaunch", stage: null }],
    ["/huggingface", { title: "Hugging Face boundary · ProofLaunch", stage: null }],
    ["/mirrors", { title: "Package mirrors · ProofLaunch", stage: null }],
    ["/models", { title: "Model records · ProofLaunch", stage: null }],
    ["/models/google/gemma-4-E4B-it", { title: "Gemma model record · ProofLaunch", stage: null }],
    ["/PDF", { title: "Required specification PDF · ProofLaunch", stage: null }],
    ["/rocm", { title: "ROCm boundary · ProofLaunch", stage: null }],
    ["/seed/model", { title: "Model seed · ProofLaunch", stage: null }],
    ["/spec", { title: "Supplied specification · ProofLaunch", stage: null }],
    ["/wheels", { title: "Runtime wheels · ProofLaunch", stage: null }],
    ["/www", { title: "External web references · ProofLaunch", stage: null }]
  ]);

  const storageKey = "prooflaunch-local-state-v2";
  const tenantSessionKey = "prooflaunch-tenant-token-v1";
  const blindReviewAttestation = "I personally reviewed this blinded pair without access to candidate identity, provider identity, private side mapping, automatic score, or another reviewer's choice.";
  const judgeCalibrationAttestation = "I personally evaluated this blinded case without access to the model-judge prediction, provider identity, private mapping, or another reviewer's label.";
  const campaignPackReviewAttestation = "I independently reviewed the identity-hidden campaign packs; I did not use candidate, provider, model, private-mapping, or other-reviewer information.";
  const multimodalSelectionAttestation = "I explicitly select the completed blind-review recommendation as a multimodal production seed; this does not authorize GPU execution, spend, publication, or an effect claim.";
  const terminalRunStatuses = new Set(["delivered", "rejected", "blocked", "failed", "cancelled"]);
  const acceptedEventTypes = [
    "run_created",
    "run_queued",
    "run_started",
    "stage_changed",
    "evidence_bound",
    "claim_mined",
    "brief_created",
    "asset_created",
    "audit_completed",
    "repair_started",
    "repair_completed",
    "release_awaiting_approval",
    "human_approval",
    "release_rejected",
    "campaign_delivered",
    "run_blocked",
    "run_failed",
    "artifact_linked",
    "job_enqueued",
    "job_leased",
    "job_finished",
    "run_status_changed",
    "prepare_completed",
    "release_decision_recorded",
    "effect_observation_recorded",
    "learning_memory_promoted",
    "supervisor_claims_extracted",
    "supervisor_briefs_planned",
    "supervisor_assets_created",
    "supervisor_release_audited",
    "supervisor_assets_repaired",
    "supervisor_release_awaiting_approval",
    "supervisor_release_approved",
    "supervisor_campaign_delivered"
  ];
  const selectOptionSets = {
    launchPlatform: [["LinkedIn", "LinkedIn"], ["Instagram", "Instagram"], ["TikTok", "TikTok"], ["YouTube", "YouTube"], ["X", "X"], ["Reddit", "Reddit"]],
    launchEmotion: [["joy", "Joy"], ["love", "Love / care"], ["surprise", "Surprise"], ["fear", "Protective caution"]],
    businessModel: [["b2b", "B2B"], ["b2c", "B2C"]],
    lifecycle: [["pre_pmf", "Pre-PMF"], ["launch", "Launch"], ["growth", "Growth"], ["mature", "Mature"]],
    budget: [["zero", "Zero media spend"], ["small", "Small"], ["scaled", "Scaled"]],
    productSurface: [["web_app", "Web app"], ["mobile_app", "iOS / Android app"], ["web_agent", "Web Agent"], ["desktop_app", "Desktop app"], ["api", "API"], ["physical_product", "Physical product"], ["service", "Service"], ["hybrid", "Hybrid"]],
    industryRisk: [["standard", "Standard"], ["high_regulation", "High regulation"]],
    companyScale: [["solo", "Solo"], ["startup", "Startup"], ["scaleup", "Scale-up"], ["enterprise", "Enterprise"]],
    strength: [["none", "None"], ["emerging", "Emerging"], ["established", "Established"], ["strong", "Strong"]],
    contentCapacity: [["lean", "Lean"], ["standard", "Standard"], ["studio", "Studio"]],
    salesMotion: [["self_serve", "Self-serve"], ["sales_led", "Sales-led"], ["hybrid", "Hybrid"]],
    claimAssurance: [["owner_attested", "Owner-attested · draft only"], ["verified", "Verified by named approver · public-channel review"]],
    timezone: [["UTC", "UTC"], ["America/New_York", "America/New_York"], ["America/Los_Angeles", "America/Los_Angeles"], ["Europe/London", "Europe/London"], ["Europe/Berlin", "Europe/Berlin"], ["Asia/Shanghai", "Asia/Shanghai"], ["Asia/Tokyo", "Asia/Tokyo"], ["Asia/Singapore", "Asia/Singapore"]],
    blindScope: [["portfolio", "9-case portfolio · 54 pairs"], ["mission", "Current text campaign · 6 pairs"], ["campaign_pack", "Campaign visual system · V5 vs V6"], ["calibration", "Judge calibration · 100 cases / 300 labels"]],
    reviewerSlot: [["1", "Reviewer 1"], ["2", "Reviewer 2"], ["3", "Reviewer 3"], ["4", "Reviewer 4"], ["5", "Reviewer 5"]],
    approvalDecision: [["approve", "Approve local evidence bundle"], ["reject", "Reject and stop"]]
  };

  document.querySelectorAll("select[data-option-set]").forEach((select) => {
    const options = selectOptionSets[select.dataset.optionSet];
    if (!Array.isArray(options)) {
      throw new Error(`Unknown select option set: ${select.dataset.optionSet}`);
    }
    const selected = select.dataset.selected ?? "";
    options.forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = value === selected;
      select.append(option);
    });
  });
  const routePanels = Array.from(document.querySelectorAll("[data-route]"));
  const stageLinks = Array.from(document.querySelectorAll("[data-stage-link]"));
  const routeLinks = Array.from(document.querySelectorAll("[data-route-link]"));

  const state = {
    route: "/",
    stage: null,
    createState: "ready",
    verifyState: "blocked",
    repairRounds: 0,
    selectedInspector: "evidence-boundary",
    briefMarket: "United States",
    briefObjective: "Product launch review",
    pendingControl: null,
    runId: null,
    runStatus: null,
    apiConnected: false,
    productArtifact: null,
    signalArtifact: null,
    signalReceiptArtifact: null,
    productFile: null,
    eventPollTimer: null,
    eventPollGeneration: 0,
    lastEventId: 0,
    tenantToken: null,
    eventKeys: new Set(),
    previewBlobUrl: null,
    previewReady: false,
    approvalAttempt: null,
    effectContract: null,
    outcomeAttempt: null,
    latestEffectObservation: null,
    learningMemories: null,
    learningPromotionAttempt: null,
    productReadiness: null,
    campaignWorkspace: null,
    gtmCockpit: null,
    platformCapabilityShowcase: null,
    codexIntegratedCampaignPortfolio: null,
    codexCampaignAdaptationSummary: null,
    codexLighthousePortfolio: null,
    publicSignalPilot: null,
    syntheticLifecycleDemo: null,
    blindReviewAssignment: null
  };
  const qualificationMediaUrls = [];
  const frontierMediaUrls = [];
  let frontierCurrentResult = null;
  let frontierPendingSurfaceFocus = null;

  async function loadMemoryCapsules() {
    const projectInput = getElement("memory-project-id");
    const projectId = projectInput instanceof HTMLInputElement ? projectInput.value.trim() : "";
    if (!projectId) {
      setText("memory-capsule-output", "Memory lookup blocked: enter a project ID.");
      return;
    }
    try {
      const collection = await requestJson(`/v1/memory-capsules?project_id=${encodeURIComponent(projectId)}`);
      renderJson("memory-capsule-output", collection);
    } catch (error) {
      setText("memory-capsule-output", `Memory lookup failed closed: ${String(error.message ?? error)}`);
    }
  }

  const safeMarkets = new Set(["United States", "Japan", "Germany"]);
  const safeObjectives = new Set([
    "Product launch review",
    "Claim-safe campaign draft",
    "Channel adaptation review"
  ]);

  function getElement(id) {
    return document.getElementById(id);
  }

  function setText(id, text) {
    const element = getElement(id);
    if (element) {
      element.textContent = text;
    }
  }

  function setFeedback(id, text, feedbackState = "info") {
    const element = getElement(id);
    if (!element) {
      return;
    }
    element.textContent = text;
    element.dataset.state = feedbackState;
  }

  function selectInspectorView(selected) {
    document.querySelectorAll("[data-inspector-tab]").forEach((tab) => {
      tab.setAttribute("aria-selected", String(tab.getAttribute("data-inspector-tab") === selected));
    });
    document.querySelectorAll("[data-inspector-view]").forEach((view) => {
      view.hidden = view.getAttribute("data-inspector-view") !== selected;
    });
  }

  function selectFrontierOutputTab(selected, { focus = false } = {}) {
    const tabs = Array.from(document.querySelectorAll("[data-frontier-output-tab]"));
    const panels = Array.from(document.querySelectorAll("[data-frontier-output-panel]"));
    tabs.forEach((tab) => {
      const active = tab.getAttribute("data-frontier-output-tab") === selected;
      tab.setAttribute("aria-selected", String(active));
      tab.tabIndex = active ? 0 : -1;
      if (active && focus && tab instanceof HTMLElement) tab.focus();
    });
    panels.forEach((panel) => {
      panel.hidden = panel.getAttribute("data-frontier-output-panel") !== selected;
    });
  }

  function setFrontierFlowStep(step, stateName, detail) {
    const item = document.querySelector(`[data-frontier-flow-step="${step}"]`);
    if (!(item instanceof HTMLElement)) return;
    item.dataset.state = stateName;
    const small = item.querySelector("small");
    if (small && detail) small.textContent = detail;
  }

  const frontierStageGuidance = {
    brief: {
      number: "STEP 01 / 06",
      title: "Brief · establish the decision contract",
      copy: "Confirm one audience, one costly tension, one desired behavior and the only approved product truth before production begins.",
      action: "Review brief fields"
    },
    strategy: {
      number: "STEP 02 / 06",
      title: "Agent council · debate twelve creative genomes",
      copy: "Six specialist nodes diagnose the market, challenge twelve hook/narrative/visual/tone combinations and preserve a content-addressed receipt for every handoff.",
      action: "Inspect Agent graph"
    },
    concept: {
      number: "STEP 03 / 06",
      title: "Creative systems · cut to three mutually distinct routes",
      copy: "Every finalist must change hook, narrative grammar, visual grammar and tone—not merely recolor one campaign template. The jury records the kill rule and selection boundary.",
      action: "Compare territories"
    },
    production: {
      number: "STEP 04 / 06",
      title: "Native production · execute one coherent creative genome",
      copy: "The selected tone rewrites platform copy, its visual grammar changes composition, and its narrative grammar becomes a six-shot film—not a reformatted generic answer.",
      action: "Open live assets"
    },
    audit: {
      number: "STEP 05 / 06",
      title: "Audit · separate evidence from aspiration",
      copy: "Inspect model source, live-render receipt, truth boundary, cross-format continuity and every remaining human quality gate.",
      action: "Open quality receipts"
    },
    release: {
      number: "STEP 06 / 06",
      title: "Release · require a named human decision",
      copy: "Production success never grants authority to publish, send or spend. Craft, rights and final release remain independently gated.",
      action: "Open approval gate"
    }
  };

  let frontierSelectedStage = "brief";

  function showFrontierStageGuide(stage, { execute = false } = {}) {
    const guidance = frontierStageGuidance[stage];
    if (!guidance) return;
    frontierSelectedStage = stage;
    setText("frontier-stage-guide-number", guidance.number);
    setText("frontier-stage-guide-title", guidance.title);
    setText("frontier-stage-guide-copy", guidance.copy);
    setText("frontier-stage-guide-action", `${guidance.action} ${stage === "release" ? "↗" : "↓"}`);
    document.querySelectorAll("[data-frontier-flow-action]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-frontier-flow-action") === stage));
    });
    if (!execute) return;
    const result = getElement("frontier-gtm-result");
    const hasResult = result instanceof HTMLElement && !result.hidden;
    if (stage === "brief") {
      const intelligence = document.querySelector(".frontier-brief-details");
      if (intelligence instanceof HTMLDetailsElement) intelligence.open = true;
      getElement("frontier-gtm-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    if (stage === "release") {
      navigate("/control/human-gate");
      return;
    }
    if (hasResult) {
      selectFrontierOutputTab(stage === "production" ? "assets" : stage === "audit" ? "review" : "overview", { focus: true });
      result.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    getElement("frontier-gtm-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
    if (stage === "production") getElement("generate-realtime-campaign")?.focus();
    setFeedback("frontier-gtm-feedback", `${guidance.title}. Produce a campaign first to inspect this stage's sealed output.`, "info");
  }

  function renderFrontierInspector(result, manifest = result?.rendered_media) {
    if (!result || typeof result !== "object") return;
    const assets = Array.isArray(manifest?.assets) ? manifest.assets : [];
    const hash = String(result.envelope_sha256 ?? result.content_sha256 ?? "");
    const release = String(result.release_review_status ?? "human_release_required").replaceAll("_", " ");
    setText("inspector-run-id", String(result.brief?.brief_id ?? hash.slice(0, 18) ?? "Generated campaign"));
    setText("inspector-run-stage", assets.length ? "Model-backed assets rendered" : "Strategy generated");
    setText("inspector-run-assets", `${assets.length} file${assets.length === 1 ? "" : "s"}`);
    setText("inspector-run-renderer", String(manifest?.renderer ?? result.provider ?? "Server production runtime"));
    setText("inspector-run-hash", hash ? `sha256:${hash.slice(0, 14)}…` : "Not sealed");
    setText("inspector-run-release", release);
    const quality = result.quality_control ?? {};
    const qualityLabel = quality.target_tier === "production_review_candidate" && quality.human_craft_approved === false
      ? "Production candidate · human validation pending"
      : "Production candidate";
    setText("inspector-run-summary", assets.length
      ? `The ${qualityLabel.toLowerCase()} is sealed with strategy, copy and observed media. Inspect craft, rights and every asset before the named-human release gate.`
      : "The strategy package is sealed. Binary media requires a separately observed renderer receipt.");
    setText("inspector-summary", "The current campaign is bound to the declared product truth, a content-addressed server response and a named-human release boundary.");
    setText("inspector-source", "Brief bound");
    setText("inspector-approval", "Human review pending");
    setText("inspector-runtime", assets.length
      ? (manifest?.model_master_inference_pre_generated === true ? "Verified model master + live adaptation" : "Binary renderer observed")
      : "Strategy runtime observed");
    setText("inspector-provenance", hash ? "SHA-256 sealed" : "Pending");
    const badge = getElement("inspector-run-badge");
    if (badge) {
      badge.textContent = assets.length ? qualityLabel : "Strategy ready";
      badge.className = "status-badge status-badge--required";
    }
    selectInspectorView("run");
  }

  function downloadFrontierManifest() {
    if (!frontierCurrentResult) {
      setFeedback("frontier-gtm-feedback", "Generate a campaign before downloading its manifest.", "error");
      return;
    }
    const blob = new Blob([`${JSON.stringify(frontierCurrentResult, null, 2)}\n`], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `prooflaunch-${String(frontierCurrentResult.brief?.brief_id ?? "campaign")}.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }

  const frontierRecipes = {
    "b2b-launch": {
      business_model: "b2b", lifecycle: "launch", budget: "zero", market: "North America",
      industry: "AI software", category: "governed AI GTM employee", product_surface: "web agent",
      audience: "Founder-led B2B teams evaluating whether an AI employee can create credible pipeline without surrendering release control",
      audience_problem: "AI campaign output is abundant, but buyers cannot see which evidence, expert judgment and accountable owner justify the work",
      audience_outcome: "Run one inspectable proof review and book a qualified design-partner session",
      product_truth: "Compiles a rights-bound brief into review-ready GTM assets.",
      brand_voice: "Category-defining, forensic, concise and senior-operator credible; translate one thesis into native text, image and video systems",
      primary_goal: "Qualified evidence reviews from accountable GTM operators"
    },
    "technical-proof": {
      business_model: "b2b", lifecycle: "growth", budget: "lean", market: "Global English",
      industry: "B2B technology", category: "technical product", product_surface: "web app",
      audience: "Technical evaluators and economic buyers who distrust feature claims without a reproducible rejection test",
      audience_problem: "Feature-led promotion collapses architecture, evidence and measurable consequence into undifferentiated AI language",
      audience_outcome: "Inspect the rejection test, compare the evidence and advance only if the operating claim survives",
      product_truth: "Creates an inspectable evidence package from owner-approved product facts.",
      brand_voice: "Precise technical editorial; proof before benefit; turn the teardown into text, diagram imagery and a short proof film",
      primary_goal: "Evaluation-stage visits that complete the proof review"
    },
    "founder-narrative": {
      business_model: "b2b", lifecycle: "pre_pmf", budget: "zero", market: "North America",
      industry: "Technology startup", category: "new category", product_surface: "web agent",
      audience: "Early adopters who recognize the costly status quo and want to understand the founder's non-obvious conviction",
      audience_problem: "Generic launch language hides the specific lived tension that made the new category necessary",
      audience_outcome: "Recognize the category problem, follow the build journey and request an accountable early evaluation",
      product_truth: "Transforms an approved founder brief into review-ready campaign assets.",
      brand_voice: "Human, sharp and belief-led without mythology; build one origin story across essay, visual motif and founder film",
      primary_goal: "High-intent design-partner conversations"
    },
    "b2c-drop": {
      business_model: "b2c", lifecycle: "launch", budget: "zero", market: "Global English",
      industry: "Consumer technology", category: "mobile product", product_surface: "mobile app",
      audience: "Mobile-first creators who share useful discoveries when the product gives them a visible new behavior",
      audience_problem: "Polished AI launches look interchangeable and give the audience no repeatable action worth sharing",
      audience_outcome: "Try one product ritual, publish the result and invite another person into the loop",
      product_truth: "Creates review-ready campaign assets from an approved product brief.",
      brand_voice: "Fast, culturally literate and visually decisive; one reveal becomes feed copy, image sequence and vertical video",
      primary_goal: "Qualified product trials attributed to the organic launch ritual"
    },
    "category-takeover": {
      business_model: "b2b", lifecycle: "growth", budget: "lean", market: "Global English",
      industry: "Professional software", category: "competitive workflow", product_surface: "web app",
      audience: "Category buyers comparing established workflows with a materially different operating model",
      audience_problem: "Competitors own the vocabulary, so buyers evaluate new products using assumptions the new approach was built to replace",
      audience_outcome: "Adopt the new evaluation frame, compare evidence and shortlist the product on the changed criteria",
      product_truth: "Produces review-ready GTM assets from approved evidence and a bounded brief.",
      brand_voice: "Contrarian but evidence-bound; connect manifesto text, comparison imagery, search answers and a category film",
      primary_goal: "Qualified comparison traffic and shortlist inclusion"
    }
  };

  function routeDomain(path) {
    if (path === "/") return "Mission";
    if (path.startsWith("/workspace/")) return "Workflow";
    if (path.startsWith("/front/")) return "Front office";
    if (path.startsWith("/control/")) return "Operations";
    if (path.startsWith("/admin/")) return "Governance";
    return "Sources";
  }

  function routeLabel(path) {
    return String(routeMetadata.get(path)?.title ?? "ProofLaunch").replace(/ · ProofLaunch$/, "");
  }

  function setupConsoleShell() {
    const root = document.documentElement;
    const toggle = document.querySelector("[data-console-action='toggle-navigation']");
    let navigationCollapsed = false;
    try { navigationCollapsed = window.localStorage.getItem("prooflaunch-navigation-collapsed-v1") === "true"; } catch { /* session remains usable */ }
    const renderNavigationState = () => {
      root.dataset.navigationCollapsed = String(navigationCollapsed);
      if (toggle instanceof HTMLButtonElement) {
        toggle.setAttribute("aria-pressed", String(navigationCollapsed));
        toggle.setAttribute("aria-label", navigationCollapsed ? "Expand navigation" : "Collapse navigation");
      }
    };
    renderNavigationState();
    toggle?.addEventListener("click", () => {
      navigationCollapsed = !navigationCollapsed;
      renderNavigationState();
      try { window.localStorage.setItem("prooflaunch-navigation-collapsed-v1", String(navigationCollapsed)); } catch { /* non-critical */ }
    });

    const inspectorTabs = Array.from(document.querySelectorAll("[data-inspector-tab]"));
    inspectorTabs.forEach((tab) => tab.addEventListener("click", () => {
      selectInspectorView(tab.getAttribute("data-inspector-tab"));
    }));

    document.querySelectorAll("[data-frontier-output-tab]").forEach((tab) => {
      tab.addEventListener("click", () => selectFrontierOutputTab(tab.getAttribute("data-frontier-output-tab")));
    });
    document.querySelectorAll("[data-frontier-flow-action]").forEach((button) => {
      button.addEventListener("click", () => showFrontierStageGuide(button.getAttribute("data-frontier-flow-action"), { execute: true }));
    });
    getElement("frontier-stage-guide-action")?.addEventListener("click", () => {
      showFrontierStageGuide(frontierSelectedStage, { execute: true });
    });
    getElement("frontier-download-manifest")?.addEventListener("click", downloadFrontierManifest);
    getElement("inspector-open-assets")?.addEventListener("click", () => {
      selectFrontierOutputTab("assets");
      getElement("frontier-gtm-result")?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
    });
    getElement("generate-realtime-campaign")?.addEventListener("click", (event) => {
      const form = getElement("frontier-gtm-form");
      const button = event.currentTarget;
      if (!(form instanceof HTMLFormElement) || !(button instanceof HTMLButtonElement)) return;
      if (!form.reportValidity()) return;
      if (!state.tenantToken) {
        setFeedback("frontier-gtm-feedback", "Generation blocked: the tenant evaluation session is not active.", "error");
        return;
      }
      button.setAttribute("data-running", "true");
      void runRealtimePresetCampaign(form, button);
    });

    const dialog = getElement("command-dialog");
    const search = getElement("command-search");
    const results = getElement("command-results");
    let commandMatches = [];
    let commandIndex = 0;
    const renderCommands = () => {
      if (!(results instanceof HTMLElement) || !(search instanceof HTMLInputElement)) return;
      const query = search.value.trim().toLowerCase();
      commandMatches = Array.from(routeMetadata.keys()).filter((path) => {
        const haystack = `${routeDomain(path)} ${routeLabel(path)} ${path}`.toLowerCase();
        return !query || haystack.includes(query);
      }).slice(0, 14);
      commandIndex = Math.max(0, Math.min(commandIndex, commandMatches.length - 1));
      results.replaceChildren(...commandMatches.map((path, index) => {
        const link = document.createElement("a");
        link.href = path;
        link.dataset.commandActive = String(index === commandIndex);
        const strong = document.createElement("strong");
        strong.textContent = routeLabel(path);
        const small = document.createElement("small");
        small.textContent = routeDomain(path);
        const arrow = document.createElement("span");
        arrow.textContent = "↗";
        link.append(strong, small, arrow);
        link.addEventListener("click", (event) => {
          event.preventDefault();
          if (dialog instanceof HTMLDialogElement) dialog.close();
          navigate(path);
        });
        return link;
      }));
    };
    const openCommand = () => {
      if (!(dialog instanceof HTMLDialogElement) || !(search instanceof HTMLInputElement)) return;
      commandIndex = 0;
      search.value = "";
      renderCommands();
      dialog.showModal();
      window.requestAnimationFrame(() => search.focus());
    };
    document.querySelector("[data-console-action='open-command']")?.addEventListener("click", openCommand);
    search?.addEventListener("input", () => { commandIndex = 0; renderCommands(); });
    search?.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") { event.preventDefault(); commandIndex = Math.min(commandMatches.length - 1, commandIndex + 1); renderCommands(); }
      if (event.key === "ArrowUp") { event.preventDefault(); commandIndex = Math.max(0, commandIndex - 1); renderCommands(); }
      if (event.key === "Enter" && commandMatches[commandIndex]) { event.preventDefault(); dialog?.close(); navigate(commandMatches[commandIndex]); }
    });
    dialog?.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    window.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); openCommand(); }
    });

    document.querySelectorAll("[data-frontier-recipe]").forEach((button) => {
      button.addEventListener("click", () => {
        const recipe = frontierRecipes[button.getAttribute("data-frontier-recipe")];
        const form = getElement("frontier-gtm-form");
        if (!recipe || !(form instanceof HTMLFormElement)) return;
        Object.entries(recipe).forEach(([name, value]) => {
          const field = form.elements.namedItem(name);
          if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement) field.value = value;
        });
        document.querySelectorAll("[data-frontier-recipe]").forEach((candidate) => candidate.removeAttribute("data-running"));
        button.setAttribute("data-running", "true");
        setFeedback("recipe-feedback", state.tenantToken ? "Recipe loaded. Running six specialist Agent nodes across twelve creative genomes, then rendering the selected copy, visual grammar and six-beat film…" : "Recipe loaded. Production is blocked until a tenant session is activated; no fake output was created.", state.tenantToken ? "info" : "error");
        if (state.tenantToken) void runRealtimePresetCampaign(form, button);
        if (!state.tenantToken) button.removeAttribute("data-running");
      });
    });
  }

  function saveRecoveryState() {
    const recoveryState = {
      route: state.route,
      stage: state.stage,
      createState: state.createState,
      verifyState: state.verifyState,
      repairRounds: state.repairRounds,
      selectedInspector: state.selectedInspector,
      briefMarket: state.briefMarket,
      briefObjective: state.briefObjective,
      runId: null,
      runStatus: null,
      productArtifact: null,
      signalArtifact: null,
      signalReceiptArtifact: null
    };

    try {
      window.localStorage.setItem(storageKey, JSON.stringify(recoveryState));
    } catch {
      setFeedback("evidence-feedback", "Local recovery storage is unavailable; the current browser session remains usable.");
    }
  }

  function restoreRecoveryState() {
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (!stored) {
        return;
      }
      const candidate = JSON.parse(stored);
      if (routeMetadata.has(candidate.route)) {
        state.route = candidate.route;
      }
      if (["ready", "waiting", "recovered"].includes(candidate.createState)) {
        state.createState = candidate.createState;
      }
      if (["blocked", "failed", "repaired", "recovered"].includes(candidate.verifyState)) {
        state.verifyState = candidate.verifyState;
      }
      if (Number.isInteger(candidate.repairRounds) && candidate.repairRounds >= 0 && candidate.repairRounds <= 2) {
        state.repairRounds = candidate.repairRounds;
      }
      if (safeMarkets.has(candidate.briefMarket)) {
        state.briefMarket = candidate.briefMarket;
      }
      if (safeObjectives.has(candidate.briefObjective)) {
        state.briefObjective = candidate.briefObjective;
      }
      if (typeof candidate.runId === "string" && /^run-[A-Za-z0-9_-]{8,96}$/.test(candidate.runId)) {
        state.runId = candidate.runId;
      }
      if (typeof candidate.runStatus === "string" && /^[a-z_]{3,40}$/.test(candidate.runStatus)) {
        state.runStatus = candidate.runStatus;
      }
      if (
        candidate.productArtifact &&
        typeof candidate.productArtifact === "object" &&
        typeof candidate.productArtifact.sha256 === "string" &&
        /^[0-9a-f]{64}$/.test(candidate.productArtifact.sha256) &&
        typeof candidate.productArtifact.name === "string" &&
        Number.isInteger(candidate.productArtifact.size)
      ) {
        state.productArtifact = {
          sha256: candidate.productArtifact.sha256,
          name: candidate.productArtifact.name.slice(0, 200),
          size: candidate.productArtifact.size,
          deduplicated: Boolean(candidate.productArtifact.deduplicated)
        };
      }
      if (
        candidate.signalArtifact &&
        typeof candidate.signalArtifact === "object" &&
        typeof candidate.signalArtifact.sha256 === "string" &&
        /^[0-9a-f]{64}$/.test(candidate.signalArtifact.sha256) &&
        typeof candidate.signalArtifact.name === "string" &&
        Number.isInteger(candidate.signalArtifact.size)
      ) {
        state.signalArtifact = {
          sha256: candidate.signalArtifact.sha256,
          name: candidate.signalArtifact.name.slice(0, 200),
          size: candidate.signalArtifact.size,
          deduplicated: Boolean(candidate.signalArtifact.deduplicated)
        };
      }
    } catch {
      window.localStorage.removeItem(storageKey);
    }
  }

  function updateInspector({
    heading,
    summary,
    source = "Required",
    approval = "Unavailable",
    runtime = "Not connected",
    provenance = "Unknown"
  }) {
    setText("inspector-heading", heading);
    setText("inspector-summary", summary);
    setText("inspector-source", source);
    setText("inspector-approval", approval);
    setText("inspector-runtime", runtime);
    setText("inspector-provenance", provenance);
  }

  function updateInspectorForRoute(path) {
    if (path === "/control/gtm-cockpit") {
      updateInspector({
        heading: "Lifecycle decision cockpit",
        summary: "This surface derives strategy, workspace, approval, aggregate effect, unit economics, promoted memory, and the next bounded action from one tenant-scoped run. It never creates a second source of truth.",
        source: state.runId ? "Run-bound" : "Run required",
        approval: state.runStatus === "awaiting_release" ? "Decision required" : state.runStatus ?? "Not started",
        runtime: state.apiConnected ? "Local API" : "Disconnected",
        provenance: state.gtmCockpit?.content_sha256 ? "Content hashed" : "Not loaded"
      });
      return;
    }
    if (path === "/control/world-state" || path === "/control/trajectory") {
      updateInspector({
        heading: "Local Agent execution",
        summary: "This surface connects to the same-origin deterministic Agent and shows only persisted run state and observable events. No external publisher or connector is called.",
        source: state.productArtifact ? "SHA-256 bound" : "Required",
        approval: state.runStatus === "awaiting_release" ? "Decision required" : "Server controlled",
        runtime: state.apiConnected ? "Local API" : "Disconnected",
        provenance: state.runId ? "Run-bound" : "Not started"
      });
      return;
    }
    if (path === "/control/human-gate" || path === "/control/ledger") {
      updateInspector({
        heading: "Content-bound release",
        summary: "The browser cannot choose the digest, approver identity, approval kind, or server timestamp. Download is exposed only after delivered; external release remains unexecuted.",
        source: state.runStatus === "awaiting_release" || state.runStatus === "delivered" ? "Prepared" : "Waiting",
        approval: state.runStatus ?? "Not started",
        runtime: state.apiConnected ? "Local API" : "Disconnected",
        provenance: state.runId ? "Hash ledger" : "Not available"
      });
      return;
    }
    if (path.startsWith("/front/")) {
      updateInspector({
        heading: "Operator decision surface",
        summary: "This front-office view models a persistent GTM object and its human decision boundary; all campaign outputs remain synthetic or absent until source evidence is approved.",
        source: "Required",
        approval: "Human gated",
        runtime: "Prototype only",
        provenance: "Modeled"
      });
      return;
    }
    if (path === "/admin/tenants") {
      updateInspector({
        heading: "Tenant principal boundary",
        summary: "The local server maps a session bearer token to an immutable tenant principal and scopes protected runs, artifacts, memory, jobs, events, cache, previews and bundles. Enterprise IdP and distributed RLS remain unimplemented.",
        source: state.tenantToken ? "Session principal active" : "Bearer token required",
        approval: "Server enforced",
        runtime: state.apiConnected ? "Single-node local API" : "Disconnected",
        provenance: "Mechanically tested vertical slice"
      });
      return;
    }
    if (path.startsWith("/admin/")) {
      updateInspector({
        heading: "Governance boundary",
        summary: "This back-office view expresses policy and operating contracts. No identity provider, tenant store, connector, production runtime, or compliance result is attached.",
        source: "Local contract",
        approval: "Not configured",
        runtime: "Not connected",
        provenance: "Design-state only"
      });
      return;
    }
    if (path === "/workspace/brief") {
      updateInspector({
        heading: "Brief decision context",
        summary: "Local brief choices preserve market, objective, and review surfaces without unlocking model execution.",
        source: "Still required",
        approval: "Not established"
      });
      return;
    }
    if (path === "/workspace/create") {
      updateInspector({
        heading: "Runtime boundary",
        summary: "A named model, dataset, and seed appear in the supplied notebook; no website runtime or post-tuning result is established.",
        source: "Supplied metadata",
        approval: "Unavailable",
        runtime: "Backend absent"
      });
      return;
    }
    if (path === "/workspace/verify") {
      updateInspector({
        heading: "Audit custody",
        summary: "Failure and repair controls are deterministic local states. No artifact or audit threshold exists to produce a real pass.",
        source: "Missing",
        approval: "Review only",
        runtime: "Not executed"
      });
      return;
    }
    if (path === "/workspace/export") {
      updateInspector({
        heading: "Release boundary",
        summary: "Factual audit and provenance are separate unresolved gates. No package, signature, or publication action is available.",
        source: "Missing",
        approval: "Blocked",
        runtime: "Not executed",
        provenance: "Not demonstrated"
      });
      return;
    }
    updateInspector({
      heading: "Evidence boundary",
      summary: "No rights-cleared multimodal evidence was supplied. The interface stays inspectable without inventing source proof."
    });
  }

  function updateActiveNavigation(path) {
    const activeStage = routeMetadata.get(path)?.stage ?? null;
    stageLinks.forEach((link) => {
      if (activeStage && link.dataset.stageLink === activeStage) {
        link.setAttribute("aria-current", "page");
      } else {
        link.removeAttribute("aria-current");
      }
    });
    routeLinks.forEach((link) => {
      let linkPath = "";
      try { linkPath = new URL(link.getAttribute("href") ?? "", window.location.origin).pathname; } catch { return; }
      if (linkPath === path && link.closest(".control-nav")) link.setAttribute("aria-current", "page");
      else if (link.closest(".control-nav")) link.removeAttribute("aria-current");
    });
    setText("route-domain", routeDomain(path));
    setText("route-title", routeLabel(path));
  }

  function navigate(path, { push = true, focus = true } = {}) {
    const safePath = routeMetadata.has(path) ? path : "/";
    const commitRoute = () => {
      routePanels.forEach((panel) => {
        panel.hidden = panel.dataset.route !== safePath;
      });

      state.route = safePath;
      state.stage = routeMetadata.get(safePath)?.stage ?? null;
      document.title = routeMetadata.get(safePath)?.title ?? "ProofLaunch";
      document.documentElement.dataset.currentRoute = safePath;
      updateActiveNavigation(safePath);
      updateInspectorForRoute(safePath);
      refreshControlSurface(safePath);

      if (push && window.location.pathname !== safePath) {
        window.history.pushState({ route: safePath }, "", safePath);
      }

      document.querySelectorAll(".source-menu[open]").forEach((menu) => {
        menu.open = false;
      });

      saveRecoveryState();
    };

    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const transition = push && !reduceMotion && typeof document.startViewTransition === "function"
      ? document.startViewTransition(commitRoute)
      : null;
    if (!transition) commitRoute();

    const focusCurrentHeading = () => {
      if (!focus) return;
      const panel = routePanels.find((candidate) => candidate.dataset.route === safePath);
      const heading = panel?.querySelector("h2[tabindex='-1']");
      if (heading) {
        window.requestAnimationFrame(() => heading.focus({ preventScroll: false }));
      }
    };
    if (transition) transition.finished.then(focusCurrentHeading).catch(focusCurrentHeading);
    else focusCurrentHeading();
  }

  function setupMissionMotion() {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const hero = document.querySelector(".hero-stage");
    if (hero instanceof HTMLElement && !reduceMotion && window.matchMedia("(pointer: fine)").matches) {
      hero.addEventListener("pointermove", (event) => {
        const bounds = hero.getBoundingClientRect();
        const x = Math.max(0, Math.min(100, ((event.clientX - bounds.left) / bounds.width) * 100));
        const y = Math.max(0, Math.min(100, ((event.clientY - bounds.top) / bounds.height) * 100));
        hero.style.setProperty("--pointer-x", `${x.toFixed(1)}%`);
        hero.style.setProperty("--pointer-y", `${y.toFixed(1)}%`);
      }, { passive: true });
    }

    const revealTargets = Array.from(document.querySelectorAll("[data-reveal]"));
    if (reduceMotion || typeof IntersectionObserver !== "function") {
      revealTargets.forEach((target) => target.setAttribute("data-reveal-state", "visible"));
    } else {
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.setAttribute("data-reveal-state", "visible");
          observer.unobserve(entry.target);
        });
      }, { rootMargin: "0px 0px -8%", threshold: 0.12 });
      revealTargets.forEach((target) => observer.observe(target));
    }

    const specimenButtons = Array.from(document.querySelectorAll("[data-gtm-specimen]"));
    const specimenPanels = Array.from(document.querySelectorAll("[data-specimen-panel]"));
    specimenButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const specimen = button.getAttribute("data-gtm-specimen");
        const commitSpecimen = () => {
          specimenButtons.forEach((candidate) => {
            candidate.setAttribute("aria-pressed", String(candidate === button));
          });
          specimenPanels.forEach((panel) => {
            panel.hidden = panel.getAttribute("data-specimen-panel") !== specimen;
          });
        };
        if (!reduceMotion && typeof document.startViewTransition === "function") {
          document.startViewTransition(commitSpecimen);
        } else {
          commitSpecimen();
        }
      });
    });
  }

  async function requestJson(path, options = {}) {
    const response = await window.fetch(path, {
      ...options,
      headers: tenantHeaders({ Accept: "application/json", "Content-Type": "application/json", ...(options.headers ?? {}) })
    });
    const payload = await response.json().catch(() => ({ error: "invalid_json_response" }));
    if (!response.ok) {
      const detail = payload.error ?? payload.message ?? `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return payload;
  }

  function tenantHeaders(headers = {}) {
    return state.tenantToken
      ? { ...headers, Authorization: `Bearer ${state.tenantToken}` }
      : { ...headers };
  }

  function renderTenantSessionStatus(message = null, status = "info") {
    const text = message ?? (state.tenantToken
      ? "Tenant principal active for this browser tab. Server-side authorization remains authoritative."
      : "No tenant principal active. Protected runs, artifacts, previews, events, memory, and bundles fail closed.");
    setFeedback("tenant-session-status", text, status);
  }

  function clearTenantBoundClientState() {
    disconnectTrajectory("Tenant session changed; event polling stopped.");
    state.runId = null;
    state.runStatus = null;
    state.lastEventId = 0;
    state.eventKeys.clear();
    state.productArtifact = null;
    state.signalArtifact = null;
    state.signalReceiptArtifact = null;
    state.previewReady = false;
    state.learningMemories = null;
    if (state.previewBlobUrl) {
      URL.revokeObjectURL(state.previewBlobUrl);
      state.previewBlobUrl = null;
    }
    renderProductArtifactStatus();
    updateArtifactBinding();
    updateBundleControl();
    saveRecoveryState();
  }

  function restoreTenantSession() {
    try {
      const token = window.sessionStorage.getItem(tenantSessionKey);
      if (typeof token === "string" && token.length >= 24 && token.length <= 512) {
        state.tenantToken = token;
      }
    } catch {
      state.tenantToken = null;
    }
    renderTenantSessionStatus(null, state.tenantToken ? "success" : "info");
  }

  async function activateLoopbackEvaluationSession() {
    if (state.tenantToken || !["127.0.0.1", "localhost"].includes(window.location.hostname)) return;
    try {
      const response = await window.fetch("/v1/local-evaluation-session", {
        headers: { Accept: "application/json" },
        cache: "no-store"
      });
      if (!response.ok) return;
      const payload = await response.json();
      const token = payload?.tenant_token;
      if (typeof token !== "string" || token.length < 24 || token.length > 512 || payload?.scope !== "loopback_evaluation_only") return;
      state.tenantToken = token;
      window.sessionStorage.setItem(tenantSessionKey, token);
      renderTenantSessionStatus("Loopback evaluation session active. Preset generation is ready; production deployments keep this bootstrap disabled.", "success");
      setFeedback("recipe-feedback", "Local evaluation session ready. Choose any recipe to run the Agent council and produce strategy, platform-native copy, three distinct image systems and two scored film cuts.", "success");
    } catch {
      // The optional loopback evaluator is disabled in production and must remain non-blocking.
    }
  }

  function renderJson(id, payload) {
    setText(id, JSON.stringify(payload, null, 2));
  }

  function newIdempotencyKey(prefix) {
    const randomPart = typeof window.crypto.randomUUID === "function"
      ? window.crypto.randomUUID()
      : Array.from(window.crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("");
    return `${prefix}-${randomPart}`;
  }

  async function sha256Text(value) {
    const digest = await window.crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  function frontierCard(title, body, meta = "") {
    const article = document.createElement("article");
    const heading = document.createElement("h3");
    heading.textContent = title;
    const paragraph = document.createElement("p");
    paragraph.textContent = body;
    article.append(heading, paragraph);
    if (meta) {
      const small = document.createElement("small");
      small.textContent = meta;
      article.append(small);
    }
    return article;
  }

  function renderFrontierSystem(rootId, value, meta) {
    const root = getElement(rootId);
    if (!root) return;
    const rows = value && typeof value === "object" && !Array.isArray(value) ? Object.entries(value) : [];
    root.replaceChildren(...rows.map(([key, raw]) => {
      const body = typeof raw === "string" ? raw : JSON.stringify(raw, null, 2);
      return frontierCard(key.replaceAll("_", " "), body, meta);
    }));
  }

  function renderFrontierAgentOrchestration(orchestration) {
    const root = getElement("frontier-agent-orchestration");
    if (!root) return;
    root.replaceChildren();
    if (!orchestration || typeof orchestration !== "object") {
      root.append(frontierCard("Agent receipt unavailable", "No orchestration receipt was returned; no Agent execution is claimed."));
      return;
    }

    const summary = document.createElement("div");
    summary.className = "frontier-agent-council__summary";
    const metrics = [
      [String(orchestration.candidate_blueprint_count ?? 0), "competing genomes"],
      [String(Array.isArray(orchestration.node_receipts) ? orchestration.node_receipts.length : 0), "specialist nodes"],
      [String(Array.isArray(orchestration.territories) ? orchestration.territories.length : 0), "distinct finalists"],
      [Number(orchestration.blueprint_design_space ?? 0).toLocaleString("en-US"), "possible systems"]
    ];
    metrics.forEach(([value, label]) => {
      const metric = document.createElement("article");
      const strong = document.createElement("strong");
      const small = document.createElement("small");
      strong.textContent = value;
      small.textContent = label;
      metric.append(strong, small);
      summary.append(metric);
    });

    const graph = document.createElement("ol");
    graph.className = "frontier-agent-graph";
    graph.setAttribute("aria-label", "Observed Agent execution graph");
    const receipts = Array.isArray(orchestration.node_receipts) ? orchestration.node_receipts : [];
    receipts.forEach((receipt) => {
      const node = document.createElement("li");
      const ordinal = document.createElement("span");
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      const agent = document.createElement("small");
      const output = document.createElement("p");
      const receiptLine = document.createElement("code");
      ordinal.textContent = String(receipt.order ?? "").padStart(2, "0");
      title.textContent = String(receipt.node_id ?? "Agent node").replaceAll("-", " ");
      agent.textContent = `${String(receipt.agent_id ?? "specialist agent").replaceAll("_", " ")} · ${receipt.loop_iterations ?? 0} loop${Number(receipt.loop_iterations) === 1 ? "" : "s"}`;
      output.textContent = String(receipt.output ?? "No output contract");
      receiptLine.textContent = `sha256:${String(receipt.output_sha256 ?? "").slice(0, 10)}…`;
      copy.append(title, agent, output, receiptLine);
      node.append(ordinal, copy);
      graph.append(node);
    });

    const boundary = document.createElement("p");
    boundary.className = "frontier-agent-council__boundary";
    const selectedScore = Array.isArray(orchestration.selection_scorecards)
      ? orchestration.selection_scorecards.find((row) => row?.territory_id === orchestration.selected_territory_id)
      : null;
    boundary.textContent = orchestration.deterministic_agent_node_execution_observed === true
      ? `Selected ${orchestration.selected_territory_id ?? "one route"} by declared-context fit ${selectedScore?.context_fit_score ?? "unavailable"}—not by hidden taste. Observed: deterministic Graph/Loop/Harness execution · ${receipts.length} content-addressed handoffs · external actions ${orchestration.external_action_count ?? 0}. Boundary: ${orchestration.truth_boundary ?? "no autonomous model reasoning claim"}`
      : "Agent execution was not observed; no orchestration claim is made.";
    root.append(summary, graph, boundary);
  }

  function frontierSurfaceLabel(surfaceId) {
    const labels = {
      linkedin: "LinkedIn",
      youtube: "YouTube",
      instagram: "Instagram",
      tiktok: "TikTok",
      google_search: "Google Search",
      perplexity_answers: "Perplexity Answers"
    };
    return labels[String(surfaceId ?? "")] ?? String(surfaceId ?? "Platform").replaceAll("_", " ");
  }

  function frontierSurfaceCopy(copySystem, surfaceId) {
    const keysBySurface = {
      linkedin: ["linkedin_post"],
      youtube: ["youtube_title", "youtube_opening"],
      instagram: ["instagram_caption"],
      tiktok: ["tiktok_opening_overlay", "tiktok_creator_prompt"],
      google_search: ["search_answer_lead"],
      perplexity_answers: ["search_answer_lead"]
    };
    return (keysBySurface[surfaceId] ?? [])
      .map((key) => copySystem?.[key])
      .filter((value) => typeof value === "string" && value.trim())
      .join("\n\n");
  }

  function renderFrontierPlatformKits(result) {
    const root = getElement("frontier-platform-kits");
    if (!root) return;
    root.replaceChildren();
    const assets = Array.isArray(result?.rendered_media?.assets) ? result.rendered_media.assets : [];
    const imageAssets = assets.filter((asset) => String(asset.media_type).startsWith("image/"));
    const videoAssets = assets.filter((asset) => String(asset.media_type).startsWith("video/"));
    const copySystem = result?.final_production?.channel_copy_system ?? {};
    const portfolioRows = Object.entries(result?.final_production?.channel_portfolio ?? {});
    const exclusivity = result?.rendered_media?.platform_asset_exclusivity ?? {};
    const imagegenSkill = result?.agent_orchestration?.imagegen_skill_contract ?? {};
    setText(
      "frontier-uniqueness-receipt",
      `imagegen skill ${imagegenSkill.capability_state ?? "unavailable"} · ${imagegenSkill.placement_brief_count ?? 0} visual briefs · ${exclusivity.unique_placement_count ?? 0} exclusive placements · ${exclusivity.creative_source_reuse_count ?? "?"} source reuse · ${exclusivity.cross_surface_copy_reuse_count ?? "?"} copy reuse · ${exclusivity.same_surface_cross_modality_source_reuse_count ?? "?"} same-platform cross-modal reuse`
    );

    imageAssets.forEach((imageAsset, index) => {
      const surfaceId = String(imageAsset.surface_id ?? "unknown_surface");
      const videoAsset = videoAssets.find((asset) => asset.surface_id === surfaceId);
      const [portfolioRole, portfolioRow] = portfolioRows.find(([, row]) => row?.surface_id === surfaceId) ?? ["platform_delivery", {}];
      const platformCopy = frontierSurfaceCopy(copySystem, surfaceId) || String(portfolioRow?.native_asset ?? "No platform-native text receipt returned.");
      const card = document.createElement("article");
      card.className = "frontier-platform-kit";
      card.dataset.surfaceId = surfaceId;

      const header = document.createElement("header");
      const identity = document.createElement("div");
      const ordinal = document.createElement("span");
      const titleWrap = document.createElement("div");
      const title = document.createElement("h3");
      const role = document.createElement("small");
      const state = document.createElement("span");
      ordinal.textContent = String(index + 1).padStart(2, "0");
      title.textContent = frontierSurfaceLabel(surfaceId);
      role.textContent = `${String(portfolioRole).replaceAll("_", " ")} · ${String(portfolioRow?.qualified_metric ?? "qualified review")}`;
      state.textContent = "Exclusive kit";
      titleWrap.append(title, role);
      identity.append(ordinal, titleWrap);
      header.append(identity, state);

      const job = document.createElement("p");
      job.className = "frontier-platform-kit__job";
      job.textContent = String(portfolioRow?.native_asset ?? "Platform-native delivery");

      const delivery = document.createElement("div");
      delivery.className = "frontier-platform-kit__delivery";
      const modules = [
        {
          number: "01",
          label: "Native text",
          title: String(imageAsset.copy_system_id ?? "surface-native copy").replaceAll("_", " "),
          body: platformCopy,
          meta: `copy sha256:${String(imageAsset.copy_payload_sha256 ?? "").slice(0, 10)}…`
        },
        {
          number: "02",
          label: "Image",
          title: String(imageAsset.visual_grammar_id ?? "visual system").replaceAll("_", " "),
          body: `${imageAsset.width ?? "?"}×${imageAsset.height ?? "?"} · ${String(imageAsset.filename ?? "PNG")}`,
          meta: `binary sha256:${String(imageAsset.content_sha256 ?? "").slice(0, 10)}…`
        },
        videoAsset ? {
          number: "03",
          label: "Film",
          title: String(videoAsset.copy_system_id ?? "platform film").replaceAll("_", " "),
          body: `${videoAsset.duration_seconds ?? "?"} sec · ${videoAsset.width ?? "?"}×${videoAsset.height ?? "?"} · ${String(videoAsset.visual_grammar_id ?? "film grammar").replaceAll("_", " ")}`,
          meta: `binary sha256:${String(videoAsset.content_sha256 ?? "").slice(0, 10)}…`
        } : {
          number: "03",
          label: "Film",
          title: "Not selected for this surface",
          body: "This search surface ships a persistent editorial answer, not a feed video. The omission is a channel decision, not an unavailable renderer.",
          meta: "native-format discipline"
        }
      ];
      modules.forEach((row) => {
        const module = document.createElement("section");
        module.dataset.kitModality = row.label.toLowerCase();
        const marker = document.createElement("span");
        const moduleCopy = document.createElement("div");
        const eyebrow = document.createElement("small");
        const heading = document.createElement("strong");
        const body = document.createElement("p");
        const meta = document.createElement("code");
        marker.textContent = row.number;
        eyebrow.textContent = row.label;
        heading.textContent = row.title;
        body.textContent = row.body;
        meta.textContent = row.meta;
        moduleCopy.append(eyebrow, heading, body, meta);
        module.append(marker, moduleCopy);
        delivery.append(module);
      });

      const footer = document.createElement("footer");
      const release = document.createElement("div");
      const releaseLabel = document.createElement("small");
      const releaseState = document.createElement("strong");
      const inspect = document.createElement("button");
      releaseLabel.textContent = "04 · Release gate";
      releaseState.textContent = String(portfolioRow?.release_state ?? "draft_for_human_review").replaceAll("_", " ");
      release.append(releaseLabel, releaseState);
      inspect.type = "button";
      inspect.className = "button button--secondary pressable";
      const boundFileCount = [imageAsset, videoAsset].filter(Boolean).length;
      inspect.textContent = `Inspect ${boundFileCount} live file${boundFileCount === 1 ? "" : "s"}`;
      inspect.addEventListener("click", () => {
        frontierPendingSurfaceFocus = surfaceId;
        selectFrontierOutputTab("assets");
        if (!focusFrontierSurfaceAssets(surfaceId, true)) {
          window.setTimeout(() => focusFrontierSurfaceAssets(surfaceId, true), 40);
        }
      });
      footer.append(release, inspect);
      card.append(header, job, delivery, footer);
      root.append(card);
    });
  }

  function focusFrontierSurfaceAssets(surfaceId, shouldScroll = false) {
    const cards = Array.from(document.querySelectorAll(".frontier-media-card"));
    cards.forEach((node) => node.removeAttribute("data-surface-focus"));
    const matches = cards.filter((node) => node.dataset.surfaceId === surfaceId);
    matches.forEach((node) => node.setAttribute("data-surface-focus", "true"));
    if (matches.length) frontierPendingSurfaceFocus = null;
    if (shouldScroll) {
      matches[0]?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "center" });
    }
    return matches.length;
  }

  async function frontierBriefFromForm(form) {
    const values = Object.fromEntries(new FormData(form).entries());
    const identitySource = JSON.stringify(values, Object.keys(values).sort());
    const identity = await sha256Text(identitySource);
    return {
      identity,
      brief: {
        brief_id: `frontier-${identity.slice(0, 24)}`,
        business_model: String(values.business_model ?? ""),
        industry: String(values.industry ?? "").trim(),
        category: String(values.category ?? "").trim(),
        lifecycle: String(values.lifecycle ?? ""),
        product_surface: String(values.product_surface ?? "").trim(),
        audience: String(values.audience ?? "").trim(),
        audience_problem: String(values.audience_problem ?? "").trim(),
        audience_outcome: String(values.audience_outcome ?? "").trim(),
        product_truth: String(values.product_truth ?? "").trim(),
        brand_voice: String(values.brand_voice ?? "").trim(),
        budget: String(values.budget ?? ""),
        market: String(values.market ?? "").trim(),
        primary_goal: String(values.primary_goal ?? "").trim(),
        recent_organic_signal_context: "Server binds the verified public-signal context or the declared preset boundary.",
        signal_provenance: "Server-side source and renderer receipts remain authoritative."
      }
    };
  }

  function clearFrontierMediaUrls() {
    frontierMediaUrls.splice(0).forEach((url) => URL.revokeObjectURL(url));
  }

  async function renderFrontierMedia(manifest) {
    const gallery = getElement("frontier-media-gallery");
    const badge = getElement("frontier-media-status");
    if (!gallery || !badge) return;
    clearFrontierMediaUrls();
    gallery.replaceChildren();
    const assets = Array.isArray(manifest?.assets) ? manifest.assets : [];
    if (!assets.length) {
      badge.textContent = "No binary receipt";
      badge.className = "status-badge status-badge--blocked";
      return;
    }
    badge.textContent = `Loading ${assets.length} assets`;
    badge.className = "status-badge status-badge--waiting";
    for (const asset of assets) {
      const response = await window.fetch(String(asset.url ?? ""), {
        headers: tenantHeaders({ Accept: String(asset.media_type ?? "application/octet-stream") })
      });
      if (!response.ok) throw new Error(`media ${asset.role ?? "asset"} unavailable: HTTP ${response.status}`);
      const objectUrl = URL.createObjectURL(await response.blob());
      frontierMediaUrls.push(objectUrl);
      const figure = document.createElement("figure");
      figure.className = `frontier-media-card ${String(asset.media_type).startsWith("video/") ? "frontier-media-card--video" : ""}`;
      figure.dataset.surfaceId = String(asset.surface_id ?? "unknown_surface");
      figure.id = `frontier-asset-${String(asset.role ?? "campaign-asset").replace(/[^a-z0-9-]+/gi, "-").toLowerCase()}`;
      const stage = document.createElement("div");
      stage.className = "frontier-media-card__stage";
      if (String(asset.media_type).startsWith("video/")) {
        const video = document.createElement("video");
        video.src = objectUrl;
        video.controls = true;
        video.muted = true;
        video.loop = true;
        video.playsInline = true;
        video.preload = "metadata";
        stage.append(video);
      } else {
        const image = document.createElement("img");
        image.src = objectUrl;
        image.alt = `${String(asset.role ?? "Campaign").replaceAll("_", " ")} generated campaign asset`;
        image.loading = "eager";
        stage.append(image);
      }
      const caption = document.createElement("figcaption");
      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = `${String(asset.surface_id ?? "surface").replaceAll("_", " ")} · ${String(asset.role ?? "campaign asset").replaceAll("_", " ")}`;
      const meta = document.createElement("small");
      meta.textContent = `${String(asset.visual_grammar_id ?? "visual grammar unavailable").replaceAll("_", " ")} · ${String(asset.copy_system_id ?? "copy system unavailable").replaceAll("_", " ")} · ${asset.width ?? "?"}×${asset.height ?? "?"} · ${Math.max(1, Math.round(Number(asset.bytes ?? 0) / 1024))} KB · sha256:${String(asset.content_sha256 ?? "").slice(0, 12)}`;
      copy.append(title, meta);
      const download = document.createElement("a");
      download.href = objectUrl;
      download.download = String(asset.filename ?? "prooflaunch-asset");
      download.className = "button button--secondary";
      download.textContent = "Download";
      caption.append(copy, download);
      figure.append(stage, caption);
      gallery.append(figure);
    }
    badge.textContent = `${assets.length}/${assets.length} binaries rendered`;
    badge.className = "status-badge status-badge--passed";
    if (frontierPendingSurfaceFocus) focusFrontierSurfaceAssets(frontierPendingSurfaceFocus, true);
    setText("frontier-output-asset-count", String(assets.length));
    const imageMasters = Array.isArray(manifest.exclusive_image_master_receipts) ? manifest.exclusive_image_master_receipts : [];
    const filmMasters = Array.isArray(manifest.exclusive_video_master_receipts) ? manifest.exclusive_video_master_receipts : [];
    const mastersVerified = [...imageMasters, ...filmMasters].length === Number(manifest.verified_model_master_asset_count ?? 0)
      && [...imageMasters, ...filmMasters].every((row) => row?.model_inference_observed === true);
    setText("frontier-media-boundary", mastersVerified
      ? `Verified imagegen masters used once each: ${manifest.verified_model_master_asset_count ?? 0} · ${imageMasters.length} image masters + ${filmMasters.length} six-scene film storyboards · this click produced 3 platform-specific PNGs + ${manifest.video_platform_cut_count ?? 0} independently edited H.264/AAC films / ${manifest.total_rendered_video_shots ?? 0} exclusive generated shots · procedural image sources=${manifest.exclusive_procedural_visual_source_count ?? "?"} · same-platform cross-modal source reuse=${manifest.platform_asset_exclusivity?.same_surface_cross_modality_source_reuse_count ?? "?"} · video-diffusion inference=${manifest.video_model_inference_claimed === true} · human release required.`
      : `${manifest.renderer ?? "Observed renderer"} · no verified model-source receipt · PNG=${manifest.binary_image_rendering_observed === true} · MP4=${manifest.binary_video_rendering_observed === true} · human release required.`);
    renderFrontierInspector(frontierCurrentResult, manifest);
  }

  async function runRealtimePresetCampaign(form, trigger) {
    const badge = getElement("frontier-gtm-status");
    try {
      const { identity, brief } = await frontierBriefFromForm(form);
      setFrontierFlowStep("brief", "complete", "Brief sealed");
      setFrontierFlowStep("strategy", "running", "Diagnosing");
      setFrontierFlowStep("concept", "waiting", "Awaiting strategy");
      setFrontierFlowStep("production", "waiting", "0 files");
      setFrontierFlowStep("audit", "waiting", "Not run");
      if (badge) {
        badge.textContent = "Rendering live assets";
        badge.className = "status-badge status-badge--waiting";
      }
      setFeedback("frontier-gtm-feedback", "Running market diagnosis, twelve-genome strategy debate, platform language, multimodal direction, adversarial cut and release harness; then rendering three platform-specific image systems and three independently edited six-scene film cuts. No external action is permitted.", "info");
      const result = await requestJson("/v1/realtime-preset-campaigns", {
        method: "POST",
        headers: { "Idempotency-Key": `realtime-preset-v8-${identity}` },
        body: JSON.stringify({ brief })
      });
      renderFrontierRun(result);
      await renderFrontierMedia(result.rendered_media);
      setFrontierFlowStep("strategy", "complete", `${result.agent_orchestration?.candidate_blueprint_count ?? 0} genomes debated`);
      setFrontierFlowStep("concept", "complete", "3 systems · 4 axes distinct");
      setFrontierFlowStep("production", "complete", `3 platform kits · ${result.rendered_media?.asset_count ?? 0} unique files`);
      setFrontierFlowStep("audit", "complete", "Preflight passed");
      setFrontierFlowStep("release", "gated", "Human decision");
      selectFrontierOutputTab("assets");
      if (badge) {
        badge.textContent = "Campaign rendered";
        badge.className = "status-badge status-badge--passed";
      }
      setFeedback("frontier-gtm-feedback", `Agent council sealed · ${result.agent_orchestration?.candidate_blueprint_count ?? 0} genomes · ${result.agent_orchestration?.node_receipts?.length ?? 0} specialist nodes · ${result.rendered_media?.asset_count ?? 0} live-rendered assets · envelope sha256:${result.envelope_sha256 ?? "unavailable"} · release still human-gated.`, "success");
      setFeedback("recipe-feedback", "Creative council completed: the Agent graph, three axis-distinct systems, platform-native copy, three visually distinct PNGs and three playable six-scene platform-native films are visible below.", "success");
    } catch (error) {
      setFrontierFlowStep("strategy", "failed", "Failed closed");
      if (badge) {
        badge.textContent = "Render failed closed";
        badge.className = "status-badge status-badge--blocked";
      }
      setFeedback("frontier-gtm-feedback", `Realtime preset unavailable: ${String(error.message ?? error)}. No fake media was substituted.`, "error");
      setFeedback("recipe-feedback", "Preset render failed closed; no generated result was invented.", "error");
    } finally {
      trigger?.removeAttribute("data-running");
    }
  }

  function renderFrontierRun(result) {
    const root = getElement("frontier-gtm-result");
    if (root) root.hidden = false;
    frontierCurrentResult = result;
    const assetCount = Number(result.rendered_media?.asset_count ?? 0);
    setText("frontier-output-title", String(result.final_production?.campaign_platform ?? "Production package ready"));
    const quality = result.quality_control ?? {};
    const qualityLabel = quality.target_tier === "production_review_candidate" && quality.human_craft_approved === false
      ? "Production candidate · not yet human-validated"
      : "Production candidate";
    setText("frontier-output-meta", `${qualityLabel} · ${String(result.brief?.market ?? "Declared market")} · ${String(result.brief?.business_model ?? "GTM").toUpperCase()} · ${assetCount} rendered asset${assetCount === 1 ? "" : "s"} · named-human release required`);
    setText("frontier-output-asset-count", String(assetCount));
    renderFrontierInspector(result);
    renderFrontierAgentOrchestration(result.agent_orchestration);
    const strategyRoot = getElement("frontier-strategy-summary");
    const strategy = result.strategy ?? {};
    if (strategyRoot) {
      strategyRoot.replaceChildren(frontierCard(
        String(strategy.non_consensus_bet ?? "Strategy unavailable"),
        String(strategy.market_diagnosis ?? ""),
        [strategy.primary_distribution_surface, strategy.secondary_distribution_surface,
          strategy.primary_search_surface, strategy.primary_geo_surface].filter(Boolean).join(" · ")
      ));
    }
    const conceptRoot = getElement("frontier-concept-summary");
    if (conceptRoot) {
      const selected = result.jury?.selected_territory_id;
      const territories = Array.isArray(result.concepts?.territories) ? result.concepts.territories : [];
      conceptRoot.replaceChildren(...territories.map((territory) => frontierCard(
        `${territory.campaign_name ?? territory.territory_id}${territory.territory_id === selected ? " · SELECTED" : ""}`,
        String(territory.first_line ?? ""),
        `${String(territory.tone_id ?? "tone unknown").replaceAll("_", " ")} · ${String(territory.visual_grammar_id ?? "visual unknown").replaceAll("_", " ")} · ${String(territory.narrative_grammar_id ?? "narrative unknown").replaceAll("_", " ")} · ${territory.primary_platform ?? ""}`
      )));
    }
    const channelRoot = getElement("frontier-channel-summary");
    if (channelRoot) {
      const portfolio = result.final_production?.channel_portfolio ?? {};
      channelRoot.replaceChildren(...Object.entries(portfolio).map(([key, row]) => frontierCard(
        `${key.replaceAll("_", " ")} · ${row?.surface_id ?? "unknown"}`,
        String(row?.native_asset ?? ""),
        `${row?.qualified_metric ?? ""} · ${row?.release_state ?? ""}`
      )));
    }
    renderFrontierSystem("frontier-copy-summary", {
      ...(result.final_production?.primary_native_text ?? {}),
      ...(result.final_production?.channel_copy_system ?? {})
    }, "Platform-native production candidate · named-human craft review required");
    renderFrontierSystem("frontier-image-summary", result.final_production?.image_system, result.rendered_media ? "Direction bound to rendered binaries below" : "Server-generated direction · media execution separately observed");
    renderFrontierSystem("frontier-video-summary", result.final_production?.video_system, result.rendered_media ? "Three platform-native six-scene film systems bound to the rendered MP4 cuts below" : "Server-generated film system · media execution separately observed");
    renderFrontierPlatformKits(result);
    const auditRoot = getElement("frontier-audit-summary");
    const audit = result.final_audit ?? {};
    if (auditRoot) {
      const failures = ["blocking_defects", "claim_violations", "platform_mismatches", "generic_language",
        "cross_modal_breaks", "zero_budget_breaks", "skill_gate_failures", "surface_gate_failures",
        "evidence_gate_failures"].reduce((sum, key) => sum + (Array.isArray(audit[key]) ? audit[key].length : 0), 0);
      const gates = quality.gates && typeof quality.gates === "object" ? Object.values(quality.gates) : [];
      const passedGates = gates.filter((value) => value === true).length;
      const humanGates = Array.isArray(quality.human_gates_remaining) ? quality.human_gates_remaining : [];
      auditRoot.replaceChildren(frontierCard(
        String(result.release_review_status ?? "Unknown release state").replaceAll("_", " "),
        `Final audit: ${String(audit.status ?? "unknown")} · unresolved failures: ${failures}`,
        `${result.activated_role_count ?? 0} roles · ${result.activated_skill_card_count ?? 0} skill cards · ${result.named_product_stress_count ?? 0} named-product targets · publish/send/spend disabled`
      ), frontierCard(
        qualityLabel,
        `${passedGates}/${gates.length} mechanical quality gates passed · human craft approval: ${quality.human_craft_approved === true ? "approved" : "pending"}`,
        humanGates.length ? `Remaining: ${humanGates.join(" · ")}` : "No human gate declaration found"
      ));
    }
    renderJson("frontier-run-json", result);
    document.querySelectorAll("[data-frontier-recipe]").forEach((button) => button.removeAttribute("data-running"));
    setFeedback("recipe-feedback", result.rendered_media ? "Production candidate generated with differentiated strategy, platform-native copy, three image systems, three six-scene film cuts and observed binaries. Human craft review and live-market validation remain required." : "Strategy candidate generated. Review the platform copy, creative system and audit boundary before production.", "success");
    root?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }

  function statusMarkerClass(status) {
    if (status === "delivered") return "status-badge--passed";
    if (["rejected", "failed"].includes(status)) return "status-badge--failed";
    if (["blocked", "cancelled"].includes(status)) return "status-badge--blocked";
    if (status === "awaiting_release") return "status-badge--required";
    return "status-badge--waiting";
  }

  function setRunStatus(status) {
    if (typeof status !== "string" || !status) return;
    state.runStatus = status;
    const badge = getElement("run-status-badge");
    if (badge) {
      badge.textContent = status.replaceAll("_", " ");
      badge.className = `status-badge ${statusMarkerClass(status)}`;
    }
    setText("inspector-run-id", state.runId ?? "Not created");
    setText("inspector-run-stage", status.replaceAll("_", " "));
    setText("inspector-run-summary", terminalRunStatuses.has(status)
      ? `The governed run reached ${status.replaceAll("_", " ")}. Inspect the trajectory and evidence before any next action.`
      : `The governed run is ${status.replaceAll("_", " ")}. Execution remains bounded by policy and human release.`);
    const inspectorRunBadge = getElement("inspector-run-badge");
    if (inspectorRunBadge) {
      inspectorRunBadge.textContent = status.replaceAll("_", " ");
      inspectorRunBadge.className = `status-badge ${statusMarkerClass(status)}`;
    }
    const approvalButton = getElement("approval-submit");
    if (approvalButton instanceof HTMLButtonElement) {
      if (status !== "awaiting_release") state.previewReady = false;
      approvalButton.disabled = status !== "awaiting_release" || !state.previewReady;
    }
    updateBundleControl();
    updateCreateControls();
    saveRecoveryState();
  }

  function updateBundleControl() {
    const button = getElement("bundle-download");
    if (!(button instanceof HTMLButtonElement)) return;
    const delivered = state.runStatus === "delivered";
    button.hidden = !delivered;
    button.disabled = !delivered;
    if (!delivered) {
      setText("ledger-output", "Bundle download appears only after the run reaches delivered.");
    }
  }

  function updateArtifactBinding() {
    if (!state.productArtifact) {
      setText("launch-artifact-binding", "Product image: not staged. Return to Evidence to hash and upload one PNG.");
      return;
    }
    const mode = state.productArtifact.deduplicated ? "already present" : "uploaded";
    setText(
      "launch-artifact-binding",
      `Product image: ${state.productArtifact.name} · sha256:${state.productArtifact.sha256} · ${mode}`
    );
    if (!state.signalArtifact || !state.signalReceiptArtifact) {
      setText("launch-signal-binding", "Creative signals: optional · snapshot and matching receipt not staged.");
    } else {
      const signalMode = state.signalArtifact.deduplicated ? "already present" : "uploaded";
      const receiptMode = state.signalReceiptArtifact.deduplicated ? "already present" : "uploaded";
      setText(
        "launch-signal-binding",
        `Creative signals: ${state.signalArtifact.name} · sha256:${state.signalArtifact.sha256} · ${signalMode}; receipt ${state.signalReceiptArtifact.name} · sha256:${state.signalReceiptArtifact.sha256} · ${receiptMode}`
      );
    }
  }

  async function sha256Hex(file) {
    const bytes = await file.arrayBuffer();
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  }

  function stableJsonValue(value) {
    if (Array.isArray(value)) return value.map(stableJsonValue);
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.keys(value).sort().map((key) => [key, stableJsonValue(value[key])])
      );
    }
    return value;
  }

  async function sha256Text(text) {
    const bytes = new TextEncoder().encode(text);
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
  }

  async function blindReviewDigest(review) {
    const material = { ...review, review_content_sha256: null };
    return sha256Text(JSON.stringify(stableJsonValue(material)));
  }

  async function assertPng(file) {
    if (file.size <= 0 || file.size > 25 * 1024 * 1024) {
      throw new Error("PNG must be between 1 byte and 25 MB");
    }
    const signature = new Uint8Array(await file.slice(0, 8).arrayBuffer());
    const expected = [137, 80, 78, 71, 13, 10, 26, 10];
    if (signature.length !== expected.length || signature.some((value, index) => value !== expected[index])) {
      throw new Error("Selected file is not a valid PNG byte stream");
    }
  }

  async function stageProductImage(file) {
    await assertPng(file);
    const digest = await sha256Hex(file);
    const artifactPath = `/v1/artifacts/${digest}`;
    const headResponse = await window.fetch(artifactPath, { method: "HEAD", headers: tenantHeaders() });
    let deduplicated = false;
    if (headResponse.ok) {
      deduplicated = true;
    } else if (headResponse.status === 404) {
      const putResponse = await window.fetch(artifactPath, {
        method: "PUT",
        headers: tenantHeaders({ "Content-Type": "image/png" }),
        body: file
      });
      if (!putResponse.ok) {
        const payload = await putResponse.json().catch(() => null);
        throw new Error(payload?.error ?? `artifact upload failed with HTTP ${putResponse.status}`);
      }
    } else {
      throw new Error(`artifact lookup failed with HTTP ${headResponse.status}`);
    }
    return { sha256: digest, name: file.name, size: file.size, deduplicated };
  }

  async function stageCreativeSignalCollectionReceipt(file, snapshotContentSha256) {
    if (!(file instanceof File) || file.size <= 0 || file.size > 1_000_000) {
      throw new Error("Creative signal collection receipt must be a non-empty JSON file up to 1 MB");
    }
    let payload;
    try {
      payload = JSON.parse(await file.text());
    } catch {
      throw new Error("Creative signal collection receipt must be valid UTF-8 JSON");
    }
    if (
      payload?.schema !== "ProofLaunchOpenSourceSocialCollectionRunV2" ||
      payload?.status !== "completed" ||
      payload?.derived_signal_filter_passed !== true ||
      payload?.training_admitted !== false ||
      payload?.strategy_mutation_executed !== false ||
      payload?.external_publish_executed !== false ||
      payload?.creative_signal_snapshot_sha256 !== snapshotContentSha256 ||
      !Array.isArray(payload?.runs) ||
      payload.runs.length < 1 ||
      payload.runs.some((run) => (
        run?.status !== "completed" ||
        run?.captcha_or_auth_bypass_attempted !== false ||
        run?.raw_content_training_admitted !== false
      )) ||
      !/^[0-9a-f]{64}$/.test(payload?.receipt_sha256 ?? "") ||
      !/^[0-9a-f]{64}$/.test(payload?.plan_sha256 ?? "")
    ) {
      throw new Error("Creative signal collection receipt failed the browser provenance preflight");
    }
    const digest = await sha256Hex(file);
    const artifactPath = `/v1/artifacts/${digest}`;
    const headResponse = await window.fetch(artifactPath, { method: "HEAD", headers: tenantHeaders() });
    let deduplicated = false;
    if (headResponse.ok) {
      deduplicated = true;
    } else if (headResponse.status === 404) {
      const putResponse = await window.fetch(artifactPath, {
        method: "PUT",
        headers: tenantHeaders({ "Content-Type": "application/json" }),
        body: file
      });
      if (!putResponse.ok) {
        const response = await putResponse.json().catch(() => null);
        throw new Error(response?.error ?? `signal receipt upload failed with HTTP ${putResponse.status}`);
      }
    } else {
      throw new Error(`signal receipt lookup failed with HTTP ${headResponse.status}`);
    }
    return { sha256: digest, name: file.name, size: file.size, deduplicated };
  }

  async function stageCreativeSignalSnapshot(file) {
    if (!(file instanceof File) || file.size <= 0 || file.size > 1_000_000) {
      throw new Error("Creative signal snapshot must be a non-empty JSON file up to 1 MB");
    }
    let payload;
    try {
      payload = JSON.parse(await file.text());
    } catch {
      throw new Error("Creative signal snapshot must be valid UTF-8 JSON");
    }
    if (
      payload?.schema !== "ProofLaunchCreativeSignalSnapshotV1" ||
      payload?.contains_personal_data !== false ||
      payload?.contains_copied_creative !== false ||
      !Array.isArray(payload?.signals) ||
      payload.signals.length < 1 ||
      payload.signals.length > 500
    ) {
      throw new Error("Creative signal snapshot failed the browser safety preflight");
    }
    const digest = await sha256Hex(file);
    const artifactPath = `/v1/artifacts/${digest}`;
    const headResponse = await window.fetch(artifactPath, { method: "HEAD", headers: tenantHeaders() });
    let deduplicated = false;
    if (headResponse.ok) {
      deduplicated = true;
    } else if (headResponse.status === 404) {
      const putResponse = await window.fetch(artifactPath, {
        method: "PUT",
        headers: tenantHeaders({ "Content-Type": "application/json" }),
        body: file
      });
      if (!putResponse.ok) {
        const response = await putResponse.json().catch(() => null);
        throw new Error(response?.error ?? `signal upload failed with HTTP ${putResponse.status}`);
      }
    } else {
      throw new Error(`signal lookup failed with HTTP ${headResponse.status}`);
    }
    const contentSha256 = await sha256Text(JSON.stringify(stableJsonValue(payload)));
    return { sha256: digest, contentSha256, name: file.name, size: file.size, deduplicated };
  }

  function renderProductArtifactStatus(message = null) {
    const list = getElement("selected-file-list");
    if (!list) return;
    const item = document.createElement("li");
    if (!state.productArtifact) {
      item.className = "empty-row";
      item.textContent = message ?? "No product PNG staged.";
      list.replaceChildren(item);
      return;
    }
    const name = document.createElement("span");
    const metadata = document.createElement("span");
    name.textContent = state.productArtifact.name;
    metadata.className = "mono-value";
    metadata.textContent = `sha256:${state.productArtifact.sha256} · ${Math.max(1, Math.round(state.productArtifact.size / 1024))} KB`;
    item.append(name, metadata);
    list.replaceChildren(item);
  }

  function replaceList(id, rows, emptyText, formatter) {
    const list = getElement(id);
    if (!list) return;
    const safeRows = Array.isArray(rows) ? rows : [];
    if (safeRows.length === 0) {
      const item = document.createElement("li");
      item.textContent = emptyText;
      list.replaceChildren(item);
      return;
    }
    list.replaceChildren(...safeRows.map((row) => {
      const item = document.createElement("li");
      item.textContent = formatter(row);
      return item;
    }));
  }

  function safePreviewUrl(candidate) {
    if (typeof candidate !== "string" || !state.runId) return null;
    try {
      const url = new URL(candidate, window.location.origin);
      const prefix = `/v1/runs/${encodeURIComponent(state.runId)}/`;
      return url.origin === window.location.origin && url.pathname.startsWith(prefix) ? url.pathname + url.search : null;
    } catch {
      return null;
    }
  }

  async function renderSafePreviewAsset(preview) {
    const container = getElement("preview-asset");
    if (!container) return;
    if (state.previewBlobUrl) {
      URL.revokeObjectURL(state.previewBlobUrl);
      state.previewBlobUrl = null;
    }
    const assets = Array.isArray(preview.assets) ? preview.assets : [];
    const candidate = assets.find((asset) => asset && typeof asset === "object" && (asset.preview_url || asset.url));
    const url = safePreviewUrl(candidate?.preview_url ?? candidate?.url ?? preview.preview_url);
    if (!url) {
      const note = document.createElement("p");
      note.textContent = assets.length > 0
        ? `${assets.length} generated artifact record${assets.length === 1 ? "" : "s"}; no same-origin PNG preview was exposed.`
        : "No generated asset preview is available.";
      container.replaceChildren(note);
      return;
    }
    try {
      const response = await window.fetch(url, { headers: tenantHeaders({ Accept: "image/png" }) });
      const contentType = response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase();
      if (!response.ok || contentType !== "image/png") {
        throw new Error("preview endpoint did not return PNG");
      }
      const blob = await response.blob();
      state.previewBlobUrl = URL.createObjectURL(blob);
      const image = document.createElement("img");
      image.src = state.previewBlobUrl;
      image.alt = "Agent-generated campaign preview awaiting human release decision";
      image.loading = "lazy";
      container.replaceChildren(image);
    } catch (error) {
      const note = document.createElement("p");
      note.textContent = `Safe preview unavailable: ${String(error.message ?? error)}`;
      container.replaceChildren(note);
    }
  }

  function renderChannelPortfolio(portfolio) {
    const grid = getElement("channel-portfolio-grid");
    const status = getElement("channel-portfolio-status");
    const rows = Array.isArray(portfolio?.portfolio) ? portfolio.portfolio : [];
    const allowedStates = new Set(["focus", "test", "observe", "excluded"]);
    const validRows = rows.filter((row) => (
      row &&
      typeof row === "object" &&
      typeof row.channel === "string" &&
      /^[a-z_]{3,40}$/.test(row.channel) &&
      Number.isInteger(row.score) &&
      row.score >= 0 &&
      row.score <= 100 &&
      allowedStates.has(row.activation_state) &&
      typeof row.minimum_viable_asset === "string"
    ));
    if (!grid || portfolio?.schema !== "ProofLaunchChannelPortfolioV1" || validRows.length !== 12) {
      if (status) {
        status.textContent = "Portfolio unavailable";
        status.className = "status-badge status-badge--blocked";
      }
      return;
    }
    const humanize = (value) => value.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    grid.replaceChildren(...validRows.map((row) => {
      const article = document.createElement("article");
      const mark = document.createElement("span");
      const title = document.createElement("strong");
      const detail = document.createElement("small");
      const stateLabel = document.createElement("em");
      article.setAttribute("role", "listitem");
      article.className = `channel-card channel-card--${row.activation_state}`;
      mark.textContent = row.channel.split("_").map((part) => part[0]).join("").slice(0, 3).toUpperCase();
      title.textContent = humanize(row.channel);
      detail.textContent = row.minimum_viable_asset;
      stateLabel.textContent = `${row.activation_state.toUpperCase()} · ${row.score}`;
      article.append(mark, title, detail, stateLabel);
      return article;
    }));
    const focus = Array.isArray(portfolio.focus_channels) ? portfolio.focus_channels : [];
    setText("channel-strategy-focus", focus.map(humanize).join(" + ") || "No focus selected");
    setText(
      "channel-strategy-market",
      `${humanize(String(portfolio.business_model ?? "unknown"))} · ${humanize(String(portfolio.lifecycle ?? "unknown"))} · ${humanize(String(portfolio.decision_context?.company_scale ?? "unknown"))}`
    );
    setText(
      "channel-strategy-budget",
      `${humanize(String(portfolio.budget ?? "unknown"))} · ${humanize(String(portfolio.decision_confidence ?? "unknown"))} confidence · ${Number.isInteger(portfolio.focus_margin_points) ? portfolio.focus_margin_points : 0} point focus margin · automatic allocation disabled`
    );
    if (status) {
      status.textContent = `2 focus · ${portfolio.test_channels?.length ?? 0} bounded tests · 0 auto activations`;
      status.className = "status-badge status-badge--verified";
    }
  }

  function renderIndustryGTMProfile(profile) {
    const status = getElement("industry-profile-status");
    const arraysValid = [
      profile?.decision_unit,
      profile?.evidence_ladder,
      profile?.unit_economics_metrics,
      profile?.feedback_signals,
      profile?.creative_constraints
    ].every((values) => Array.isArray(values) && values.length > 0 && values.every((value) => typeof value === "string"));
    const valid = profile?.schema === "ProofLaunchIndustryGTMProfileV1" &&
      typeof profile.industry_archetype === "string" &&
      typeof profile.buying_motion === "string" &&
      typeof profile.conversion_unit === "string" &&
      typeof profile.zero_budget_growth_engine === "string" &&
      typeof profile.proof_gate === "string" &&
      typeof profile.lifecycle_operating_focus === "string" &&
      profile.external_activation_executed === false &&
      profile.automatic_budget_allocation_enabled === false &&
      arraysValid;
    if (!valid) {
      if (status) {
        status.textContent = "Industry profile unavailable";
        status.className = "status-badge status-badge--blocked";
      }
      return;
    }
    const humanize = (value) => String(value).split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    setText("industry-profile-archetype", humanize(profile.industry_archetype));
    setText(
      "industry-profile-fit",
      `${humanize(profile.business_model)} · ${profile.business_model_fit ? "model fit" : "fit requires review"} · ${humanize(profile.classification_status)}`
    );
    setText("industry-profile-conversion", profile.conversion_unit);
    setText("industry-profile-proof", profile.proof_gate);
    setText("industry-profile-engine", profile.zero_budget_growth_engine);
    setText("industry-profile-focus", `${humanize(profile.lifecycle)} · ${profile.lifecycle_operating_focus}`);
    setText("industry-profile-economics", profile.unit_economics_metrics.map(humanize).join(" · "));
    setText("industry-profile-feedback", profile.feedback_signals.map(humanize).join(" · "));
    if (status) {
      const confirmation = profile.human_classification_confirmation_required === true;
      status.textContent = confirmation ? "Human classification confirmation required" : "Industry contract compiled · 0 auto activations";
      status.className = confirmation ? "status-badge status-badge--required" : "status-badge status-badge--verified";
    }
  }

  function renderContentCalendar(calendar) {
    const list = getElement("content-calendar-list");
    const status = getElement("content-calendar-status");
    const slots = Array.isArray(calendar?.slots) ? calendar.slots : [];
    const valid = calendar?.schema === "ProofLaunchContentCalendarV1" && slots.length === 7 && slots.every((slot) => (
      slot &&
      typeof slot === "object" &&
      Number.isInteger(slot.sequence) &&
      typeof slot.channel === "string" &&
      typeof slot.scheduled_local === "string" &&
      typeof slot.review_due_at_utc === "string" &&
      slot.status === "draft_pending_human_review" &&
      slot.external_activation_executed === false
    ));
    if (!list || !valid) {
      if (status) {
        status.textContent = "Calendar unavailable";
        status.className = "status-badge status-badge--blocked";
      }
      return;
    }
    const humanize = (value) => String(value).split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    list.replaceChildren(...slots.map((slot) => {
      const item = document.createElement("li");
      const sequence = document.createElement("span");
      const body = document.createElement("div");
      const title = document.createElement("strong");
      const detail = document.createElement("small");
      const gate = document.createElement("em");
      sequence.textContent = String(slot.sequence).padStart(2, "0");
      title.textContent = `${humanize(slot.channel)} · ${slot.theme}`;
      detail.textContent = `${slot.scheduled_local} · review by ${slot.review_due_at_utc}`;
      gate.textContent = "HUMAN REVIEW";
      body.append(title, detail);
      item.append(sequence, body, gate);
      return item;
    }));
    if (status) {
      status.textContent = `7 pending · ${calendar.timezone} · 0 auto publishes`;
      status.className = "status-badge status-badge--verified";
    }
  }

  function renderBreakoutGrowthLoop(loop) {
    const list = getElement("breakout-loop-steps");
    const status = getElement("breakout-loop-status");
    const thesis = getElement("breakout-loop-thesis");
    const expected = ["sense", "make", "seed", "convert", "learn"];
    const steps = Array.isArray(loop?.steps) ? loop.steps : [];
    const valid = loop?.schema === "ProofLaunchBreakoutGrowthLoopV1" &&
      /^[0-9a-f]{64}$/.test(String(loop?.content_sha256 ?? "")) &&
      loop?.external_action_performed === false &&
      loop?.automatic_publish_enabled === false &&
      loop?.automatic_outreach_enabled === false &&
      loop?.automatic_budget_activation_enabled === false &&
      loop?.automatic_learning_promotion_enabled === false &&
      loop?.core_loop_functions_without_paid_media === true &&
      steps.length === expected.length &&
      steps.every((step, index) => (
        step &&
        step.step_id === expected[index] &&
        typeof step.operator_action === "string" &&
        typeof step.audience_value === "string" &&
        typeof step.success_signal === "string" &&
        typeof step.stop_condition === "string" &&
        step.human_release_required === true &&
        step.external_action_performed === false
      ));
    if (!list || !valid) {
      if (status) {
        status.textContent = "Growth loop unavailable";
        status.className = "status-badge status-badge--blocked";
      }
      return;
    }
    const humanize = (value) => String(value).split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    if (thesis) thesis.textContent = String(loop.operating_thesis ?? "Earned-growth hypothesis unavailable");
    list.replaceChildren(...steps.map((step, index) => {
      const item = document.createElement("li");
      const sequence = document.createElement("span");
      const body = document.createElement("div");
      const title = document.createElement("strong");
      const action = document.createElement("p");
      const value = document.createElement("small");
      const gate = document.createElement("em");
      sequence.textContent = String(index + 1).padStart(2, "0");
      title.textContent = `${humanize(step.step_id)} · ${humanize(step.channel)}`;
      action.textContent = step.operator_action;
      value.textContent = `Value: ${step.audience_value} · Measure: ${step.success_signal} · Stop: ${step.stop_condition}`;
      gate.textContent = "HUMAN RELEASE";
      body.append(title, action, value);
      item.append(sequence, body, gate);
      return item;
    }));
    if (status) {
      status.textContent = `${humanize(loop.archetype)} · paid-independent core · 0 auto actions`;
      status.className = "status-badge status-badge--verified";
    }
  }

  function renderTextCreativeChallenger(challenger) {
    const list = getElement("creative-challenger-list");
    const status = getElement("creative-challenger-status");
    const boundary = getElement("creative-challenger-boundary");
    const expected = ["decision_xray", "proof_before_promise", "voluntary_relay"];
    const valid = challenger &&
      /^[0-9a-f]{64}$/.test(String(challenger.content_sha256 ?? "")) &&
      challenger.territory_count === 3 &&
      Array.isArray(challenger.territory_ids) &&
      challenger.territory_ids.length === expected.length &&
      challenger.territory_ids.every((value, index) => value === expected[index]) &&
      challenger.official_first_required === true &&
      challenger.maximum_model_calls === 3 &&
      challenger.execution_policy?.mode === "sequential_fail_fast" &&
      challenger.execution_policy?.maximum_concurrency === 1 &&
      challenger.execution_policy?.default_retry_rounds === 0 &&
      challenger.winner_selected === false &&
      challenger.blind_review_completed === false &&
      challenger.external_publish_executed === false;
    if (!list || !valid) {
      if (status) {
        status.textContent = "Challenger plan unavailable";
        status.className = "status-badge status-badge--blocked";
      }
      return;
    }
    const labels = {
      decision_xray: "Decision x-ray",
      proof_before_promise: "Proof before promise",
      voluntary_relay: "Voluntary relay",
    };
    list.replaceChildren(...expected.map((territory, index) => {
      const item = document.createElement("li");
      const sequence = document.createElement("span");
      const body = document.createElement("div");
      const title = document.createElement("strong");
      const detail = document.createElement("small");
      const gate = document.createElement("em");
      sequence.textContent = String(index + 1).padStart(2, "0");
      title.textContent = labels[territory];
      detail.textContent = "Exact proof + exact CTA + native channel format · mechanical validation before blind human review";
      gate.textContent = "NOT GENERATED";
      body.append(title, detail);
      item.append(sequence, body, gate);
      return item;
    }));
    if (boundary) boundary.textContent = String(challenger.truth_boundary ?? "Model outputs remain unreviewed drafts.");
    if (status) {
      status.textContent = `3 planned · sequential · concurrency 1 · ${challenger.maximum_model_calls} call cap`;
      status.className = "status-badge status-badge--verified";
    }
  }

  function renderCampaignWorkspace(workspace) {
    const status = getElement("campaign-workspace-status");
    const humanize = (value) => String(value).split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    const landing = workspace?.landing_page;
    const email = workspace?.lifecycle_email;
    const faqs = Array.isArray(workspace?.seo_geo?.faqs) ? workspace.seo_geo.faqs : [];
    const metrics = Array.isArray(workspace?.analytics?.metrics) ? workspace.analytics.metrics : [];
    const valid = workspace?.schema === "ProofLaunchCampaignWorkspacePublicV1" &&
      /^[0-9a-f]{64}$/.test(String(workspace.artifact_set_sha256 ?? "")) &&
      workspace.artifact_count === 9 &&
      workspace.human_release_required === true &&
      workspace.automatic_publish_enabled === false &&
      workspace.automatic_send_enabled === false &&
      workspace.automatic_spend_enabled === false &&
      workspace.external_activation_executed === false &&
      landing?.schema === "ProofLaunchLandingPageDraftV1" &&
      landing?.truth_status === "draft_only" &&
      landing?.human_release_required === true &&
      landing?.automated_publish_allowed === false &&
      email?.schema === "ProofLaunchLifecycleEmailDraftV1" &&
      email?.truth_status === "draft_only" &&
      email?.human_release_required === true &&
      email?.automated_send_allowed === false &&
      faqs.length === 4 &&
      metrics.length > 0;

    if (!valid) {
      state.campaignWorkspace = null;
      if (status) {
        status.textContent = "Workspace unavailable";
        status.className = "status-badge status-badge--blocked";
      }
      setText("landing-workspace-status", "Validated run required");
      setText("email-workspace-status", "Validated run required · send disabled");
      return;
    }

    state.campaignWorkspace = workspace;
    if (status) {
      status.textContent = `${workspace.artifact_count} bound drafts · 0 auto activations`;
      status.className = "status-badge status-badge--verified";
    }
    setText("campaign-workspace-boundary", String(workspace.truth_boundary));
    replaceList(
      "campaign-workspace-faqs",
      faqs,
      "No source-bound FAQ drafts.",
      (item) => `${item.question} — ${item.answer_draft}`
    );
    replaceList(
      "campaign-workspace-metrics",
      metrics,
      "No pre-registered metrics.",
      (item) => `${humanize(item.metric)} · ${humanize(item.direction)} · min n=${item.minimum_sample} · ${item.measurement_window_days}d`
    );

    setText("landing-draft-headline", landing.hero.headline);
    setText("landing-draft-proof", landing.hero.supporting_proof);
    setText("landing-draft-objection", landing.hero.objection_question);
    setText("landing-draft-cta", landing.hero.call_to_action);
    setText("landing-draft-citation", `Claim ${landing.citation.proof_claim_id} · ${landing.citation.evidence_sha256.slice(0, 12)}… · human release required`);
    setText("landing-workspace-status", "Source-bound draft · publish disabled");
    const landingStatus = getElement("landing-workspace-status");
    if (landingStatus) landingStatus.className = "status-badge status-badge--verified";
    renderJson("landing-workspace-output", {
      schema: landing.schema,
      truth_status: landing.truth_status,
      automated_publish_allowed: landing.automated_publish_allowed,
      external_publish_executed: landing.external_publish_executed,
      artifact_set_sha256: workspace.artifact_set_sha256,
    });

    setText("email-draft-subject", email.subject);
    setText("email-draft-preheader", email.preheader);
    setText("email-draft-cta", email.call_to_action);
    setText("email-draft-citation", `Claim ${email.citation.proof_claim_id} · ${email.citation.evidence_sha256.slice(0, 12)}… · no message sent`);
    const emailBody = getElement("email-draft-body");
    if (emailBody) {
      emailBody.replaceChildren(...email.body_blocks.map((block) => {
        const paragraph = document.createElement("p");
        paragraph.textContent = block;
        return paragraph;
      }));
    }
    setText("email-workspace-status", "Source-bound draft · send disabled");
    const emailStatus = getElement("email-workspace-status");
    if (emailStatus) emailStatus.className = "status-badge status-badge--verified";
    renderJson("email-workspace-output", {
      schema: email.schema,
      truth_status: email.truth_status,
      automated_send_allowed: email.automated_send_allowed,
      external_send_executed: email.external_send_executed,
      artifact_set_sha256: workspace.artifact_set_sha256,
    });
  }

  async function renderGTMCockpit(cockpit) {
    const status = getElement("gtm-cockpit-status");
    const unsigned = cockpit && typeof cockpit === "object" ? { ...cockpit } : null;
    const suppliedDigest = unsigned?.content_sha256;
    if (unsigned) delete unsigned.content_sha256;
    const computedDigest = unsigned
      ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
      : null;
    const capabilityRows = Array.isArray(
      cockpit?.capability_effect_matrix?.capabilities
    ) ? cockpit.capability_effect_matrix.capabilities : [];
    const observedGeneratedCount = capabilityRows.filter(
      (row) => row.generated_deliverable_observed === true
    ).length;
    const observedHumanCount = capabilityRows.filter(
      (row) => row.named_human_quality_observed === true
    ).length;
    const valid = cockpit?.schema === "ProofLaunchGTMCockpitV1" &&
      /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
      computedDigest === suppliedDigest &&
      cockpit.four_a_effect_claim_eligible === false &&
      cockpit.top1_claim_eligible === false &&
      cockpit.human_boundary?.automatic_publish_enabled === false &&
      cockpit.human_boundary?.automatic_send_enabled === false &&
      cockpit.human_boundary?.automatic_spend_enabled === false &&
      cockpit.human_boundary?.automatic_strategy_mutation_enabled === false &&
      cockpit.effect_and_revenue?.pipeline_counted_as_revenue === false &&
      cockpit.effect_and_revenue?.causal_revenue_claim_allowed === false &&
      cockpit.capability_effect_matrix?.schema === "ProofLaunchGTMCapabilityEffectMatrixV1" &&
      cockpit.capability_effect_matrix?.capability_count === 11 &&
      Array.isArray(cockpit.capability_effect_matrix?.capabilities) &&
      cockpit.capability_effect_matrix.capabilities.length === 11 &&
      cockpit.capability_effect_matrix?.generated_deliverable_count === observedGeneratedCount &&
      cockpit.capability_effect_matrix?.named_human_quality_count === observedHumanCount &&
      cockpit.capability_effect_matrix?.production_effect_attributed_count === 0 &&
      cockpit.capability_effect_matrix?.all_capability_effects_proven === false &&
      cockpit.capability_effect_matrix.capabilities.every((row) =>
        typeof row.generated_deliverable_observed === "boolean" &&
        typeof row.named_human_quality_observed === "boolean" &&
        (!row.named_human_quality_observed || row.generated_deliverable_observed) &&
        row.production_effect_attributed === false
      ) &&
      (!cockpit.strategy_and_channels?.available || (
        /^[0-9a-f]{64}$/.test(String(cockpit.goal_diagnosis?.brief_intelligence_sha256 ?? "")) &&
        /^[0-9a-f]{64}$/.test(String(cockpit.goal_diagnosis?.product_evidence_register_sha256 ?? "")) &&
        typeof cockpit.goal_diagnosis?.primary_growth_tension_id === "string" &&
        Number.isInteger(cockpit.goal_diagnosis?.critical_question_count) &&
        cockpit.goal_diagnosis.critical_question_count >= 0 &&
        cockpit.goal_diagnosis.critical_question_count <= 5 &&
        Array.isArray(cockpit.goal_diagnosis?.critical_questions) &&
        cockpit.goal_diagnosis.critical_questions.length === cockpit.goal_diagnosis.critical_question_count &&
        Number.isInteger(cockpit.goal_diagnosis?.product_claim_count) &&
        cockpit.goal_diagnosis.product_claim_count >= 1 &&
        typeof cockpit.goal_diagnosis?.all_claims_public_release_eligible === "boolean"
      )) &&
      (!cockpit.strategy_and_channels?.available || (
        /^[0-9a-f]{64}$/.test(String(cockpit.strategy_and_channels?.adaptive_capability_plan_sha256 ?? "")) &&
        typeof cockpit.strategy_and_channels?.adaptive_context_id === "string" &&
        Object.keys(cockpit.strategy_and_channels?.adaptive_lane_states ?? {}).length === 13 &&
        cockpit.strategy_and_channels?.adaptive_focus_lanes?.length === 4 &&
        cockpit.strategy_and_channels?.adaptive_test_lanes?.length === 4 &&
        cockpit.strategy_and_channels?.adaptive_distribution_aggregation === "weakest_link_operating_floor" &&
        cockpit.strategy_and_channels?.adaptive_hardware_and_provider_in_plan_identity === false &&
        cockpit.strategy_and_channels?.adaptive_human_release_required === true &&
        cockpit.strategy_and_channels?.adaptive_automatic_external_actions === 0 &&
        /^[0-9a-f]{64}$/.test(String(cockpit.strategy_and_channels?.creative_alpha_plan_sha256 ?? "")) &&
        typeof cockpit.strategy_and_channels?.creative_alpha_growth_case_status === "string" &&
        cockpit.strategy_and_channels?.creative_alpha_style_ids?.length >= 2 &&
        cockpit.strategy_and_channels?.creative_alpha_style_ids?.length <= 4 &&
        cockpit.strategy_and_channels?.creative_alpha_platform_grammar_count === 2 &&
        cockpit.strategy_and_channels?.creative_alpha_external_actions === 0 &&
        cockpit.strategy_and_channels?.creative_alpha_human_release_required === true &&
        /^[0-9a-f]{64}$/.test(String(cockpit.strategy_and_channels?.market_language_contract_sha256 ?? "")) &&
        /^[0-9a-f]{64}$/.test(String(cockpit.strategy_and_channels?.market_language_signature_sha256 ?? "")) &&
        typeof cockpit.strategy_and_channels?.market_language_reference_family === "string" &&
        typeof cockpit.strategy_and_channels?.market_language_primary_role === "string" &&
        cockpit.strategy_and_channels?.market_language_external_actions === 0 &&
        /^[0-9a-f]{64}$/.test(String(cockpit.strategy_and_channels?.gtm_team_capability_contract_sha256 ?? "")) &&
        cockpit.strategy_and_channels?.gtm_team_full_role_count === 22 &&
        cockpit.strategy_and_channels?.gtm_team_full_atomic_skill_count === 220 &&
        cockpit.strategy_and_channels?.gtm_team_active_role_ids?.includes("gtm_general_manager") &&
        cockpit.strategy_and_channels?.gtm_team_automatic_external_actions === 0
      )) &&
      cockpit.cross_device_memory?.human_promoted_only === true &&
      cockpit.cross_device_memory?.frozen_at_run_creation === true &&
      cockpit.cross_device_memory?.human_application_required === true &&
      cockpit.cross_device_memory?.automatic_strategy_mutation_executed === false &&
      cockpit.cross_device_memory?.automatic_schedule_mutation_executed === false &&
      cockpit.cross_device_memory?.automatic_budget_activation_executed === false &&
      cockpit.cross_device_memory?.source_run_mutated === false &&
      typeof cockpit.cross_device_memory?.future_resolution_recorded === "boolean" &&
      typeof cockpit.cross_device_memory?.future_resolution_complete === "boolean" &&
      Array.isArray(cockpit.cross_device_memory?.future_resolution_remaining_channels) &&
      Array.isArray(cockpit.cross_device_memory?.future_resolution_sha256) &&
      Array.isArray(cockpit.cross_device_memory?.future_resolution_winner_memory_ids) &&
      Array.isArray(cockpit.cross_device_memory?.conflicts) &&
      Array.isArray(cockpit.cross_device_memory?.unresolved_conflict_channels) &&
      Array.isArray(cockpit.cross_device_memory?.selected_directives) &&
      Array.isArray(cockpit.next_best_actions) &&
      cockpit.next_best_actions.length > 0;
    if (!valid) {
      state.gtmCockpit = null;
      if (status) {
        status.textContent = "Cockpit integrity blocked";
        status.className = "status-badge status-badge--blocked";
      }
      throw new Error("GTM cockpit failed schema, digest, or authority validation");
    }

    state.gtmCockpit = cockpit;
    const context = cockpit.operating_context ?? {};
    const diagnosis = cockpit.goal_diagnosis ?? {};
    const strategy = cockpit.strategy_and_channels ?? {};
    const workspace = cockpit.campaign_workspace ?? {};
    const capabilityMatrix = cockpit.capability_effect_matrix ?? {};
    const effect = cockpit.effect_and_revenue ?? {};
    const inheritedLearning = cockpit.cross_device_memory ?? {};
    const boundary = cockpit.human_boundary ?? {};
    const focusChannels = Array.isArray(strategy.focus_channels) ? strategy.focus_channels : [];
    const testChannels = Array.isArray(strategy.test_channels) ? strategy.test_channels : [];
    const adaptiveFocus = Array.isArray(strategy.adaptive_focus_lanes) ? strategy.adaptive_focus_lanes : [];
    const adaptiveTest = Array.isArray(strategy.adaptive_test_lanes) ? strategy.adaptive_test_lanes : [];
    const creativeStyles = Array.isArray(strategy.creative_alpha_style_ids) ? strategy.creative_alpha_style_ids : [];
    const activeGtmRoles = Array.isArray(strategy.gtm_team_active_role_ids) ? strategy.gtm_team_active_role_ids : [];
    if (status) {
      status.textContent = String(cockpit.run_status).replaceAll("_", " ");
      status.className = `status-badge ${statusMarkerClass(String(cockpit.run_status))}`;
    }
    setText("cockpit-run-stage", `${cockpit.run_id} · ${String(cockpit.run_status).replaceAll("_", " ")}`);
    const operatingContext = [
      context.business_model,
      context.lifecycle,
      context.budget === "zero" ? "zero media spend" : context.budget,
      context.industry,
      context.product_category,
      context.product_surface,
      context.audience_role,
      context.distribution_platform,
      context.market
    ].filter(Boolean).join(" · ") || "Context unavailable";
    const signalContext = state.publicSignalPilot
      ? `${state.publicSignalPilot.signal_count} verified public metadata signals · ${state.publicSignalPilot.hypothesis_count} source-bound hypotheses · human release required`
      : "real public-signal pilot unavailable";
    setText(
      "cockpit-context",
      `${operatingContext} · ${signalContext} · growth tension ${diagnosis.primary_growth_tension_id ?? "pending"} · claims ${diagnosis.public_release_eligible_claim_count ?? 0}/${diagnosis.product_claim_count ?? 0} release-eligible · ${diagnosis.critical_question_count ?? 0} material questions`
    );
    setText(
      "cockpit-channel-focus",
      strategy.available
        ? `Primary ${strategy.primary_channel ?? "unresolved"} · channels ${focusChannels.join(", ") || "none"} · market language ${strategy.market_language_reference_family ?? "unresolved"}/${strategy.market_language_primary_role ?? "unresolved"} · active GTM crafts ${activeGtmRoles.length}/${strategy.gtm_team_full_role_count ?? 0} · capability focus ${adaptiveFocus.join(", ") || "none"} · capability tests ${adaptiveTest.join(", ") || "none"} · creative styles ${creativeStyles.join(", ") || "pending"} · growth cases ${strategy.creative_alpha_growth_case_status ?? "pending"}`
        : "Strategy pending"
    );
    setText(
      "cockpit-workspace",
      workspace.available
        ? `${workspace.artifact_count} source-bound artifacts · ${workspace.schedule_slot_count} scheduled slots · ${capabilityMatrix.contract_connected_count}/11 capability contracts · ${capabilityMatrix.generated_deliverable_count} run-bound generated deliverables · ${capabilityMatrix.named_human_quality_count} human-rated · ${capabilityMatrix.production_effect_attributed_count} effect-attributed · activation disabled`
        : "Campaign Workspace pending"
    );
    setText(
      "cockpit-effect",
      `${effect.manual_publication_receipt_count ?? 0} manual publication receipts · ${effect.observation_count} aggregate observations · ${effect.latest_effect_decision ?? "effect unobserved"}`
    );
    setText(
      "cockpit-revenue",
      `${effect.economics_count} reconciled economics records · ${effect.positive_feedback_observation_count} positive-feedback records · causal claim disabled`
    );
    setText(
      "cockpit-learning",
      `${inheritedLearning.inherited_memory_count} inherited · ${inheritedLearning.eligible_memory_count ?? 0} context-eligible · ${inheritedLearning.effective_application_status ?? inheritedLearning.application_status ?? "not compiled"} · ${inheritedLearning.resolved_conflict_count ?? 0}/${inheritedLearning.conflict_count ?? 0} conflicts resolved · ${effect.human_promoted_memory_count} promoted in this run · source run immutable · human application required`
    );
    setText(
      "cockpit-approval",
      boundary.approval_recorded
        ? `${boundary.approval_decision ?? "decision"} recorded · external action remains separately controlled`
        : "No content-bound approval recorded"
    );
    replaceList(
      "cockpit-next-actions",
      cockpit.next_best_actions,
      "No bounded next action returned.",
      (item) => `${String(item.priority).toUpperCase()} · ${item.owner} — ${item.action} ${item.reason}`
    );
    setText("cockpit-boundary", `${cockpit.truth_boundary} · sha256:${suppliedDigest}`);
    updateInspectorForRoute("/control/gtm-cockpit");
  }

  async function loadLastMileProductionQuality() {
    const badge = getElement("last-mile-quality-status");
    try {
      const quality = await requestJson("/v1/last-mile-production-quality");
      const unsigned = quality && typeof quality === "object" ? { ...quality } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const lanes = Array.isArray(quality?.lanes) ? quality.lanes : [];
      const portfolio = quality?.portfolio ?? {};
      const ladder = quality?.quality_ladder ?? {};
      const gates = ladder?.gates ?? {};
      const valid = quality?.schema === "ProofLaunchGTMLastMileProductionQualityBenchmarkV1" &&
        quality?.effect_definition?.primary === "last_mile_generated_execution_quality" &&
        quality?.effect_definition?.secondary === "observed_business_outcome" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        computedDigest === suppliedDigest &&
        quality.lane_count === 14 && lanes.length === 14 &&
        ladder.schema === "ProofLaunchGTMProductionQualityEvaluationV1" &&
        ladder.current_state === "mechanically_ready" &&
        ladder.promotion_allowed === false &&
        gates?.G0_contract?.passed === true &&
        gates?.G1_professional_editor?.passed === false &&
        gates?.G2_same_brief_blind_pk?.passed === false &&
        gates?.G3_production_effect?.passed === false &&
        portfolio.mechanical_pack_assembled === true &&
        portfolio.same_brief_internal_challenger_compiled_lane_count === 14 &&
        portfolio.last_mile_execution_quality_alignment_achieved === false &&
        portfolio.business_outcome_observed === false &&
        portfolio.four_a_quality_proven === false &&
        lanes.every((lane) =>
          lane.mechanical_ready === true &&
          lane.same_brief_peer_comparison_completed === false &&
          lane.last_mile_execution_quality_alignment_achieved === false &&
          lane.business_outcome_observed === false
        );
      if (!valid) throw new Error("last-mile scorecard failed schema, digest, or truth-boundary validation");
      if (badge) {
        badge.textContent = `${ladder.current_state} · ${portfolio.mechanically_ready_lane_count}/14 mechanical · ${quality.current_review_evidence?.unified_submitted ?? 0}/${quality.current_review_evidence?.unified_expected ?? 80} human reviews · 0/130 named-product PK · production unobserved`;
        badge.className = "status-badge status-badge--required";
      }
      replaceList(
        "last-mile-quality-lanes",
        lanes,
        "No last-mile quality lanes are available.",
        (lane) => `${lane.label} · artifact verified · same-brief human PK pending · business outcome separate`
      );
      setText(
        "last-mile-quality-boundary",
        `${quality.truth_boundary} · sha256:${suppliedDigest}`
      );
      return quality;
    } catch (error) {
      if (badge) {
        badge.textContent = "Last-mile scorecard unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      replaceList("last-mile-quality-lanes", [], "Scorecard unavailable.", (item) => String(item));
      setText("last-mile-quality-boundary", `Quality evidence failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  function renderPlatformCapabilityShowcase() {
    const showcase = state.platformCapabilityShowcase;
    const grid = getElement("platform-capability-grid");
    const selector = getElement("platform-capability-surface");
    if (!showcase || !grid || !(selector instanceof HTMLSelectElement)) return;
    const surfaceId = selector.value;
    const cards = showcase.bundles.map((bundle) => {
      const candidate = bundle.candidates.find((row) => row.surface_id === surfaceId);
      if (!candidate) throw new Error(`missing capability surface: ${bundle.business_model}:${surfaceId}`);
      const article = document.createElement("article");
      article.className = "platform-capability-card";
      const header = document.createElement("header");
      const title = document.createElement("div");
      const label = document.createElement("span");
      label.className = "mono-label";
      label.textContent = bundle.business_model.toUpperCase();
      const heading = document.createElement("h4");
      heading.textContent = candidate.campaign_platform;
      title.append(label, heading);
      const status = document.createElement("span");
      status.className = "status-badge status-badge--required";
      status.textContent = "Craft pass · release blocked";
      header.append(title, status);
      const hook = document.createElement("p");
      hook.className = "platform-capability-card__hook";
      hook.textContent = candidate.hook;
      const body = document.createElement("ol");
      candidate.body.forEach((block) => {
        const item = document.createElement("li");
        item.textContent = block;
        body.append(item);
      });
      const details = document.createElement("dl");
      [
        ["CTA", candidate.cta],
        ["Participation", candidate.participation_mechanism],
        ["Proof", candidate.proof_integration],
        ["Stop condition", candidate.falsifier],
        ["Publication state", candidate.publication_state]
      ].forEach(([term, description]) => {
        const group = document.createElement("div");
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = term;
        dd.textContent = description;
        group.append(dt, dd);
        details.append(group);
      });
      article.append(header, hook, body, details);
      return article;
    });
    grid.replaceChildren(...cards);
  }

  async function loadPlatformCapabilityShowcase() {
    const badge = getElement("platform-capability-status");
    try {
      const showcase = await requestJson("/v1/platform-capability-showcase");
      const unsigned = showcase && typeof showcase === "object" ? { ...showcase } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const bundles = Array.isArray(showcase?.bundles) ? showcase.bundles : [];
      const valid = showcase?.schema === "ProofLaunchPlatformCapabilityShowcasePublicV1" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        computedDigest === suppliedDigest &&
        showcase.business_model_count === 2 &&
        showcase.surface_count_per_business_model === 13 &&
        showcase.candidate_count === 26 &&
        showcase.pre_human_quality_pass_count === 26 &&
        showcase.release_eligible_count === 0 &&
        showcase.human_review_completed_count === 0 &&
        showcase.production_effect_observed === false &&
        showcase.named_product_baseline_count === 0 &&
        showcase.four_a_claim_eligible === false &&
        showcase.top1_claim_eligible === false &&
        showcase.automatic_publish_enabled === false &&
        bundles.length === 2 &&
        bundles.map((bundle) => bundle.business_model).join(",") === "b2b,b2c" &&
        bundles.every((bundle) => bundle.surface_count === 13 &&
          bundle.pre_human_quality_pass_count === 13 &&
          bundle.release_eligible_count === 0 &&
          bundle.human_review_completed_count === 0 &&
          bundle.production_effect_observed === false &&
          Array.isArray(bundle.candidates) && bundle.candidates.length === 13 &&
          bundle.candidates.every((candidate) => candidate.capability_quality_pass === true &&
            candidate.release_eligible === false &&
            Array.isArray(candidate.body) && candidate.body.length >= 3));
      if (!valid) throw new Error("platform capability showcase failed schema, digest, or authority validation");
      state.platformCapabilityShowcase = showcase;
      renderPlatformCapabilityShowcase();
      if (badge) {
        badge.textContent = "26/26 craft · 0 release eligible · 0 human/effect";
        badge.className = "status-badge status-badge--required";
      }
      setText(
        "platform-capability-boundary",
        `${showcase.truth_boundary} · sha256:${suppliedDigest}`
      );
      return showcase;
    } catch (error) {
      state.platformCapabilityShowcase = null;
      if (badge) {
        badge.textContent = "Capability showcase unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      const grid = getElement("platform-capability-grid");
      if (grid) {
        const message = document.createElement("p");
        message.textContent = "Capability references failed closed.";
        grid.replaceChildren(message);
      }
      setText("platform-capability-boundary", `Capability evidence failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  function renderCodexIntegratedCampaignPortfolio() {
    const portfolio = state.codexIntegratedCampaignPortfolio;
    const selector = getElement("integrated-campaign-model");
    const core = getElement("integrated-campaign-core");
    if (!portfolio || !(selector instanceof HTMLSelectElement) || !core) return;
    const pack = portfolio.packs.find((row) => row.business_model === selector.value);
    if (!pack) throw new Error(`missing integrated campaign pack: ${selector.value}`);
    const coreRows = [
      ["Campaign system", pack.strategic_core.campaign_system_name],
      ["Human tension", pack.strategic_core.human_tension],
      ["Organizing idea", pack.strategic_core.organizing_idea],
      ["Proof spine", pack.strategic_core.proof_spine],
      ["Primary surfaces", pack.channel_strategy.primary_surfaces.join(" + ")],
      ["Rejection rule", pack.strategic_core.rejection_rule]
    ].map(([term, description]) => {
      const group = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      dd.textContent = description;
      group.append(dt, dd);
      return group;
    });
    core.replaceChildren(...coreRows);
    replaceList(
      "integrated-campaign-phases",
      pack.lifecycle_phases,
      "No lifecycle jobs available.",
      (phase) => `${phase.phase_id} · ${phase.surface_ids.join(", ")} · ${phase.decision_job} · STOP: ${phase.stop_rule}`
    );
    replaceList(
      "integrated-campaign-emails",
      pack.email_sequence,
      "No email sequence available.",
      (message) => `${message.sequence}. ${message.subject} · ${message.cta}`
    );
    replaceList(
      "integrated-campaign-media",
      pack.production_directions,
      "No production directions available.",
      (direction) => `${direction.kind} · ${direction.concept} · TEST: ${direction.acceptance_test}`
    );
    replaceList(
      "integrated-campaign-experiments",
      pack.experiment_registry,
      "No experiments available.",
      (experiment) => `${experiment.experiment_id} · ${experiment.primary_metric} · KILL: ${experiment.kill_rule}`
    );
    setText(
      "integrated-campaign-boundary",
      `${pack.truth_boundary} · ${pack.publication_policy_state} · sha256:${pack.content_sha256}`
    );
  }

  async function loadCodexIntegratedCampaignPortfolio() {
    const badge = getElement("integrated-campaign-status");
    try {
      const portfolio = await requestJson("/v1/codex-integrated-campaign-portfolio");
      const unsigned = portfolio && typeof portfolio === "object" ? { ...portfolio } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const packs = Array.isArray(portfolio?.packs) ? portfolio.packs : [];
      const valid = portfolio?.schema === "ProofLaunchCodexIntegratedCampaignPortfolioV1" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        computedDigest === suppliedDigest &&
        portfolio.pack_count === 2 &&
        portfolio.platform_candidate_count === 26 &&
        portfolio.email_count === 8 &&
        portfolio.production_direction_count === 6 &&
        portfolio.search_geo_node_count === 14 &&
        portfolio.seven_day_flight_slot_count === 14 &&
        portfolio.experiment_count === 8 &&
        portfolio.capability_quality_pass_count === 26 &&
        portfolio.release_eligible_count === 0 &&
        portfolio.human_review_completed_count === 0 &&
        portfolio.production_effect_observed === false &&
        portfolio.causal_effect_claim_allowed === false &&
        portfolio.named_product_pk_completed_count === 0 &&
        portfolio.four_a_claim_eligible === false &&
        portfolio.top1_claim_eligible === false &&
        portfolio.external_publish_executed === false &&
        portfolio.automatic_send_spend_or_strategy_mutation === false &&
        portfolio.paid_media_spend_usd === 0 &&
        packs.length === 2 &&
        packs.map((pack) => pack.business_model).join(",") === "b2b,b2c" &&
        packs.every((pack) => Array.isArray(pack.platform_candidates) && pack.platform_candidates.length === 13 &&
          Array.isArray(pack.lifecycle_phases) && pack.lifecycle_phases.length === 4 &&
          Array.isArray(pack.email_sequence) && pack.email_sequence.length === 4 &&
          Array.isArray(pack.production_directions) && pack.production_directions.length === 3 &&
          Array.isArray(pack.search_geo_system?.nodes) && pack.search_geo_system.nodes.length === 7 &&
          Array.isArray(pack.seven_day_flight) && pack.seven_day_flight.length === 7 &&
          Array.isArray(pack.experiment_registry) && pack.experiment_registry.length === 4 &&
          pack.release_eligible_count === 0 &&
          pack.human_review_completed === false &&
          pack.production_effect_observed === false &&
          pack.external_publish_executed === false);
      if (!valid) throw new Error("integrated Codex campaign portfolio failed schema, digest, or authority validation");
      state.codexIntegratedCampaignPortfolio = portfolio;
      renderCodexIntegratedCampaignPortfolio();
      if (badge) {
        badge.textContent = "2 systems · 26 native assets · 8 emails · 8 experiments";
        badge.className = "status-badge status-badge--required";
      }
      return portfolio;
    } catch (error) {
      state.codexIntegratedCampaignPortfolio = null;
      if (badge) {
        badge.textContent = "Integrated campaign systems unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      ["integrated-campaign-phases", "integrated-campaign-emails", "integrated-campaign-media", "integrated-campaign-experiments"].forEach((id) => {
        replaceList(id, [], "Campaign evidence unavailable.", (item) => String(item));
      });
      setText("integrated-campaign-boundary", `Integrated campaign evidence failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  function renderCodexCampaignAdaptationSummary() {
    const summary = state.codexCampaignAdaptationSummary;
    const selector = getElement("codex-adaptation-archetype");
    const core = getElement("codex-adaptation-core");
    if (!summary || !(selector instanceof HTMLSelectElement) || !core) return;
    const archetype = summary.archetypes.find(
      (row) => row.industry_archetype === selector.value
    );
    if (!archetype) throw new Error(`missing adaptation archetype: ${selector.value}`);
    const coreRows = [
      ["Industry archetype", archetype.industry_archetype],
      ["Bound work orders", String(archetype.work_order_count)],
      ["Business models", archetype.business_models.join(" + ")],
      ["Lifecycle × budget", `${archetype.lifecycles.length} × ${archetype.budgets.length}`],
      ["Primary-channel variants", archetype.primary_channels.join(" · ")],
      ["Conversion unit", archetype.conversion_unit],
      ["Buying motion", archetype.buying_motion],
      ["Zero-budget engine", archetype.zero_budget_growth_engine]
    ].map(([term, description]) => {
      const group = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      dd.textContent = description;
      group.append(dt, dd);
      return group;
    });
    core.replaceChildren(...coreRows);
    const output = summary.output_contract;
    replaceList(
      "codex-adaptation-output",
      [
        `${summary.case_count} work orders · ${summary.zero_budget_work_order_count} zero-budget · ${summary.regulated_work_order_count} regulated`,
        `${summary.autonomy_level} · ${summary.graph_stage_count} graph stages · ${summary.named_failure_mode_count} named failure modes`,
        `Per brief: ${output.platform_native_asset_count} native assets · ${output.lifecycle_phase_count} phases · ${output.email_count} emails · ${output.multimodal_direction_count} media directions`,
        `Per brief: ${output.search_geo_node_count} SEO/GEO nodes · ${output.flight_slot_count} flight slots · ${output.experiment_count} frozen experiments`,
        `${summary.model_call_count} model calls · ${summary.candidate_output_count} generated candidates · ${summary.human_review_completed_count} human reviews · ${summary.release_eligible_count} release eligible`
      ],
      "Adaptation contract unavailable.",
      (item) => item
    );
    setText(
      "codex-adaptation-boundary",
      `${summary.truth_boundary} · sha256:${summary.content_sha256}`
    );
  }

  async function loadCodexCampaignAdaptationSummary() {
    const badge = getElement("codex-adaptation-status");
    try {
      const summary = await requestJson("/v1/codex-campaign-adaptation-summary");
      const unsigned = summary && typeof summary === "object" ? { ...summary } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const archetypes = Array.isArray(summary?.archetypes) ? summary.archetypes : [];
      const output = summary?.output_contract ?? {};
      const valid = summary?.schema === "ProofLaunchCodexCampaignAdaptationSummaryPublicV1" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        /^[0-9a-f]{64}$/.test(String(summary?.source_matrix_sha256 ?? "")) &&
        computedDigest === suppliedDigest &&
        summary.autonomy_level === "L2_deterministic_workflow_with_bounded_model_generation" &&
        summary.graph_stage_count === 5 &&
        summary.named_failure_mode_count === 10 &&
        summary.maximum_generation_attempts === 2 &&
        summary.maximum_critic_repair_rounds === 1 &&
        summary.industry_archetype_count === 20 &&
        summary.business_model_count === 2 &&
        summary.lifecycle_count === 4 &&
        summary.budget_count === 3 &&
        summary.case_count === 456 &&
        summary.zero_budget_work_order_count === 152 &&
        summary.regulated_work_order_count === 72 &&
        summary.human_classification_confirmation_required_count === 84 &&
        summary.distinct_primary_channel_count === 8 &&
        output.platform_native_asset_count === 13 &&
        output.lifecycle_phase_count === 4 &&
        output.email_count === 4 &&
        output.multimodal_direction_count === 3 &&
        output.search_geo_node_count === 7 &&
        output.flight_slot_count === 7 &&
        output.experiment_count === 4 &&
        summary.model_call_count === 0 &&
        summary.candidate_output_count === 0 &&
        summary.human_review_completed_count === 0 &&
        summary.release_eligible_count === 0 &&
        summary.external_publish_executed_count === 0 &&
        summary.production_effect_observed_count === 0 &&
        summary.causal_effect_claim_allowed_count === 0 &&
        archetypes.length === 20 &&
        archetypes.reduce((total, row) => total + row.work_order_count, 0) === 456;
      if (!valid) throw new Error("Codex adaptation summary failed schema, digest, coverage, or authority validation");
      state.codexCampaignAdaptationSummary = summary;
      const selector = getElement("codex-adaptation-archetype");
      if (selector instanceof HTMLSelectElement) {
        const options = archetypes.map((row) => {
          const option = document.createElement("option");
          option.value = row.industry_archetype;
          option.textContent = `${row.industry_archetype} · ${row.work_order_count}`;
          return option;
        });
        selector.replaceChildren(...options);
      }
      renderCodexCampaignAdaptationSummary();
      if (badge) {
        badge.textContent = "456/456 contracts · 20 industries · 0 inference/effect";
        badge.className = "status-badge status-badge--required";
      }
      return summary;
    } catch (error) {
      state.codexCampaignAdaptationSummary = null;
      if (badge) {
        badge.textContent = "Adaptation matrix unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      const core = getElement("codex-adaptation-core");
      if (core) core.replaceChildren();
      replaceList("codex-adaptation-output", [], "Adaptation evidence unavailable.", (item) => String(item));
      setText("codex-adaptation-boundary", `Adaptation evidence failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  function renderCodexLighthousePortfolio() {
    const portfolio = state.codexLighthousePortfolio;
    const selector = getElement("codex-lighthouse-case");
    const core = getElement("codex-lighthouse-core");
    const assetGrid = getElement("codex-lighthouse-assets");
    if (!portfolio || !(selector instanceof HTMLSelectElement) || !core || !assetGrid) return;
    const candidate = portfolio.cases.find((row) => row.candidate_id === selector.value);
    if (!candidate) throw new Error(`missing Codex lighthouse candidate: ${selector.value}`);
    const selectorData = candidate.selector;
    const campaign = candidate.campaign_system;
    const fixture = candidate.fixture;
    const audit = candidate.level_1_audit;
    const coreRows = [
      ["Case", `${selectorData.business_model.toUpperCase()} · ${selectorData.industry_archetype} · ${selectorData.lifecycle} · ${selectorData.budget}`],
      ["Product / audience", `${fixture.product_name} · ${fixture.audience}`],
      ["Campaign system", campaign.name],
      ["Human tension", campaign.human_tension],
      ["Organizing idea", campaign.organizing_idea],
      ["Exact approved claim", fixture.approved_claim],
      ["Focus surfaces", `${candidate.channel_decision.primary_surface} + ${candidate.channel_decision.secondary_surface}`],
      ["Mechanical receipt", `${audit.status} · ${audit.gate_count} gates · ${audit.critical_failure_count} failures`]
    ].map(([term, description]) => {
      const group = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      dd.textContent = description;
      group.append(dt, dd);
      return group;
    });
    core.replaceChildren(...coreRows);

    const cards = candidate.platform_assets.map((asset) => {
      const article = document.createElement("article");
      article.className = "platform-capability-card codex-lighthouse-card";
      const header = document.createElement("header");
      const title = document.createElement("div");
      const label = document.createElement("span");
      label.className = "mono-label";
      label.textContent = asset.surface_id.toUpperCase();
      const heading = document.createElement("h4");
      heading.textContent = asset.native_format;
      title.append(label, heading);
      const status = document.createElement("span");
      status.className = "status-badge status-badge--required";
      status.textContent = "L1 pass · human pending";
      header.append(title, status);
      const hook = document.createElement("p");
      hook.className = "platform-capability-card__hook";
      hook.textContent = asset.hook;
      const copy = document.createElement("p");
      copy.className = "codex-lighthouse-card__copy";
      copy.textContent = asset.full_copy;
      const details = document.createElement("dl");
      [
        ["Audience state", asset.audience_state],
        ["CTA", asset.cta],
        ["Participation", asset.participation],
        ["Proof + limitation", asset.proof_and_limitation],
        ["Release", asset.release_state]
      ].forEach(([term, description]) => {
        const group = document.createElement("div");
        const dt = document.createElement("dt");
        const dd = document.createElement("dd");
        dt.textContent = term;
        dd.textContent = description;
        group.append(dt, dd);
        details.append(group);
      });
      article.append(header, hook, copy, details);
      return article;
    });
    assetGrid.replaceChildren(...cards);

    replaceList(
      "codex-lighthouse-email",
      [candidate.email],
      "Email candidate unavailable.",
      (email) => `${email.subject} · ${email.preview} · ${email.body} · CTA: ${email.cta} · SUPPRESS: ${email.suppression}`
    );
    replaceList(
      "codex-lighthouse-search",
      [candidate.seo_page, candidate.geo_answer],
      "SEO/GEO candidate unavailable.",
      (item) => typeof item.title === "string"
        ? `SEO · ${item.title} · ${item.meta} · HERO: ${item.hero} · CTA: ${item.cta}`
        : `GEO · ${item.question} · ${item.direct_answer} · BOUNDARY: ${item.evidence_boundary}`
    );
    replaceList(
      "codex-lighthouse-video",
      candidate.video_script.shots,
      "Video script unavailable.",
      (shot) => `${shot.start}–${shot.end}s · ${shot.visual} · AUDIO: ${shot.audio} · CAPTION: ${shot.caption} · TEST: ${shot.acceptance_test}`
    );
    replaceList(
      "codex-lighthouse-experiment",
      [candidate.experiment],
      "Experiment unavailable.",
      (experiment) => `${experiment.hypothesis} · METRIC: ${experiment.primary_metric} · SAMPLE: ${experiment.minimum_sample_rule} · SUCCESS: ${experiment.success_rule} · KILL: ${experiment.kill_rule}`
    );
    setText(
      "codex-lighthouse-boundary",
      `${candidate.truth_boundary} · Level-1=${audit.passed}; human preference=${audit.human_preference_observed}; release=${audit.release_eligible}; production effect=${audit.production_effect_observed}. · candidate sha256:${candidate.candidate_sha256}`
    );
  }

  async function loadCodexLighthousePortfolio() {
    const badge = getElement("codex-lighthouse-status");
    try {
      const portfolio = await requestJson("/v1/codex-lighthouse-portfolio");
      const unsigned = portfolio && typeof portfolio === "object" ? { ...portfolio } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const cases = Array.isArray(portfolio?.cases) ? portfolio.cases : [];
      const valid = portfolio?.schema === "ProofLaunchCodexLighthousePortfolioPublicV1" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        /^[0-9a-f]{64}$/.test(String(portfolio?.source_portfolio_sha256 ?? "")) &&
        /^[0-9a-f]{64}$/.test(String(portfolio?.source_quality_sha256 ?? "")) &&
        computedDigest === suppliedDigest &&
        portfolio.candidate_count === 8 &&
        portfolio.workspace_authored_candidate_count === 8 &&
        portfolio.flagship_api_inference_observed_count === 0 &&
        portfolio.business_model_count === 2 &&
        portfolio.industry_archetype_count === 8 &&
        portfolio.lifecycle_count_per_business_model === 4 &&
        portfolio.budget_tier_count === 3 &&
        portfolio.regulated_candidate_count === 2 &&
        portfolio.platform_asset_count === 16 &&
        portfolio.email_count === 8 &&
        portfolio.seo_page_count === 8 &&
        portfolio.geo_answer_count === 8 &&
        portfolio.video_script_count === 8 &&
        portfolio.experiment_count === 8 &&
        portfolio.level_1_audit_pass_count === 8 &&
        portfolio.calibrated_model_critic_pass_count === 0 &&
        portfolio.qualified_human_review_count === 0 &&
        portfolio.release_eligible_count === 0 &&
        portfolio.external_publish_executed_count === 0 &&
        portfolio.external_action_count === 0 &&
        portfolio.production_effect_observed_count === 0 &&
        portfolio.causal_revenue_effect_proven_count === 0 &&
        portfolio.named_product_pk_completed_count === 0 &&
        portfolio.four_a_quality_proven === false &&
        portfolio.top1_claim_eligible === false &&
        cases.length === 8 &&
        new Set(cases.map((row) => row.selector.industry_archetype)).size === 8 &&
        new Set(cases.map((row) => row.selector.business_model)).size === 2 &&
        cases.every((row) => Array.isArray(row.platform_assets) && row.platform_assets.length === 2 &&
          row.authorship?.workspace_model_authorship_asserted === true &&
          row.authorship?.flagship_api_inference_observed === false &&
          row.level_1_audit?.passed === true &&
          row.level_1_audit?.critical_failure_count === 0 &&
          row.level_1_audit?.release_eligible === false &&
          row.level_1_audit?.human_preference_observed === false &&
          row.level_1_audit?.production_effect_observed === false);
      if (!valid) throw new Error("Codex lighthouse portfolio failed schema, digest, coverage, or authority validation");
      state.codexLighthousePortfolio = portfolio;
      const selector = getElement("codex-lighthouse-case");
      if (selector instanceof HTMLSelectElement) {
        selector.replaceChildren(...cases.map((row) => {
          const option = document.createElement("option");
          option.value = row.candidate_id;
          option.textContent = `${row.selector.business_model.toUpperCase()} · ${row.selector.industry_archetype} · ${row.selector.lifecycle} · ${row.selector.budget}`;
          return option;
        }));
      }
      renderCodexLighthousePortfolio();
      if (badge) {
        badge.textContent = "8 Codex outputs · 8 L1 pass · 0 human/effect";
        badge.className = "status-badge status-badge--required";
      }
      return portfolio;
    } catch (error) {
      state.codexLighthousePortfolio = null;
      if (badge) {
        badge.textContent = "Direct Codex candidates unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      const core = getElement("codex-lighthouse-core");
      const assets = getElement("codex-lighthouse-assets");
      if (core) core.replaceChildren();
      if (assets) {
        const message = document.createElement("p");
        message.textContent = "Direct candidate evidence failed closed.";
        assets.replaceChildren(message);
      }
      ["codex-lighthouse-email", "codex-lighthouse-search", "codex-lighthouse-video", "codex-lighthouse-experiment"].forEach((id) => {
        replaceList(id, [], "Candidate evidence unavailable.", (item) => String(item));
      });
      setText("codex-lighthouse-boundary", `Direct Codex evidence failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  async function loadConcreteProductEffectPK() {
    const badge = getElement("concrete-pk-status");
    try {
      const ledger = await requestJson("/v1/concrete-product-effect-pk");
      const unsigned = ledger && typeof ledger === "object" ? { ...ledger } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const categories = Array.isArray(ledger?.categories) ? ledger.categories : [];
      const rows = Array.isArray(ledger?.product_pk_rows) ? ledger.product_pk_rows : [];
      const portfolio = ledger?.portfolio ?? {};
      const valid = ledger?.schema === "ProofLaunchConcreteProductEffectPKLedgerV1" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        computedDigest === suppliedDigest &&
        ledger.category_count === 13 && categories.length === 13 &&
        ledger.reference_product_row_count === 130 && rows.length === 130 &&
        portfolio.categories_with_candidate_artifacts_present === 13 &&
        portfolio.completed_product_pk_rows === 0 &&
        portfolio.effect_aligned_categories === 0 &&
        ledger.acceptance_gate?.product_integration_can_substitute_for_effect_pk === false &&
        ledger.acceptance_gate?.model_judge_can_promote === false &&
        rows.every((row) => row.comparison_status === "not_completed" &&
          row.qualified_human_review_count === 0 &&
          row.effect_alignment_achieved === false);
      if (!valid) throw new Error("concrete product/effect PK ledger failed schema, digest, or truth-boundary validation");
      if (badge) {
        badge.textContent = "13/13 evidence-bound · 0/130 product PK complete";
        badge.className = "status-badge status-badge--required";
      }
      replaceList(
        "concrete-pk-categories",
        categories,
        "No concrete product/effect categories are available.",
        (category) => `${category.category_id} · 10 named products · ${category.open_source_project_count} pinned OSS components · internal same-Brief opponent ready · 0/10 named-product human PK`
      );
      setText("concrete-pk-boundary", `${ledger.truth_boundary} · sha256:${suppliedDigest}`);
      return ledger;
    } catch (error) {
      if (badge) {
        badge.textContent = "Concrete product/effect PK unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      replaceList("concrete-pk-categories", [], "PK ledger unavailable.", (item) => String(item));
      setText("concrete-pk-boundary", `PK evidence failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  async function loadNamedProductBaselineCaptureKit() {
    const badge = getElement("named-baseline-status");
    try {
      const [kit, portfolio, admission, qualityControl, adaptiveGraph] = await Promise.all([
        requestJson("/v1/named-product-baseline-capture-kit"),
        requestJson("/v1/named-product-pk-portfolio"),
        requestJson("/v1/named-product-challenger-admission"),
        requestJson("/v1/gtm-hybrid-quality-control"),
        requestJson("/v1/gtm-adaptive-capability-graph")
      ]);
      const unsigned = kit && typeof kit === "object" ? { ...kit } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const portfolioUnsigned = portfolio && typeof portfolio === "object" ? { ...portfolio } : null;
      const portfolioDigest = portfolioUnsigned?.content_sha256;
      if (portfolioUnsigned) delete portfolioUnsigned.content_sha256;
      const portfolioComputedDigest = portfolioUnsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(portfolioUnsigned)))
        : null;
      const admissionUnsigned = admission && typeof admission === "object" ? { ...admission } : null;
      const admissionDigest = admissionUnsigned?.content_sha256;
      if (admissionUnsigned) delete admissionUnsigned.content_sha256;
      const admissionComputedDigest = admissionUnsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(admissionUnsigned)))
        : null;
      const qualityControlUnsigned = qualityControl && typeof qualityControl === "object"
        ? { ...qualityControl }
        : null;
      const qualityControlDigest = qualityControlUnsigned?.content_sha256;
      if (qualityControlUnsigned) delete qualityControlUnsigned.content_sha256;
      const qualityControlComputedDigest = qualityControlUnsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(qualityControlUnsigned)))
        : null;
      const adaptiveGraphUnsigned = adaptiveGraph && typeof adaptiveGraph === "object"
        ? { ...adaptiveGraph }
        : null;
      const adaptiveGraphDigest = adaptiveGraphUnsigned?.content_sha256;
      if (adaptiveGraphUnsigned) delete adaptiveGraphUnsigned.content_sha256;
      const adaptiveGraphComputedDigest = adaptiveGraphUnsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(adaptiveGraphUnsigned)))
        : null;
      const categories = Array.isArray(kit?.categories) ? kit.categories : [];
      const portfolioCategories = Array.isArray(portfolio?.categories) ? portfolio.categories : [];
      const admissionCategories = Array.isArray(admission?.categories) ? admission.categories : [];
      const qualityControlLanes = Array.isArray(qualityControl?.lanes) ? qualityControl.lanes : [];
      const valid = kit?.schema === "ProofLaunchNamedProductBaselineCaptureKitPublicV1" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        computedDigest === suppliedDigest &&
        /^[0-9a-f]{64}$/.test(String(kit.source_manifest_content_sha256 ?? "")) &&
        kit.category_count === 13 && categories.length === 13 &&
        kit.capture_slot_count === 130 && kit.authorized_baseline_count === 0 &&
        kit.network_submission_enabled === false &&
        kit.automatic_product_execution_enabled === false &&
        kit.automatic_pairing_enabled === false &&
        kit.automatic_pk_promotion_enabled === false &&
        kit.human_review_required === true &&
        portfolio?.schema === "ProofLaunchNamedProductBlindPKPortfolioV1" &&
        /^[0-9a-f]{64}$/.test(String(portfolioDigest ?? "")) &&
        portfolioComputedDigest === portfolioDigest &&
        portfolio.category_count === 13 && portfolio.reference_product_row_count === 130 &&
        portfolio.completed_product_pk_rows === 0 && portfolio.candidate_won_product_pk_rows === 0 &&
        portfolio.effect_aligned_category_count === 0 && portfolioCategories.length === 13 &&
        portfolio.named_product_last_mile_alignment_achieved === false &&
        portfolio.automatic_runtime_switch_enabled === false &&
        portfolio.automatic_strategy_mutation_enabled === false &&
        portfolio.automatic_publish_enabled === false &&
        portfolio.four_a_quality_proven === false &&
        admission?.schema === "ProofLaunchNamedProductChallengerAdmissionPublicV1" &&
        /^[0-9a-f]{64}$/.test(String(admissionDigest ?? "")) &&
        admissionComputedDigest === admissionDigest &&
        admission.category_count === 13 && admission.reference_product_row_count === 130 &&
        admission.dossier_count === 13 && admission.admitted_category_count === 13 &&
        admission.blocked_category_count === 0 && admissionCategories.length === 13 &&
        admission.automatic_pairing_enabled === false &&
        admission.automatic_product_execution_enabled === false &&
        admission.automatic_pk_promotion_enabled === false &&
        admission.four_a_quality_proven === false &&
        qualityControl?.schema === "ProofLaunchGTMHybridQualityControlPublicV1" &&
        /^[0-9a-f]{64}$/.test(String(qualityControlDigest ?? "")) &&
        qualityControlComputedDigest === qualityControlDigest &&
        qualityControl.portfolio?.category_count === 13 &&
        qualityControl.portfolio?.job_count === 130 &&
        qualityControl.portfolio?.local_ready_category_count === 13 &&
        qualityControl.portfolio?.challenger_dossier_count_admitted === 13 &&
        qualityControl.portfolio?.authorized_named_product_baseline_count === 0 &&
        qualityControl.portfolio?.completed_named_product_pk_count === 0 &&
        qualityControl.portfolio?.candidate_wins === 0 &&
        qualityControl.portfolio?.effect_aligned_categories === 0 &&
        qualityControl.portfolio?.product_local_runtime_blocked_by_cloud === false &&
        qualityControl.routing_invariants?.hardware_and_provider_are_replaceable === true &&
        qualityControl.routing_invariants?.jobs_route_by_capability_not_vendor === true &&
        qualityControl.routing_invariants?.local_pipeline_continues_without_cloud === true &&
        qualityControl.routing_invariants?.cloud_gpu_is_quality_accelerator_not_product_runtime_dependency === true &&
        qualityControl.routing_invariants?.radeon_required_for_product_closure === false &&
        qualityControl.routing_invariants?.model_judge_can_promote === false &&
        qualityControl.routing_invariants?.human_release_required === true &&
        qualityControl.routing_invariants?.automatic_publish_send_spend_or_strategy_mutation === false &&
        qualityControlLanes.length === 13 &&
        qualityControlLanes.every((lane) => lane.local_route_ready === true &&
          lane.cloud_gpu_is_product_runtime_dependency === false &&
          lane.model_judge_can_promote === false && lane.human_release_required === true) &&
        adaptiveGraph?.schema === "ProofLaunchGTMAdaptiveCapabilityGraphPublicV1" &&
        /^[0-9a-f]{64}$/.test(String(adaptiveGraphDigest ?? "")) &&
        adaptiveGraphComputedDigest === adaptiveGraphDigest &&
        adaptiveGraph.coverage?.context_count === 6912 &&
        adaptiveGraph.coverage?.lane_decision_count === 89856 &&
        adaptiveGraph.coverage?.zero_budget_paid_activation_count === 0 &&
        adaptiveGraph.coverage?.regulated_missing_specialist_gate_count === 0 &&
        adaptiveGraph.coverage?.automatic_external_action_count === 0 &&
        adaptiveGraph.coverage?.named_product_pk_jobs_preserved === 130 &&
        adaptiveGraph.coverage?.named_product_pk_wins === 0 &&
        adaptiveGraph.executor_binding?.included_in_plan_identity === false &&
        adaptiveGraph.shadow_candidate_registry?.automatic_skill_script_execution_enabled === false &&
        adaptiveGraph.shadow_candidate_registry?.automatic_online_training_enabled === false &&
        adaptiveGraph.selected_context?.human_release_required === true &&
        adaptiveGraph.selected_context?.automatic_external_actions === 0 &&
        Object.keys(adaptiveGraph.selected_context?.lane_states ?? {}).length === 13 &&
        Object.values(adaptiveGraph.selected_context?.lane_states ?? {}).filter((state) => state === "FOCUS").length === 4 &&
        categories.every((category) => category.status === "awaiting_authorized_baselines" &&
          category.capture_slot_count === 10 && category.authorized_baseline_count === 0 &&
          Array.isArray(category.allowed_extensions) && category.allowed_extensions.length > 0 &&
          Number.isInteger(category.maximum_artifact_bytes) && category.maximum_artifact_bytes > 0);
      if (!valid) throw new Error("named-product capture kit failed schema, digest, or authority validation");
      if (badge) {
        badge.textContent = "6,912 adaptive contexts · 13/13 local lanes · 130 PK slots · 0 wins";
        badge.className = "status-badge status-badge--required";
      }
      replaceList(
        "named-baseline-categories",
        categories,
        "No named-product capture categories are available.",
        (category) => {
          const result = portfolioCategories.find((item) => item.category_id === category.category_id);
          const candidate = admissionCategories.find((item) => item.category_id === category.category_id);
          const admissionState = candidate?.named_product_pk_preparation_admitted
            ? "challenger admitted"
            : `repair ${candidate?.blocking_gap_count ?? "?"}: ${(candidate?.blocking_gaps ?? []).join("; ")}`;
          return `${category.category_id} · ${admissionState} · ${category.capture_slot_count}/10 frozen · ${result?.completed_product_pk_rows ?? 0}/10 reviewed · ${result?.candidate_won_product_pk_rows ?? 0}/10 won`;
        }
      );
      setText("named-baseline-boundary", `${admission.truth_boundary} · adaptive default ${adaptiveGraph.selected_context.context_id} · capability routing remains hardware/provider independent · adaptive sha256:${adaptiveGraphDigest} · routing sha256:${qualityControlDigest} · admission sha256:${admissionDigest} · capture sha256:${suppliedDigest} · PK sha256:${portfolioDigest}`);
      return kit;
    } catch (error) {
      if (badge) {
        badge.textContent = "Named-product capture kit unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      replaceList("named-baseline-categories", [], "Capture kit unavailable.", (item) => String(item));
      setText("named-baseline-boundary", `Capture evidence failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  async function loadPublicSignalPilot() {
    try {
      const pilot = await requestJson("/v1/public-signal-pilot");
      const unsigned = pilot && typeof pilot === "object" ? { ...pilot } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const platformCounts = pilot?.platform_counts;
      const valid = pilot?.schema === "ProofLaunchPublicSignalGTMPilotPublicV1" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        computedDigest === suppliedDigest &&
        pilot.status === "awaiting_human_release" &&
        pilot.run_data_class === "internal" &&
        pilot.creative_signal_data_class === "public" &&
        Number.isInteger(pilot.signal_count) && pilot.signal_count > 0 &&
        Number.isInteger(pilot.hypothesis_count) && pilot.hypothesis_count > 0 &&
        platformCounts && typeof platformCounts === "object" &&
        Object.values(platformCounts).reduce((total, value) => total + Number(value), 0) === pilot.signal_count &&
        pilot.automatic_strategy_mutation_executed === false &&
        pilot.automatic_schedule_mutation_executed === false &&
        pilot.external_release_executed === false &&
        pilot.human_release_required === true;
      if (!valid) throw new Error("public signal pilot failed schema, digest, or authority validation");
      state.publicSignalPilot = pilot;
      const platforms = Object.entries(platformCounts)
        .map(([platform, count]) => `${platform} ${count}`)
        .join(" · ");
      setText(
        "cockpit-context",
        `${pilot.signal_count} real public metadata signals · ${platforms} · ${pilot.hypothesis_count} source-bound hypotheses · human release required · automatic mutation disabled`
      );
      return pilot;
    } catch (error) {
      state.publicSignalPilot = null;
      setText("cockpit-context", `Real public-signal pilot unavailable: ${String(error.message ?? error)}`);
      return null;
    }
  }

  async function loadGTMCockpit() {
    const status = getElement("gtm-cockpit-status");
    await loadLastMileProductionQuality();
    await loadPlatformCapabilityShowcase();
    await loadCodexIntegratedCampaignPortfolio();
    await loadCodexCampaignAdaptationSummary();
    await loadCodexLighthousePortfolio();
    await loadConcreteProductEffectPK();
    await loadNamedProductBaselineCaptureKit();
    await loadPublicSignalPilot();
    if (!state.runId) {
      state.gtmCockpit = null;
      if (status) {
        status.textContent = "Run required";
        status.className = "status-badge status-badge--blocked";
      }
      setText("cockpit-run-stage", "Create a governed run in Campaign World State.");
      setText("cockpit-boundary", "No run is loaded; no strategy, effect, revenue, or quality claim is available.");
      replaceList("cockpit-next-actions", [], "Start with one rights-bound campaign run.", (item) => String(item));
      return null;
    }
    try {
      const cockpit = await requestJson(`/v1/runs/${encodeURIComponent(state.runId)}/gtm-cockpit`);
      await renderGTMCockpit(cockpit);
      return cockpit;
    } catch (error) {
      state.gtmCockpit = null;
      if (status) {
        status.textContent = "Cockpit unavailable";
        status.className = "status-badge status-badge--blocked";
      }
      setText("cockpit-boundary", `Cockpit failed closed: ${String(error.message ?? error)}`);
      return null;
    }
  }

  async function loadSyntheticLifecycleDemo(control) {
    const status = getElement("gtm-cockpit-status");
    if (status) {
      status.textContent = "Verifying synthetic proof";
      status.className = "status-badge status-badge--waiting";
    }
    try {
      const demo = state.syntheticLifecycleDemo ?? await requestJson("/v1/demo/synthetic-lifecycle");
      const unsigned = demo && typeof demo === "object" ? { ...demo } : null;
      const suppliedDigest = unsigned?.content_sha256;
      if (unsigned) delete unsigned.content_sha256;
      const computedDigest = unsigned
        ? await sha256Text(JSON.stringify(stableJsonValue(unsigned)))
        : null;
      const valid = demo?.schema === "ProofLaunchSyntheticLifecycleDemoV1" &&
        demo.evidence_class === "synthetic_mechanics_only" &&
        /^[0-9a-f]{64}$/.test(String(suppliedDigest ?? "")) &&
        computedDigest === suppliedDigest &&
        demo.external_api_calls === 0 &&
        demo.external_publish_executed === false &&
        demo.paid_media_spend_usd === 0 &&
        demo.production_effect_proven === false &&
        demo.four_a_effect_claim_eligible === false &&
        demo.device_a?.schema === "ProofLaunchGTMCockpitV1" &&
        demo.device_b?.schema === "ProofLaunchGTMCockpitV1";
      if (!valid) throw new Error("synthetic lifecycle envelope failed integrity validation");
      state.syntheticLifecycleDemo = demo;
      const device = state.gtmCockpit?.content_sha256 === demo.device_a.content_sha256
        ? "device_b"
        : (control?.dataset?.demoDevice === "device_b" ? "device_b" : "device_a");
      await renderGTMCockpit(demo[device]);
      if (status) {
        status.textContent = device === "device_a"
          ? "Synthetic closed loop · Device A"
          : "Synthetic inherited cycle · Device B";
        status.className = "status-badge status-badge--verified";
      }
      setText(
        "cockpit-boundary",
        `${demo[device].truth_boundary} · synthetic mechanics only · click the status control to switch device · envelope sha256:${suppliedDigest}`
      );
    } catch (error) {
      state.syntheticLifecycleDemo = null;
      if (status) {
        status.textContent = "Synthetic proof blocked";
        status.className = "status-badge status-badge--blocked";
      }
      setText(
        "cockpit-boundary",
        `Synthetic lifecycle demo failed closed: ${String(error.message ?? error)}`
      );
    }
  }

  async function renderRunPreview(preview) {
    setText("preview-digest", typeof preview.preview_digest === "string" ? preview.preview_digest : "Missing digest — approval disabled");
    replaceList(
      "preview-claims",
      preview.claims,
      "No claims returned.",
      (claim) => `${claim?.id ?? "claim"}: ${claim?.text ?? "missing text"} · ${claim?.approved === true ? "source-bound" : "unapproved"}`
    );
    replaceList(
      "preview-briefs",
      preview.briefs ?? (preview.brief ? [preview.brief] : []),
      "No brief returned.",
      (brief) => `${brief?.headline ?? brief?.id ?? "brief"} · ${brief?.visual_direction ?? "no visual direction"}`
    );
    replaceList(
      "preview-findings",
      preview.findings,
      "No audit findings returned.",
      (finding) => `${finding?.severity ?? "unknown"}: ${finding?.message ?? finding?.category ?? "missing finding"}`
    );
    renderChannelPortfolio(preview?.gtm_strategy?.channel_portfolio);
    renderIndustryGTMProfile(preview?.gtm_strategy?.industry_gtm_profile);
    renderBreakoutGrowthLoop(preview?.gtm_strategy?.breakout_growth_loop);
    renderTextCreativeChallenger(preview?.gtm_strategy?.text_creative_challenger);
    renderContentCalendar(preview?.gtm_strategy?.content_calendar);
    renderCampaignWorkspace(preview?.campaign_workspace);
    await renderSafePreviewAsset(preview);
    const validDigest = typeof preview.preview_digest === "string" && /^[0-9a-f]{64}$/.test(preview.preview_digest);
    state.previewReady = validDigest;
    const approvalButton = getElement("approval-submit");
    if (approvalButton instanceof HTMLButtonElement) {
      approvalButton.disabled = state.runStatus !== "awaiting_release" || !validDigest;
    }
  }

  async function loadRunPreview() {
    if (!state.runId) return null;
    try {
      const preview = await requestJson(`/v1/runs/${encodeURIComponent(state.runId)}/preview`);
      await renderRunPreview(preview);
      return preview;
    } catch (error) {
      state.previewReady = false;
      setText("preview-digest", "Preview unavailable");
      setText("approval-output", `Preview blocked: ${String(error.message ?? error)}`);
      const approvalButton = getElement("approval-submit");
      if (approvalButton instanceof HTMLButtonElement) approvalButton.disabled = true;
      return null;
    }
  }

  async function refreshRunSnapshot() {
    if (!state.runId) return null;
    const snapshot = await requestJson(`/v1/runs/${encodeURIComponent(state.runId)}`);
    if (typeof snapshot.status === "string") setRunStatus(snapshot.status);
    renderJson("world-state-output", snapshot);
    if (snapshot.status === "awaiting_release" || snapshot.status === "delivered") {
      await loadRunPreview();
    }
    return snapshot;
  }

  function setRuntimeState(label, markerClass) {
    const runtime = getElement("runtime-state");
    if (!runtime) return;
    const marker = document.createElement("span");
    marker.className = `state-mark ${markerClass}`;
    marker.setAttribute("aria-hidden", "true");
    runtime.replaceChildren(marker, document.createTextNode(label));
  }

  async function probeControlPlane() {
    try {
      const health = await requestJson("/v1/health");
      state.apiConnected = health.api_connected === true;
      setRuntimeState("Local deterministic Agent connected · external release off", "state-mark--queued");
      renderPerformance(health);
      updateCreateControls();
      return health;
    } catch {
      state.apiConnected = false;
      setRuntimeState("Static UI · control plane disconnected", "state-mark--blocked");
      updateCreateControls();
      return null;
    }
  }

  function renderPerformance(health) {
    const facts = getElement("performance-facts");
    if (!facts || !health) {
      return;
    }
    const rows = [
      ["API", health.api_connected ? "Connected" : "Disconnected"],
      ["Execution mode", health.execution_mode ?? "Unknown"],
      ["Radeon", health.radeon_metrics_observed ? "Observed" : "Not observed"],
      ["Model inference", health.model_inference_observed ? "Observed" : "Not observed"],
      ["External release", health.external_release_enabled ? "Enabled" : "Disabled"]
    ];
    facts.replaceChildren(...rows.map(([term, value]) => {
      const wrapper = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      dd.textContent = value;
      wrapper.append(dt, dd);
      return wrapper;
    }));
  }

  function renderProductReadiness(readiness) {
    state.productReadiness = readiness;
    const generation = readiness?.generation ?? {};
    const observed = readiness?.observed ?? {};
    const localModels = readiness?.local_models ?? {};
    const routeHead = localModels?.route_head ?? {};
    const generator = localModels?.generator ?? {};
    const strategyChallenger = localModels?.strategy_challenger ?? {};
    const strategyPortfolio = localModels?.strategy_portfolio ?? {};
    const localMission = readiness?.local_mission ?? {};
    const localCreativeBenchmark = readiness?.local_creative_benchmark ?? {};
    const portfolioBlindReview = readiness?.portfolio_blind_review ?? {};
    const cloudUpgrade = readiness?.cloud_upgrade ?? {};
    const localPack = readiness?.local_campaign_pack ?? {};
    const lifecycleClosure = readiness?.lifecycle_closure ?? {};
    const blueprintReady = Number(generation.official_blueprint_count) > 0;
    const apiReady = Number(generation.api_export_count) > 0;
    const backendReady = Number(generation.admitted_backend_count) > 0;
    const candidateReady = generation.candidate_search_ready === true;
    const multimodalReady = generation.progressive_multimodal_funnel_ready === true;
    const actualOutput = localPack.observed === true && localPack.mechanical_ready === true;
    const blindObserved = observed.human_blind_preference === "observed";
    const effectProven = observed.four_a_effect_claim === "eligible";
    const badge = getElement("generation-readiness-badge");
    if (badge) {
      badge.textContent = actualOutput && effectProven ? "Effect eligible" : "Production evidence incomplete";
      badge.className = `status-badge ${actualOutput && effectProven ? "status-badge--verified" : "status-badge--blocked"}`;
    }
    const gates = Array.isArray(readiness.remaining_gates) ? readiness.remaining_gates : [];
    const stages = [
      ["01 OFFICIAL BLUEPRINTS", blueprintReady ? `READY (${generation.official_blueprint_count})` : "BLOCKED"],
      ["02 API WORKFLOW EXPORT", apiReady ? `READY (${generation.api_export_count})` : "REQUIRED"],
      ["03 MODEL + GPU ADMISSION", backendReady ? `READY (${generation.admitted_backend_count})` : "REQUIRED"],
      ["04 MULTI-ROUTE SEARCH", candidateReady ? "MECHANICS READY" : "BLOCKED"],
      ["05 HUMAN BLIND FINALIST", blindObserved ? "OBSERVED" : "NOT OBSERVED"],
      ["06 VIDEO + MUSIC + SPEECH", actualOutput ? "OBSERVED" : (multimodalReady ? "MECHANICS READY" : "BLOCKED")],
      ["07 EFFECT PROOF", effectProven ? "ELIGIBLE" : "UNPROVEN"],
      ["08 FULL LIFECYCLE", lifecycleClosure.observed === true && lifecycleClosure.ten_capabilities_connected === true ? `${lifecycleClosure.case_count} CONTRACTS / ${lifecycleClosure.scenario_count} TRAJECTORIES` : "BLOCKED"],
      ["09 CAMPAIGN WORKSPACE", lifecycleClosure.campaign_workspace_artifact_count === 9 && lifecycleClosure.campaign_workspace_same_evidence_spine === true && lifecycleClosure.campaign_workspace_activations_disabled === true ? "9 BOUND DRAFTS / ACTIVATION DISABLED" : "BLOCKED"],
      [
        "10 POST-SELECTION ×456",
        lifecycleClosure.post_selection_omnichannel_lane_count === 9
          && lifecycleClosure.all_post_selection_campaign_identities_bound === true
          && lifecycleClosure.all_post_selection_creative_systems_connected === true
          && lifecycleClosure.all_post_selection_evidence_spines_connected === true
          && lifecycleClosure.all_post_selection_external_actions_disabled === true
          ? "9 LANES / SYNTHETIC CONTRACTS PASS"
          : "BLOCKED"
      ]
    ];
    setText(
      "generation-readiness-output",
      [
        "PROGRESSIVE PRODUCTION · TRUTHFUL LIVE STATE",
        "Search routes → blind finalist → hero video → music → speech → effect review",
        "",
        ...stages.map(([name, value]) => `${name.padEnd(30)} ${value}`),
        "",
        `REAL MODEL OUTPUT              ${observed.model_generated_multimodal ?? "UNKNOWN"}`,
        `COMFYUI EXECUTION              ${observed.comfyui_execution ?? "UNKNOWN"}`,
        `PREMIUM EFFECT CLAIM           ${observed.four_a_effect_claim ?? "UNKNOWN"}`,
        `LIFECYCLE FAILURE MODES        ${lifecycleClosure.named_failure_mode_count ?? 0}`,
        `MIN CASES / FAILURE MODE       ${lifecycleClosure.minimum_cases_per_failure_mode ?? 0}`,
        `ZERO-BUDGET PAID EXCLUSION     ${lifecycleClosure.zero_budget_paid_channels_excluded === true}`,
        `POSITIVE PATH HUMAN GATE       ${lifecycleClosure.positive_paths_require_human_review === true}`,
        `CAMPAIGN WORKSPACE ARTIFACTS   ${lifecycleClosure.campaign_workspace_artifact_count ?? 0}`,
        `WORKSPACE SAME EVIDENCE SPINE  ${lifecycleClosure.campaign_workspace_same_evidence_spine === true}`,
        `WORKSPACE ACTIVATION DISABLED  ${lifecycleClosure.campaign_workspace_activations_disabled === true}`,
        `POST-SELECT IDENTITY BOUND     ${lifecycleClosure.all_post_selection_campaign_identities_bound === true}`,
        `POST-SELECT CREATIVE CONNECTED ${lifecycleClosure.all_post_selection_creative_systems_connected === true}`,
        `POST-SELECT EVIDENCE CONNECTED ${lifecycleClosure.all_post_selection_evidence_spines_connected === true}`,
        `POST-SELECT HUMAN OBSERVATIONS ${lifecycleClosure.post_selection_human_observations ?? 0}`,
        `PRODUCTION OUTCOMES OBSERVED   ${lifecycleClosure.production_outcomes_observed ?? 0}`,
        "",
        "NEXT EVIDENCE GATES",
        ...(gates.length > 0 ? gates.map((gate, index) => `${index + 1}. ${gate}`) : ["None declared"])
      ].join("\n")
    );
    const trainingBadge = getElement("training-readiness-badge");
    const localTrainingObserved = routeHead.observed === true;
    const localMissionObserved = localMission.observed === true;
    if (trainingBadge) {
      trainingBadge.textContent = localMissionObserved
        ? "Local mission ready · human blind review required"
        : (localTrainingObserved ? "Local training observed · not promoted" : "Local training unobserved");
      trainingBadge.className = `status-badge ${(localMissionObserved || localTrainingObserved) ? "status-badge--verified" : "status-badge--blocked"}`;
    }
    setText(
      "training-route-model",
      localTrainingObserved ? `${routeHead.model_id} · ${String(routeHead.digest ?? "").slice(0, 12)}…` : "Not observed"
    );
    setText(
      "training-corpus",
      localTrainingObserved ? `${routeHead.training_records} rights-verified episodes · download=${routeHead.network_download_performed}` : "Not observed"
    );
    setText(
      "training-test",
      localTrainingObserved ? `${routeHead.test_examples} frozen · F1 ${Number(routeHead.macro_f1).toFixed(4)} · accepted ${(Number(routeHead.accepted_coverage) * 100).toFixed(2)}%` : "Not observed"
    );
    setText(
      "training-generator",
      generator.observed === true ? `${generator.model_id} · ${(Number(generator.first_pass_contract_rate) * 100).toFixed(2)}% → ${(Number(generator.final_contract_pass_rate) * 100).toFixed(2)}% contract` : "Not observed"
    );
    setText(
      "training-evidence-output",
      [
        "LOCAL MODEL EVIDENCE · HASH-BOUND READINESS",
        `ROUTE TRAINING OBSERVED       ${localTrainingObserved}`,
        `ROUTE PROMOTION GATE          ${routeHead.promotion_gate_passed === true ? "PASSED" : "NOT PASSED"}`,
        `ROUTE PROMOTED                ${routeHead.promoted === true}`,
        `ROUTE ACCEPTED ACCURACY       ${localTrainingObserved ? Number(routeHead.accepted_accuracy).toFixed(4) : "N/A"}`,
        `GENERATOR TRAINING OBSERVED   ${generator.training_observed === true}`,
        `GENERATOR REPAIR CALLS        ${generator.repair_calls ?? 0}`,
        `DETERMINISTIC NORMALIZATIONS  ${generator.wrapper_normalizations ?? 0}`,
        `GEMMA 3 12B CHALLENGER        ${strategyChallenger.accepted === true ? "CONTRACT ACCEPTED" : "NOT ACCEPTED"}`,
        `CHALLENGER MODEL              ${strategyChallenger.model_id ?? "N/A"}`,
        `CHALLENGER ATTEMPTS           ${strategyChallenger.attempt_count ?? 0}`,
        `CHALLENGER CANDIDATE SHA      ${strategyChallenger.candidate_sha256 ?? "N/A"}`,
        `CHALLENGER TRAIN / RADEON     ${strategyChallenger.training_observed === true} / ${strategyChallenger.radeon_local_inference_observed === true}`,
        `CHALLENGER HUMAN / EFFECT     ${strategyChallenger.human_preference_observed === true} / ${strategyChallenger.effect_observed === true}`,
        `12B STRATEGY PORTFOLIO        ${strategyPortfolio.quality_gate_passed === true ? "8/8 CONTRACT + DIVERSITY PASS" : "NOT PASSED"}`,
        `PORTFOLIO CHANNELS            ${Object.entries(strategyPortfolio.channel_distribution ?? {}).map(([channel, count]) => `${channel}:${count}`).join(" · ") || "N/A"}`,
        `PORTFOLIO UNIQUE STRATEGIES   ${strategyPortfolio.unique_strategy_count ?? 0}`,
        `PORTFOLIO MAX JACCARD         ${strategyPortfolio.maximum_pairwise_content_jaccard ?? "N/A"} / ${strategyPortfolio.maximum_allowed_pairwise_content_jaccard ?? 0.60}`,
        `PORTFOLIO HUMAN / EFFECT      ${strategyPortfolio.human_preference_observed === true} / ${strategyPortfolio.effect_observed === true}`,
        `PORTFOLIO UNIVERSAL CLAIM     ${strategyPortfolio.any_industry_generalization_claim_eligible === true}`,
        `GTM MISSION OBSERVED          ${localMissionObserved}`,
        `GTM MISSION RUN               ${localMission.run_id ?? "N/A"}`,
        `GTM MODEL CALLS               ${localMission.completed_model_calls ?? 0}`,
        `VALIDATED CANDIDATES          ${localMission.validated_candidate_count ?? 0}`,
        `BLIND PAIRS / EMPTY TASKS     ${localMission.blind_pair_count ?? 0} / ${localMission.empty_human_review_task_count ?? 0}`,
        `LIVE HUMAN REVIEWS            ${localMission.live_human_review_submitted_count ?? 0} / 30`,
        `HUMAN REVIEW COMPLETED        ${localMission.human_review_completed === true}`,
        `WINNER SELECTED               ${localMission.winner_selected === true}`,
        `MULTIMODAL ENTRY CREATED      ${localMission.multimodal_production_entry_created === true}`,
        `POST-SELECTION COMPILER       ${localMission.post_selection_compiler_ready === true ? `${localMission.post_selection_compiler_lane_count ?? 0} lanes ready` : "NOT READY"}`,
        `OMNICHANNEL COMPILER          ${localMission.omnichannel_compiler_ready === true ? `${localMission.omnichannel_compiler_lane_count ?? 0} lanes ready` : "NOT READY"}`,
        `OMNICHANNEL ACTIVATION SEEN   ${localMission.omnichannel_activation_observed === true}`,
        `OMNICHANNEL AUTO ACTION       ${localMission.omnichannel_automatic_external_action_enabled === true}`,
        `AUTOMATIC GPU EXECUTION       ${localMission.post_selection_compiler_automatic_gpu_execution_enabled === true}`,
        `8-CASE BENCHMARK STATUS       ${localCreativeBenchmark.status ?? "not_observed"}`,
        `BENCHMARK PREFLIGHT PASSED    ${localCreativeBenchmark.preflight_passed === true}`,
        `BENCHMARK CASES               ${localCreativeBenchmark.completed_case_count ?? 0} completed / ${localCreativeBenchmark.observed_case_count ?? 0} observed / ${localCreativeBenchmark.planned_case_count ?? 0} planned`,
        `BENCHMARK MODEL CALLS         ${localCreativeBenchmark.completed_model_call_count ?? 0} / ${localCreativeBenchmark.planned_model_call_count ?? 0}`,
        `BENCHMARK CANDIDATES          ${localCreativeBenchmark.validated_candidate_count ?? 0}`,
        `BENCHMARK BLOCKER             ${localCreativeBenchmark.blocker ?? "none"}`,
        `PORTFOLIO BLIND STATUS        ${portfolioBlindReview.status ?? "not_observed"}`,
        `PORTFOLIO CASES / PAIRS       ${portfolioBlindReview.case_count ?? 0} / ${portfolioBlindReview.pair_count ?? 0}`,
        `PORTFOLIO HUMAN REVIEWS       ${portfolioBlindReview.submitted_review_count ?? 0} / ${portfolioBlindReview.expected_review_count ?? 0}`,
        `PORTFOLIO REVIEW COMPLETE     ${portfolioBlindReview.review_complete === true}`,
        `PORTFOLIO PROMOTION PASSED    ${portfolioBlindReview.portfolio_promotion_passed === true}`,
        `PORTFOLIO HUMAN PREF SEEN     ${portfolioBlindReview.human_preference_observed === true}`,
        `LOCAL CLOUD CALLS             ${(routeHead.cloud_api_calls ?? 0) + (generator.cloud_api_calls ?? 0)}`,
        `FREE CLOUD CANDIDATES         ${cloudUpgrade.free_api_candidate_count ?? 0}`,
        `FREE CLOUD LIVE CALLS         ${cloudUpgrade.live_calls_executed ?? 0}`,
        `FREE GPU ROUTES               ${cloudUpgrade.free_compute_route_count ?? 0}`,
        "",
        "BOUNDARY · Generator evaluation and the 9-case benchmark are not fine-tuning. The 270-task portfolio is empty until named humans submit it. Local Apple execution is not Radeon evidence. External action remains disabled."
      ].join("\n")
    );
  }

  async function probeProductReadiness() {
    try {
      const readiness = await requestJson("/v1/product-readiness");
      renderProductReadiness(readiness);
      return readiness;
    } catch (error) {
      state.productReadiness = null;
      const badge = getElement("generation-readiness-badge");
      if (badge) {
        badge.textContent = "Readiness unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      setText("generation-readiness-output", `Readiness receipt unavailable: ${String(error.message ?? error)}`);
      return null;
    }
  }

  async function probeLaunchProofControl() {
    try {
      const control = await requestJson("/v1/launch-proof/status");
      const gates = Array.isArray(control?.gates) ? control.gates : [];
      const existing = String(getElement("training-evidence-output")?.textContent ?? "").trimEnd();
      const lines = [
        "",
        "LAUNCH PROOF CONTROL · DYNAMIC, FAIL-CLOSED",
        `DECISION                      ${control.launch_decision ?? "unavailable"}`,
        `PASSED / BLOCKED              ${control.passed_gate_count ?? 0} / ${control.blocked_gate_count ?? gates.length}`,
        ...gates.map((gate) => `${String(gate.gate_id ?? "unknown").toUpperCase().padEnd(29, " ")} ${gate.passed === true ? "PASS" : gate.observed === true ? "OBSERVED · NOT PASSED" : "NOT OBSERVED"}`),
        "",
        "NEXT REQUIRED ACTIONS",
        ...(Array.isArray(control.next_actions) && control.next_actions.length > 0
          ? control.next_actions.map((action, index) => `${index + 1}. ${String(action)}`)
          : ["All evidence gates passed; a named operator must still authorize any consequential action."]),
        "",
        `AUTOMATIC PUBLISH / SPEND     ${control.automatic_publish_enabled === true} / ${control.automatic_spend_enabled === true}`,
        `CRAFT / TOP-1 / CAUSAL REVENUE ${control.four_a_claim_allowed === true} / ${control.top1_claim_allowed === true} / ${control.causal_revenue_claim_allowed === true}`
      ];
      setText("training-evidence-output", `${existing}\n${lines.join("\n")}`);
      const badge = getElement("training-readiness-badge");
      if (badge) {
        badge.textContent = `${control.passed_gate_count ?? 0}/${control.gate_count ?? gates.length} launch-proof gates`;
        badge.className = `status-badge ${control.blocked_gate_count === 0 ? "status-badge--verified" : "status-badge--required"}`;
      }
      return control;
    } catch (error) {
      const existing = String(getElement("training-evidence-output")?.textContent ?? "").trimEnd();
      setText("training-evidence-output", `${existing}\n\nLaunch proof control unavailable: ${String(error.message ?? error)}`);
      return null;
    }
  }

  function blindReviewBase(scope) {
    if (scope === "calibration") return "/v1/judge-calibration";
    if (scope === "campaign_pack") return "/v1/campaign-pack-blind-review";
    return scope === "portfolio" ? "/v1/portfolio-blind-review" : "/v1/blind-review";
  }

  function currentBlindReviewScope() {
    const input = getElement("blind-review-scope");
    if (!(input instanceof HTMLSelectElement)) return "portfolio";
    return ["portfolio", "mission", "calibration", "campaign_pack"].includes(input.value) ? input.value : "portfolio";
  }

  function blindReviewScopeLabel(scope) {
    if (scope === "calibration") return "Judge calibration";
    if (scope === "campaign_pack") return "Campaign pack visual system";
    return scope === "mission" ? "Current campaign" : "Nine-case portfolio";
  }

  function renderBlindReviewStatus(status, scope = currentBlindReviewScope()) {
    const submitted = Number(status?.submitted_review_count ?? 0);
    const expected = Number(status?.expected_review_count ?? (scope === "portfolio" ? 270 : scope === "calibration" ? 300 : scope === "campaign_pack" ? 5 : 30));
    const remaining = Number(status?.remaining_review_count ?? Math.max(0, expected - submitted));
    const complete = status?.review_complete === true;
    const portfolio = scope === "portfolio";
    const calibration = scope === "calibration";
    const campaignPack = scope === "campaign_pack";
    const badge = getElement("blind-review-badge");
    if (badge) {
      badge.textContent = complete ? `${expected} / ${expected} · integrity complete` : `${submitted} / ${expected} · ${remaining} remaining`;
      badge.className = `status-badge ${complete ? "status-badge--verified" : "status-badge--required"}`;
    }
    const perSlot = status?.per_reviewer_slot_submitted ?? {};
    const configuredSlots = Number(status?.configured_reviewer_slot_count ?? 5);
    const perSlotExpected = configuredSlots > 0 ? expected / configuredSlots : 0;
    const selectionForm = getElement("blind-review-selection-form");
    const recommendationInput = getElement("blind-review-recommendation");
    if (selectionForm instanceof HTMLFormElement) {
      selectionForm.hidden = scope !== "mission" || !complete || status?.human_selection_eligible !== true || status?.multimodal_production_entry_created === true;
      selectionForm.dataset.aggregateSha256 = String(status?.blind_review_aggregate_sha256 ?? "");
    }
    if (recommendationInput instanceof HTMLInputElement) {
      recommendationInput.value = String(status?.recommended_territory_id ?? "");
    }
    setText(
      "blind-review-progress",
      `${blindReviewScopeLabel(scope)} public progress · ${submitted}/${expected} submitted · slots ${[1, 2, 3, 4, 5].map((slot) => `${slot}:${perSlot[String(slot)] ?? 0}/${perSlotExpected}`).join(" · ")} · private mapping exposed=${status?.private_mapping_exposed === true}`
    );
    if (complete) {
      setText(
        "blind-review-output",
        calibration
          ? `Judge calibration aggregate complete · calibrated=${status?.judge_calibrated === true} · sha256:${status?.aggregate_content_sha256 ?? "not available"}. Automatic judge promotion=false; external publish=false.`
          : campaignPack
          ? `Campaign-pack human aggregate complete · recommendation eligible=${status?.promotion_recommendation_eligible === true} · recommended candidate=${status?.recommended_candidate_id ?? "none"} · sha256:${status?.aggregate_content_sha256 ?? "not available"}. Automatic switch=false; publish=false; premium/effect claim=false.`
          : portfolio
          ? `Portfolio aggregate complete · promotion gate=${status?.portfolio_promotion_passed === true}. Automatic winner selection=false; external publish=false; causal lift/revenue/Top-1 claim=false.`
          : status?.multimodal_production_entry_created === true
          ? `Human selection bound · ${status.selected_territory_id} · media compilation sha256:${status.multimodal_seed_compilation_sha256 ?? "not created"} · omnichannel ${status.omnichannel_activation_lane_count ?? 0}/9 sha256:${status.omnichannel_activation_plan_sha256 ?? "not created"}. GPU=false; publish=false; send=false; spend=false.`
          : `Integrity-complete human aggregate. Recommendation: ${status.recommended_territory_id ?? "none passed threshold"}. Winner selected=false; external publish=false.`
      );
    }
  }

  async function probeBlindReviewStatus(scope = currentBlindReviewScope()) {
    try {
      const status = await requestJson(`${blindReviewBase(scope)}/status`);
      renderBlindReviewStatus(status, scope);
      if (scope === "mission" && status?.omnichannel_activation_plan_created === true) {
        const activation = await requestJson("/v1/blind-review/activation");
        const lanes = Array.isArray(activation?.lanes) ? activation.lanes : [];
        const byId = Object.fromEntries(lanes.map((lane) => [lane.lane_id, lane.draft ?? {}]));
        setText(
          "blind-review-output",
          [
            "HUMAN-SELECTED OMNICHANNEL ACTIVATION · DRAFT ONLY",
            `SELECTED TERRITORY            ${activation.selected_territory_id ?? "N/A"}`,
            `ACTIVATION SHA256             ${activation.content_sha256 ?? "N/A"}`,
            `LANES                         ${activation.lane_count ?? 0}/9`,
            `LANDING HEADLINE              ${byId.landing_page?.headline ?? "N/A"}`,
            `LANDING PROOF                 ${byId.landing_page?.supporting_proof ?? "N/A"}`,
            `EMAIL SUBJECT                 ${byId.lifecycle_email?.subject ?? "N/A"}`,
            `SEO/GEO QUESTION              ${byId.seo_geo_answer?.question ?? "N/A"}`,
            `SCHEDULE SLOTS                ${byId.content_schedule?.slot_count ?? 0}`,
            `PRIMARY EFFECT METRIC         ${byId.effect_instrumentation?.primary_metric ?? "N/A"}`,
            "",
            "HUMAN RELEASE REQUIRED · GPU=false · publish=false · send=false · spend=false · effect claim=false"
          ].join("\n")
        );
      }
      return status;
    } catch (error) {
      const badge = getElement("blind-review-badge");
      if (badge) {
        badge.textContent = "Blind review unavailable";
        badge.className = "status-badge status-badge--blocked";
      }
      setText("blind-review-progress", `Review queue unavailable: ${String(error.message ?? error)}`);
      return null;
    }
  }

  function appendBlindDraft(container, sideLabel, draft) {
    const article = document.createElement("article");
    article.className = "blind-review-draft";
    const heading = document.createElement("h5");
    heading.textContent = `Draft ${sideLabel}`;
    const format = document.createElement("small");
    format.textContent = String(draft?.native_format ?? draft?.channel ?? "Unknown format");
    const hook = document.createElement("p");
    const hookStrong = document.createElement("strong");
    hookStrong.textContent = "Hook · ";
    hook.append(hookStrong, document.createTextNode(String(draft?.hook ?? "")));
    const body = document.createElement("ul");
    const rows = Array.isArray(draft?.body) ? draft.body : [];
    body.replaceChildren(...rows.map((row) => {
      const item = document.createElement("li");
      item.textContent = String(row);
      return item;
    }));
    const cta = document.createElement("p");
    const ctaStrong = document.createElement("strong");
    ctaStrong.textContent = "CTA · ";
    cta.append(ctaStrong, document.createTextNode(String(draft?.cta ?? "")));
    article.append(heading, format, hook, body, cta);
    container.append(article);
  }

  function renderCalibrationTasks(assignment) {
    const list = getElement("blind-review-task-list");
    if (!list) return;
    const tasks = Array.isArray(assignment?.tasks) ? assignment.tasks : [];
    list.replaceChildren(...tasks.map((task, index) => {
      const form = document.createElement("form");
      form.className = "blind-review-card";
      form.dataset.reviewTaskId = String(task.review_task_id ?? "");
      const header = document.createElement("div");
      header.className = "blind-review-card__header";
      const title = document.createElement("h4");
      title.textContent = `Calibration case ${index + 1} · ${String(task.case?.failure_slice ?? "governance")}`;
      const stateLabel = document.createElement("span");
      stateLabel.className = "status-badge status-badge--required";
      stateLabel.textContent = "Independent binary label required";
      header.append(title, stateLabel);
      const context = document.createElement("p");
      context.className = "blind-review-card__context";
      context.textContent = `Case ${String(task.case_id ?? "unknown")} · artifact sha256:${String(task.case?.artifact_sha256 ?? "unknown")}`;
      const criterion = document.createElement("pre");
      criterion.className = "contract-output";
      criterion.textContent = String(task.case?.evaluation_prompt ?? "Frozen criterion unavailable");
      const locator = document.createElement("small");
      locator.textContent = `Evidence locator · ${String(task.case?.evidence_locator ?? "unavailable")}`;
      const fieldset = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = "Does the frozen artifact pass this exact criterion?";
      fieldset.append(legend);
      [["true", "PASS"], ["false", "FAIL"]].forEach(([value, labelText]) => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "human_label";
        input.value = value;
        input.required = true;
        label.append(input, document.createTextNode(` ${labelText}`));
        fieldset.append(label);
      });
      const reasonLabel = document.createElement("label");
      const reasonTitle = document.createElement("span");
      reasonTitle.textContent = "Reason against the frozen binary rubric";
      const reason = document.createElement("textarea");
      reason.name = "reason";
      reason.required = true;
      reason.maxLength = 2000;
      reasonLabel.append(reasonTitle, reason);
      const attestLabel = document.createElement("label");
      const attest = document.createElement("input");
      attest.type = "checkbox";
      attest.name = "human_attestation";
      attest.required = true;
      attestLabel.append(attest, document.createTextNode(" I attest this is my independent label; the model prediction and other labels were hidden"));
      const submit = document.createElement("button");
      submit.className = "button button--primary pressable";
      submit.type = "submit";
      submit.textContent = "Submit immutable calibration label";
      form.append(header, context, criterion, locator, fieldset, reasonLabel, attestLabel, submit);
      return form;
    }));
  }

  function renderCampaignPackTasks(assignment) {
    const list = getElement("blind-review-task-list");
    if (!list) return;
    const dimensions = [
      ["concept_originality", "Concept originality"],
      ["information_hierarchy", "Information hierarchy"],
      ["evidence_credibility", "Evidence credibility"],
      ["cross_format_extensibility", "Cross-format extensibility"],
      ["action_motivation", "Action motivation"]
    ];
    const roleLabels = {
      hero_4k: "4K hero",
      social_4x5: "4:5 social",
      landing_1080p: "1080p landing"
    };
    const tasks = Array.isArray(assignment?.tasks) ? assignment.tasks : [];
    list.replaceChildren(...tasks.map((task) => {
      const form = document.createElement("form");
      form.className = "blind-review-card blind-review-card--campaign-pack";
      form.dataset.reviewTaskId = String(task.review_task_id ?? "");
      const header = document.createElement("div");
      header.className = "blind-review-card__header";
      const title = document.createElement("h4");
      title.textContent = "Identity-hidden campaign-system comparison";
      const stateLabel = document.createElement("span");
      stateLabel.className = `status-badge ${task.submitted === true ? "status-badge--verified" : "status-badge--required"}`;
      stateLabel.textContent = task.submitted === true ? "Immutable review recorded" : "Five-dimension review required";
      const offlineKit = document.createElement("button");
      offlineKit.className = "button button--secondary pressable";
      offlineKit.type = "button";
      offlineKit.textContent = "Download offline review kit";
      offlineKit.addEventListener("click", async () => {
        const tokenInput = getElement("blind-review-token");
        if (!(tokenInput instanceof HTMLInputElement) || !tokenInput.value) {
          setText("blind-review-output", "Offline kit blocked: reload the invitation-bound assignment.");
          return;
        }
        offlineKit.disabled = true;
        try {
          const response = await fetch(`${blindReviewBase("campaign_pack")}/offline-kit?slot=${encodeURIComponent(String(assignment.reviewer_slot))}`, {
            headers: { "X-ProofLaunch-Reviewer-Token": tokenInput.value },
            cache: "no-store"
          });
          if (!response.ok) throw new Error(`offline kit request failed with HTTP ${response.status}`);
          const blob = await response.blob();
          const link = document.createElement("a");
          link.href = URL.createObjectURL(blob);
          link.download = `campaign-pack-review-slot-${assignment.reviewer_slot}.zip`;
          link.click();
          window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
          setText("blind-review-output", `Identity-hidden offline kit downloaded for reviewer slot ${assignment.reviewer_slot}. It contains no token and performs no network submission.`);
        } catch (error) {
          setText("blind-review-output", `Offline kit blocked: ${String(error.message ?? error)}`);
        } finally {
          offlineKit.disabled = false;
        }
      });
      const returnedReviewLabel = document.createElement("label");
      returnedReviewLabel.className = "button button--quiet";
      returnedReviewLabel.textContent = "Submit returned review JSON";
      const returnedReview = document.createElement("input");
      returnedReview.type = "file";
      returnedReview.accept = "application/json,.json";
      returnedReview.hidden = true;
      returnedReview.addEventListener("change", async () => {
        const tokenInput = getElement("blind-review-token");
        const file = returnedReview.files?.[0];
        if (!(tokenInput instanceof HTMLInputElement) || !tokenInput.value || !file) return;
        returnedReview.disabled = true;
        try {
          const review = JSON.parse(await file.text());
          if (review?.review_task_id !== task.review_task_id || review?.reviewer_slot !== assignment.reviewer_slot) {
            throw new Error("returned review does not match this invitation-bound task");
          }
          const acknowledgement = await requestJson(`${blindReviewBase("campaign_pack")}/reviews`, {
            method: "POST",
            headers: { "X-ProofLaunch-Reviewer-Token": tokenInput.value },
            body: JSON.stringify(review)
          });
          renderBlindReviewStatus(acknowledgement, "campaign_pack");
          setText("blind-review-output", `Returned offline review recorded immutably · ${acknowledgement.review_task_id} · sha256:${acknowledgement.review_content_sha256}`);
          const refreshed = await requestJson(`${blindReviewBase("campaign_pack")}/tasks?slot=${encodeURIComponent(String(assignment.reviewer_slot))}`, {
            headers: { "X-ProofLaunch-Reviewer-Token": tokenInput.value }
          });
          state.blindReviewAssignment.assignment = refreshed;
          renderBlindReviewTasks(refreshed);
        } catch (error) {
          setText("blind-review-output", `Returned review rejected: ${String(error.message ?? error)}`);
        } finally {
          returnedReview.disabled = false;
          returnedReview.value = "";
        }
      });
      returnedReviewLabel.append(returnedReview);
      header.append(title, stateLabel, offlineKit, returnedReviewLabel);
      const context = document.createElement("p");
      context.className = "blind-review-card__context";
      context.textContent = String(task.pair?.comparison_context ?? "Compare both systems across all three frozen formats.");
      const systems = document.createElement("div");
      systems.className = "campaign-pack-review-systems";
      ["left", "right"].forEach((side) => {
        const section = document.createElement("section");
        section.className = "campaign-pack-review-side";
        const heading = document.createElement("h5");
        heading.textContent = side.toUpperCase();
        section.append(heading);
        const assets = Array.isArray(task.pair?.sides?.[side]?.assets) ? task.pair.sides[side].assets : [];
        assets.forEach((asset) => {
          const figure = document.createElement("figure");
          const image = document.createElement("img");
          image.src = String(asset.url ?? "");
          image.alt = `${side} ${roleLabels[asset.role] ?? String(asset.role ?? "campaign asset")}`;
          image.loading = "lazy";
          image.decoding = "async";
          const caption = document.createElement("figcaption");
          caption.textContent = `${roleLabels[asset.role] ?? String(asset.role ?? "asset")} · ${Number(asset.width ?? 0)}×${Number(asset.height ?? 0)}`;
          figure.append(image, caption);
          section.append(figure);
        });
        systems.append(section);
      });
      const radioGroup = (name, legendText, choices) => {
        const fieldset = document.createElement("fieldset");
        const legend = document.createElement("legend");
        legend.textContent = legendText;
        fieldset.append(legend);
        choices.forEach(([value, labelText]) => {
          const label = document.createElement("label");
          const input = document.createElement("input");
          input.type = "radio";
          input.name = name;
          input.value = value;
          input.required = true;
          input.disabled = task.submitted === true;
          label.append(input, document.createTextNode(` ${labelText}`));
          fieldset.append(label);
        });
        return fieldset;
      };
      const overall = radioGroup("overall_winner", "Overall stronger production campaign system", [["left", "LEFT"], ["right", "RIGHT"]]);
      const dimensionGrid = document.createElement("div");
      dimensionGrid.className = "campaign-pack-review-dimensions";
      dimensions.forEach(([name, label]) => {
        dimensionGrid.append(radioGroup(`dimension_${name}`, label, [["left", "LEFT"], ["right", "RIGHT"], ["tie", "TIE"]]));
      });
      const defect = radioGroup("blocking_defect_side", "Blocking production defect", [["none", "NONE"], ["left", "LEFT"], ["right", "RIGHT"], ["both", "BOTH"]]);
      const defectReasonLabel = document.createElement("label");
      const defectReasonTitle = document.createElement("span");
      defectReasonTitle.textContent = "Located defect reason (required unless NONE)";
      const defectReason = document.createElement("textarea");
      defectReason.name = "blocking_defect_reason";
      defectReason.maxLength = 1200;
      defectReason.disabled = task.submitted === true;
      defectReasonLabel.append(defectReasonTitle, defectReason);
      const notesLabel = document.createElement("label");
      const notesTitle = document.createElement("span");
      notesTitle.textContent = "Independent rationale (24–2000 characters)";
      const notes = document.createElement("textarea");
      notes.name = "notes";
      notes.required = true;
      notes.minLength = 24;
      notes.maxLength = 2000;
      notes.disabled = task.submitted === true;
      notesLabel.append(notesTitle, notes);
      const attestLabel = document.createElement("label");
      const attest = document.createElement("input");
      attest.type = "checkbox";
      attest.name = "human_attestation";
      attest.required = true;
      attest.disabled = task.submitted === true;
      attestLabel.append(attest, document.createTextNode(" I attest that candidate, provider, model, mapping, and other-reviewer identities were hidden"));
      const submit = document.createElement("button");
      submit.className = "button button--primary pressable";
      submit.type = "submit";
      submit.disabled = task.submitted === true;
      submit.textContent = task.submitted === true ? "Recorded" : "Submit immutable campaign review";
      form.append(header, context, systems, overall, dimensionGrid, defect, defectReasonLabel, notesLabel, attestLabel, submit);
      return form;
    }));
  }

  function renderBlindReviewTasks(assignment) {
    const list = getElement("blind-review-task-list");
    if (!list) return;
    if (assignment?.schema === "ProofLaunchJudgeCalibrationAssignmentV1") {
      renderCalibrationTasks(assignment);
      return;
    }
    if (assignment?.schema === "ProofLaunchCampaignPackVisualBlindReviewAssignmentV1") {
      renderCampaignPackTasks(assignment);
      return;
    }
    const tasks = Array.isArray(assignment?.tasks) ? assignment.tasks : [];
    list.replaceChildren(...tasks.map((task, index) => {
      const form = document.createElement("form");
      form.className = "blind-review-card";
      form.dataset.reviewTaskId = String(task.review_task_id ?? "");
      const header = document.createElement("div");
      header.className = "blind-review-card__header";
      const title = document.createElement("h4");
      title.textContent = `Pair ${index + 1} · ${String(task.pair?.channel ?? "channel")}`;
      const stateLabel = document.createElement("span");
      stateLabel.className = `status-badge ${task.submitted === true ? "status-badge--verified" : "status-badge--required"}`;
      stateLabel.textContent = task.submitted === true ? "Immutable review recorded" : "Review required";
      header.append(title, stateLabel);
      const portfolioCase = task.portfolio_case;
      const context = document.createElement("p");
      context.className = "blind-review-card__context";
      context.textContent = portfolioCase
        ? `Frozen scenario · ${portfolioCase.case_id} · ${portfolioCase.business_model} · ${portfolioCase.lifecycle} · budget ${portfolioCase.budget} · risk ${portfolioCase.industry_risk}`
        : "Focused campaign pair · candidate and territory identities remain sealed";
      const drafts = document.createElement("div");
      drafts.className = "blind-review-card__drafts";
      appendBlindDraft(drafts, "LEFT", task.pair?.left);
      appendBlindDraft(drafts, "RIGHT", task.pair?.right);
      const fieldset = document.createElement("fieldset");
      const legend = document.createElement("legend");
      legend.textContent = "Independent choice";
      fieldset.append(legend);
      ["left", "right", "abstain"].forEach((choice) => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "radio";
        input.name = "choice";
        input.value = choice;
        input.required = true;
        input.disabled = task.submitted === true;
        label.append(input, document.createTextNode(` ${choice}`));
        fieldset.append(label);
      });
      const reasonLabel = document.createElement("label");
      const reasonTitle = document.createElement("span");
      reasonTitle.textContent = "Why this draft should advance";
      const reason = document.createElement("textarea");
      reason.name = "reason";
      reason.required = true;
      reason.maxLength = 1200;
      reason.disabled = task.submitted === true;
      reasonLabel.append(reasonTitle, reason);
      const controls = document.createElement("div");
      controls.className = "blind-review-card__choices";
      const criticalLabel = document.createElement("label");
      const critical = document.createElement("input");
      critical.type = "checkbox";
      critical.name = "critical_failure";
      critical.disabled = task.submitted === true;
      criticalLabel.append(critical, document.createTextNode(" Critical safety/evidence failure"));
      const attestLabel = document.createElement("label");
      const attest = document.createElement("input");
      attest.type = "checkbox";
      attest.name = "human_attestation";
      attest.required = true;
      attest.disabled = task.submitted === true;
      attestLabel.append(attest, document.createTextNode(" I attest this was my independent blinded review"));
      controls.append(criticalLabel, attestLabel);
      const submit = document.createElement("button");
      submit.className = "button button--primary pressable";
      submit.type = "submit";
      submit.disabled = task.submitted === true;
      submit.textContent = task.submitted === true ? "Recorded" : "Submit immutable review";
      form.append(header, context, drafts, fieldset, reasonLabel, controls, submit);
      return form;
    }));
  }

  function disconnectTrajectory(message = "Event stream closed.") {
    state.eventPollGeneration += 1;
    if (state.eventPollTimer !== null) {
      window.clearTimeout(state.eventPollTimer);
      state.eventPollTimer = null;
    }
    setFeedback("trajectory-connection", message);
  }

  function appendTrajectoryEvent(messageEvent) {
    const list = getElement("trajectory-events");
    if (!list) return null;
    let payload;
    try {
      payload = JSON.parse(messageEvent.data);
    } catch {
      setFeedback("trajectory-connection", "Ignored a malformed event frame; the Agent stream remains open.", "error");
      return null;
    }
    const sequence = payload.sequence ?? messageEvent.lastEventId ?? state.eventKeys.size + 1;
    const eventType = payload.type ?? messageEvent.type ?? "message";
    const eventKey = `${sequence}:${eventType}`;
    if (state.eventKeys.has(eventKey)) return payload;
    state.eventKeys.add(eventKey);
    if (list.children.length === 1 && list.firstElementChild?.textContent?.startsWith("No current run")) {
      list.replaceChildren();
    }
    const item = document.createElement("li");
    const status = payload.status ?? payload.stage ?? payload.payload?.status ?? "observed";
    item.textContent = `${sequence}. ${eventType} · ${status}`;
    list.append(item);
    if (typeof status === "string" && /^[a-z_]{3,40}$/.test(status)) {
      setRunStatus(status);
    }
    if (eventType === "release_awaiting_approval") {
      setRunStatus("awaiting_release");
      loadRunPreview();
    }
    if (status === "awaiting_release" && !state.previewReady) loadRunPreview();
    if (eventType === "campaign_delivered") setRunStatus("delivered");
    if (eventType === "release_rejected") setRunStatus("rejected");
    return payload;
  }

  async function pollTrajectory(generation) {
    if (generation !== state.eventPollGeneration || !state.runId || !state.tenantToken) return;
    try {
      const eventsPath = `/v1/runs/${encodeURIComponent(state.runId)}/events`;
      const batch = await requestJson(eventsPath, {
        headers: { "Last-Event-ID": String(state.lastEventId) }
      });
      if (batch?.schema !== "ProofLaunchRunEventBatchV1" || !Array.isArray(batch.events)) {
        throw new Error("event batch contract mismatch");
      }
      batch.events.forEach((payload) => {
        appendTrajectoryEvent({
          data: JSON.stringify(payload),
          lastEventId: String(payload.event_id ?? ""),
          type: payload.type ?? "message"
        });
        if (Number.isInteger(payload.event_id) && payload.event_id > state.lastEventId) {
          state.lastEventId = payload.event_id;
        }
      });
      if (typeof batch.current_status === "string") setRunStatus(batch.current_status);
      setFeedback("trajectory-connection", "Authenticated Agent event polling connected.", "success");
      if (batch.terminal === true || terminalRunStatuses.has(state.runStatus)) {
        disconnectTrajectory(`Run reached terminal state: ${state.runStatus}.`);
        return;
      }
      if (generation === state.eventPollGeneration) {
        state.eventPollTimer = window.setTimeout(() => pollTrajectory(generation), 800);
      }
    } catch (error) {
      if (generation !== state.eventPollGeneration) return;
      setFeedback("trajectory-connection", `Authenticated event polling stopped: ${String(error.message ?? error)}`, "error");
    }
  }

  function refreshTrajectory() {
    const list = getElement("trajectory-events");
    if (!list) return;
    if (!state.runId) {
      const item = document.createElement("li");
      item.textContent = "No current run. Create one in World State.";
      list.replaceChildren(item);
      disconnectTrajectory("Event stream is idle.");
      return;
    }
    if (terminalRunStatuses.has(state.runStatus)) {
      disconnectTrajectory(`Run is terminal: ${state.runStatus}.`);
      return;
    }
    if (!state.tenantToken) {
      disconnectTrajectory("Tenant bearer token required; activate it in Tenants & access.");
      return;
    }
    disconnectTrajectory("Connecting authenticated Agent event polling…");
    const generation = state.eventPollGeneration;
    pollTrajectory(generation);
  }

  async function loadModelCards() {
    const container = getElement("model-card-list");
    if (!container) return;
    try {
      const [models, evals] = await Promise.all([
        requestJson("/v1/model-cards"),
        requestJson("/v1/evals/leaderboard")
      ]);
      const records = [...models.model_cards.map((card) => ({ kind: "Model card", title: card.model_id, detail: `${card.revision} · ${card.promotion_status}` })), ...evals.leaderboard.map((row) => ({ kind: "Eval", title: row.model_id, detail: `${row.evidence_class} · blinded=${row.blinded}` }))];
      container.replaceChildren(...records.map((record) => {
        const article = document.createElement("article");
        const label = document.createElement("small");
        const title = document.createElement("strong");
        const detail = document.createElement("span");
        label.textContent = record.kind;
        title.textContent = record.title;
        detail.textContent = record.detail;
        article.append(label, title, detail);
        return article;
      }));
    } catch (error) {
      container.textContent = `Registry unavailable: ${String(error.message ?? error)}`;
    }
  }

  async function loadPlatformMarketExpansion() {
    const facts = getElement("platform-market-expansion-facts");
    const container = getElement("platform-market-expansion-list");
    if (!facts || !container) return;
    try {
      const expansion = await requestJson("/v1/platform-market-expansion");
      const valid =
        expansion.schema === "ProofLaunchPlatformMarketExpansionPublicV1" &&
        expansion.target_lane_count === 126 &&
        expansion.discovery_is_not_coverage === true &&
        expansion.automatic_external_publish_count === 0 &&
        expansion.automatic_learning_memory_write_count === 0 &&
        Array.isArray(expansion.platforms) &&
        expansion.platforms.length === 9;
      if (!valid) throw new Error("platform-market expansion contract failed closed");
      const fact = (label, value, detail) => {
        const wrapper = document.createElement("div");
        const term = document.createElement("dt");
        const description = document.createElement("dd");
        const strong = document.createElement("strong");
        const span = document.createElement("span");
        term.textContent = label;
        strong.textContent = String(value);
        span.textContent = detail;
        description.append(strong, span);
        wrapper.append(term, description);
        return wrapper;
      };
      facts.replaceChildren(
        fact("Priority lanes", expansion.target_lane_count, "9 platforms · B2B/B2C · 7 markets"),
        fact("Sources discovered", expansion.discovered_candidate_slot_count, "Identity-bound; not coverage"),
        fact("Recent qualified", expansion.verified_recent_lane_count, `${expansion.remaining_verified_recent_lane_count} lanes still open`),
        fact("Human handoff", expansion.handoff_candidate_slot_count, "Access boundary preserved")
      );
      container.replaceChildren(...expansion.platforms.map((platform) => {
        const article = document.createElement("article");
        const mark = document.createElement("span");
        const body = document.createElement("div");
        const title = document.createElement("strong");
        const detail = document.createElement("small");
        const status = document.createElement("em");
        mark.className = "connector-mark";
        mark.textContent = String(platform.platform).slice(0, 2).toUpperCase();
        title.textContent = platform.platform;
        detail.textContent = `${platform.discovered_candidate_slot_count} discovered · ${platform.executed_candidate_slot_count} executed · ${platform.handoff_candidate_slot_count} handoff`;
        status.textContent = platform.verified_recent_lane_count > 0
          ? `${platform.verified_recent_lane_count}/${platform.target_lane_count} verified`
          : "0 recent-qualified";
        body.append(title, detail);
        article.append(mark, body, status);
        return article;
      }));
    } catch (error) {
      container.textContent = `Platform expansion unavailable: ${String(error.message ?? error)}`;
    }
  }

  async function loadSocialConnectors() {
    const container = getElement("social-connector-list");
    const landscapeSummary = getElement("social-oss-landscape-summary");
    if (!container) return;
    try {
      const [registry, landscape] = await Promise.all([
        requestJson("/v1/social-connectors"),
        requestJson("/v1/social-oss-landscape")
      ]);
      if (
        landscape.schema !== "ProofLaunchSocialOSSAdapterLandscapePublicV1" ||
        landscape.repository_discovery_is_not_runtime_admission !== true ||
        landscape.authentication_or_captcha_bypass_enabled !== false ||
        landscape.external_publish_enabled !== false
      ) throw new Error("OSS landscape contract failed closed");
      if (landscapeSummary) {
        const access = landscape.access_mode_counts ?? {};
        landscapeSummary.textContent = `${landscape.candidate_count} OSS candidates audited · ${landscape.resolved_count} revisions resolved · ${landscape.production_admitted_count} runtime-proven · ${access.ordinary_public_pages_or_protocol ?? 0} public/protocol candidates · ${access.operator_credentials_required ?? 0} credential-bound · ${access.operator_supplied_capture ?? 0} operator-capture. Search breadth is not runtime proof.`;
      }
      const admitted = new Set(registry.live_execution_admitted ?? []);
      container.replaceChildren(...registry.connectors.map((connector) => {
        const article = document.createElement("article");
        const mark = document.createElement("span");
        const body = document.createElement("div");
        const title = document.createElement("strong");
        const detail = document.createElement("small");
        const status = document.createElement("em");
        mark.className = "connector-mark";
        mark.textContent = connector.connector_id.slice(0, 2).toUpperCase();
        title.textContent = connector.connector_id;
        detail.textContent = `${connector.modalities.join(" · ")} · ${connector.revision.slice(0, 8)}`;
        status.textContent = admitted.has(connector.connector_id) ? "Executable" : "Pinned candidate";
        body.append(title, detail);
        article.append(mark, body, status);
        return article;
      }));
    } catch (error) {
      container.textContent = `Connector registry unavailable: ${String(error.message ?? error)}`;
      if (landscapeSummary) landscapeSummary.textContent = "OSS landscape unavailable; no adapter admission inferred.";
    }
  }

  function setEffectFormEnabled(enabled) {
    const button = getElement("effect-submit");
    if (button instanceof HTMLButtonElement) button.disabled = !enabled;
    const kitButton = getElement("production-observation-kit-download");
    if (kitButton instanceof HTMLButtonElement) kitButton.disabled = !enabled;
    const importInput = getElement("production-observation-json-import");
    if (importInput instanceof HTMLInputElement) importInput.disabled = !enabled;
    const publicationInput = getElement("manual-publication-receipt-json-import");
    if (publicationInput instanceof HTMLInputElement) publicationInput.disabled = !enabled;
  }

  function setEconomicsImportEnabled(enabled) {
    const input = getElement("production-economics-json-import");
    if (input instanceof HTMLInputElement) input.disabled = !enabled;
  }

  function setEffectFormValue(form, name, value) {
    const control = form.elements.namedItem(name);
    if (control instanceof HTMLInputElement || control instanceof HTMLSelectElement) {
      if (control.type === "checkbox") control.checked = value === true;
      else control.value = String(value ?? "");
    }
  }

  function importProductionObservationPayload(payload) {
    const form = getElement("effect-observation-form");
    if (!(form instanceof HTMLFormElement) || !state.effectContract) {
      throw new Error("a delivered experiment contract is required");
    }
    if (
      payload?.experiment_id !== state.effectContract.experiment_id ||
      payload?.strategy_plan_sha256 !== state.effectContract.strategy_plan_sha256
    ) {
      throw new Error("observation JSON does not match the delivered experiment and strategy");
    }
    const localTime = (value) => {
      const parsed = new Date(String(value ?? ""));
      if (Number.isNaN(parsed.valueOf())) throw new Error("observation JSON contains an invalid window");
      return parsed.toISOString().slice(0, 19);
    };
    setEffectFormValue(form, "source_kind", payload.source_kind);
    setEffectFormValue(form, "source_reference_sha256", payload.source_reference_sha256);
    setEffectFormValue(form, "channel", payload.channel);
    setEffectFormValue(form, "assignment_method", payload.assignment_method);
    setEffectFormValue(form, "window_start", localTime(payload.window_start));
    setEffectFormValue(form, "window_end", localTime(payload.window_end));
    const fields = {
      reach: "eligible_reach",
      qualified: "qualified_actions",
      engagement: "evidence_engagements",
      complaints: "complaints",
      conversions: "conversions",
      revenue: "revenue_usd",
      spend: "spend_usd"
    };
    for (const [suffix, key] of Object.entries(fields)) {
      setEffectFormValue(form, `observed_${suffix}`, payload.metrics?.[key]);
      setEffectFormValue(form, `baseline_${suffix}`, payload.baseline_metrics?.[key]);
    }
    setEffectFormValue(form, "deduplicated", payload.deduplicated);
    setEffectFormValue(form, "bot_filter_applied", payload.bot_filter_applied);
    state.outcomeAttempt = null;
  }

  function ensureProductionObservationKitControls() {
    if (getElement("production-observation-kit-download")) return;
    const form = getElement("effect-observation-form");
    const actionStack = form?.querySelector(".action-stack");
    if (!(form instanceof HTMLFormElement) || !actionStack) return;
    const downloadButton = document.createElement("button");
    downloadButton.id = "production-observation-kit-download";
    downloadButton.type = "button";
    downloadButton.className = "button button--secondary";
    downloadButton.textContent = "Download production observation kit";
    downloadButton.disabled = true;
    downloadButton.addEventListener("click", async () => {
      const tokenInput = getElement("effect-approval-token");
      if (!(tokenInput instanceof HTMLInputElement) || !tokenInput.value) {
        setText("effect-output", "Field kit blocked: enter the local operator approval token. It is used for this request only and is never written into the ZIP.");
        return;
      }
      if (!state.runId || state.runStatus !== "delivered") {
        setText("effect-output", "Field kit blocked: a delivered run is required.");
        return;
      }
      downloadButton.disabled = true;
      try {
        const response = await window.fetch(`/v1/runs/${encodeURIComponent(state.runId)}/production-observation-kit`, {
          headers: tenantHeaders({ "X-ProofLaunch-Approval-Token": tokenInput.value }),
          cache: "no-store"
        });
        if (!response.ok) {
          const detail = await response.json().catch(() => ({}));
          throw new Error(detail.error ?? `HTTP ${response.status}`);
        }
        const blob = await response.blob();
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = `${state.runId}-production-observation-kit.zip`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        setText("effect-output", "Production observation field kit downloaded. It is empty of results and credentials; collect real aggregate evidence before importing JSON.");
      } catch (error) {
        setText("effect-output", `Field kit blocked: ${String(error.message ?? error)}`);
      } finally {
        downloadButton.disabled = false;
      }
    });
    const importLabel = document.createElement("label");
    importLabel.className = "button button--quiet";
    importLabel.textContent = "Load observation JSON";
    const importInput = document.createElement("input");
    importInput.id = "production-observation-json-import";
    importInput.type = "file";
    importInput.accept = "application/json,.json";
    importInput.hidden = true;
    importInput.disabled = true;
    importInput.addEventListener("change", async () => {
      const file = importInput.files?.[0];
      if (!file) return;
      try {
        const payload = JSON.parse(await file.text());
        importProductionObservationPayload(payload);
        setText("effect-output", "Observation JSON loaded into the bounded aggregate form. Human inspection and authenticated submission are still required.");
      } catch (error) {
        setText("effect-output", `Observation import rejected: ${String(error.message ?? error)}`);
      } finally {
        importInput.value = "";
      }
    });
    importLabel.append(importInput);
    const publicationLabel = document.createElement("label");
    publicationLabel.className = "button button--quiet";
    publicationLabel.textContent = "Record publication receipt";
    const publicationInput = document.createElement("input");
    publicationInput.id = "manual-publication-receipt-json-import";
    publicationInput.type = "file";
    publicationInput.accept = "application/json,.json";
    publicationInput.hidden = true;
    publicationInput.disabled = true;
    publicationInput.addEventListener("change", async () => {
      const file = publicationInput.files?.[0];
      const tokenInput = getElement("effect-approval-token");
      if (!file) return;
      try {
        if (!state.runId || state.runStatus !== "delivered") {
          throw new Error("a delivered, human-approved run is required");
        }
        if (!(tokenInput instanceof HTMLInputElement) || !tokenInput.value) {
          throw new Error("enter the local operator approval token before recording publication");
        }
        const payload = JSON.parse(await file.text());
        const receiptId = String(payload?.receipt_id ?? "");
        if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(receiptId)) {
          throw new Error("receipt_id is invalid");
        }
        publicationInput.disabled = true;
        const result = await requestJson(
          `/v1/runs/${encodeURIComponent(state.runId)}/publication-receipts`,
          {
            method: "POST",
            headers: {
              "X-ProofLaunch-Approval-Token": tokenInput.value,
              "Idempotency-Key": receiptId
            },
            body: JSON.stringify(payload)
          }
        );
        tokenInput.value = "";
        renderJson("effect-output", result);
      } catch (error) {
        setText("effect-output", `Publication receipt rejected: ${String(error.message ?? error)}`);
      } finally {
        publicationInput.value = "";
        publicationInput.disabled = state.runStatus !== "delivered";
      }
    });
    publicationLabel.append(publicationInput);
    const economicsLabel = document.createElement("label");
    economicsLabel.className = "button button--quiet";
    economicsLabel.textContent = "Submit economics JSON";
    const economicsInput = document.createElement("input");
    economicsInput.id = "production-economics-json-import";
    economicsInput.type = "file";
    economicsInput.accept = "application/json,.json";
    economicsInput.hidden = true;
    economicsInput.disabled = true;
    economicsInput.addEventListener("change", async () => {
      const file = economicsInput.files?.[0];
      const observation = state.latestEffectObservation;
      const tokenInput = getElement("effect-approval-token");
      if (!file) return;
      try {
        if (!observation || !state.runId) {
          throw new Error("a recorded aggregate observation is required");
        }
        if (!(tokenInput instanceof HTMLInputElement) || !tokenInput.value) {
          throw new Error("enter the local operator approval token before submitting economics");
        }
        const payload = JSON.parse(await file.text());
        if (
          payload?.effect_observation_id !== observation.observation_id ||
          payload?.effect_observation_sha256 !== observation.observation_sha256
        ) {
          throw new Error("economics JSON does not match the latest observation ID and SHA-256");
        }
        const economicsId = String(payload?.economics_id ?? "");
        if (!/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(economicsId)) {
          throw new Error("economics_id is invalid");
        }
        economicsInput.disabled = true;
        const result = await requestJson(
          `/v1/runs/${encodeURIComponent(state.runId)}/outcomes/${encodeURIComponent(observation.observation_id)}/economics`,
          {
            method: "POST",
            headers: {
              "X-ProofLaunch-Approval-Token": tokenInput.value,
              "Idempotency-Key": economicsId
            },
            body: JSON.stringify(payload)
          }
        );
        tokenInput.value = "";
        renderJson("effect-output", result);
      } catch (error) {
        setText("effect-output", `Economics submission rejected: ${String(error.message ?? error)}`);
      } finally {
        economicsInput.value = "";
        economicsInput.disabled = !state.latestEffectObservation;
      }
    });
    economicsLabel.append(economicsInput);
    actionStack.prepend(importLabel);
    actionStack.prepend(publicationLabel);
    actionStack.prepend(economicsLabel);
    actionStack.prepend(downloadButton);
  }

  function setLearningPromotionEnabled(enabled) {
    const button = getElement("learning-promote-submit");
    if (button instanceof HTMLButtonElement) button.disabled = !enabled;
  }

  function renderLearningMemories(collection) {
    state.learningMemories = collection;
    const memories = Array.isArray(collection?.memories) ? collection.memories : [];
    const latest = state.latestEffectObservation;
    const promoted = latest
      ? memories.find((memory) => memory?.observation_id === latest.observation_id)
      : null;
    const eligible = Boolean(
      latest?.comparison_ready === true &&
      latest?.zero_budget_contract_breach === false
    );
    const status = getElement("learning-memory-status");
    if (promoted) {
      if (status) {
        status.textContent = "Promoted · next run will snapshot";
        status.className = "status-badge status-badge--passed";
      }
      setLearningPromotionEnabled(false);
      renderJson("learning-memory-output", promoted);
      return;
    }
    if (eligible) {
      if (status) {
        status.textContent = "Eligible · human decision required";
        status.className = "status-badge status-badge--required";
      }
      setLearningPromotionEnabled(true);
      setText("learning-memory-output", `Observation ${latest.observation_id} is sufficient but not promoted.`);
      return;
    }
    if (status) {
      status.textContent = "No eligible observation";
      status.className = "status-badge status-badge--blocked";
    }
    setLearningPromotionEnabled(false);
    setText("learning-memory-output", latest
      ? "Latest observation failed the comparison or budget gate; project-memory promotion is blocked."
      : "No source-bound observation is available for promotion.");
  }

  function renderEffectObservationCollection(collection) {
    const observations = Array.isArray(collection?.observations) ? collection.observations : [];
    const latest = observations.at(-1);
    state.latestEffectObservation = latest ?? null;
    setEconomicsImportEnabled(Boolean(latest));
    setText("experiment-contract-id", typeof collection?.experiment_id === "string" ? collection.experiment_id : "No delivered run");
    setText("experiment-observed-outcome", observations.length > 0 ? `${observations.length} aggregate observation${observations.length === 1 ? "" : "s"}` : "Not observed");
    const contractStatus = getElement("effect-contract-status");
    if (contractStatus) {
      contractStatus.textContent = "Experiment contract loaded";
      contractStatus.className = "status-badge status-badge--passed";
    }
    if (!latest) {
      setText("learning-decision", "No evidence-backed learning decision yet");
      setText("learning-decision-detail", "The approved experiment is ready for one source-bound aggregate observation.");
      setText("effect-output", `Experiment ${collection.experiment_id} loaded. No observation has been recorded.`);
      return;
    }
    const decision = String(latest.next_cycle_decision ?? "human_review_required");
    const reason = String(latest.decision_reason ?? "No bounded decision reason was returned.");
    setText("learning-decision", decision.replaceAll("_", " "));
    setText("learning-decision-detail", `${reason} Automatic strategy mutation: disabled.`);
    renderJson("effect-output", latest);
  }

  async function loadEffectObservations() {
    ensureProductionObservationKitControls();
    state.effectContract = null;
    state.latestEffectObservation = null;
    state.learningMemories = null;
    setEffectFormEnabled(false);
    setEconomicsImportEnabled(false);
    setLearningPromotionEnabled(false);
    if (!state.runId || state.runStatus !== "delivered") {
      setText("experiment-contract-id", "Delivered run required");
      setText("experiment-observed-outcome", "Not observed");
      const status = getElement("effect-contract-status");
      if (status) {
        status.textContent = "Delivered run required";
        status.className = "status-badge status-badge--blocked";
      }
      setText("effect-output", "Create, review, approve, and deliver a run before importing results.");
      renderLearningMemories({ memories: [] });
      return;
    }
    try {
      const collection = await requestJson(`/v1/runs/${encodeURIComponent(state.runId)}/outcomes`);
      if (
        typeof collection.experiment_id !== "string" ||
        typeof collection.strategy_plan_sha256 !== "string" ||
        !/^[0-9a-f]{64}$/.test(collection.strategy_plan_sha256)
      ) {
        throw new Error("server returned an invalid experiment identity");
      }
      state.effectContract = collection;
      renderEffectObservationCollection(collection);
      const memories = await requestJson(`/v1/runs/${encodeURIComponent(state.runId)}/learning-memories`);
      renderLearningMemories(memories);
      setEffectFormEnabled(true);
    } catch (error) {
      setText("effect-output", `Effect contract unavailable: ${String(error.message ?? error)}`);
    }
  }

  function refreshControlSurface(path) {
    if (path === "/control/gtm-cockpit") loadGTMCockpit();
    if (path === "/control/trajectory") refreshTrajectory();
    if (path === "/control/world-state" && state.runId) {
      refreshRunSnapshot().catch((error) => setText("world-state-output", `Run refresh failed closed: ${String(error.message ?? error)}`));
    }
    if (path === "/control/human-gate" && state.runId) loadRunPreview();
    if (path === "/control/ledger") updateBundleControl();
    if (path === "/control/distillation") loadModelCards();
    if (path === "/admin/connectors") {
      loadPlatformMarketExpansion();
      loadSocialConnectors();
    }
    if (path === "/front/experiments" || path === "/front/learning") loadEffectObservations();
    if (path === "/control/performance") probeControlPlane();
    if (path === "/control/videos") probeProductReadiness();
    if (path === "/control/training") {
      probeBlindReviewStatus();
      probeProductReadiness().then(() => probeLaunchProofControl());
    }
  }

  function updateCreateControls() {
    const badge = getElement("create-badge");
    const handoff = getElement("create-run-handoff");
    setText("create-runtime-state", state.apiConnected ? "Connected · same-origin local API" : "Disconnected · start the production API first");
    if (state.runId && state.runStatus) {
      if (badge) {
        badge.textContent = state.runStatus.replaceAll("_", " ");
        badge.className = `status-badge ${statusMarkerClass(state.runStatus)}`;
      }
      if (handoff) handoff.textContent = "Open current Agent run";
      setText("create-state-copy", `Run ${state.runId} is ${state.runStatus.replaceAll("_", " ")}. Resume from its persisted Campaign World State.`);
      setFeedback("create-feedback", "The current run is persisted. Reopening it does not replay model calls or external actions.", "success");
      return;
    }
    if (badge) {
      badge.textContent = state.productArtifact ? "Ready to configure" : "Evidence required";
      badge.className = `status-badge ${state.productArtifact ? "status-badge--required" : "status-badge--blocked"}`;
    }
    if (handoff) handoff.textContent = state.productArtifact ? "Configure and start Agent" : "Open Campaign World State";
    setText(
      "create-state-copy",
      state.productArtifact
        ? "The product image is content-bound. Review the full strategy diagnosis and start the persisted Agent run."
        : "Stage one rights-cleared product PNG, save the brief, then configure the persisted Agent run."
    );
    setFeedback(
      "create-feedback",
      state.apiConnected
        ? state.productArtifact
          ? "Local API connected and evidence staged; the Agent launch form is ready for human review."
          : "Local API connected; evidence is still required before launch."
        : "Local API disconnected; product inputs can be reviewed but execution remains unavailable.",
      state.apiConnected && state.productArtifact ? "success" : "info"
    );
  }

  function updateRepairControls() {
    const remaining = Math.max(0, 2 - state.repairRounds);
    setText("repair-allowance", `${remaining} ${remaining === 1 ? "review" : "reviews"} available`);
    const reviewButton = document.querySelector("[data-action='review-repair']");
    if (reviewButton) {
      reviewButton.disabled = remaining === 0;
    }

    if (state.verifyState === "failed") {
      setText("verify-badge", "Failed preview");
      setFeedback(
        "verify-feedback",
        "Failed state shown: source custody cannot pass because required owner-supplied evidence is absent.",
        "error"
      );
    } else if (state.verifyState === "repaired") {
      setText("verify-badge", "Review recorded");
      setFeedback(
        "verify-feedback",
        `Repair review recorded locally. ${remaining} ${remaining === 1 ? "review remains" : "reviews remain"}; no asset was changed.`,
        "success"
      );
    } else if (state.verifyState === "recovered") {
      setText("verify-badge", "Safe state");
      setFeedback("verify-feedback", "Prior safe state restored. Audit remains blocked before execution.", "success");
    } else {
      setText("verify-badge", remaining === 0 ? "Repair limit reached" : "Audit blocked");
      setFeedback(
        "verify-feedback",
        remaining === 0
          ? "Repair review limit reached. Export remains blocked; no asset was changed."
          : "Audit remains blocked before execution.",
        remaining === 0 ? "error" : "info"
      );
    }
  }

  function openDialog(id, invokingControl) {
    const dialog = getElement(id);
    if (!dialog || typeof dialog.showModal !== "function") {
      return;
    }
    state.pendingControl = invokingControl;
    dialog.showModal();
  }

  function handleAction(action, control) {
    if (action === "inspect-requirements") {
      state.selectedInspector = "required-inputs";
      updateInspector({
        heading: "Required production inputs",
        summary: "Supply one owned or licensed PNG. The browser verifies its PNG signature, computes SHA-256, and stores the original bytes at the matching same-origin artifact address.",
        source: state.productArtifact ? "SHA-256 bound" : "Missing",
        approval: "Unavailable"
      });
      setFeedback("evidence-feedback", "Required input: one rights-cleared PNG plus source specification text in Campaign World State.");
    }

    if (action === "review-claim-approval") {
      openDialog("claim-dialog", control);
    }

    if (action === "confirm-claim-review") {
      setFeedback(
        "evidence-feedback",
        "Claim review closed: product-image staging never approves factual claims; use the content-bound release preview.",
        "success"
      );
    }

    if (action === "save-review-note") {
      setFeedback(
        "evidence-feedback",
        "Local review note saved. No claim or external action was approved.",
        "success"
      );
    }

    if (action === "show-failure") {
      state.verifyState = "failed";
      updateRepairControls();
    }

    if (action === "review-repair" && state.repairRounds < 2) {
      openDialog("repair-dialog", control);
    }

    if (action === "confirm-repair-review" && state.repairRounds < 2) {
      state.repairRounds += 1;
      state.verifyState = state.repairRounds >= 2 ? "blocked" : "repaired";
      updateRepairControls();
    }

    if (action === "recover-safe-state") {
      state.verifyState = "recovered";
      updateRepairControls();
    }

    if (action === "review-export-blockers") {
      updateInspectorForRoute("/workspace/export");
      setFeedback("export-feedback", "Export review complete: release remains blocked by four unresolved gates.");
    }

    if (action === "inspect-provenance") {
      updateInspector({
        heading: "Provenance boundary",
        summary: "C2PA creation and verification are not demonstrated. This status remains separate from factual and visual audit status.",
        source: "Missing",
        approval: "Blocked",
        runtime: "Not executed",
        provenance: "Not demonstrated"
      });
      setFeedback("export-feedback", "Provenance boundary opened: C2PA evidence is not demonstrated.");
    }

    if (action === "refresh-trajectory") {
      refreshTrajectory();
    }

    if (action === "refresh-gtm-cockpit") {
      loadGTMCockpit();
    }

    if (action === "load-synthetic-lifecycle-demo") {
      loadSyntheticLifecycleDemo(control);
    }

    if (action === "load-model-cards") {
      loadModelCards();
    }

    if (action === "load-social-connectors") {
      loadSocialConnectors();
    }

    if (action === "load-platform-market-expansion") {
      loadPlatformMarketExpansion();
    }

    if (action === "refresh-performance") {
      probeControlPlane();
    }

    if (action === "download-bundle") {
      if (!state.runId || state.runStatus !== "delivered") {
        setText("ledger-output", "Bundle remains hidden until the current run reaches delivered.");
      } else {
        window.fetch(`/v1/runs/${encodeURIComponent(state.runId)}/bundle`, { headers: tenantHeaders() }).then(async (response) => {
          if (!response.ok) {
            const payload = await response.json().catch(() => ({ error: `HTTP ${response.status}` }));
            throw new Error(payload.error);
          }
          const blob = await response.blob();
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url;
          link.download = `${state.runId}.zip`;
          link.click();
          URL.revokeObjectURL(url);
          setText("ledger-output", `Downloaded ${state.runId}.zip. External release was not executed.`);
        }).catch((error) => setText("ledger-output", `Bundle blocked: ${String(error.message ?? error)}`));
      }
    }

    saveRecoveryState();
  }

  routeLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const path = link.getAttribute("href");
      if (!path || !routeMetadata.has(path)) {
        return;
      }
      event.preventDefault();
      navigate(path);
    });
  });

  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const control = event.target.closest("[data-action]");
    if (!(control instanceof HTMLElement)) {
      return;
    }
    const action = control.dataset.action;
    if (action) {
      handleAction(action, control);
    }
  });

  let evidenceStageSequence = 0;

  async function handleEvidenceSelection() {
    const input = getElement("evidence-files");
    const rights = getElement("evidence-rights");
    const rightsBasis = getElement("evidence-rights-basis");
    if (
      !(input instanceof HTMLInputElement) ||
      !(rights instanceof HTMLInputElement) ||
      !(rightsBasis instanceof HTMLSelectElement)
    ) return;
    const sequence = ++evidenceStageSequence;
    const file = input.files?.[0] ?? null;
    if (!file) {
      state.productFile = null;
      state.productArtifact = null;
      renderProductArtifactStatus();
      updateArtifactBinding();
      setFeedback("evidence-feedback", "Evidence gate is waiting for a rights-cleared product PNG.");
      updateCreateControls();
      saveRecoveryState();
      return;
    }
    if (!rights.checked || !rightsBasis.value) {
      state.productFile = null;
      state.productArtifact = null;
      renderProductArtifactStatus(`${file.name} selected; confirm rights and select a rights basis before hashing and upload.`);
      updateArtifactBinding();
      setFeedback("evidence-feedback", "Rights confirmation and a non-empty rights basis are required before this local upload.", "error");
      updateCreateControls();
      saveRecoveryState();
      return;
    }
    state.productFile = null;
    state.productArtifact = null;
    renderProductArtifactStatus(`Verifying and hashing ${file.name}…`);
    updateArtifactBinding();
    setFeedback("evidence-feedback", "Computing SHA-256 locally and checking the same-origin artifact store…");
    try {
      const artifact = await stageProductImage(file);
      if (sequence !== evidenceStageSequence) return;
      state.productFile = file;
      state.productArtifact = artifact;
      renderProductArtifactStatus();
      updateArtifactBinding();
      setFeedback(
        "evidence-feedback",
        artifact.deduplicated
          ? "Product PNG verified; the matching SHA-256 artifact already exists locally."
          : "Product PNG verified, hashed, and uploaded to the local content-addressed store.",
        "success"
      );
      updateCreateControls();
      saveRecoveryState();
    } catch (error) {
      if (sequence !== evidenceStageSequence) return;
      state.productFile = null;
      state.productArtifact = null;
      renderProductArtifactStatus(`Staging failed: ${String(error.message ?? error)}`);
      updateArtifactBinding();
      setFeedback("evidence-feedback", `Product image rejected: ${String(error.message ?? error)}`, "error");
      updateCreateControls();
      saveRecoveryState();
    }
  }

  getElement("evidence-files")?.addEventListener("change", handleEvidenceSelection);
  getElement("evidence-rights")?.addEventListener("change", handleEvidenceSelection);
  getElement("evidence-rights-basis")?.addEventListener("change", handleEvidenceSelection);

  getElement("brief-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const selectedMarket = formData.get("market");
    const selectedObjective = formData.get("objective");
    state.briefMarket = safeMarkets.has(selectedMarket) ? selectedMarket : "United States";
    state.briefObjective = safeObjectives.has(selectedObjective) ? selectedObjective : "Product launch review";
    const launchMarket = getElement("launch-market");
    const launchGoal = getElement("launch-goal");
    if (launchMarket instanceof HTMLInputElement) launchMarket.value = state.briefMarket;
    if (launchGoal instanceof HTMLInputElement) {
      launchGoal.value = {
        "Product launch review": "Create a source-bound launch system for human review",
        "Claim-safe campaign draft": "Create a claim-safe cross-channel campaign system for human review",
        "Channel adaptation review": "Adapt one evidence spine into a governed channel portfolio for human review"
      }[state.briefObjective];
    }
    setFeedback(
      "brief-feedback",
      "Brief saved and carried into Campaign World State. No claim was approved and no campaign output was generated.",
      "success"
    );
    saveRecoveryState();
  });

  getElement("launch-run-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.productArtifact) {
      setText("world-state-output", "Run creation blocked: stage a rights-cleared product PNG in Evidence first.");
      return;
    }
    const rightsConfirmation = getElement("evidence-rights");
    const rightsBasis = getElement("evidence-rights-basis");
    if (
      !(rightsConfirmation instanceof HTMLInputElement) ||
      !rightsConfirmation.checked ||
      !(rightsBasis instanceof HTMLSelectElement) ||
      !rightsBasis.value
    ) {
      setText("world-state-output", "Run creation blocked: confirm rights for both product image and specification, then select a rights basis in Evidence.");
      return;
    }
    const formData = new FormData(event.currentTarget);
    const claimAssurance = String(formData.get("claim_assurance") ?? "").trim();
    const claimApprovedBy = String(formData.get("claim_approved_by") ?? "").trim();
    const specialistApprovedBy = String(formData.get("specialist_approved_by") ?? "").trim();
    const industryRisk = String(formData.get("industry_risk") ?? "").trim();
    if (claimAssurance === "verified" && !claimApprovedBy) {
      setText("world-state-output", "Run creation blocked: verified claim assurance requires a named accountable claim approver.");
      getElement("launch-claim-approved-by")?.focus();
      return;
    }
    if (industryRisk === "high_regulation" && !specialistApprovedBy) {
      setText("world-state-output", "Run creation blocked: high-regulation work requires a named qualified specialist approver.");
      getElement("launch-specialist-approved-by")?.focus();
      return;
    }
    const signalFile = formData.get("creative_signal_snapshot");
    const signalReceiptFile = formData.get("creative_signal_collection_receipt");
    const hasSignalFile = signalFile instanceof File && signalFile.size > 0;
    const hasSignalReceiptFile = signalReceiptFile instanceof File && signalReceiptFile.size > 0;
    if (hasSignalFile !== hasSignalReceiptFile) {
      setText(
        "world-state-output",
        "Run creation blocked: a creative signal snapshot and its matching collection receipt must be supplied together."
      );
      return;
    }
    if (hasSignalFile && hasSignalReceiptFile) {
      try {
        state.signalArtifact = await stageCreativeSignalSnapshot(signalFile);
        state.signalReceiptArtifact = await stageCreativeSignalCollectionReceipt(
          signalReceiptFile,
          state.signalArtifact.contentSha256
        );
        updateArtifactBinding();
        saveRecoveryState();
      } catch (error) {
        state.signalArtifact = null;
        state.signalReceiptArtifact = null;
        updateArtifactBinding();
        setText("world-state-output", `Run creation blocked by signal safety gate: ${String(error.message ?? error)}`);
        return;
      }
    }
    if (Boolean(state.signalArtifact) !== Boolean(state.signalReceiptArtifact)) {
      setText(
        "world-state-output",
        "Run creation blocked: staged creative signal provenance is incomplete. Re-select both collector files."
      );
      return;
    }
    const requestId = newIdempotencyKey("browser-run");
    const payload = {
      request_id: requestId,
      campaign_id: `campaign-${requestId.slice("browser-run-".length)}`,
      campaign: {
        product_name: String(formData.get("product_name") ?? "").trim(),
        specification_text: String(formData.get("specification_text") ?? "").trim(),
        market: String(formData.get("market") ?? "").trim(),
        platform: String(formData.get("platform") ?? "").trim(),
        goal: String(formData.get("goal") ?? "").trim(),
        target_emotion: String(formData.get("target_emotion") ?? "").trim()
      },
      strategy: {
        business_model: String(formData.get("business_model") ?? "").trim(),
        lifecycle: String(formData.get("lifecycle") ?? "").trim(),
        budget: String(formData.get("budget") ?? "").trim(),
        industry: String(formData.get("industry") ?? "").trim(),
        product_category: String(formData.get("product_category") ?? "").trim(),
        product_surface: String(formData.get("product_surface") ?? "").trim(),
        audience_role: String(formData.get("audience_role") ?? "").trim(),
        industry_risk: String(formData.get("industry_risk") ?? "").trim(),
        company_scale: String(formData.get("company_scale") ?? "").trim(),
        brand_reach: String(formData.get("brand_reach") ?? "").trim(),
        owned_audience_strength: String(formData.get("owned_audience_strength") ?? "").trim(),
        community_access: String(formData.get("community_access") ?? "").trim(),
        partner_access: String(formData.get("partner_access") ?? "").trim(),
        content_capacity: String(formData.get("content_capacity") ?? "").trim(),
        sales_motion: String(formData.get("sales_motion") ?? "").trim(),
        audience_name: String(formData.get("audience_name") ?? "").trim(),
        audience_problem: String(formData.get("core_problem") ?? "").trim(),
        audience_outcome: String(formData.get("desired_outcome") ?? "").trim(),
        buying_context: String(formData.get("buying_context") ?? "").trim(),
        brand_purpose: String(formData.get("brand_purpose") ?? "").trim(),
        customer_promise: String(formData.get("brand_promise") ?? "").trim(),
        brand_voice: String(formData.get("brand_voice") ?? "").trim(),
        offer: String(formData.get("offer") ?? "").trim(),
        landing_url: String(formData.get("landing_url") ?? "").trim(),
        schedule_timezone: String(formData.get("schedule_timezone") ?? "").trim(),
        claim_assurance: claimAssurance,
        ...(claimApprovedBy ? { claim_approved_by: claimApprovedBy } : {}),
        ...(specialistApprovedBy ? { specialist_approved_by: specialistApprovedBy } : {})
      },
      input_artifacts: {
        product_image: state.productArtifact.sha256,
        ...(state.signalArtifact && state.signalReceiptArtifact ? {
          creative_signal_snapshot: state.signalArtifact.sha256,
          creative_signal_collection_receipt: state.signalReceiptArtifact.sha256
        } : {})
      },
      rights: { confirmed: true, basis: rightsBasis.value },
      human_release_required: true,
      data_class: "internal",
      ...(state.signalArtifact ? { creative_signal_data_class: "public" } : {})
    };
    const launchButton = getElement("launch-run-button");
    if (launchButton instanceof HTMLButtonElement) launchButton.disabled = true;
    setText("world-state-output", "Run accepted locally; waiting for the Agent worker…");
    try {
      const result = await requestJson("/v1/runs", { method: "POST", body: JSON.stringify(payload) });
      if (typeof result.run_id !== "string" || !/^run-[A-Za-z0-9_-]{8,96}$/.test(result.run_id)) {
        throw new Error("server returned an invalid run identifier");
      }
      disconnectTrajectory("Switching to the new run event stream…");
      state.runId = result.run_id;
      state.lastEventId = 0;
      state.eventKeys.clear();
      state.previewReady = false;
      state.approvalAttempt = null;
      setRunStatus(typeof result.status === "string" ? result.status : "queued");
      renderJson("world-state-output", result);
      refreshTrajectory();
      saveRecoveryState();
    } catch (error) {
      setText("world-state-output", `Run creation failed closed: ${String(error.message ?? error)}`);
    } finally {
      if (launchButton instanceof HTMLButtonElement) launchButton.disabled = false;
    }
  });

  getElement("tenant-session-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const input = getElement("tenant-session-token");
    if (!(input instanceof HTMLInputElement) || !input.checkValidity()) {
      input?.reportValidity?.();
      renderTenantSessionStatus("Tenant token must contain 24–512 characters.", "error");
      return;
    }
    const token = input.value;
    if (token !== state.tenantToken) clearTenantBoundClientState();
    state.tenantToken = token;
    try {
      window.sessionStorage.setItem(tenantSessionKey, token);
    } catch {
      state.tenantToken = null;
      renderTenantSessionStatus("Session storage is unavailable; token was not retained.", "error");
      return;
    }
    input.value = "";
    renderTenantSessionStatus(null, "success");
  });

  getElement("tenant-session-clear")?.addEventListener("click", () => {
    state.tenantToken = null;
    try {
      window.sessionStorage.removeItem(tenantSessionKey);
    } catch {
      // The in-memory principal is still cleared.
    }
    clearTenantBoundClientState();
    renderTenantSessionStatus();
  });

  getElement("memory-export-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement) || !form.checkValidity()) {
      form?.reportValidity?.();
      return;
    }
    const data = new FormData(form);
    try {
      const capsule = await requestJson("/v1/memory-capsules/export", {
        method: "POST",
        body: JSON.stringify({
          project_id: String(data.get("project_id") ?? "").trim(),
          ttl_seconds: Number(data.get("ttl_seconds"))
        })
      });
      const capsuleInput = getElement("memory-capsule-json");
      const capsuleIdInput = getElement("memory-capsule-id");
      if (capsuleInput instanceof HTMLTextAreaElement) capsuleInput.value = JSON.stringify(capsule, null, 2);
      if (capsuleIdInput instanceof HTMLInputElement) capsuleIdInput.value = String(capsule.capsule_id ?? "");
      renderJson("memory-capsule-output", capsule);
    } catch (error) {
      setText("memory-capsule-output", `Memory export failed closed: ${String(error.message ?? error)}`);
    }
  });

  getElement("memory-import-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const projectInput = getElement("memory-project-id");
    if (!(form instanceof HTMLFormElement) || !(projectInput instanceof HTMLInputElement) || !form.checkValidity()) {
      form?.reportValidity?.();
      return;
    }
    try {
      const capsule = JSON.parse(String(new FormData(form).get("capsule_json") ?? ""));
      const staged = await requestJson("/v1/memory-capsules/import", {
        method: "POST",
        body: JSON.stringify({ project_id: projectInput.value.trim(), capsule })
      });
      const capsuleIdInput = getElement("memory-capsule-id");
      if (capsuleIdInput instanceof HTMLInputElement) capsuleIdInput.value = String(staged.capsule_id ?? "");
      renderJson("memory-capsule-output", staged);
    } catch (error) {
      setText("memory-capsule-output", `Memory import rejected: ${String(error.message ?? error)}`);
    }
  });

  getElement("memory-review-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement) || !form.checkValidity()) {
      form?.reportValidity?.();
      return;
    }
    const data = new FormData(form);
    const capsuleId = String(data.get("capsule_id") ?? "").trim();
    const approvalToken = String(data.get("approval_token") ?? "");
    try {
      const reviewed = await requestJson(`/v1/memory-capsules/${encodeURIComponent(capsuleId)}/reviews`, {
        method: "POST",
        headers: { "X-ProofLaunch-Approval-Token": approvalToken },
        body: JSON.stringify({
          decision: String(data.get("decision") ?? ""),
          reason: String(data.get("reason") ?? "").trim()
        })
      });
      const tokenInput = form.querySelector("input[name='approval_token']");
      if (tokenInput instanceof HTMLInputElement) tokenInput.value = "";
      renderJson("memory-capsule-output", reviewed);
    } catch (error) {
      setText("memory-capsule-output", `Memory review rejected: ${String(error.message ?? error)}`);
    }
  });

  getElement("memory-list")?.addEventListener("click", loadMemoryCapsules);

  getElement("qualification-media-load")?.addEventListener("click", async () => {
    const button = getElement("qualification-media-load");
    if (button instanceof HTMLButtonElement) button.disabled = true;
    try {
      const qualification = await requestJson("/v1/local-multimodal-qualification");
      const bindings = [
        ["qualification-speech", "/v1/local-multimodal-qualification/assets/speech-master"],
        ["qualification-video", "/v1/local-multimodal-qualification/assets/video-one-stage"]
      ];
      for (const [elementId, path] of bindings) {
        const response = await window.fetch(path, { headers: tenantHeaders() });
        if (!response.ok) throw new Error(`media fetch failed with HTTP ${response.status}`);
        if (response.headers.get("X-ProofLaunch-Evidence-Class") !== "local-qualification-not-product") {
          throw new Error("media evidence class header is missing");
        }
        const url = URL.createObjectURL(await response.blob());
        qualificationMediaUrls.push(url);
        const element = getElement(elementId);
        if (element instanceof HTMLMediaElement) {
          element.src = url;
          element.hidden = false;
        }
      }
      renderJson("qualification-media-output", {
        content_sha256: qualification.content_sha256,
        host_accelerator: qualification.execution.host_accelerator,
        local_model_inference_observed: qualification.execution.local_model_inference_observed,
        cloud_api_calls: qualification.execution.cloud_api_calls,
        speech_human_review_passed: qualification.quality_gates.speech_named_human_listening_review,
        video_delivery_gate_passed: qualification.quality_gates.video_delivery_gate_passed,
        product_admission_passed: qualification.quality_gates.product_admission_passed,
        truth_boundary: qualification.truth_boundary
      });
    } catch (error) {
      setText("qualification-media-output", `Local media unavailable: ${String(error.message ?? error)}`);
      if (button instanceof HTMLButtonElement) button.disabled = false;
    }
  });

  getElement("campaign-pack-load")?.addEventListener("click", async () => {
    const button = getElement("campaign-pack-load");
    if (button instanceof HTMLButtonElement) button.disabled = true;
    try {
      const pack = await requestJson("/v1/local-campaign-pack");
      const bindings = [
        ["campaign-pack-video", pack.artifacts["film-4k"].url],
        ["campaign-pack-hero", pack.artifacts["hero-4k"].url],
        ["campaign-pack-audio", pack.artifacts["audio-master"].url]
      ];
      for (const [elementId, path] of bindings) {
        const response = await window.fetch(path, { headers: tenantHeaders() });
        if (!response.ok) throw new Error(`campaign media fetch failed with HTTP ${response.status}`);
        if (response.headers.get("X-ProofLaunch-Evidence-Class") !== "local-campaign-pack-mechanical-not-product") {
          throw new Error("campaign media evidence class header is missing");
        }
        const url = URL.createObjectURL(await response.blob());
        qualificationMediaUrls.push(url);
        const element = getElement(elementId);
        if (element instanceof HTMLMediaElement || element instanceof HTMLImageElement) {
          element.src = url;
          element.hidden = false;
        }
      }
      renderJson("campaign-pack-output", {
        campaign_id: pack.campaign_id,
        content_sha256: pack.content_sha256,
        source_model: pack.source_generation.model,
        source_accelerator: pack.source_generation.accelerator,
        cloud_api_calls: pack.source_generation.cloud_api_calls,
        mechanical_campaign_pack_ready: pack.quality_gates.mechanical_campaign_pack_ready,
        named_human_blind_review_passed: pack.quality_gates.named_human_blind_review_passed,
        four_a_preference_proven: pack.quality_gates.four_a_preference_proven,
        product_admission_passed: pack.quality_gates.product_admission_passed,
        external_publish_executed: pack.external_publish_executed,
        truth_boundary: pack.truth_boundary
      });
    } catch (error) {
      setText("campaign-pack-output", `Campaign pack unavailable: ${String(error.message ?? error)}`);
      if (button instanceof HTMLButtonElement) button.disabled = false;
    }
  });

  getElement("effect-observation-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement) || !form.checkValidity()) {
      form?.reportValidity?.();
      setText("effect-output", "Observation blocked: complete every bounded aggregate field and both data-quality attestations.");
      return;
    }
    if (!state.runId || state.runStatus !== "delivered" || !state.effectContract) {
      setText("effect-output", "Observation blocked: a delivered experiment contract is required.");
      return;
    }
    const formData = new FormData(form);
    const token = String(formData.get("approval_token") ?? "");
    if (!token) {
      setText("effect-output", "Observation blocked: enter the local operator approval token.");
      return;
    }
    const integer = (name) => {
      const raw = String(formData.get(name) ?? "");
      if (!/^\d+$/.test(raw)) throw new Error(`${name} must be a non-negative integer`);
      const value = Number(raw);
      if (!Number.isSafeInteger(value)) throw new Error(`${name} is outside the safe integer range`);
      return value;
    };
    const decimal = (name) => {
      const value = Number(String(formData.get(name) ?? ""));
      if (!Number.isFinite(value) || value < 0) throw new Error(`${name} must be a finite non-negative number`);
      return value;
    };
    const metricBlock = (prefix) => ({
      eligible_reach: integer(`${prefix}_reach`),
      qualified_actions: integer(`${prefix}_qualified`),
      evidence_engagements: integer(`${prefix}_engagement`),
      complaints: integer(`${prefix}_complaints`),
      conversions: integer(`${prefix}_conversions`),
      revenue_usd: decimal(`${prefix}_revenue`),
      spend_usd: decimal(`${prefix}_spend`)
    });
    try {
      const inputCore = {
        experiment_id: state.effectContract.experiment_id,
        strategy_plan_sha256: state.effectContract.strategy_plan_sha256,
        source_kind: String(formData.get("source_kind") ?? ""),
        source_reference_sha256: String(formData.get("source_reference_sha256") ?? "").trim(),
        channel: String(formData.get("channel") ?? "").trim(),
        window_start: String(formData.get("window_start") ?? "").trim(),
        window_end: String(formData.get("window_end") ?? "").trim(),
        assignment_method: String(formData.get("assignment_method") ?? ""),
        metrics: metricBlock("observed"),
        baseline_metrics: metricBlock("baseline"),
        deduplicated: formData.get("deduplicated") === "on",
        bot_filter_applied: formData.get("bot_filter_applied") === "on"
      };
      const fingerprint = JSON.stringify(inputCore);
      if (!state.outcomeAttempt || state.outcomeAttempt.fingerprint !== fingerprint) {
        const identity = newIdempotencyKey(`effect-${state.runId}`);
        state.outcomeAttempt = { fingerprint, observationId: identity, idempotencyKey: identity };
      }
      const payload = { observation_id: state.outcomeAttempt.observationId, ...inputCore };
      const button = getElement("effect-submit");
      if (button instanceof HTMLButtonElement) button.disabled = true;
      const tokenInput = getElement("effect-approval-token");
      if (tokenInput instanceof HTMLInputElement) tokenInput.value = "";
      const result = await requestJson(`/v1/runs/${encodeURIComponent(state.runId)}/outcomes`, {
        method: "POST",
        headers: {
          "X-ProofLaunch-Approval-Token": token,
          "Idempotency-Key": state.outcomeAttempt.idempotencyKey
        },
        body: JSON.stringify(payload)
      });
      renderJson("effect-output", result);
      await loadEffectObservations();
    } catch (error) {
      setText("effect-output", `Observation rejected: ${String(error.message ?? error)}`);
      setEffectFormEnabled(true);
    }
  });

  getElement("learning-promotion-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement) || !form.checkValidity()) {
      form?.reportValidity?.();
      setText("learning-memory-output", "Promotion blocked: enter a bounded reason and operator token.");
      return;
    }
    const observation = state.latestEffectObservation;
    if (
      !state.runId ||
      state.runStatus !== "delivered" ||
      !observation ||
      observation.comparison_ready !== true ||
      observation.zero_budget_contract_breach !== false
    ) {
      setText("learning-memory-output", "Promotion blocked: the latest delivered observation is not eligible.");
      return;
    }
    const formData = new FormData(form);
    const reason = String(formData.get("reason") ?? "").trim();
    const token = String(formData.get("approval_token") ?? "");
    const fingerprint = JSON.stringify({ observation_id: observation.observation_id, reason });
    if (!state.learningPromotionAttempt || state.learningPromotionAttempt.fingerprint !== fingerprint) {
      state.learningPromotionAttempt = {
        fingerprint,
        idempotencyKey: newIdempotencyKey(`learning-${state.runId}`)
      };
    }
    const tokenInput = getElement("learning-approval-token");
    if (tokenInput instanceof HTMLInputElement) tokenInput.value = "";
    setLearningPromotionEnabled(false);
    try {
      const result = await requestJson(
        `/v1/runs/${encodeURIComponent(state.runId)}/outcomes/${encodeURIComponent(observation.observation_id)}/promotions`,
        {
          method: "POST",
          headers: {
            "X-ProofLaunch-Approval-Token": token,
            "Idempotency-Key": state.learningPromotionAttempt.idempotencyKey
          },
          body: JSON.stringify({
            reason,
            idempotency_key: state.learningPromotionAttempt.idempotencyKey
          })
        }
      );
      renderJson("learning-memory-output", result);
      await loadEffectObservations();
    } catch (error) {
      setText("learning-memory-output", `Promotion rejected: ${String(error.message ?? error)}`);
      setLearningPromotionEnabled(true);
    }
  });

  getElement("approval-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!state.runId) {
      setText("approval-output", "No current run. Create one in World State first.");
      return;
    }
    if (state.runStatus !== "awaiting_release") {
      setText("approval-output", `Decision blocked: current run status is ${state.runStatus ?? "unknown"}, not awaiting_release.`);
      return;
    }
    const formData = new FormData(event.currentTarget);
    const decision = String(formData.get("decision") ?? "");
    const reason = String(formData.get("reason") ?? "").trim();
    const tokenInput = getElement("approval-token");
    const approvalToken = tokenInput instanceof HTMLInputElement ? tokenInput.value : "";
    if (!approvalToken) {
      setText("approval-output", "Decision blocked: enter the local approval token.");
      return;
    }
    if (tokenInput instanceof HTMLInputElement) tokenInput.value = "";
    const attemptFingerprint = JSON.stringify({ decision, reason });
    if (!state.approvalAttempt || state.approvalAttempt.fingerprint !== attemptFingerprint) {
      state.approvalAttempt = {
        fingerprint: attemptFingerprint,
        idempotencyKey: newIdempotencyKey(`approval-${state.runId}`)
      };
    }
    const payload = {
      decision,
      reason,
      idempotency_key: state.approvalAttempt.idempotencyKey
    };
    const approvalButton = getElement("approval-submit");
    if (approvalButton instanceof HTMLButtonElement) approvalButton.disabled = true;
    try {
      const result = await requestJson(`/v1/runs/${encodeURIComponent(state.runId)}/approvals`, {
        method: "POST",
        headers: { "X-ProofLaunch-Approval-Token": approvalToken },
        body: JSON.stringify(payload)
      });
      renderJson("approval-output", result);
      if (typeof result.status === "string") setRunStatus(result.status);
      await refreshRunSnapshot();
      refreshTrajectory();
    } catch (error) {
      setText("approval-output", `Decision rejected: ${String(error.message ?? error)}`);
      if (approvalButton instanceof HTMLButtonElement) approvalButton.disabled = true;
      if (state.runStatus === "awaiting_release") await loadRunPreview();
    }
  });

  getElement("blind-review-access-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const scopeInput = getElement("blind-review-scope");
    const slotInput = getElement("blind-review-slot");
    const tokenInput = getElement("blind-review-token");
    const pseudonymInput = getElement("blind-review-pseudonym");
    if (!(scopeInput instanceof HTMLSelectElement) || !(slotInput instanceof HTMLSelectElement) || !(tokenInput instanceof HTMLInputElement) || !(pseudonymInput instanceof HTMLInputElement)) return;
    const scope = ["portfolio", "mission", "calibration", "campaign_pack"].includes(scopeInput.value) ? scopeInput.value : "portfolio";
    const slot = Number(slotInput.value);
    const token = tokenInput.value;
    const pseudonym = pseudonymInput.value.trim();
    if (!Number.isInteger(slot) || slot < 1 || slot > 5 || !token || !pseudonym) {
      setText("blind-review-output", "Assignment blocked: slot, invitation token, and stable pseudonym are required.");
      return;
    }
    try {
      const assignment = await requestJson(`${blindReviewBase(scope)}/tasks?slot=${encodeURIComponent(slot)}`, {
        headers: { "X-ProofLaunch-Reviewer-Token": token }
      });
      state.blindReviewAssignment = { assignment, slot, pseudonym, scope };
      renderBlindReviewTasks(assignment);
      renderBlindReviewStatus(await requestJson(`${blindReviewBase(scope)}/status`), scope);
      setText(
        "blind-review-output",
        scope === "calibration"
          ? `Loaded ${assignment.task_count} blinded calibration cases for slot ${slot}. Model prediction, provider identity, private mapping, and other human labels remain hidden.`
          : scope === "campaign_pack"
          ? `Loaded ${assignment.task_count} identity-hidden three-format campaign-system pair for slot ${slot}. Candidate, provider, model, private mapping, and other human choices remain hidden.`
          : `Loaded ${assignment.task_count} blinded pairs for slot ${slot} in the ${scope === "portfolio" ? "nine-case portfolio" : "current campaign"} scope. No candidate or provider identity was revealed.`
      );
    } catch (error) {
      state.blindReviewAssignment = null;
      setText("blind-review-output", `Assignment blocked: ${String(error.message ?? error)}`);
    }
  });

  getElement("blind-review-task-list")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const tokenInput = getElement("blind-review-token");
    if (!(form instanceof HTMLFormElement) || !(tokenInput instanceof HTMLInputElement)) return;
    const active = state.blindReviewAssignment;
    const taskId = form.dataset.reviewTaskId;
    const task = active?.assignment?.tasks?.find((row) => row.review_task_id === taskId);
    if (!active || !task || !tokenInput.value) {
      setText("blind-review-output", "Submission blocked: reload the invitation-bound assignment.");
      return;
    }
    const formData = new FormData(form);
    if (formData.get("human_attestation") !== "on") {
      setText("blind-review-output", "Submission blocked: the independent human-review attestation is required.");
      return;
    }
    const calibrationLabel = String(formData.get("human_label") ?? "");
    if (active.scope === "calibration" && !["true", "false"].includes(calibrationLabel)) {
      setText("blind-review-output", "Submission blocked: choose PASS or FAIL for the frozen calibration criterion.");
      return;
    }
    const campaignPackDimensions = ["concept_originality", "information_hierarchy", "evidence_credibility", "cross_format_extensibility", "action_motivation"];
    const campaignOverall = String(formData.get("overall_winner") ?? "");
    const campaignDefect = String(formData.get("blocking_defect_side") ?? "");
    const campaignDefectReason = String(formData.get("blocking_defect_reason") ?? "").trim();
    const campaignNotes = String(formData.get("notes") ?? "").trim();
    const campaignDimensionWinners = Object.fromEntries(
      campaignPackDimensions.map((dimension) => [dimension, String(formData.get(`dimension_${dimension}`) ?? "")])
    );
    if (active.scope === "campaign_pack" && (
      !["left", "right"].includes(campaignOverall)
      || !["none", "left", "right", "both"].includes(campaignDefect)
      || Object.values(campaignDimensionWinners).some((choice) => !["left", "right", "tie"].includes(choice))
      || campaignNotes.length < 24
      || (campaignDefect !== "none" && campaignDefectReason.length < 16)
    )) {
      setText("blind-review-output", "Submission blocked: complete the overall, five dimension, blocking-defect, and located rationale fields.");
      return;
    }
    const review = active.scope === "calibration"
      ? {
          schema: "ProofLaunchJudgeCalibrationHumanLabelV1",
          review_task_id: task.review_task_id,
          case_id: task.case_id,
          case_sha256: task.case_sha256,
          reviewer_slot: active.slot,
          reviewer_pseudonym: active.pseudonym,
          human_attestation: judgeCalibrationAttestation,
          human_label: calibrationLabel === "true",
          reason: String(formData.get("reason") ?? "").trim(),
          reviewed_at: new Date().toISOString(),
          review_content_sha256: null
        }
      : active.scope === "campaign_pack"
      ? {
          schema: "ProofLaunchCampaignPackVisualHumanReviewV1",
          review_task_id: task.review_task_id,
          pair_id: task.pair_id,
          pair_sha256: task.pair_sha256,
          reviewer_slot: active.slot,
          reviewer_pseudonym: active.pseudonym,
          human_attestation: campaignPackReviewAttestation,
          overall_winner: campaignOverall,
          dimension_winners: campaignDimensionWinners,
          blocking_defect_side: campaignDefect,
          blocking_defect_reason: campaignDefectReason,
          notes: campaignNotes,
          reviewed_at: new Date().toISOString(),
          review_content_sha256: null
        }
      : {
          schema: "ProofLaunchTextCreativeHumanBlindReviewV1",
          review_task_id: task.review_task_id,
          pair_id: task.pair_id,
          pair_sha256: task.pair_sha256,
          reviewer_slot: active.slot,
          reviewer_pseudonym: active.pseudonym,
          human_attestation: blindReviewAttestation,
          choice: String(formData.get("choice") ?? ""),
          reason: String(formData.get("reason") ?? "").trim(),
          critical_failure: formData.get("critical_failure") === "on",
          reviewed_at: new Date().toISOString(),
          review_content_sha256: null
        };
    review.review_content_sha256 = await blindReviewDigest(review);
    const submit = form.querySelector("button[type='submit']");
    if (submit instanceof HTMLButtonElement) submit.disabled = true;
    try {
      const base = blindReviewBase(active.scope);
      const acknowledgement = await requestJson(`${base}/reviews`, {
        method: "POST",
        headers: { "X-ProofLaunch-Reviewer-Token": tokenInput.value },
        body: JSON.stringify(review)
      });
      renderBlindReviewStatus(acknowledgement, active.scope);
      setText("blind-review-output", `Immutable review recorded · ${acknowledgement.review_task_id} · sha256:${acknowledgement.review_content_sha256}`);
      const refreshed = await requestJson(`${base}/tasks?slot=${encodeURIComponent(active.slot)}`, {
        headers: { "X-ProofLaunch-Reviewer-Token": tokenInput.value }
      });
      state.blindReviewAssignment.assignment = refreshed;
      renderBlindReviewTasks(refreshed);
    } catch (error) {
      if (submit instanceof HTMLButtonElement) submit.disabled = false;
      setText("blind-review-output", `Review rejected: ${String(error.message ?? error)}`);
    }
  });

  getElement("blind-review-scope")?.addEventListener("change", () => {
    state.blindReviewAssignment = null;
    const list = getElement("blind-review-task-list");
    if (list) {
      const message = document.createElement("p");
      message.textContent = "Scope changed. Load the invitation-bound assignment for this scope.";
      list.replaceChildren(message);
    }
    probeBlindReviewStatus(currentBlindReviewScope());
  });

  getElement("blind-review-selection-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    const formData = new FormData(form);
    const approvalToken = String(formData.get("approval_token") ?? "");
    const aggregateSha = String(form.dataset.aggregateSha256 ?? "");
    if (formData.get("selection_attestation") !== "on" || !approvalToken || !/^[0-9a-f]{64}$/.test(aggregateSha)) {
      setText("blind-review-output", "Multimodal admission blocked: complete aggregate, operator token, and explicit boundary attestation are required.");
      return;
    }
    const payload = {
      aggregate_content_sha256: aggregateSha,
      selected_territory_id: String(formData.get("selected_territory_id") ?? ""),
      reason: String(formData.get("reason") ?? "").trim(),
      human_attestation: multimodalSelectionAttestation,
      idempotency_key: newIdempotencyKey("multimodal-selection")
    };
    const button = form.querySelector("button[type='submit']");
    if (button instanceof HTMLButtonElement) button.disabled = true;
    try {
      const admission = await requestJson("/v1/blind-review/selections", {
        method: "POST",
        headers: { "X-ProofLaunch-Approval-Token": approvalToken },
        body: JSON.stringify(payload)
      });
      const tokenInput = getElement("blind-review-approval-token");
      if (tokenInput instanceof HTMLInputElement) tokenInput.value = "";
      setText("blind-review-output", `Selected creative system admitted · ${admission.selected_territory_id} · media sha256:${admission.multimodal_seed_compilation_sha256 ?? "not created"} · omnichannel sha256:${admission.omnichannel_activation_plan_sha256 ?? "not created"}. GPU=false; publish=false; send=false; spend=false.`);
      await probeBlindReviewStatus();
    } catch (error) {
      if (button instanceof HTMLButtonElement) button.disabled = false;
      setText("blind-review-output", `Multimodal admission rejected: ${String(error.message ?? error)}`);
    }
  });

  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("close", () => {
      if (state.pendingControl instanceof HTMLElement) {
        state.pendingControl.focus();
      }
      state.pendingControl = null;
    });
  });

  getElement("platform-capability-surface")?.addEventListener(
    "change",
    renderPlatformCapabilityShowcase
  );
  getElement("open-official-contest-page")?.addEventListener("click", () => {
    window.open("https://huggingface.co/blog/LeRobot-worldwide-hackathon/amd-ai-devmaster", "_blank", "noopener,noreferrer");
  });
  getElement("frontier-gtm-form")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (!(form instanceof HTMLFormElement)) return;
    const button = form.querySelector("button[type='submit']");
    const badge = getElement("frontier-gtm-status");
    if (!state.tenantToken) {
      setFeedback("frontier-gtm-feedback", "Run blocked: activate the tenant session in Tenants & access first.", "error");
      return;
    }
    const { identity, brief } = await frontierBriefFromForm(form);
    if (button instanceof HTMLButtonElement) button.disabled = true;
    if (badge) {
      badge.textContent = "Cloud board running";
      badge.className = "status-badge status-badge--waiting";
    }
    setFeedback("frontier-gtm-feedback", "Strategy, creative jury, integrated production and adversarial audit are running. Do not resubmit; the request is idempotent.", "info");
    try {
      setFrontierFlowStep("brief", "complete", "Brief sealed");
      setFrontierFlowStep("strategy", "running", "Cloud upgrade");
      const result = await requestJson("/v1/frontier-gtm/runs", {
        method: "POST",
        headers: { "Idempotency-Key": `frontier-${identity}` },
        body: JSON.stringify({ brief })
      });
      renderFrontierRun(result);
      setFrontierFlowStep("strategy", "complete", "Strategy sealed");
      setFrontierFlowStep("concept", "complete", "Jury selected");
      setFrontierFlowStep("production", "waiting", "No binary receipt");
      setFrontierFlowStep("audit", result.release_review_status === "ready_for_named_human_release_review" ? "complete" : "failed", result.release_review_status === "ready_for_named_human_release_review" ? "Audit passed" : "Audit blocked");
      setFrontierFlowStep("release", "gated", "Human decision");
      selectFrontierOutputTab("overview");
      if (badge) {
        const ready = result.release_review_status === "ready_for_named_human_release_review";
        badge.textContent = ready ? "Ready for human review" : "Blocked by audit";
        badge.className = `status-badge ${ready ? "status-badge--passed" : "status-badge--blocked"}`;
      }
      setFeedback("frontier-gtm-feedback", `Run sealed · sha256:${result.content_sha256} · no external action executed.`, "success");
    } catch (error) {
      setFrontierFlowStep("strategy", "failed", "Failed closed");
      if (badge) {
        badge.textContent = "Failed closed";
        badge.className = "status-badge status-badge--blocked";
      }
      setFeedback("frontier-gtm-feedback", `Frontier run unavailable: ${String(error.message ?? error)}. No local fallback was attempted.`, "error");
    } finally {
      if (button instanceof HTMLButtonElement) button.disabled = false;
      document.querySelectorAll("[data-frontier-recipe]").forEach((recipeButton) => recipeButton.removeAttribute("data-running"));
    }
  });
  getElement("integrated-campaign-model")?.addEventListener(
    "change",
    renderCodexIntegratedCampaignPortfolio
  );
  getElement("codex-adaptation-archetype")?.addEventListener(
    "change",
    renderCodexCampaignAdaptationSummary
  );
  getElement("codex-lighthouse-case")?.addEventListener(
    "change",
    renderCodexLighthousePortfolio
  );

  window.addEventListener("popstate", () => {
    navigate(window.location.pathname, { push: false });
  });

  window.addEventListener("beforeunload", () => {
    if (state.eventPollTimer !== null) window.clearTimeout(state.eventPollTimer);
    if (state.previewBlobUrl) URL.revokeObjectURL(state.previewBlobUrl);
    qualificationMediaUrls.forEach((url) => URL.revokeObjectURL(url));
    clearFrontierMediaUrls();
  });

  restoreTenantSession();
  void activateLoopbackEvaluationSession();
  restoreRecoveryState();
  const initialPath = routeMetadata.has(window.location.pathname) ? window.location.pathname : state.route;
  const marketSelect = getElement("brief-market");
  const objectiveSelect = getElement("brief-objective");
  if (marketSelect instanceof HTMLSelectElement) {
    marketSelect.value = state.briefMarket;
  }
  if (objectiveSelect instanceof HTMLSelectElement) {
    objectiveSelect.value = state.briefObjective;
  }
  renderProductArtifactStatus();
  updateArtifactBinding();
  if (state.runStatus) setRunStatus(state.runStatus);
  else updateBundleControl();
  updateCreateControls();
  updateRepairControls();
  setupMissionMotion();
  setupConsoleShell();
  probeControlPlane().then(() => {
    probeProductReadiness();
    if (!state.runId) return;
    refreshRunSnapshot()
      .then(() => {
        if (!terminalRunStatuses.has(state.runStatus) && state.route !== "/control/trajectory") refreshTrajectory();
      })
      .catch((error) => setText("world-state-output", `Stored run is unavailable: ${String(error.message ?? error)}`));
  });
  navigate(initialPath, { push: false, focus: false });
})();

/* MKO Web UI — Full Frontend Application */

(function () {
  "use strict";

  // ─── State ──────────────────────────────────────────────────────────
  let currentAgent = "general";
  let currentProvider = "groq";
  let currentModel = "llama-3.3-70b-versatile";
  let isStreaming = false;
  let abortController = null;
  let lastComputeBenchResult = null;
  let lastProviderBenchResults = null;

  // ─── Slash-suggest state (autocomplete dropdown over #chatInput) ────
  //   `suggestOpen`   – dropdown is currently rendered (not just empty).
  //   `suggestRows`   – current KNOWN_COMMANDS rows shown, in order.
  //   `suggestHighlight` – -1 (none), else the row index that gets the
  //                      `.active` class. Keys (↑/↓/Tab/Enter/Esc) act
  //                      only when suggestOpen && suggestRows.length > 0.
  let suggestOpen = false;
  let suggestRows = [];
  let suggestHighlight = -1;

  // ─── DOM refs ───────────────────────────────────────────────────────
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => document.querySelectorAll(s);
  const chatMessages = $("#chatMessages");
  const chatInput = $("#chatInput");
  const sendBtn = $("#sendBtn");
  const stopBtn = $("#stopBtn");
  const agentList = $("#agentList");
  const navCredits = $("#navCredits");
  const currentAgentBadge = $("#currentAgentBadge");
  const currentModelInfo = $("#currentModelInfo");
  const providerSelect = $("#providerSelect");
  const modelSelect = $("#modelSelect");
  const settingsPanel = $("#settingsPanel");
  const settingsToggle = $("#settingsToggle");

  // ─── Init ───────────────────────────────────────────────────────────

  async function init() {
    await loadConfig();
    await loadAgents();
    await loadCredits();
    wirePanels();
    wireBenchmarks();
    wireMoeConfig();
    wireRag();
    wireSettings();
    wireChat();
    wireSlashSuggest();      // builds the dropdown element + listeners
    wireWelcomeAgents();
    wireDownloadBenchmarkButtons();
  }

  // ─── Config ─────────────────────────────────────────────────────────

  async function loadConfig() {
    try {
      const res = await fetch("/api/config");
      const cfg = await res.json();
      currentProvider = cfg.provider || "groq";
      currentModel = cfg.model || "";
      providerSelect.value = currentProvider;

      // Populate API key fields
      if (cfg.providers) {
        if (cfg.providers.groq) {
          const input = $("#groqKey");
          if (input) input.placeholder = "✓ Configured";
        }
        if (cfg.providers.openai) {
          const input = $("#openaiKey");
          if (input) input.placeholder = "✓ Configured";
        }
        if (cfg.providers.anthropic) {
          const input = $("#anthropicKey");
          if (input) input.placeholder = "✓ Configured";
        }
        if (cfg.providers.huggingface) {
          const input = $("#hfKey");
          if (input) input.placeholder = "✓ Configured";
        }
      }

      updateModelInfo();
      await loadModels();
    } catch (e) {
      console.error("Failed to load config:", e);
    }
  }

  async function loadModels() {
    try {
      const res = await fetch("/api/models");
      const models = await res.json();
      modelSelect.innerHTML = '<option value="">Default</option>';
      const provModels = models[currentProvider] || [];
      provModels.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m;
        if (m === currentModel) opt.selected = true;
        modelSelect.appendChild(opt);
      });
    } catch (e) {
      console.error("Failed to load models:", e);
    }
  }

  // ─── Credits ────────────────────────────────────────────────────────

  async function loadCredits() {
    try {
      const res = await fetch("/api/credits?username=demo");
      const data = await res.json();
      navCredits.textContent = `💎 ${data.credits}`;
    } catch (e) {
      /* ignore */
    }
  }

  // ─── Agents ─────────────────────────────────────────────────────────

  async function loadAgents() {
    try {
      const res = await fetch("/api/agents");
      const data = await res.json();
      renderAgentList(data.agents || []);
      renderWelcomeCards(data.agents || []);
    } catch (e) {
      console.error("Failed to load agents:", e);
    }
  }

  function renderAgentList(agents) {
    agentList.innerHTML = agents
      .map(
        (a) => `
        <button class="agent-btn ${a.id === currentAgent ? "active" : ""}" data-agent="${a.id}">
          <span class="agent-icon">${a.icon}</span>
          <span class="agent-name">${a.name}</span>
        </button>
      `
      )
      .join("");

    agentList.querySelectorAll(".agent-btn").forEach((btn) => {
      btn.addEventListener("click", () => selectAgent(btn.dataset.agent));
    });
  }

  function renderWelcomeCards(agents) {
    const container = $("#welcomeAgents");
    if (!container) return;
    container.innerHTML = agents
      .map(
        (a) => `
        <button class="welcome-agent-card" data-agent="${a.id}">
          <span class="wa-icon">${a.icon}</span>
          <span class="wa-name">${a.name}</span>
          <span class="wa-desc">${a.description}</span>
        </button>
      `
      )
      .join("");

    container.querySelectorAll(".welcome-agent-card").forEach((btn) => {
      btn.addEventListener("click", () => selectAgent(btn.dataset.agent));
    });
  }

  function selectAgent(agentId) {
    currentAgent = agentId;
    agentList.querySelectorAll(".agent-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.agent === agentId);
    });

    const agentNames = {
      general: "🧠 General Assistant",
      planner: "📋 Planner",
      research: "🔍 Researcher",
      reasoner: "⚖️ Reasoner",
      actor: "⚡ Actor",
      memory: "💾 Memory",
      rag: "📚 RAG Agent",
      moe: "🔀 MoE Agent",
    };
    currentAgentBadge.textContent = agentNames[agentId] || "🧠 General Assistant";

    // Show special UI for certain agents
    if (agentId === "rag") {
      openPanel("rag");
    }
    if (agentId === "moe") {
      openPanel("moe-config");
    }
  }

  // ─── Chat ───────────────────────────────────────────────────────────

  function wireChat() {
    sendBtn.addEventListener("click", sendMessage);
    chatInput.addEventListener("keydown", (e) => {
      // Slash-suggest owns keydown while open (it handles Enter, Tab,
      // Escape, ↑, ↓). This handler only fires for sendMessage when
      // the popup is closed. Registration order: this listener is
      // registered FIRST, then wireSlashSuggest() registers its own
      // listener SECOND — both fire on the same event, so the suggest
      // handler still runs and acts (it calls preventDefault before
      // any default action; sendMessage is gated by suggestOpen here).
      if (suggestOpen) return;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
    stopBtn.addEventListener("click", stopStreaming);
  }

  // ─── Slash-command autocomplete dropdown ────────────────────────────
  //
  // Shows a small panel above #chatInput listing the KNOWN_COMMANDS
  // rows whose canonical form matches the current text. Pure data
  // filtering lives in MKOSlash.getSuggestions(); this file only does
  // DOM rendering and keyboard plumbing.
  //
  // UX (pin this — tests in tests/test_slash_commands.mjs cover the
  // pure parts; e2e is exercised manually):
  //   trigger       text starts with `/` and has no whitespace
  //   filter        case-insensitive prefix match against `cmd`
  //   arrow keys    move highlight (clamp at ends, no loop)
  //   Tab           autocomplete the highlight (or row 0 if -1)
  //   Enter         autocomplete the highlight (or row 0 if -1)
  //                 (NEVER auto-sends — unexpected sends are a UX sin)
  //   Shift+Enter   passes through (newline in textarea)
  //   Escape        close & refocuses input
  //   outside click close
  //   no matches    hide the dropdown entirely (no "no match" row)
  //
  // On autocomplete, the input value becomes `/cmd` + a single trailing
  // space — uniform cheap behavior; trailing whitespace also auto-hides
  // the dropdown via the next input event because getSuggestions sees
  // the space.

  function ensureSuggestEl() {
    let el = document.getElementById("chatSuggest");
    if (el) return el;
    el = document.createElement("div");
    el.id = "chatSuggest";
    el.className = "mko-suggest";
    el.setAttribute("role", "listbox");
    el.setAttribute("aria-label", "Slash command suggestions");
    // Position relative to the .input-area (CSS makes the area the
    // positioning context).
    const inputArea = document.querySelector(".input-area");
    if (inputArea) inputArea.appendChild(el);
    // Delegated click — clicking any row triggers autocomplete.
    el.addEventListener("click", (e) => {
      const row = e.target.closest(".mko-suggest-row");
      if (!row) return;
      const idx = Number(row.dataset.idx);
      if (!Number.isInteger(idx) || !suggestRows[idx]) return;
      applySuggestion(suggestRows[idx]);
    });
    // Mouseover updates the highlight so keyboard and mouse stay in sync.
    el.addEventListener("mousemove", (e) => {
      const row = e.target.closest(".mko-suggest-row");
      if (!row) return;
      const idx = Number(row.dataset.idx);
      if (!Number.isInteger(idx) || idx === suggestHighlight) return;
      suggestHighlight = idx;
      paintSuggestHighlight();
    });
    return el;
  }

  // Render (or hide) the dropdown based on current input value.
  function renderSuggest() {
    const el = ensureSuggestEl();
    const matches = (typeof MKOSlash !== "undefined" && MKOSlash.getSuggestions)
      ? MKOSlash.getSuggestions(chatInput.value)
      : null;
    // matches === null  → trigger predicate failed: hide (and reset).
    // matches === []    → starts with `/`, no rows: also hide quietly.
    if (!matches || matches.length === 0) {
      if (suggestOpen) hideSuggest();
      return;
    }
    suggestRows = matches;
    // Multi-row → start highlight at 0 so ↓/↑ feel responsive.
    // Single row → leave highlight at -1 (Enter still picks first).
    suggestHighlight = matches.length > 1 ? 0 : -1;
    el.innerHTML = matches.map((c, i) => {
      const active = i === suggestHighlight ? " active" : "";
      const selected = active ? "true" : "false";
      return (
        '<div class="mko-suggest-row' + active + '"' +
        ' role="option" data-idx="' + i + '"' +
        ' aria-selected="' + selected + '">' +
        '<span class="mko-suggest-cmd">' + c.cmd + '</span>' +
        // escapeHtml on `desc` is defensive: KNOWN_COMMANDS is currently
        // a developer-controlled literal array, but if a future maintainer
        // ever sources rows from user input, the dropdown stays XSS-safe.
        '<span class="mko-suggest-desc">' + escapeHtml(c.desc) + '</span>' +
        '</div>'
      );
    }).join("");
    el.classList.add("open");
    suggestOpen = true;
  }

  function paintSuggestHighlight() {
    const el = document.getElementById("chatSuggest");
    if (!el) return;
    el.querySelectorAll(".mko-suggest-row").forEach((row, i) => {
      const isActive = i === suggestHighlight;
      row.classList.toggle("active", isActive);
      row.setAttribute("aria-selected", isActive ? "true" : "false");
    });
  }

  function hideSuggest() {
    const el = document.getElementById("chatSuggest");
    if (el) {
      el.innerHTML = "";
      el.classList.remove("open");
    }
    suggestOpen = false;
    suggestRows = [];
    suggestHighlight = -1;
  }

  function applySuggestion(cmd) {
    // Uniform completion: `/cmd` + trailing space. Even for /help &
    // /commands the space is harmless (the parser ignores extra args).
    chatInput.value = cmd.cmd + " ";
    chatInput.focus();
    // Cursor to end so the user can type the topic immediately.
    const end = chatInput.value.length;
    try { chatInput.setSelectionRange(end, end); } catch (_) { /* ignore */ }
    // Re-evaluate (text ends with a space → next render will hide UI).
    renderSuggest();
  }

  function onDocClickMaybeCloseSuggest(e) {
    if (!suggestOpen) return;
    const t = e.target;
    if (chatInput.contains(t)) return;
    const el = document.getElementById("chatSuggest");
    if (el && el.contains(t)) return;
    hideSuggest();
  }

  function onChatKeydownSuggest(e) {
    if (!suggestOpen || suggestRows.length === 0) return;
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        suggestHighlight = Math.min(suggestHighlight + 1, suggestRows.length - 1);
        if (suggestHighlight < 0) suggestHighlight = 0;
        paintSuggestHighlight();
        break;
      case "ArrowUp":
        e.preventDefault();
        suggestHighlight = Math.max(suggestHighlight - 1, 0);
        paintSuggestHighlight();
        break;
      case "Tab":
        // Tab always autocompletes the highlight (or first row).
        e.preventDefault();
        if (suggestHighlight < 0) suggestHighlight = 0;
        if (suggestRows[suggestHighlight]) {
          applySuggestion(suggestRows[suggestHighlight]);
        }
        break;
      case "Enter":
        if (e.shiftKey) return;          // Shift+Enter = textarea newline
        e.preventDefault();
        if (suggestHighlight < 0) suggestHighlight = 0;  // pick first
        if (suggestRows[suggestHighlight]) {
          applySuggestion(suggestRows[suggestHighlight]);
        }
        break;
      case "Escape":
        e.preventDefault();
        hideSuggest();
        chatInput.focus();
        break;
    }
  }

  function wireSlashSuggest() {
    ensureSuggestEl();           // create the DOM node once
    chatInput.addEventListener("input", renderSuggest);
    chatInput.addEventListener("keydown", onChatKeydownSuggest);
    // Outside-click closer. blur would also work but selecting a row
    // steals focus from the textarea before the click registers, closing
    // the popup prematurely; document-level click sidesteps that.
    document.addEventListener("click", onDocClickMaybeCloseSuggest);
  }

  async function sendMessage() {
    const text = chatInput.value.trim();
    if (!text || isStreaming) return;

    // ─── Slash command interception ────────────────────────────────
    //   /plan <topic>, /research <q>, /summary <text>     → switch agent + seed input
    //   /model groq/llama-3.1-8b-instant                 → swap provider/model + confirm
    //   /provider ollama                                 → swap provider + confirm
    //   /foobar <stuff>                                  → forward as plain chat + warning
    //   anything else                                    → plain chat
    if (typeof MKOSlash !== "undefined" && MKOSlash.parse) {
      const cmd = MKOSlash.parse(text);
      if (cmd && cmd.type === "unknown") {
        appendSystemMessage(
          `⚠️ Unknown slash command: /${cmd.cmd}. Sent as a regular chat message.`
        );
        // fall through to send
      } else if (cmd && cmd.type && cmd.type !== "unknown") {
        const handled = handleSlashCommand(cmd);
        if (handled !== false) {
          // Slash command was handled; do NOT call /api/chat.
          chatInput.value = "";
          return;
        }
        // handler chose to fall through (rare — e.g., parsed but no actionable state)
      }
    }

    chatInput.value = "";
    isStreaming = true;
    sendBtn.classList.add("hidden");
    stopBtn.classList.remove("hidden");

    // Remove welcome message
    const welcome = chatMessages.querySelector(".welcome-message");
    if (welcome) welcome.remove();

    // Add user message
    appendMessage("user", text);

    // Add assistant message placeholder
    const assistantDiv = document.createElement("div");
    assistantDiv.className = "message assistant";
    assistantDiv.innerHTML = `
      <div class="msg-avatar">🤖</div>
      <div class="msg-bubble">
        <div class="msg-content"><span class="typing-cursor">▊</span></div>
      </div>
    `;
    chatMessages.appendChild(assistantDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    const contentDiv = assistantDiv.querySelector(".msg-content");
    const bubble = assistantDiv.querySelector(".msg-bubble");

    // Clear previous abort
    if (abortController) abortController.abort();
    abortController = new AbortController();

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [{ role: "user", content: text }],
          model: currentModel || undefined,
          provider: currentProvider,
          temperature: 0.7,
          username: "demo",
          agent_type: currentAgent,
        }),
        signal: abortController.signal,
      });

      if (!res.ok) {
        const err = await res.json();
        contentDiv.innerHTML = `<span class="msg-error">❌ ${err.detail || "Request failed"}</span>`;
        isStreaming = false;
        sendBtn.classList.remove("hidden");
        stopBtn.classList.add("hidden");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let fullResponse = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") continue;

          try {
            const event = JSON.parse(data);
            switch (event.type) {
              case "token":
                fullResponse += event.content;
                contentDiv.innerHTML = renderMarkdown(fullResponse);
                chatMessages.scrollTop = chatMessages.scrollHeight;
                break;

              case "info":
                contentDiv.innerHTML = `<em>${event.content}</em>`;
                break;

              case "moe_debug":
                appendMoeDebug(bubble, event.content);
                break;

              case "error":
                contentDiv.innerHTML = `<span class="msg-error">❌ ${event.content}</span>`;
                break;
            }
          } catch (e) {
            /* ignore parse errors */
          }
        }
      }

      // Add timestamp
      const timeEl = document.createElement("div");
      timeEl.className = "msg-time";
      timeEl.textContent = new Date().toLocaleTimeString();
      bubble.appendChild(timeEl);

      loadCredits();
    } catch (e) {
      if (e.name !== "AbortError") {
        contentDiv.innerHTML = `<span class="msg-error">❌ Connection error</span>`;
      }
    }

    isStreaming = false;
    sendBtn.classList.remove("hidden");
    stopBtn.classList.add("hidden");
  }

  function stopStreaming() {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
  }

  // ─── MoE Debug ──────────────────────────────────────────────────────

  function appendMoeDebug(bubble, debugData) {
    const details = debugData.details || [];
    const weights = debugData.weights || {};
    const gateInput = debugData.gate_input_tokens || 0;
    const gateOutput = debugData.gate_output_tokens || 0;
    const totalExpertTokens = details.reduce((s, d) => s + (d.tokens || 0), 0);
    const totalTokens = totalExpertTokens + gateInput + gateOutput;
    const moeCost = Math.max(Object.keys(weights).length * 3, 1);
    const savingsPercent = totalTokens > 0
      ? Math.round((1 - (totalTokens) / (totalTokens + gateInput)) * 100)
      : 0;

    let html = `<div class="moe-debug-panel">
      <div class="moe-debug-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
        🔀 MoE Debug — ${details.length} Experts
        <span class="moe-toggle">▼</span>
      </div>
      <div class="moe-debug-body">`;

    details.forEach((d) => {
      const pct = gateInput > 0
        ? Math.round(((d.tokens || 0) / totalExpertTokens) * 100)
        : 0;
      html += `
        <div class="moe-expert-card">
          <div class="moe-expert-title">${d.provider}</div>
          <div class="moe-expert-stats">
            <span>⏱ ${d.time_ms}ms</span>
            <span>📝 ${d.tokens || 0} tokens (${pct}%)</span>
            <span>⚖️ weight ${d.weight}x</span>
          </div>
          <pre class="moe-expert-response">${escapeHtml(d.response || "(empty)")}</pre>
        </div>`;
    });

    html += `
        <div class="moe-cost-summary">
          <strong>💰 Token Cost Analysis</strong>
          <div class="cost-row">
            <span>Expert tokens:</span><span>${totalExpertTokens}</span>
          </div>
          <div class="cost-row">
            <span>Gate input tokens:</span><span>${gateInput}</span>
          </div>
          <div class="cost-row">
            <span>Gate output tokens:</span><span>${gateOutput}</span>
          </div>
          <div class="cost-row total">
            <span>Total MoE tokens:</span><span>${totalTokens}</span>
          </div>
          <div class="cost-row savings">
            <span>Estimated savings vs single model:</span><span>~${savingsPercent}%</span>
          </div>
          <div class="cost-row">
            <span>Credit cost:</span><span>${moeCost} credits (${details.length} experts × 3)</span>
          </div>
        </div>
      </div>
    </div>`;

    bubble.insertAdjacentHTML("beforeend", html);
    // Inject the inline-SVG Agent DAG canvas at the top of every
    // .moe-debug-body that this panel produced. Pure layout + SVG
    // renderer live in MKOGraph (moe-graph.js); this is the only
    // DOM glue. Skips the inject when there are zero experts.
    renderMoEDAG(bubble, debugData);
  }

  // ─── Agent DAG canvas (inline SVG) ────────────────────────────────────
  //
  // Injects the inline-SVG Agent DAG canvas at the top of every
  // .moe-debug-body that the most-recent appendMoeDebug produced.
  // Pure layout + SVG renderer live in MKOGraph (moe-graph.js); this
  // helper is the only DOM glue. Skips the inject when there are zero
  // experts (= computeMoEGraphLayout returns null per design).
  //
  // Defensive: also skips when a `.moe-dag` already exists inside the
  // body so streaming-event replays don't stack two DAGs on top of
  // each other.

  function renderMoEDAG(bubble, debugData) {
    if (typeof MKOGraph === "undefined" ||
        !MKOGraph.computeMoEGraphLayout) return;
    var layout = MKOGraph.computeMoEGraphLayout(debugData);
    if (!layout) return;                          // empty / null details
    var svg = MKOGraph.renderMoEGraphSVG(layout);
    if (!svg) return;
    var bodies = bubble.querySelectorAll(".moe-debug-body");
    Array.prototype.forEach.call(bodies, function (body) {
      if (body.querySelector(".moe-dag")) return;  // already injected
      var wrap = document.createElement("div");
      wrap.className = "moe-dag-wrap";
      wrap.innerHTML = svg;
      body.insertBefore(wrap, body.firstChild || null);
    });
  }


  // ─── Append Message ─────────────────────────────────────────────────

  // ─── Slash command handler ────────────────────────────────────────
  //
  // Called from sendMessage() when MKOSlash.parse() returns a known type.
  // Each branch mutates UI state (selectAgent(), modelSelect.value, etc.)
  // and emits a ⚙️ system message.  Returns false to fall through to plain
  // chat, true to signal "slash command consumed, don't POST /api/chat".

  function handleSlashCommand(cmd) {
    switch (cmd.type) {
      case "plan":
        selectAgent("planner");
        chatInput.value = cmd.topic;
        renderSuggest();                  // sync autocompleter to new value
        chatInput.focus();
        appendSystemMessage(
          `✓ Switched to Planner · topic: "${cmd.topic}". ` +
          `Edit if you like, then press Enter to send.`
        );
        return true;
      case "research":
        selectAgent("research");
        chatInput.value = cmd.query;
        renderSuggest();                  // sync autocompleter to new value
        chatInput.focus();
        appendSystemMessage(
          `✓ Switched to Researcher · query: "${cmd.query}". ` +
          `Edit if you like, then press Enter to send.`
        );
        return true;
      case "summary":
        if (currentAgent !== "general") selectAgent("general");
        chatInput.value = cmd.text;
        renderSuggest();                  // sync autocompleter to new value
        chatInput.focus();
        appendSystemMessage(
          `✓ Switched to General · summary text: "${truncate(cmd.text, 60)}". ` +
          `Edit if you like, then press Enter to send.`
        );
        return true;
      case "help":
        // Multi-line system message; use the block variant.
        appendSystemBlock(MKOSlash.formatHelp(cmd));
        return true;
      case "model":
        currentProvider = cmd.provider;
        providerSelect.value = currentProvider;
        currentModel = cmd.model || "";
        // Refresh the model dropdown, then sync it (and the bottom badge)
        // once /api/models returns.
        loadModels().then(() => {
          if (currentModel) {
            // If the model is already in the dropdown, select it; else
            // leave "Default" selected — the chat will still send the
            // typed model name because the body carries `currentModel`.
            const found = Array.from(modelSelect.options).some(
              (o) => o.value === currentModel
            );
            modelSelect.value = found ? currentModel : "";
          }
          updateModelInfo();
        });
        appendSystemMessage(
          MKOSlash.formatConfirmation(cmd) ||
            `✓ Switched model → ${cmd.provider}${cmd.model ? " / " + cmd.model : ""}`
        );
        return true;
      case "provider":
        currentProvider = cmd.provider;
        providerSelect.value = currentProvider;
        currentModel = "";
        loadModels().then(() => {
          modelSelect.value = "";
          updateModelInfo();
        });
        appendSystemMessage(
          MKOSlash.formatConfirmation(cmd) ||
            `✓ Switched provider → ${cmd.provider}`
        );
        return true;
      case "empty":
        appendSystemMessage(
          `ℹ️ Slash with no command. Try /plan <topic> or /model <provider>.`
        );
        return true;
      case "plan_empty":
        selectAgent("planner");
        appendSystemMessage(
          `✓ Switched to Planner. Type your topic and press Enter.`
        );
        return true;
      case "research_empty":
        selectAgent("research");
        appendSystemMessage(
          `✓ Switched to Researcher. Type your query and press Enter.`
        );
        return true;
      case "summary_empty":
        selectAgent("general");
        appendSystemMessage(
          `✓ Switched to General. Type the text to summarize and press Enter.`
        );
        return true;
      case "model_empty":
        appendSystemMessage(
          `ℹ️ /model needs a provider or provider/model. ` +
          `Try: /model ollama  or  /model groq/llama-3.1-8b-instant.`
        );
        return true;
      case "provider_empty":
        appendSystemMessage(
          `ℹ️ /provider needs a provider name. ` +
          `Try: /provider ollama  /provider groq  /provider huggingface.`
        );
        return true;
      case "model_unknown_provider":
        appendSystemMessage(
          `⚠️ Unknown provider "${cmd.provider}". ` +
          `Known: ${MKOSlash.KNOWN_PROVIDERS.join(", ")}.`
        );
        return true;
      case "provider_unknown":
        appendSystemMessage(
          `⚠️ Unknown provider "${cmd.provider}". ` +
          `Known: ${MKOSlash.KNOWN_PROVIDERS.join(", ")}.`
        );
        return true;
      default:
        return false;
    }
  }

  function truncate(s, n) {
    if (!s) return "";
    return s.length > n ? s.slice(0, n - 1) + "\u2026" : s;
  }

  // ─── System message helper ───────────────────────────────────────
  // Renders a one-line ⚙️ note into the chat stream — distinct from user
  // and assistant bubbles so history of state changes stays readable.

  function appendSystemMessage(text) {
    const div = document.createElement("div");
    div.className = "message system";
    div.style.cssText =
      "opacity: 0.92; background: rgba(255,255,255,0.04); border-left: 3px solid #8b8bff;";
    div.innerHTML = `
      <div class="msg-avatar">⚙️</div>
      <div class="msg-bubble">
        <div class="msg-content" style="font-style: italic;">${escapeHtml(text)}</div>
        <div class="msg-time">${new Date().toLocaleTimeString()}</div>
      </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // ─── Multi-line system message helper ─────────────────────────────
  // For /help (and future block-form output). Same visual chrome as
  // appendSystemMessage (⚙️ avatar, italic styling, purple left border),
  // but renders lines as <br>-separated HTML so multi-line text doesn't
  // collapse. Intentionally uses escapeHtml — same contract as the
  // one-line variant; do NOT switch to renderMarkdown without rethinking
  // what users could paste into a /help response.

  function appendSystemBlock(text) {
    const div = document.createElement("div");
    div.className = "message system";
    div.style.cssText =
      "opacity: 0.92; background: rgba(255,255,255,0.04); border-left: 3px solid #8b8bff;";
    const html = text.split("\n").map(escapeHtml).join("<br>");
    div.innerHTML = `
      <div class="msg-avatar">⚙️</div>
      <div class="msg-bubble">
        <div class="msg-content" style="font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 0.92em; line-height: 1.45;">${html}</div>
        <div class="msg-time">${new Date().toLocaleTimeString()}</div>
      </div>
    `;
    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function appendMessage(role, content) {
    const div = document.createElement("div");
    div.className = `message ${role}`;

    const avatar = role === "user" ? "👤" : "🤖";

    div.innerHTML = `
      <div class="msg-avatar">${avatar}</div>
      <div class="msg-bubble">
        <div class="msg-content">${renderMarkdown(content)}</div>
        <div class="msg-time">${new Date().toLocaleTimeString()}</div>
      </div>
    `;

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  // ─── Markdown Renderer ──────────────────────────────────────────────

  function renderMarkdown(text) {
    if (!text) return "";
    let html = escapeHtml(text);

    // Placeholder tokens to protect code content from bold/italic matching
    const codeBlocks = [];
    const inlineCodes = [];

    // Protect fenced code blocks (```...```)
    html = html.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
      const idx = codeBlocks.length;
      codeBlocks.push(`<pre><code class="lang-${lang || "none"}">${code.trim()}</code></pre>`);
      return `%%CODEBLOCK_${idx}%%`;
    });

    // Protect inline code (`...`)
    html = html.replace(/`([^`]+)`/g, (_, code) => {
      const idx = inlineCodes.length;
      inlineCodes.push(`<code>${code}</code>`);
      return `%%INLINECODE_${idx}%%`;
    });

    // Bold (safe now — code is protected behind placeholders)
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

    // Italic
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");

    // Line breaks
    html = html.replace(/\n/g, "<br>");

    // Restore code blocks
    html = html.replace(/%%CODEBLOCK_(\d+)%%/g, (_, idx) => codeBlocks[parseInt(idx)]);

    // Restore inline code
    html = html.replace(/%%INLINECODE_(\d+)%%/g, (_, idx) => inlineCodes[parseInt(idx)]);

    return html;
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  // ─── Settings ───────────────────────────────────────────────────────

  function wireSettings() {
    settingsToggle.addEventListener("click", () => {
      settingsPanel.classList.toggle("open");
    });

    providerSelect.addEventListener("change", () => {
      currentProvider = providerSelect.value;
      loadModels();
      updateModelInfo();
    });

    modelSelect.addEventListener("change", () => {
      currentModel = modelSelect.value;
      updateModelInfo();
    });

    $("#saveSettings").addEventListener("click", async () => {
      const apiKeys = {};
      const groqKey = $("#groqKey").value.trim();
      const hfKey = $("#hfKey").value.trim();
      const openaiKey = $("#openaiKey").value.trim();
      const anthropicKey = $("#anthropicKey").value.trim();
      if (groqKey) apiKeys.groq = groqKey;
      if (hfKey) apiKeys.huggingface = hfKey;
      if (openaiKey) apiKeys.openai = openaiKey;
      if (anthropicKey) apiKeys.anthropic = anthropicKey;

      const statusEl = $("#settingsStatus");
      try {
        const res = await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider: currentProvider,
            model: currentModel,
            api_keys: Object.keys(apiKeys).length > 0 ? apiKeys : undefined,
          }),
        });
        const data = await res.json();
        if (data.status === "ok") {
          statusEl.textContent = "✅ Saved!";
          statusEl.className = "settings-status success";
          // Clear password fields (keys are saved)
          $("#groqKey").value = "";
          // Update placeholders
          if (groqKey) $("#groqKey").placeholder = "✓ Configured";
          if (hfKey) $("#hfKey").placeholder = "✓ Configured";
          if (openaiKey) $("#openaiKey").placeholder = "✓ Configured";
          if (anthropicKey) $("#anthropicKey").placeholder = "✓ Configured";
        }
      } catch (e) {
        statusEl.textContent = "❌ Failed to save";
        statusEl.className = "settings-status";
      }
      setTimeout(() => { statusEl.textContent = ""; }, 3000);
    });
  }

  function updateModelInfo() {
    currentModelInfo.textContent = `${currentProvider} / ${currentModel || "default"}`;
  }

  // ─── Panel Management ───────────────────────────────────────────────

  function wirePanels() {
    // Tool buttons open panels
    document.querySelectorAll(".tool-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tool = btn.dataset.tool;
        const panelId = {
          benchmark: "benchmarkPanel",
          "provider-bench": "providerBenchPanel",
          "moe-config": "moeConfigPanel",
          rag: "ragPanel",
        }[tool];
        if (panelId) openPanel(panelId);
      });
    });

    // Close buttons
    document.querySelectorAll(".panel-close").forEach((btn) => {
      btn.addEventListener("click", () => {
        btn.closest(".panel").classList.remove("open");
      });
    });
  }

  function openPanel(panelId) {
    // Close all panels
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("open"));
    const panel = document.getElementById(panelId);
    if (panel) panel.classList.add("open");
  }

  // ─── Welcome Agent Cards ────────────────────────────────────────────

  function wireWelcomeAgents() {
    // Already handled in renderWelcomeCards
  }

  // ─── Benchmark (Compute) ────────────────────────────────────────────

  function wireBenchmarks() {
    $("#runBenchmarkBtn").addEventListener("click", runComputeBenchmark);
    $("#runProviderBenchBtn").addEventListener("click", runProviderBenchmark);
  }

  async function runComputeBenchmark() {
    const btn = $("#runBenchmarkBtn");
    const progress = $("#benchmarkProgress");
    const fill = $("#benchProgressFill");
    const label = $("#benchProgressLabel");
    const results = $("#benchmarkResults");

    btn.disabled = true;
    btn.textContent = "⏳ Running...";
    progress.classList.remove("hidden");
    results.classList.add("hidden");
    fill.style.width = "0%";

    try {
      const res = await fetch("/api/benchmark/run");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();

          try {
            const event = JSON.parse(data);

            switch (event.type) {
              case "progress":
                fill.style.width = `${event.value}%`;
                label.textContent = event.label;
                break;

              case "benchmark_result":
                lastComputeBenchResult = event.data;
                renderBenchmarkResults(event.data, results);
                break;
            }
          } catch (e) {
            /* ignore */
          }
        }
      }
    } catch (e) {
      label.textContent = "❌ Benchmark failed";
    }

    btn.disabled = false;
    btn.textContent = "▶ Run Benchmark";
    progress.classList.add("hidden");
  }

  function renderBenchmarkResults(data, container) {
    container.classList.remove("hidden");
    const gpuInfo = data.gpu_name
      ? `<div class="bench-gpu">GPU: ${data.gpu_name} (${data.gpu_memory_gb} GB)</div>`
      : "";
    const hasGpu = data.backend !== "cpu";

    let tableRows = "";
    if (data.matrix_results) {
      data.matrix_results.forEach((r) => {
        const gpuCell = r.gpu_ms ? `${r.gpu_ms}ms` : "N/A";
        const speedup = r.speedup ? `${r.speedup}x` : "-";
        tableRows += `
          <tr>
            <td>${r.size}x${r.size}</td>
            <td>${r.cpu_ms}ms</td>
            <td>${gpuCell}</td>
            <td>${speedup}</td>
          </tr>`;
      });
    }

    container.innerHTML = `
      <div class="bench-header">
        <h4>📊 Compute Benchmark Results</h4>
        <div class="bench-meta">Backend: <strong>${data.backend}</strong> | Tokens/sec (est): <strong>${data.llm_est_tokens_per_sec}</strong></div>
        ${gpuInfo}
      </div>
      <div class="bench-table-wrapper">
        <table class="bench-table">
          <thead>
            <tr><th>Matrix</th><th>CPU</th><th>GPU</th><th>Speedup</th></tr>
          </thead>
          <tbody>${tableRows}</tbody>
        </table>
      </div>
      <div class="bench-footer">
        <span class="bench-avg-speedup">⚡ Avg Speedup: <strong>${data.avg_speedup}x</strong></span>
        <button id="downloadBenchmarkBtn" class="benchmark-download-btn">⬇ JSON</button>
        <button id="rerunBenchmarkBtn" class="benchmark-rerun-btn">🔄 Rerun</button>
      </div>
    `;

    const rerunBtn = container.querySelector("#rerunBenchmarkBtn");
    if (rerunBtn) rerunBtn.addEventListener("click", runComputeBenchmark);

    const downloadBtn = container.querySelector("#downloadBenchmarkBtn");
    if (downloadBtn) downloadBtn.addEventListener("click", downloadBenchmarkResults);
  }

  // ─── Provider Latency Benchmark ─────────────────────────────────────

  async function runProviderBenchmark() {
    const btn = $("#runProviderBenchBtn");
    const progress = $("#providerBenchProgress");
    const fill = $("#providerBenchProgressFill");
    const label = $("#providerBenchLabel");
    const results = $("#providerBenchResults");

    btn.disabled = true;
    btn.textContent = "⏳ Running...";
    progress.classList.remove("hidden");
    results.classList.add("hidden");
    fill.style.width = "0%";

    try {
      const res = await fetch("/api/benchmark/providers");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();

          try {
            const event = JSON.parse(data);
            switch (event.type) {
              case "progress":
                fill.style.width = `${event.value}%`;
                label.textContent = event.label;
                break;
              case "provider_benchmark_result":
                lastProviderBenchResults = event.data;
                renderProviderBenchResults(event.data, results);
                break;
            }
          } catch (e) {
            /* ignore */
          }
        }
      }
    } catch (e) {
      label.textContent = "❌ Benchmark failed";
    }

    btn.disabled = false;
    btn.textContent = "▶ Run Test";
    progress.classList.add("hidden");
  }

  function renderProviderBenchResults(data, container) {
    container.classList.remove("hidden");

    const rows = data
      .map((r) => {
        const isOk = r.status === "ok";
        const name = r.provider.charAt(0).toUpperCase() + r.provider.slice(1);
        const timeCol = isOk
          ? `${r.time_to_first_token_ms}ms / ${r.total_time_ms}ms`
          : `<span class="bench-error">❌ ${r.error || "Failed"}</span>`;
        return `
          <tr>
            <td>${name}</td>
            <td>${r.model}</td>
            <td>${isOk ? "✅" : "❌"}</td>
            <td>${timeCol}</td>
          </tr>
        `;
      })
      .join("");

    container.innerHTML = `
      <div class="bench-header">
        <h4>⚡ Provider Latency Results</h4>
        <div class="bench-meta">Time-to-first-token / Total time (lower is better)</div>
      </div>
      <div class="bench-table-wrapper">
        <table class="bench-table">
          <thead>
            <tr><th>Provider</th><th>Model</th><th>Status</th><th>Latency</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      <div class="bench-footer">
        <button id="downloadProviderBenchBtn" class="benchmark-download-btn">⬇ JSON</button>
        <button id="rerunProviderBenchBtn" class="benchmark-rerun-btn">🔄 Rerun</button>
      </div>
    `;

    const rerunBtn = container.querySelector("#rerunProviderBenchBtn");
    if (rerunBtn) rerunBtn.addEventListener("click", runProviderBenchmark);

    const downloadBtn = container.querySelector("#downloadProviderBenchBtn");
    if (downloadBtn) downloadBtn.addEventListener("click", downloadBenchmarkResults);
  }

  // ─── Download Benchmark Results ─────────────────────────────────────

  function wireDownloadBenchmarkButtons() {
    // Dynamic buttons are wired when rendered; this is a safety net for existing buttons
  }

  function downloadBenchmarkResults() {
    const payload = {
      exported_at: new Date().toISOString(),
      compute_benchmark: lastComputeBenchResult,
      provider_latency_benchmark: lastProviderBenchResults,
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `mko-benchmark-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ─── MoE Config ─────────────────────────────────────────────────────

  function wireMoeConfig() {
    const tempSlider = $("#moeTemp");
    const tempVal = $("#moeTempVal");

    tempSlider.addEventListener("input", () => {
      tempVal.textContent = tempSlider.value;
    });

    // Load existing config
    fetch("/api/moe/config")
      .then((r) => r.json())
      .then((cfg) => {
        if (cfg.experts) {
          document.querySelectorAll("#moeExpertCheckboxes input").forEach((cb) => {
            cb.checked = cfg.experts.includes(cb.value);
          });
        }
        if (cfg.synthesis_temperature != null) {
          tempSlider.value = cfg.synthesis_temperature;
          tempVal.textContent = cfg.synthesis_temperature;
        }
      })
      .catch(() => {});

    $("#saveMoeConfig").addEventListener("click", async () => {
      const experts = [];
      document.querySelectorAll("#moeExpertCheckboxes input:checked").forEach((cb) => {
        experts.push(cb.value);
      });

      const weights = {};
      experts.forEach((e) => {
        const weightInput = prompt(`Weight for ${e} (default: 1.0):`, "1.0");
        weights[e] = parseFloat(weightInput) || 1.0;
      });

      const statusEl = $("#moeConfigStatus");
      try {
        const res = await fetch("/api/moe/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            experts,
            weights,
            synthesis_temperature: parseFloat(tempSlider.value),
          }),
        });
        const data = await res.json();
        statusEl.textContent = data.status === "ok" ? "✅ MoE config saved!" : "❌ Failed";
        statusEl.className = "settings-status success";
      } catch (e) {
        statusEl.textContent = "❌ Failed to save";
        statusEl.className = "settings-status";
      }
      setTimeout(() => { statusEl.textContent = ""; }, 3000);
    });
  }

  // ─── RAG Upload ─────────────────────────────────────────────────────

  function wireRag() {
    const dropzone = $("#ragDropzone");
    const fileInput = $("#ragFileInput");
    const statusEl = $("#ragStatus");

    dropzone.addEventListener("click", () => fileInput.click());

    dropzone.addEventListener("dragover", (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    });

    dropzone.addEventListener("dragleave", () => {
      dropzone.classList.remove("drag-over");
    });

    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        uploadRagFile(files[0]);
      }
    });

    fileInput.addEventListener("change", () => {
      if (fileInput.files.length > 0) {
        uploadRagFile(fileInput.files[0]);
      }
    });

    // Load existing collections
    loadRagCollections();
  }

  async function loadRagCollections() {
    try {
      const res = await fetch("/api/rag/collections?username=demo");
      const data = await res.json();
      const container = $("#ragCollections");
      if (data.collections && data.collections.length > 0) {
        container.innerHTML = `
          <div class="rag-collections-header">📚 Uploaded Collections</div>
          ${data.collections
            .map(
              (c) => `
            <div class="rag-collection-item">
              <span>${c.name.slice(0, 40)}...</span>
              <span class="rag-chunk-count">${c.count} chunks</span>
            </div>
          `
            )
            .join("")}
        `;
      } else {
        container.innerHTML = `<div class="rag-empty">No documents uploaded yet.</div>`;
      }
    } catch (e) {
      /* ignore */
    }
  }

  async function uploadRagFile(file) {
    const statusEl = $("#ragStatus");
    const allowed = [".txt", ".md", ".json", ".csv"];
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();

    if (!allowed.includes(ext)) {
      statusEl.textContent = "❌ Unsupported file type. Use .txt, .md, .json, or .csv";
      statusEl.className = "rag-status error";
      return;
    }

    statusEl.textContent = `📤 Uploading ${file.name}...`;
    statusEl.className = "rag-status";

    const formData = new FormData();
    formData.append("file", file);
    formData.append("username", "demo");

    try {
      const res = await fetch("/api/rag/ingest", {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (data.status === "ok") {
        statusEl.textContent = `✅ Indexed ${data.chunks} chunks from ${file.name}`;
        statusEl.className = "rag-status success";
        loadRagCollections();
      } else {
        statusEl.textContent = `❌ ${data.message || "Upload failed"}`;
        statusEl.className = "rag-status error";
      }
    } catch (e) {
      statusEl.textContent = `❌ Upload error: ${e.message}`;
      statusEl.className = "rag-status error";
    }
  }

  // ─── Init on DOM ready ──────────────────────────────────────────────

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

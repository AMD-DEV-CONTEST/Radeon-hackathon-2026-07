/**
 * Insurance Q&A Agent frontend logic
 *
 * Features:
 * - Consumes the POST SSE stream (/api/chat/stream) via fetch + ReadableStream
 * - Displays the TriggerFlow 5-step pipeline progress in real time
 * - Markdown rendering (marked.js CDN)
 * - Collapsible citations panel
 * - Session management
 * - Toast error notifications
 */

(function () {
  "use strict";

  // ── DOM element references ──
  const messageList = document.getElementById("messageList");
  const messageInput = document.getElementById("messageInput");
  const sendBtn = document.getElementById("sendBtn");
  const sessionList = document.getElementById("sessionList");
  const sessionEmpty = document.getElementById("sessionEmpty");
  const newSessionBtn = document.getElementById("newSessionBtn");
  const healthBtn = document.getElementById("healthBtn");
  const pipelinePanel = document.getElementById("pipelinePanel");
  const pipelineStages = document.getElementById("pipelineStages");
  const welcomeScreen = document.getElementById("welcomeScreen");
  const toastContainer = document.getElementById("toastContainer");

  // ── State ──
  let isProcessing = false;
  let currentSessionId = "default";
  let abortController = null;

  // ── Configure marked.js ──
  if (typeof marked !== "undefined") {
    marked.setOptions({
      breaks: true,
      gfm: true,
    });
  }

  // ════════════════════════════════════════
  //  Utility functions
  // ════════════════════════════════════════

  /**
   * Toast notification
   * @param {string} message - Message content
   * @param {"error"|"success"|"info"} type - Type
   */
  function showToast(message, type = "info") {
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.classList.add("fade-out");
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  /** Auto-scroll to the latest message */
  function scrollToBottom() {
    requestAnimationFrame(() => {
      messageList.scrollTop = messageList.scrollHeight;
    });
  }

  /** Adjust the input box height */
  function autoResize() {
    messageInput.style.height = "auto";
    messageInput.style.height = Math.min(messageInput.scrollHeight, 140) + "px";
  }

  /**
   * Escape HTML special characters
   * @param {string} text
   * @returns {string}
   */
  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Replace the [1] [2] numbered markers in the answer with clickable citation links
   * Note: the backend pipeline.py has already replaced [[ref:e1]] with the [1] format;
   * here we render it as an <a> hyperlink that expands the corresponding source card
   * in the citations panel when clicked.
   * @param {string} html - Rendered HTML
   * @returns {string}
   */
  function renderCitationRefs(html) {
    return html.replace(
      /\[(\d+)\]/g,
      '<a class="citation-ref" data-num="$1" href="#ref-$1">[$1]</a>'
    );
  }

  /**
   * Render Markdown text
   * @param {string} text
   * @returns {string}
   */
  function renderMarkdown(text) {
    if (typeof marked !== "undefined") {
      try {
        return renderCitationRefs(marked.parse(text));
      } catch (e) {
        console.warn("Markdown rendering failed:", e);
      }
    }
    return renderCitationRefs(escapeHtml(text).replace(/\n/g, "<br>"));
  }

  // ════════════════════════════════════════
  //  Message rendering
  // ════════════════════════════════════════

  /**
   * Add a message to the list
   * @param {"user"|"assistant"} role
   * @param {string} content
   * @param {object} [options]
   * @returns {HTMLElement} Message element
   */
  function addMessage(role, content, options = {}) {
    // Hide the welcome screen
    if (welcomeScreen) {
      welcomeScreen.style.display = "none";
    }

    const messageEl = document.createElement("div");
    messageEl.className = `message ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = role === "user" ? "You" : "AI";

    const contentEl = document.createElement("div");
    contentEl.className = "message-content";

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    if (role === "user") {
      bubble.textContent = content;
    } else {
      bubble.innerHTML = renderMarkdown(content);
    }

    contentEl.appendChild(bubble);

    // Status badge
    if (options.status) {
      const badge = document.createElement("span");
      badge.className = `status-badge ${options.status}`;
      const statusText = {
        completed: "Completed",
        partial: "Partial",
        blocked: "Blocked",
        failed: "Failed",
      };
      badge.textContent = statusText[options.status] || options.status;
      contentEl.appendChild(badge);
    }

    // Citations panel
    if (role === "assistant" && options.citations && options.citations.length > 0) {
      const citationsPanel = createCitationsPanel(
        options.citations,
        options.source_details
      );
      contentEl.appendChild(citationsPanel);
    }

    // Bind click events for citation links
    if (role === "assistant") {
      bubble.querySelectorAll(".citation-ref").forEach((ref) => {
        ref.addEventListener("click", (e) => {
          e.preventDefault();
          const num = ref.getAttribute("data-num");
          const card = contentEl.querySelector(`.citation-card[data-num="${num}"]`);
          if (card) {
            // Expand the citations panel (if collapsed)
            const list = card.parentElement;
            if (list && !list.classList.contains("show")) {
              list.classList.add("show");
              const toggle = list.parentElement.querySelector(".citations-toggle");
              if (toggle) toggle.classList.add("expanded");
            }
            // Highlight the target card and scroll
            card.classList.add("highlight");
            card.scrollIntoView({ behavior: "smooth", block: "nearest" });
            setTimeout(() => card.classList.remove("highlight"), 2000);
          }
        });
      });
    }

    messageEl.appendChild(avatar);
    messageEl.appendChild(contentEl);
    messageList.appendChild(messageEl);
    scrollToBottom();
    return messageEl;
  }

  /**
   * Create a collapsible citations panel
   * @param {Array} citations - Citation list (with ref_id, quoted_text)
   * @param {Array} [sourceDetails] - Source details (with num, title, snippet, source)
   * @returns {HTMLElement}
   */
  function createCitationsPanel(citations, sourceDetails) {
    const panel = document.createElement("div");
    panel.className = "citations-panel";

    const toggle = document.createElement("div");
    toggle.className = "citations-toggle";
    toggle.innerHTML =
      '<span class="arrow">&#9654;</span>' +
      `Citations (${citations.length})`;

    const list = document.createElement("div");
    list.className = "citations-list";

    // Build a mapping from number → source_details
    const detailMap = {};
    if (sourceDetails && sourceDetails.length > 0) {
      sourceDetails.forEach((sd) => {
        if (sd.num) detailMap[sd.num] = sd;
      });
    }

    citations.forEach((c, idx) => {
      const num = idx + 1;
      const detail = detailMap[num] || {};
      const card = document.createElement("div");
      card.className = "citation-card";
      card.setAttribute("data-num", num);
      card.setAttribute("id", `ref-${num}`);

      // Title line: [num] document title · paragraph title
      const titleLine = document.createElement("div");
      titleLine.className = "citation-title";
      titleLine.textContent = `[${num}] ${detail.title || c.ref_id || "Source"}`;

      // Original quoted snippet
      const snippetText = detail.snippet || c.quoted_text || c.text || "";
      const snippetEl = document.createElement("div");
      snippetEl.className = "quoted-text";
      snippetEl.textContent = snippetText;

      card.appendChild(titleLine);
      card.appendChild(snippetEl);
      list.appendChild(card);
    });

    toggle.addEventListener("click", () => {
      toggle.classList.toggle("expanded");
      list.classList.toggle("show");
    });

    panel.appendChild(toggle);
    panel.appendChild(list);
    return panel;
  }

  /** Show the typing indicator */
  function showTypingIndicator() {
    const el = document.createElement("div");
    el.className = "message assistant";
    el.id = "typingIndicator";
    el.innerHTML =
      '<div class="message-avatar">AI</div>' +
      '<div class="message-content">' +
      '<div class="bubble"><div class="typing-indicator">' +
      "<span></span><span></span><span></span>" +
      "</div></div></div>";
    messageList.appendChild(el);
    scrollToBottom();
  }

  /** Remove the typing indicator */
  function removeTypingIndicator() {
    const el = document.getElementById("typingIndicator");
    if (el) el.remove();
  }

  // ════════════════════════════════════════
  //  Pipeline stage indicator
  // ════════════════════════════════════════

  /** Show the pipeline panel */
  function showPipeline() {
    // Reset all stage states
    pipelineStages.querySelectorAll(".stage").forEach((s) => {
      s.classList.remove("started", "completed");
    });
    pipelineStages.querySelectorAll(".stage-connector").forEach((c) => {
      c.classList.remove("active");
    });
    pipelinePanel.hidden = false;
    scrollToBottom();
  }

  /** Hide the pipeline panel */
  function hidePipeline() {
    pipelinePanel.hidden = true;
  }

  /**
   * Update a stage's status
   * @param {string} stageKey - Stage key
   * @param {"started"|"completed"} status
   */
  function updateStage(stageKey, status) {
    const stageEl = pipelineStages.querySelector(`.stage[data-stage="${stageKey}"]`);
    if (!stageEl) return;

    if (status === "started") {
      // Mark the previous stage as completed
      const prevStage = getPreviousStage(stageKey);
      if (prevStage && !pipelineStages.querySelector(`.stage[data-stage="${prevStage}"]`).classList.contains("completed")) {
        markStageCompleted(prevStage);
      }
      stageEl.classList.add("started");
      stageEl.classList.remove("completed");
    } else if (status === "completed") {
      markStageCompleted(stageKey);
    }
    scrollToBottom();
  }

  /** Mark a stage as completed and activate the connector */
  function markStageCompleted(stageKey) {
    const stageEl = pipelineStages.querySelector(`.stage[data-stage="${stageKey}"]`);
    if (!stageEl) return;
    stageEl.classList.remove("started");
    stageEl.classList.add("completed");
    // Activate the connector after this stage
    const connector = stageEl.nextElementSibling;
    if (connector && connector.classList.contains("stage-connector")) {
      connector.classList.add("active");
    }
  }

  /** Get the previous stage */
  function getPreviousStage(stageKey) {
    const stages = ["understand", "plan", "validate", "retrieve", "answer"];
    const idx = stages.indexOf(stageKey);
    return idx > 0 ? stages[idx - 1] : null;
  }

  /** Mark all stages as completed */
  function completeAllStages() {
    ["understand", "plan", "validate", "retrieve", "answer"].forEach((s) => {
      const el = pipelineStages.querySelector(`.stage[data-stage="${s}"]`);
      if (el && !el.classList.contains("completed")) {
        markStageCompleted(s);
      }
    });
  }

  // ════════════════════════════════════════
  //  SSE streaming chat
  // ════════════════════════════════════════

  /**
   * Parse an SSE data chunk
   * SSE format: "data: {...}\n\n"
   * @param {string} chunk
   * @returns {Array<object>} Parsed event list
   */
  function parseSSEChunk(chunk) {
    const events = [];
    const lines = chunk.split("\n");
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith("data:")) {
        const dataStr = trimmed.slice(5).trim();
        if (!dataStr) continue;
        try {
          events.push(JSON.parse(dataStr));
        } catch (e) {
          console.warn("SSE data parsing failed:", dataStr, e);
        }
      }
    }
    return events;
  }

  /**
   * Send a message and receive the response via the SSE stream
   * @param {string} message
   */
  async function sendMessage(message) {
    if (isProcessing || !message.trim()) return;

    isProcessing = true;
    sendBtn.disabled = true;
    messageInput.value = "";
    autoResize();

    // Add the user message
    addMessage("user", message);

    // Show the pipeline
    showPipeline();
    showTypingIndicator();

    // Abort controller
    abortController = new AbortController();

    let assistantEl = null;

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: message,
          session_id: currentSessionId,
        }),
        signal: abortController.signal,
      });

      if (!response.ok) {
        throw new Error(`Service returned ${response.status}: ${response.statusText}`);
      }

      removeTypingIndicator();

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = parseSSEChunk(buffer);
        buffer = "";

        for (const event of events) {
          handleSSEEvent(event);
        }

        // Create/update the assistant message when an answer event is received
        if (events.some((e) => e.type === "answer")) {
          const answerEvent = events.find((e) => e.type === "answer");
          if (answerEvent && !assistantEl) {
            assistantEl = addMessage("assistant", answerEvent.content, {
              citations: answerEvent.citations,
              source_details: answerEvent.source_details,
              status: answerEvent.status,
            });
          }
        }
      }

      // Process remaining data in the buffer
      if (buffer.trim()) {
        const remaining = parseSSEChunk(buffer);
        for (const event of remaining) {
          handleSSEEvent(event);
        }
      }
    } catch (err) {
      removeTypingIndicator();
      if (err.name === "AbortError") {
        showToast("Request cancelled", "info");
      } else {
        console.error("SSE streaming request failed:", err);
        showToast(`Request failed: ${err.message}`, "error");
        addMessage("assistant", `Sorry, an error occurred while processing your request: ${err.message}`, {
          status: "failed",
        });
      }
    } finally {
      completeAllStages();
      setTimeout(hidePipeline, 800);
      isProcessing = false;
      sendBtn.disabled = false;
      messageInput.focus();
      abortController = null;
      // Refresh the session list to update the latest topics and ordering
      loadSessions();
    }
  }

  /**
   * Handle a single SSE event
   * @param {object} event
   */
  function handleSSEEvent(event) {
    switch (event.type) {
      case "stage":
        if (event.stage === "pipeline") {
          // Pipeline started as a whole
          break;
        }
        updateStage(event.stage, event.status);
        break;

      case "answer":
        completeAllStages();
        break;

      case "error":
        showToast(event.message || "Processing error", "error");
        break;

      case "done":
        completeAllStages();
        break;
    }
  }

  // ════════════════════════════════════════
  //  Session management
  // ════════════════════════════════════════

  /**
   * Load the latest top-5 session list (including model-summarized topics)
   */
  async function loadSessions() {
    try {
      const response = await fetch(
        `/api/sessions?_t=${Date.now()}`
      );
      if (!response.ok) return;
      const data = await response.json();
      const sessions = data.sessions || [];
      renderSessionList(sessions);
    } catch (e) {
      // Fail silently; loading the session list does not affect core features
      console.debug("Failed to load session list:", e);
    }
  }

  /**
   * Render the session list (top 5 + topics)
   * @param {Array} sessions - [{session_id, topic, saved_at, message_count}]
   */
  function renderSessionList(sessions) {
    sessionList.innerHTML = "";
    if (!sessions || sessions.length === 0) {
      sessionList.appendChild(sessionEmpty);
      sessionEmpty.style.display = "";
      return;
    }

    sessionEmpty.style.display = "none";
    sessions.forEach((s) => {
      const item = document.createElement("div");
      item.className = "session-item";
      item.dataset.sessionId = s.session_id;
      item.setAttribute("role", "button");
      item.setAttribute("tabindex", "0");

      const topicEl = document.createElement("div");
      topicEl.className = "session-topic";
      topicEl.textContent = s.topic || s.session_id || "New chat";

      const metaEl = document.createElement("div");
      metaEl.className = "session-meta";
      if (s.saved_at) {
        const d = new Date(s.saved_at * 1000);
        const pad = (n) => String(n).padStart(2, "0");
        metaEl.textContent = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
      } else {
        metaEl.textContent = `${s.message_count || 0} messages`;
      }

      item.appendChild(topicEl);
      item.appendChild(metaEl);

      if (s.session_id === currentSessionId) {
        item.classList.add("active");
      }

      item.addEventListener("click", () => {
        currentSessionId = s.session_id;
        renderSessionList(sessions);
        loadSessionHistory(currentSessionId);
      });

      sessionList.appendChild(item);
    });
  }

  /**
   * Load the session history and display it
   * @param {string} sessionId
   */
  async function loadSessionHistory(sessionId) {
    try {
      const response = await fetch(`/api/sessions/${sessionId}/history`);
      if (!response.ok) return;
      const data = await response.json();

      // Clear the message list
      messageList.innerHTML = "";
      if (welcomeScreen) {
        welcomeScreen.style.display = "";
        messageList.appendChild(welcomeScreen);
      }

      if (data.history && data.history.length > 0) {
        // Hide the welcome screen
        if (welcomeScreen) welcomeScreen.style.display = "none";

        data.history.forEach((item) => {
          if (item.role === "system") return;
          const role = item.role === "user" ? "user" : "assistant";
          addMessage(role, item.content || "");
        });
      }
    } catch (e) {
      console.debug("Failed to load session history:", e);
    }
  }

  // ════════════════════════════════════════
  //  Health check
  // ════════════════════════════════════════

  async function checkHealth() {
    // Remove an existing popup
    const existing = document.querySelector(".health-modal");
    if (existing) {
      existing.remove();
      return;
    }

    const modal = document.createElement("div");
    modal.className = "health-modal";
    modal.innerHTML =
      "<h3>Service status</h3>" +
      '<div class="health-row"><span class="label">Checking...</span></div>';
    document.body.appendChild(modal);

    try {
      const response = await fetch("/api/health");
      if (!response.ok) throw new Error("Health check failed");
      const data = await response.json();

      const ragDot = data.rag_ready
        ? '<span class="health-dot ok"></span>Ready'
        : '<span class="health-dot warn"></span>Not ready';

      const modelInfo = data.model_info || {};
      const rows = [
        `<div class="health-row"><span class="label">Service status</span><span class="value"><span class="health-dot ok"></span>${escapeHtml(data.status)}</span></div>`,
        `<div class="health-row"><span class="label">RAG retrieval</span><span class="value">${ragDot}</span></div>`,
        `<div class="health-row"><span class="label">Chat model</span><span class="value">${escapeHtml(modelInfo.chat || "—")}</span></div>`,
        `<div class="health-row"><span class="label">Embedding model</span><span class="value">${escapeHtml(modelInfo.embedding || "—")}</span></div>`,
        `<div class="health-row"><span class="label">Reasoning model</span><span class="value">${escapeHtml(modelInfo.reasoning || "—")}</span></div>`,
      ];
      modal.innerHTML = "<h3>Service status</h3>" + rows.join("");
    } catch (e) {
      modal.innerHTML =
        "<h3>Service status</h3>" +
        `<div class="health-row"><span class="label">Status</span><span class="value"><span class="health-dot warn"></span>Unreachable</span></div>` +
        `<div class="health-row"><span class="value" style="font-size:12px;color:#ff3b30">${escapeHtml(e.message)}</span></div>`;
    }

    // Close when clicking outside
    setTimeout(() => {
      document.addEventListener("click", function closeHandler(ev) {
        if (!modal.contains(ev.target) && ev.target !== healthBtn) {
          modal.remove();
          document.removeEventListener("click", closeHandler);
        }
      });
    }, 100);
  }

  // ════════════════════════════════════════
  //  Event binding
  // ════════════════════════════════════════

  // Input box
  messageInput.addEventListener("input", () => {
    autoResize();
    sendBtn.disabled = !messageInput.value.trim() || isProcessing;
  });

  // Enter to send / Shift+Enter for a new line
  messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!sendBtn.disabled) {
        sendMessage(messageInput.value);
      }
    }
  });

  // Send button
  sendBtn.addEventListener("click", () => {
    sendMessage(messageInput.value);
  });

  // Suggestion chips
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const query = chip.getAttribute("data-query");
      if (query && !isProcessing) {
        sendMessage(query);
      }
    });
  });

  // Session switching (list clicks are already bound in renderSessionList)

  // New session
  newSessionBtn.addEventListener("click", () => {
    const sessionId = `session-${Date.now().toString(36)}`;
    currentSessionId = sessionId;
    messageList.innerHTML = "";
    if (welcomeScreen) {
      welcomeScreen.style.display = "";
      messageList.appendChild(welcomeScreen);
    }
    showToast("New chat created", "success");
    loadSessions();
  });

  // Health check
  healthBtn.addEventListener("click", checkHealth);

  // Citation badge click (event delegation)
  messageList.addEventListener("click", (e) => {
    if (e.target.classList.contains("citation-ref")) {
      const refId = e.target.getAttribute("data-ref");
      // Find the corresponding citations panel and expand it
      const messageEl = e.target.closest(".message");
      if (messageEl) {
        const toggle = messageEl.querySelector(".citations-toggle");
        const list = messageEl.querySelector(".citations-list");
        if (toggle && list && !list.classList.contains("show")) {
          toggle.classList.add("expanded");
          list.classList.add("show");
        }
        // Highlight the corresponding card
        const card = list.querySelector(`.citation-card .ref-id`);
        if (card) {
          const cards = list.querySelectorAll(".citation-card");
          cards.forEach((c) => (c.style.boxShadow = ""));
          const matchCard = Array.from(cards).find((c) =>
            c.querySelector(".ref-id").textContent.trim() === refId
          );
          if (matchCard) {
            matchCard.style.boxShadow = "0 0 0 2px var(--accent)";
            matchCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
        }
      }
    }
  });

  // ── Initialization ──
  messageInput.focus();
  loadSessions();
})();
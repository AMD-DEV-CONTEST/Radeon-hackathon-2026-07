(() => {
  "use strict";

  const TOKEN_KEY = "beaver-memory.token";
  let correctionContext = null;
  let previousFocus = null;

  function getToken() {
    return localStorage.getItem(TOKEN_KEY) || "";
  }

  function setToken(value) {
    const token = String(value || "").trim();
    localStorage.setItem(TOKEN_KEY, token);
    document.querySelectorAll("[data-bm-token]").forEach((input) => {
      if (input.value !== token) input.value = token;
    });
    return token;
  }

  function authHeaders(extra = {}) {
    const token = getToken();
    return token ? { ...extra, authorization: `Bearer ${token}` } : { ...extra };
  }

  function idempotencyKey() {
    const provider = globalThis.crypto;
    if (provider && typeof provider.randomUUID === "function") {
      return provider.randomUUID();
    }
    const bytes = new Uint8Array(16);
    if (provider && typeof provider.getRandomValues === "function") {
      provider.getRandomValues(bytes);
    } else {
      for (let index = 0; index < bytes.length; index += 1) {
        bytes[index] = Math.floor(Math.random() * 256);
      }
    }
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
    })[character]);
  }

  function ensureDrawer() {
    let layer = document.getElementById("bmCorrectionLayer");
    if (layer) return layer;
    layer = document.createElement("div");
    layer.id = "bmCorrectionLayer";
    layer.className = "bm-correction-layer";
    layer.hidden = true;
    layer.innerHTML = `
      <button class="bm-correction-scrim" type="button" data-bm-close-correction aria-label="关闭修正抽屉"></button>
      <aside class="bm-correction-drawer" role="dialog" aria-modal="true" aria-labelledby="bmCorrectionTitle">
        <div class="bm-correction-head">
          <div><div class="bm-correction-eyebrow">MEMORY CORRECTION</div><h2 id="bmCorrectionTitle">修正这条记忆</h2></div>
          <button class="bm-correction-close" type="button" data-bm-close-correction aria-label="关闭">×</button>
        </div>
        <form class="bm-correction-form" id="bmCorrectionForm">
          <div class="bm-correction-field"><label for="bmCorrectionOriginal">当前内容</label><textarea id="bmCorrectionOriginal" readonly></textarea></div>
          <div class="bm-correction-field"><label for="bmCorrectionValue">修正后内容</label><textarea id="bmCorrectionValue" required></textarea></div>
          <div class="bm-correction-field"><label for="bmCorrectionNote">修正原因（可选）</label><input id="bmCorrectionNote" maxlength="1000" placeholder="例如：人物、地点或事件描述不准确" /></div>
          <div class="bm-correction-evidence" id="bmCorrectionEvidence"></div>
          <div class="bm-correction-status" id="bmCorrectionStatus" role="status" aria-live="polite"></div>
          <div class="bm-correction-actions"><button class="bm-button-secondary" type="button" data-bm-close-correction>取消</button><button class="bm-button-primary" id="bmCorrectionSubmit" type="submit">保存修正</button></div>
        </form>
      </aside>`;
    document.body.appendChild(layer);
    layer.querySelectorAll("[data-bm-close-correction]").forEach((button) => button.addEventListener("click", closeCorrection));
    layer.querySelector("#bmCorrectionForm").addEventListener("submit", submitCorrection);
    return layer;
  }

  function normalizeContext(input) {
    const evidenceRefs = [...new Set((input.evidenceRefs || []).map((value) => String(value || "").trim()).filter(Boolean))];
    if (!input.targetType || !input.targetId || !input.fieldPath) throw new Error("这条记忆缺少稳定来源，暂时无法修正。");
    if (!evidenceRefs.length) evidenceRefs.push(`${input.targetType}://${input.targetId}`);
    return {
      targetType: input.targetType,
      targetId: String(input.targetId),
      fieldPath: input.fieldPath,
      originalValue: String(input.originalValue || ""),
      evidenceRefs,
      title: input.title || "修正这条记忆",
      note: input.note || "",
      onApplied: typeof input.onApplied === "function" ? input.onApplied : null
    };
  }

  function openCorrection(input) {
    const layer = ensureDrawer();
    correctionContext = normalizeContext(input || {});
    previousFocus = document.activeElement;
    layer.querySelector("#bmCorrectionTitle").textContent = correctionContext.title;
    layer.querySelector("#bmCorrectionOriginal").value = correctionContext.originalValue;
    layer.querySelector("#bmCorrectionValue").value = correctionContext.originalValue;
    layer.querySelector("#bmCorrectionNote").value = correctionContext.note;
    layer.querySelector("#bmCorrectionEvidence").textContent = `已自动关联 ${correctionContext.evidenceRefs.length} 条来源证据；内部标识和证据地址无需手动填写。`;
    const status = layer.querySelector("#bmCorrectionStatus");
    status.textContent = "";
    status.className = "bm-correction-status";
    layer.hidden = false;
    document.body.classList.add("bm-drawer-open");
    requestAnimationFrame(() => layer.querySelector("#bmCorrectionValue").focus());
    return correctionContext;
  }

  function closeCorrection() {
    const layer = document.getElementById("bmCorrectionLayer");
    if (!layer || layer.hidden) return;
    layer.hidden = true;
    document.body.classList.remove("bm-drawer-open");
    correctionContext = null;
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
    previousFocus = null;
  }

  async function submitCorrection(event) {
    event.preventDefault();
    if (!correctionContext) return;
    const layer = ensureDrawer();
    const value = layer.querySelector("#bmCorrectionValue").value.trim();
    const note = layer.querySelector("#bmCorrectionNote").value.trim();
    const submit = layer.querySelector("#bmCorrectionSubmit");
    const status = layer.querySelector("#bmCorrectionStatus");
    if (!value) {
      status.textContent = "修正后内容不能为空。";
      status.className = "bm-correction-status error";
      return;
    }
    if (value === correctionContext.originalValue.trim()) {
      status.textContent = "内容没有变化，无需保存。";
      status.className = "bm-correction-status warning";
      return;
    }
    submit.disabled = true;
    status.textContent = "正在保存修正…";
    status.className = "bm-correction-status";
    try {
      const response = await fetch("/v1/memory/corrections", {
        method: "POST",
        headers: authHeaders({
          "content-type": "application/json",
          "Idempotency-Key": idempotencyKey()
        }),
        body: JSON.stringify({
          target_type: correctionContext.targetType,
          target_id: correctionContext.targetId,
          field_path: correctionContext.fieldPath,
          old_value: correctionContext.originalValue,
          new_value: value,
          status: "confirmed",
          evidence_refs: correctionContext.evidenceRefs,
          note: note || "用户在记忆卡片上修正"
        })
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
      const flushed = payload.everos_writeback?.status === "flushed";
      status.textContent = flushed ? "已修正并写回 EverOS。" : "修正已保存，等待写回 EverOS。";
      status.className = `bm-correction-status ${flushed ? "success" : "warning"}`;
      if (correctionContext.onApplied) await correctionContext.onApplied(payload, value);
      setTimeout(closeCorrection, 700);
    } catch (error) {
      status.textContent = `保存失败：${error.message}。输入内容已保留，可直接重试。`;
      status.className = "bm-correction-status error";
    } finally {
      submit.disabled = false;
    }
  }

  function syncShell() {
    const current = location.pathname.replace(/\/$/, "") || "/";
    document.querySelectorAll(".bm-nav a[href]").forEach((link) => {
      const path = new URL(link.href, location.origin).pathname.replace(/\/$/, "") || "/";
      const active = path === current;
      link.classList.toggle("active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    document.querySelectorAll("[data-bm-token]").forEach((input) => {
      const container = input.closest(".token-card,.token-box,.bm-notice") || input.parentElement;
      if (container) container.hidden = true;
    });
    const sidebar = typeof document.querySelector === "function" ? document.querySelector(".bm-sidebar") : null;
    if (sidebar && !document.getElementById("bmAccount")) {
      const account = document.createElement("div");
      account.id = "bmAccount";
      account.className = "bm-notice";
      account.style.cssText = "position:absolute;left:20px;right:20px;bottom:22px";
      account.innerHTML = `<strong data-account-name>正在读取用户…</strong><small data-account-id style="display:block;margin:4px 0 10px;color:var(--bm-muted)"></small><button type="button" data-account-logout style="width:100%;padding:8px;border:1px solid var(--bm-line);border-radius:9px;background:transparent;cursor:pointer">退出登录</button>`;
      sidebar.appendChild(account);
      fetch("/v1/auth/me", { cache: "no-store" }).then(response => {
        if (!response.ok) throw new Error("unauthorized");
        return response.json();
      }).then(payload => {
        account.querySelector("[data-account-name]").textContent = payload.user.display_name;
        account.querySelector("[data-account-id]").textContent = payload.user.user_id;
      }).catch(() => { location.replace(`/login?next=${encodeURIComponent(location.pathname)}`); });
      account.querySelector("[data-account-logout]").addEventListener("click", async () => {
        await fetch("/v1/auth/logout", { method: "POST" }).catch(() => {});
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem("everlens.token");
        location.replace("/login");
      });
    }
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeCorrection();
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", syncShell);
  else syncShell();

  window.BeaverMemoryUI = { getToken, setToken, authHeaders, idempotencyKey, openCorrection, closeCorrection, syncShell };
})();

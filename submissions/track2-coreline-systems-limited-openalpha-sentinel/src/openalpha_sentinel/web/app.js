(() => {
  "use strict";

  const API = "/api";
  const ACTIVE_JOB_STATUSES = new Set([
    "created",
    "queued",
    "pending",
    "planning",
    "discovering",
    "fetching",
    "normalizing",
    "license_checking",
    "deduplicating",
    "extracting",
    "extracting_on_gpu",
    "indexing",
    "notifying",
    "running",
    "processing",
    "retry_wait",
  ]);
  const RESOURCE_COUNT = 7;

  const ZH = {
    "Skip to content": "跳到内容",
    "Primary navigation": "主导航",
    "Overview": "总览",
    "Strategy cards": "策略卡片",
    "Agent chat": "智能体对话",
    "Sources": "来源",
    "Jobs": "任务",
    "Watch rules": "监控规则",
    "Local controls": "本地控制",
    "Local runtime": "本地运行环境",
    "Loading controls": "正在加载控制项",
    "Network collection": "网络采集",
    "Connection state and domains": "连接状态与域名",
    "Loading permissions": "正在加载权限",
    "Local memory": "本地记忆",
    "Saved preferences": "已保存偏好",
    "Loading memory": "正在加载记忆",
    "Recent audit": "最近审计",
    "Loading events": "正在加载事件",
    "Language": "语言",
    "Connecting": "正在连接",
    "Local workspace": "本地工作区",
    "Open navigation": "打开导航",
    "Close navigation": "关闭导航",
    "Refresh data": "刷新数据",
    "Research intelligence": "研究情报",
    "Waiting for local index": "正在等待本地索引",
    "Discover GitHub": "发现 GitHub 项目",
    "Seed demo": "载入演示数据",
    "Index summary": "索引概况",
    "Indexed research": "已索引研究",
    "Tracked sources": "跟踪来源",
    "With provenance": "可追溯来源",
    "Jobs (24h)": "24 小时任务",
    "Collector queue": "采集队列",
    "Scheduled monitors": "定时监控",
    "Recent strategies": "最近策略",
    "Latest evidence-backed records": "最新证据化记录",
    "View all": "查看全部",
    "Loading strategies": "正在加载策略",
    "Collector activity": "采集活动",
    "Discovery and indexing pipeline": "发现与索引流水线",
    "Loading jobs": "正在加载任务",
    "Collection coverage": "采集覆盖",
    "Source health": "来源状态",
    "GitHub": "GitHub",
    "Waiting": "等待中",
    "RSS / Atom": "RSS / Atom",
    "Local snapshots": "本地快照",
    "Knowledge index": "知识索引",
    "Loading records": "正在加载记录",
    "Refresh": "刷新",
    "Strategy filters": "策略筛选",
    "Search strategy cards": "搜索策略卡片",
    "Search title, market, or source": "搜索标题、市场或来源",
    "Filter by family": "按策略类型筛选",
    "All families": "全部类型",
    "Filter by license": "按许可证筛选",
    "All licenses": "全部许可证",
    "Licensed": "许可证明确",
    "Unknown": "未知",
    "Local research agent": "本地研究智能体",
    "Local session": "本地会话",
    "Conversation": "对话",
    "Research the local index": "检索本地索引",
    "Ask about strategy logic, evidence, licenses, or disclosed risks.": "查询策略逻辑、证据、许可证或已披露风险。",
    "Transaction costs": "交易成本",
    "Compare strategies": "比较策略",
    "Clear licenses": "许可证明确",
    "Which strategies disclose transaction costs?": "哪些策略披露了交易成本？",
    "Compare the indexed strategies by entry logic and source evidence.": "按入场逻辑和来源证据比较已索引策略。",
    "Show strategies with a clear open-source license.": "显示开源许可证明确的策略。",
    "Question": "问题",
    "Ask the local strategy index": "询问本地策略索引",
    "Send question": "发送问题",
    "Answer sources": "回答来源",
    "0 cited": "引用 0 项",
    "Sources appear with an answer.": "回答生成后将在此显示来源。",
    "Provenance registry": "溯源登记",
    "Loading sources": "正在加载来源",
    "Ingest feed": "导入订阅源",
    "Pipeline operations": "流水线运行",
    "Filter jobs": "筛选任务",
    "All": "全部",
    "Active": "活动中",
    "Completed": "已完成",
    "Failed": "失败",
    "Partial success": "部分成功",
    "Skipped": "已跳过",
    "Continuous monitoring": "持续监控",
    "Loading schedules": "正在加载计划",
    "New rule": "新建规则",
    "Close dialog": "关闭对话框",
    "Source discovery": "来源发现",
    "Repository query": "仓库查询",
    "Result limit": "结果上限",
    "Cancel": "取消",
    "Start discovery": "开始发现",
    "Feed ingestion": "订阅源导入",
    "Ingest RSS or Atom": "导入 RSS 或 Atom",
    "Feed URL": "订阅源 URL",
    "Scheduled collection": "定时采集",
    "New watch rule": "新建监控规则",
    "Rule name": "规则名称",
    "Daily mean-reversion scan": "每日均值回归扫描",
    "Source type": "来源类型",
    "Frequency": "频率",
    "Every hour": "每小时",
    "Every 6 hours": "每 6 小时",
    "Every 12 hours": "每 12 小时",
    "Every day": "每天",
    "mean reversion language:python": "mean reversion language:python",
    "Create rule": "创建规则",
    "Strategy record": "策略记录",
    "Strategy detail": "策略详情",
    "Close strategy detail": "关闭策略详情",
    "Local API online": "本地 API 在线",
    "API unavailable": "API 不可用",
    "Partial data": "部分数据可用",
    "Updated {time}": "更新于 {time}",
    "{count} records": "{count} 条记录",
    "{count} sources": "{count} 个来源",
    "{count} jobs": "{count} 个任务",
    "{count} rules": "{count} 条规则",
    "{count} cited": "引用 {count} 项",
    "{count} licensed": "{count} 项许可证明确",
    "{count} running": "{count} 项运行中",
    "{count} enabled": "{count} 条已启用",
    "{domains} domains · {preferences} preferences": "{domains} 个域名 · {preferences} 项偏好",
    "{count} domains": "{count} 个域名",
    "{count} preferences": "{count} 项偏好",
    "{count} events": "{count} 条事件",
    "No strategy cards yet": "暂无策略卡片",
    "Seed the deterministic demo or run a source discovery.": "载入确定性演示数据或运行来源发现。",
    "No matching strategies": "没有匹配的策略",
    "Adjust the search or license filter.": "调整搜索条件或许可证筛选。",
    "No collector jobs yet": "暂无采集任务",
    "Discovery and ingestion runs will appear here.": "发现与导入任务会显示在这里。",
    "No matching jobs": "没有匹配的任务",
    "Choose another status filter.": "请选择其他状态筛选。",
    "No watch rules yet": "暂无监控规则",
    "Create a rule to schedule incremental collection.": "创建规则以定时执行增量采集。",
    "No sources indexed": "尚未索引来源",
    "Ingest a feed, discover GitHub repositories, or seed the demo.": "导入订阅源、发现 GitHub 仓库或载入演示数据。",
    "Unable to load data": "无法加载数据",
    "The local API did not return this resource.": "本地 API 未返回该资源。",
    "Try again": "重试",
    "Untitled strategy": "未命名策略",
    "Unknown source": "未知来源",
    "Unknown family": "未知类型",
    "Unspecified": "未说明",
    "Not available": "不可用",
    "Clear": "明确",
    "No assertion": "未声明",
    "Title": "标题",
    "Family": "策略类型",
    "Market": "市场",
    "Timeframe": "周期",
    "License": "许可证",
    "Source": "来源",
    "Updated": "更新时间",
    "Strategy": "策略",
    "Status": "状态",
    "Stage": "阶段",
    "Progress": "进度",
    "Attempts": "尝试次数",
    "Started": "开始时间",
    "Rule": "规则",
    "Schedule": "计划",
    "Next run": "下次运行",
    "Last run": "上次运行",
    "Cards": "卡片数",
    "Type": "类型",
    "Revision": "版本",
    "Last seen": "最近发现",
    "GitHub sources": "GitHub 来源",
    "RSS sources": "RSS 来源",
    "Snapshot sources": "快照来源",
    "Summary": "摘要",
    "Entry logic": "入场逻辑",
    "Exit logic": "退出逻辑",
    "Risk notes": "风险说明",
    "Evidence": "证据",
    "No evidence snippets were returned for this card.": "该卡片未返回证据片段。",
    "Open immutable source": "打开不可变来源",
    "Open source": "打开来源",
    "You": "你",
    "Sentinel": "哨兵",
    "The agent could not answer this question.": "智能体无法回答此问题。",
    "The local agent returned no answer.": "本地智能体未返回回答。",
    "No citations were returned.": "未返回引用。",
    "Demo data indexed.": "演示数据已完成索引。",
    "GitHub discovery completed.": "GitHub 发现任务已完成。",
    "Feed ingestion completed.": "订阅源导入已完成。",
    "Watch rule created.": "监控规则已创建。",
    "Request failed": "请求失败",
    "Network request failed": "网络请求失败",
    "Request timed out": "请求超时",
    "Running": "运行中",
    "Processing": "处理中",
    "Queued": "排队中",
    "Pending": "等待中",
    "Retry wait": "等待重试",
    "Cancelled": "已取消",
    "Created": "已创建",
    "Discovering": "发现中",
    "Fetching": "抓取中",
    "Normalizing": "规范化中",
    "License checking": "检查许可证",
    "Deduplicating": "去重中",
    "Extracting": "抽取中",
    "Extracting on gpu": "GPU 抽取中",
    "Indexing": "索引中",
    "Notifying": "通知中",
    "Github": "GitHub",
    "Rss": "RSS",
    "Snapshot": "快照",
    "Manual": "手动",
    "Demo seed": "演示数据",
    "Github discovery": "GitHub 发现",
    "Rss ingestion": "RSS 导入",
    "Enabled": "已启用",
    "Disabled": "已停用",
    "Idle": "空闲",
    "Healthy": "正常",
    "Offline mode": "离线模式",
    "Network collection enabled": "网络采集已启用",
    "Network collection paused": "网络采集已暂停",
    "Allowed domains": "允许的域名",
    "No domains configured": "未配置域名",
    "Domain": "域名",
    "Add domain": "新增域名",
    "No saved preferences": "暂无已保存偏好",
    "No audit events": "暂无审计事件",
    "Key": "键",
    "Value": "值",
    "Event": "事件",
    "Actor": "执行者",
    "Detail": "详情",
    "Time": "时间",
    "Offline mode enabled.": "离线模式已启用。",
    "Offline mode disabled.": "离线模式已关闭。",
    "Domain added.": "域名已添加。",
    "Offline mode changed": "离线模式变更",
    "Domain granted": "域名授权",
  };

  const state = {
    locale: localStorage.getItem("oas.locale") === "zh" ? "zh" : "en",
    view: "overview",
    dashboard: null,
    cards: [],
    jobs: [],
    watchRules: [],
    permissions: null,
    memory: null,
    audit: [],
    dashboardSources: [],
    errors: {},
    loading: new Set(["dashboard", "cards", "jobs", "watchRules", "permissions", "memory", "audit"]),
    jobFilter: "all",
    messages: [],
    latestCitations: [],
    sessionId: localStorage.getItem("oas.session") || createId(),
    cardById: new Map(),
    staticText: [],
    staticAttributes: [],
  };

  localStorage.setItem("oas.session", state.sessionId);

  function createId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `oas-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function t(key, values = {}) {
    let output = state.locale === "zh" ? ZH[key] || key : key;
    for (const [name, value] of Object.entries(values)) {
      output = output.replaceAll(`{${name}}`, String(value));
    }
    return output;
  }

  function captureStaticStrings() {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if (["SCRIPT", "STYLE"].includes(node.parentElement?.tagName)) return NodeFilter.FILTER_REJECT;
        if (node.parentElement?.closest('[translate="no"]')) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    let node;
    while ((node = walker.nextNode())) {
      state.staticText.push({ node, original: node.nodeValue });
    }

    const attributes = ["placeholder", "aria-label", "title"];
    document.querySelectorAll("*").forEach((element) => {
      attributes.forEach((attribute) => {
        if (element.hasAttribute(attribute)) {
          state.staticAttributes.push({
            element,
            attribute,
            original: element.getAttribute(attribute),
          });
        }
      });
    });
  }

  function applyStaticTranslations() {
    document.documentElement.lang = state.locale === "zh" ? "zh-CN" : "en";
    state.staticText.forEach(({ node, original }) => {
      const trimmed = original.trim();
      const leading = original.match(/^\s*/)?.[0] || "";
      const trailing = original.match(/\s*$/)?.[0] || "";
      node.nodeValue = `${leading}${t(trimmed)}${trailing}`;
    });
    state.staticAttributes.forEach(({ element, attribute, original }) => {
      element.setAttribute(attribute, t(original));
    });
    document.querySelectorAll("[data-locale]").forEach((button) => {
      const active = button.dataset.locale === state.locale;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }

  function switchLocale(locale) {
    if (!new Set(["en", "zh"]).has(locale) || locale === state.locale) return;
    state.locale = locale;
    localStorage.setItem("oas.locale", locale);
    document.getElementById("toast-region").replaceChildren();
    applyStaticTranslations();
    syncWatchForm();
    renderAll();
  }

  function refreshIcons() {
    if (!window.lucide || typeof window.lucide.createIcons !== "function") return;
    try {
      window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
      document.documentElement.classList.add("lucide-ready");
    } catch (error) {
      console.warn("Lucide icons unavailable", error);
    }
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function safeUrl(value) {
    if (!value) return "";
    try {
      const url = new URL(String(value), window.location.origin);
      if (!["http:", "https:"].includes(url.protocol)) return "";
      return url.href;
    } catch {
      return "";
    }
  }

  function get(object, paths, fallback = null) {
    if (!object) return fallback;
    for (const path of Array.isArray(paths) ? paths : [paths]) {
      let value = object;
      for (const part of String(path).split(".")) {
        if (value == null || typeof value !== "object") {
          value = undefined;
          break;
        }
        value = value[part];
      }
      if (value !== undefined && value !== null && value !== "") return value;
    }
    return fallback;
  }

  function displayValue(value, fallback = "Unspecified") {
    if (value === undefined || value === null || value === "") return t(fallback);
    if (Array.isArray(value)) return value.length ? value.map((item) => displayValue(item, fallback)).join(", ") : t(fallback);
    if (typeof value === "object") {
      return displayValue(value.name ?? value.title ?? value.value ?? value.id, fallback);
    }
    return String(value);
  }

  function listFrom(payload, keys) {
    if (Array.isArray(payload)) return payload;
    for (const key of keys) {
      const value = get(payload, key);
      if (Array.isArray(value)) return value;
    }
    if (payload?.data) return listFrom(payload.data, keys);
    return [];
  }

  function numberFrom(payload, paths, fallback = 0) {
    const value = Number(get(payload, paths, fallback));
    return Number.isFinite(value) ? value : fallback;
  }

  function formatDate(value, includeTime = false) {
    if (!value) return t("Not available");
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat(state.locale === "zh" ? "zh-CN" : "en", {
      year: "numeric",
      month: "short",
      day: "2-digit",
      ...(includeTime ? { hour: "2-digit", minute: "2-digit" } : {}),
    }).format(date);
  }

  function humanize(value, fallback = "Unknown") {
    if (!value) return t(fallback);
    const words = String(value).replaceAll("-", " ").replaceAll("_", " ").toLowerCase();
    const label = words.charAt(0).toUpperCase() + words.slice(1);
    return t(label);
  }

  function statusClass(value) {
    return String(value || "unknown").toLowerCase().replaceAll("_", "-").replace(/[^a-z0-9-]/g, "");
  }

  function normalizeEvidence(raw) {
    const evidence = listFrom(raw, ["evidence", "evidences", "citations", "sources"]);
    return evidence.map((item, index) => {
      if (typeof item === "string") {
        const url = safeUrl(item);
        return { id: `S${index + 1}`, label: url ? sourceNameFromUrl(url) : item, excerpt: "", url };
      }
      const url = safeUrl(get(item, ["immutable_url", "source_url", "url", "href", "permalink"]));
      return {
        id: displayValue(get(item, ["id", "evidence_id", "chunk_id", "label"], `S${index + 1}`)),
        label: displayValue(get(item, ["field_path", "field_name", "field", "title", "source", "name"], url ? sourceNameFromUrl(url) : `S${index + 1}`)),
        excerpt: displayValue(get(item, ["excerpt", "quote", "text", "snippet"], ""), ""),
        url,
      };
    });
  }

  function sourceNameFromUrl(value) {
    try {
      const url = new URL(value);
      if (url.hostname.includes("github.com")) {
        const parts = url.pathname.split("/").filter(Boolean);
        if (parts.length >= 5 && parts[2] === "blob") {
          const file = parts.at(-1).replace(/\.(md|markdown|txt|py|ipynb)$/i, "");
          return `${parts[0]}/${parts[1]} · ${file}`;
        }
        if (parts.length >= 2) return `${parts[0]}/${parts[1]}`;
      }
      return url.hostname.replace(/^www\./, "");
    } catch {
      return t("Unknown source");
    }
  }

  function normalizeLicense(raw) {
    let value = get(raw, [
      "license.spdx_id",
      "license.spdx",
      "license.name",
      "license_spdx",
      "spdx_id",
      "license_id",
      "license",
    ]);
    if (typeof value === "object") value = value.spdx_id || value.name || value.id;
    value = displayValue(value, "Unknown");
    const status = String(get(raw, ["license.status", "license_status"], "")).toLowerCase();
    const unknownValues = new Set(["unknown", "noassertion", "no assertion", "other", "none", "not available"]);
    const isClear = status === "clear" || status === "licensed" || (!unknownValues.has(value.toLowerCase()) && value !== t("Unknown"));
    return { value, isClear, status: isClear ? "success" : "unknown" };
  }

  function normalizeCard(raw, index = 0) {
    const sourceUrl = safeUrl(get(raw, [
      "source.immutable_url",
      "source.url",
      "immutable_url",
      "source_url",
      "repository_url",
      "url",
    ])) || normalizeEvidence(raw).find((item) => item.url)?.url || "";
    const explicitSourceName = get(raw, [
      "source.repository",
      "source.name",
      "repository",
      "repo",
      "source_name",
    ]);
    const sourceName = displayValue(
      explicitSourceName || (sourceUrl ? sourceNameFromUrl(sourceUrl) : get(raw, "author")),
      "Unknown source",
    );
    const title = displayValue(get(raw, ["title", "name", "strategy_name", "card.title"]), "Untitled strategy");
    const id = String(get(raw, ["card_id", "id", "strategy_id"], `${sourceName}:${title}:${index}`));
    const license = normalizeLicense(raw);
    const risks = get(raw, ["risks", "risk_flags", "risk_notes", "card.risks"], []);

    return {
      raw,
      id,
      title,
      family: displayValue(get(raw, ["strategy_type", "strategy_family", "family", "strategy.family", "category", "type"]), "Unknown family"),
      market: displayValue(get(raw, ["market", "markets", "asset_class", "strategy.market"])),
      timeframe: displayValue(get(raw, ["timeframes", "timeframe", "frequency", "bar_frequency", "strategy.timeframe"])),
      summary: displayValue(get(raw, ["summary", "description", "abstract", "card.summary"], ""), ""),
      entryLogic: displayValue(get(raw, ["entry_logic", "strategy.entry_logic", "rules.entry", "signal"], ""), ""),
      exitLogic: displayValue(get(raw, ["exit_logic", "strategy.exit_logic", "rules.exit"], ""), ""),
      risks: Array.isArray(risks) ? risks.map((risk) => displayValue(risk)).join("; ") : displayValue(risks, ""),
      license,
      sourceUrl,
      sourceName,
      sourceType: String(get(raw, ["source.type", "source_type", "kind"], inferSourceType(sourceUrl))).toLowerCase(),
      revision: displayValue(get(raw, ["source.commit", "commit", "revision", "revision_key", "version"], ""), ""),
      updatedAt: get(raw, ["updated_at", "fetched_at", "created_at", "source.fetched_at"]),
      score: get(raw, ["readiness_score", "quality_score", "score"]),
      evidence: normalizeEvidence(raw),
    };
  }

  function inferSourceType(url) {
    if (!url) return "snapshot";
    if (url.includes("openalpha_revision=")) return "snapshot";
    if (url.includes("github.com")) return "github";
    return "rss";
  }

  function normalizeJob(raw, index = 0) {
    const status = String(get(raw, ["status", "state"], "unknown")).toLowerCase();
    const kind = displayValue(get(raw, ["kind", "job_type", "type", "source_type"]), "Manual");
    const completed = numberFrom(raw, ["items_processed", "processed", "completed_items", "progress.completed"], 0);
    const total = numberFrom(raw, ["total", "total_items", "progress.total"], 0);
    const progressValue = get(raw, ["progress_percent", "percent"]);
    const explicitProgress = progressValue === null ? Number.NaN : Number(progressValue);
    const progress = Number.isFinite(explicitProgress)
      ? Math.max(0, Math.min(100, explicitProgress))
      : total > 0 ? Math.round((completed / total) * 100) : status === "completed" ? 100 : 0;
    return {
      raw,
      id: String(get(raw, ["job_id", "id"], `job-${index}`)),
      name: displayValue(get(raw, ["name", "title"], ""), ""),
      kind,
      source: displayValue(get(raw, ["source", "query", "url", "input.query", "input.url", "input_summary"], ""), ""),
      status,
      stage: String(get(raw, ["stage", "current_step", "phase"], status)),
      progress,
      completed,
      total,
      attempts: numberFrom(raw, ["attempts", "retry_count", "retries"], 0),
      startedAt: get(raw, ["started_at", "created_at", "queued_at"]),
      updatedAt: get(raw, ["updated_at", "finished_at", "completed_at", "started_at"]),
      error: displayValue(get(raw, ["error", "error_message", "last_error"], ""), ""),
    };
  }

  function normalizeRule(raw, index = 0) {
    const config = get(raw, "config", {}) || {};
    const kind = String(get(raw, ["kind", "source_type", "type"], "github")).toLowerCase();
    const interval = numberFrom(raw, ["interval_minutes", "interval", "frequency_minutes"], 360);
    const enabledValue = get(raw, ["enabled", "active", "is_active"], true);
    return {
      raw,
      id: String(get(raw, ["rule_id", "id"], `rule-${index}`)),
      name: displayValue(get(raw, ["name", "title"], `${humanize(kind)} rule`)),
      kind,
      config: displayValue(get(config, ["query", "url"], get(raw, ["query", "url"], "")), ""),
      interval,
      enabled: enabledValue !== false && String(enabledValue).toLowerCase() !== "false",
      nextRun: get(raw, ["next_run_at", "next_run", "scheduled_at"]),
      lastRun: get(raw, ["last_run_at", "last_run", "updated_at"]),
    };
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), options.timeout || 20000);
    const headers = new Headers(options.headers || {});
    if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
    try {
      const response = await fetch(`${API}${path}`, { ...options, headers, signal: controller.signal });
      const contentType = response.headers.get("content-type") || "";
      let payload = null;
      if (response.status !== 204) {
        payload = contentType.includes("application/json") ? await response.json() : await response.text();
      }
      if (!response.ok) {
        const detail = typeof payload === "object" ? get(payload, ["detail", "message", "error"]) : payload;
        throw new Error(detail || `${t("Request failed")} (${response.status})`);
      }
      return payload ?? {};
    } catch (error) {
      if (error.name === "AbortError") throw new Error(t("Request timed out"));
      if (error instanceof TypeError) throw new Error(t("Network request failed"));
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  async function loadDashboard({ quiet = false } = {}) {
    if (!quiet) state.loading.add("dashboard");
    try {
      const payload = await request("/dashboard");
      state.dashboard = payload || {};
      state.dashboardSources = listFrom(payload, ["sources", "recent_sources", "data.sources"]);
      delete state.errors.dashboard;
    } catch (error) {
      state.errors.dashboard = error;
    } finally {
      state.loading.delete("dashboard");
      renderOverview();
    }
  }

  async function loadCards({ quiet = false } = {}) {
    if (!quiet) state.loading.add("cards");
    try {
      const payload = await request("/cards");
      state.cards = listFrom(payload, ["cards", "items", "results", "data.cards"]).map(normalizeCard);
      state.cardById = new Map(state.cards.map((card) => [card.id, card]));
      delete state.errors.cards;
    } catch (error) {
      state.errors.cards = error;
    } finally {
      state.loading.delete("cards");
      renderCards();
      renderSources();
      renderOverview();
    }
  }

  async function loadJobs({ quiet = false } = {}) {
    if (!quiet) state.loading.add("jobs");
    try {
      const payload = await request("/jobs");
      state.jobs = listFrom(payload, ["jobs", "items", "results", "data.jobs"]).map(normalizeJob);
      delete state.errors.jobs;
    } catch (error) {
      state.errors.jobs = error;
    } finally {
      state.loading.delete("jobs");
      renderJobs();
      renderOverview();
    }
  }

  async function loadWatchRules({ quiet = false } = {}) {
    if (!quiet) state.loading.add("watchRules");
    try {
      const payload = await request("/watch-rules");
      state.watchRules = listFrom(payload, ["watch_rules", "rules", "items", "results", "data.watch_rules"]).map(normalizeRule);
      delete state.errors.watchRules;
    } catch (error) {
      state.errors.watchRules = error;
    } finally {
      state.loading.delete("watchRules");
      renderRules();
      renderOverview();
    }
  }

  async function loadPermissions({ quiet = false } = {}) {
    if (!quiet) state.loading.add("permissions");
    try {
      state.permissions = await request("/permissions");
      delete state.errors.permissions;
    } catch (error) {
      state.errors.permissions = error;
    } finally {
      state.loading.delete("permissions");
      renderControls();
    }
  }

  async function loadMemory({ quiet = false } = {}) {
    if (!quiet) state.loading.add("memory");
    try {
      state.memory = await request("/memory");
      delete state.errors.memory;
    } catch (error) {
      state.errors.memory = error;
    } finally {
      state.loading.delete("memory");
      renderControls();
    }
  }

  async function loadAudit({ quiet = false } = {}) {
    if (!quiet) state.loading.add("audit");
    try {
      const payload = await request("/audit");
      state.audit = listFrom(payload, ["events", "audit", "items", "results", "data.events"]);
      delete state.errors.audit;
    } catch (error) {
      state.errors.audit = error;
    } finally {
      state.loading.delete("audit");
      renderControls();
    }
  }

  async function loadControls(options = {}) {
    await Promise.all([loadPermissions(options), loadMemory(options), loadAudit(options)]);
  }

  async function loadAll(options = {}) {
    setRuntime("loading");
    await Promise.all([
      loadDashboard(options),
      loadCards(options),
      loadJobs(options),
      loadWatchRules(options),
      loadControls(options),
    ]);
    const failures = Object.keys(state.errors).length;
    setRuntime(failures === 0 ? "online" : failures < RESOURCE_COUNT ? "partial" : "error");
  }

  function setRuntime(status) {
    const dot = document.getElementById("runtime-dot");
    const label = document.getElementById("runtime-status");
    const detail = document.getElementById("runtime-detail");
    dot.classList.toggle("is-loading", status === "loading");
    dot.classList.toggle("is-error", status === "error");
    if (status === "loading") {
      label.textContent = t("Connecting");
      detail.textContent = state.permissions?.offline ? t("Offline mode") : t("Local workspace");
    } else if (status === "online") {
      label.textContent = t("Local API online");
      detail.textContent = state.permissions?.offline ? t("Offline mode") : t("Local workspace");
    } else if (status === "partial") {
      label.textContent = t("Partial data");
      detail.textContent = t("Local workspace");
    } else {
      label.textContent = t("API unavailable");
      detail.textContent = t("Local workspace");
    }
  }

  function renderOverview() {
    const loading = state.loading.has("dashboard") && !state.dashboard;
    const activeJobs = state.jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status)).length;
    const sources = aggregateSources();
    const enabledRules = state.watchRules.filter((rule) => rule.enabled).length;
    const dashboard = state.dashboard || {};
    const cardCount = numberFrom(dashboard, ["strategies", "card_count", "cards_count", "stats.cards", "counts.cards"], state.cards.length);
    const sourceCount = numberFrom(dashboard, ["sources", "source_count", "sources_count", "stats.sources", "counts.sources"], sources.length);
    const jobCount = numberFrom(dashboard, ["jobs_last_24h", "active_jobs", "active_job_count", "stats.active_jobs", "counts.active_jobs"], state.jobs.length);
    const ruleCount = numberFrom(dashboard, ["active_watch_rules", "watch_rule_count", "watch_rules_count", "stats.watch_rules", "counts.watch_rules"], state.watchRules.length);
    const licensedCount = state.cards.filter((card) => card.license.isClear).length;

    document.getElementById("metric-cards").textContent = loading ? "--" : String(cardCount);
    document.getElementById("metric-sources").textContent = loading ? "--" : String(sourceCount);
    document.getElementById("metric-jobs").textContent = loading ? "--" : String(jobCount);
    document.getElementById("metric-rules").textContent = loading ? "--" : String(ruleCount);
    document.getElementById("metric-cards-detail").textContent = t("{count} licensed", { count: licensedCount });
    document.getElementById("metric-sources-detail").textContent = t("With provenance");
    document.getElementById("metric-jobs-detail").textContent = t("{count} running", { count: activeJobs });
    document.getElementById("metric-rules-detail").textContent = t("{count} enabled", { count: enabledRules });

    const updated = get(dashboard, ["updated_at", "last_updated", "generated_at"]);
    document.getElementById("overview-updated").textContent = state.dashboard
      ? t("Updated {time}", { time: formatDate(updated || new Date(), true) })
      : t("Waiting for local index");

    const alert = document.getElementById("overview-alert");
    if (state.errors.dashboard) {
      alert.textContent = `${t("Unable to load data")}: ${state.errors.dashboard.message}`;
      alert.classList.remove("is-hidden");
    } else {
      alert.classList.add("is-hidden");
    }

    renderOverviewCards();
    renderOverviewJobs();
    renderCoverage(sources);
  }

  function renderOverviewCards() {
    const container = document.getElementById("overview-cards");
    if (state.loading.has("cards")) return;
    if (state.errors.cards) {
      container.innerHTML = compactError("cards");
      bindRetryButtons(container);
      return;
    }
    const cards = [...state.cards]
      .sort((a, b) => new Date(b.updatedAt || 0) - new Date(a.updatedAt || 0))
      .slice(0, 4);
    if (!cards.length) {
      container.innerHTML = `<div class="compact-row"><div class="compact-primary"><strong>${escapeHtml(t("No strategy cards yet"))}</strong><span>${escapeHtml(t("Seed the deterministic demo or run a source discovery."))}</span></div></div>`;
      return;
    }
    container.innerHTML = cards.map((card) => `
      <button class="compact-row" type="button" data-card-id="${escapeHtml(card.id)}">
        <span class="compact-primary">
          <strong>${escapeHtml(card.title)}</strong>
          <span>${escapeHtml(card.family)} · ${escapeHtml(card.market)}</span>
        </span>
        <span class="compact-meta">${escapeHtml(card.sourceName)}<br>${escapeHtml(formatDate(card.updatedAt))}</span>
      </button>
    `).join("");
    bindCardOpeners(container);
  }

  function renderOverviewJobs() {
    const container = document.getElementById("overview-jobs");
    if (state.loading.has("jobs")) return;
    if (state.errors.jobs) {
      container.innerHTML = compactError("jobs");
      bindRetryButtons(container);
      return;
    }
    const jobs = [...state.jobs]
      .sort((a, b) => new Date(b.updatedAt || 0) - new Date(a.updatedAt || 0))
      .slice(0, 4);
    if (!jobs.length) {
      container.innerHTML = `<div class="compact-row"><div class="compact-primary"><strong>${escapeHtml(t("No collector jobs yet"))}</strong><span>${escapeHtml(t("Discovery and ingestion runs will appear here."))}</span></div></div>`;
      return;
    }
    container.innerHTML = jobs.map((job) => `
      <div class="compact-row">
        <div class="compact-primary">
          <strong>${escapeHtml(job.name || humanize(job.kind))}</strong>
          <span>${escapeHtml(humanize(job.stage))}${job.error ? ` · ${escapeHtml(job.error)}` : ""}</span>
        </div>
        <span class="status-badge ${statusClass(job.status)}">${escapeHtml(humanize(job.status))}</span>
      </div>
    `).join("");
  }

  function renderCoverage(sources = aggregateSources()) {
    const counts = { github: 0, rss: 0, snapshot: 0 };
    sources.forEach((source) => {
      const type = source.type.includes("github") ? "github" : source.type.includes("rss") || source.type.includes("atom") ? "rss" : "snapshot";
      counts[type] += 1;
    });
    const container = document.getElementById("coverage-items");
    container.innerHTML = `
      <div class="coverage-item"><span class="source-symbol github" aria-hidden="true">GH</span><span><strong>GitHub</strong><small>${escapeHtml(t("{count} sources", { count: counts.github }))}</small></span></div>
      <div class="coverage-item"><span class="source-symbol rss" aria-hidden="true">RS</span><span><strong>RSS / Atom</strong><small>${escapeHtml(t("{count} sources", { count: counts.rss }))}</small></span></div>
      <div class="coverage-item"><span class="source-symbol snapshot" aria-hidden="true">FS</span><span><strong>${escapeHtml(t("Local snapshots"))}</strong><small>${escapeHtml(t("{count} sources", { count: counts.snapshot }))}</small></span></div>
    `;
  }

  function renderCards() {
    const surface = document.getElementById("cards-surface");
    const count = document.getElementById("cards-count");
    if (state.loading.has("cards")) {
      count.textContent = t("Loading records");
      return;
    }
    if (state.errors.cards) {
      count.textContent = t("Unable to load data");
      surface.innerHTML = errorState("cards");
      bindRetryButtons(surface);
      return;
    }

    updateFamilyOptions();
    const query = document.getElementById("cards-search").value.trim().toLowerCase();
    const family = document.getElementById("cards-family-filter").value;
    const license = document.getElementById("cards-license-filter").value;
    const filtered = state.cards.filter((card) => {
      const searchable = `${card.title} ${card.family} ${card.market} ${card.sourceName}`.toLowerCase();
      if (query && !searchable.includes(query)) return false;
      if (family && card.family !== family) return false;
      if (license === "licensed" && !card.license.isClear) return false;
      if (license === "unknown" && card.license.isClear) return false;
      return true;
    });
    count.textContent = t("{count} records", { count: filtered.length });

    if (!state.cards.length) {
      surface.innerHTML = emptyState("database", "No strategy cards yet", "Seed the deterministic demo or run a source discovery.", true);
      bindSeedButtons(surface);
      refreshIcons();
      return;
    }
    if (!filtered.length) {
      surface.innerHTML = emptyState("search-x", "No matching strategies", "Adjust the search or license filter.");
      refreshIcons();
      return;
    }

    surface.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th style="width:30%">${escapeHtml(t("Strategy"))}</th>
          <th style="width:15%">${escapeHtml(t("Family"))}</th>
          <th style="width:12%">${escapeHtml(t("Market"))}</th>
          <th style="width:13%">${escapeHtml(t("License"))}</th>
          <th style="width:18%">${escapeHtml(t("Source"))}</th>
          <th style="width:12%">${escapeHtml(t("Updated"))}</th>
        </tr></thead>
        <tbody>${filtered.map((card) => `
          <tr data-card-id="${escapeHtml(card.id)}" tabindex="0" aria-label="${escapeHtml(card.title)}">
            <td><span class="table-title">${escapeHtml(card.title)}</span><span class="table-subtitle">${escapeHtml(card.timeframe)}</span></td>
            <td>${escapeHtml(card.family)}</td>
            <td>${escapeHtml(card.market)}</td>
            <td><span class="status-badge ${card.license.status}">${escapeHtml(card.license.value)}</span></td>
            <td><span class="table-title">${escapeHtml(card.sourceName)}</span><span class="table-subtitle">${escapeHtml(card.revision ? card.revision.slice(0, 12) : t("Not available"))}</span></td>
            <td>${escapeHtml(formatDate(card.updatedAt))}</td>
          </tr>
        `).join("")}</tbody>
      </table>`;
    bindCardOpeners(surface);
  }

  function updateFamilyOptions() {
    const select = document.getElementById("cards-family-filter");
    const current = select.value;
    const families = [...new Set(state.cards.map((card) => card.family).filter(Boolean))].sort();
    select.innerHTML = `<option value="">${escapeHtml(t("All families"))}</option>${families.map((family) => `<option value="${escapeHtml(family)}">${escapeHtml(family)}</option>`).join("")}`;
    if (families.includes(current)) select.value = current;
  }

  function aggregateSources() {
    const sources = new Map();
    const add = (source) => {
      const url = safeUrl(get(source, ["url", "source_url", "immutable_url", "repository_url"]));
      const name = displayValue(get(source, ["name", "title", "repository", "repo"], url ? sourceNameFromUrl(url) : null), "Unknown source");
      const key = url || `${get(source, ["type", "kind"], "unknown")}:${name}`;
      const existing = sources.get(key) || {
        name,
        url,
        type: String(get(source, ["type", "kind", "source_type"], inferSourceType(url))).toLowerCase(),
        revision: displayValue(get(source, ["revision", "commit", "revision_key", "version"], ""), ""),
        lastSeen: get(source, ["last_seen_at", "fetched_at", "updated_at"]),
        cards: 0,
      };
      existing.cards += Number(get(source, ["cards", "card_count"], 0)) || 0;
      sources.set(key, existing);
    };

    state.dashboardSources.forEach(add);
    state.cards.forEach((card) => {
      const key = card.sourceUrl || `${card.sourceType}:${card.sourceName}`;
      const existing = sources.get(key) || {
        name: card.sourceName,
        url: card.sourceUrl,
        type: card.sourceType,
        revision: card.revision,
        lastSeen: card.updatedAt,
        cards: 0,
      };
      existing.cards += 1;
      if (new Date(card.updatedAt || 0) > new Date(existing.lastSeen || 0)) existing.lastSeen = card.updatedAt;
      sources.set(key, existing);
    });
    return [...sources.values()];
  }

  function renderSources() {
    const surface = document.getElementById("sources-surface");
    const count = document.getElementById("sources-count");
    const summary = document.getElementById("source-summary");
    if (state.loading.has("cards")) return;
    if (state.errors.cards && !state.dashboardSources.length) {
      count.textContent = t("Unable to load data");
      surface.innerHTML = errorState("cards");
      bindRetryButtons(surface);
      return;
    }
    const sources = aggregateSources();
    count.textContent = t("{count} sources", { count: sources.length });
    const sourceCounts = { github: 0, rss: 0, snapshot: 0 };
    sources.forEach((source) => {
      if (source.type.includes("github")) sourceCounts.github += 1;
      else if (source.type.includes("rss") || source.type.includes("atom")) sourceCounts.rss += 1;
      else sourceCounts.snapshot += 1;
    });
    summary.innerHTML = [
      [sourceCounts.github, "GitHub sources", "github"],
      [sourceCounts.rss, "RSS sources", "rss"],
      [sourceCounts.snapshot, "Snapshot sources", "snapshot"],
    ].map(([value, label, kind]) => `
      <div class="source-summary-item"><span class="source-symbol ${kind}" aria-hidden="true">${kind === "github" ? "GH" : kind === "rss" ? "RS" : "FS"}</span><div><strong>${value}</strong><span>${escapeHtml(t(label))}</span></div></div>
    `).join("");

    if (!sources.length) {
      surface.innerHTML = emptyState("database", "No sources indexed", "Ingest a feed, discover GitHub repositories, or seed the demo.", true);
      bindSeedButtons(surface);
      refreshIcons();
      return;
    }
    surface.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th style="width:34%">${escapeHtml(t("Source"))}</th>
          <th style="width:13%">${escapeHtml(t("Type"))}</th>
          <th style="width:14%">${escapeHtml(t("Cards"))}</th>
          <th style="width:23%">${escapeHtml(t("Revision"))}</th>
          <th style="width:16%">${escapeHtml(t("Last seen"))}</th>
        </tr></thead>
        <tbody>${sources.map((source) => `
          <tr>
            <td>${source.url ? `<a class="table-title" href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(source.name)}</a>` : `<span class="table-title">${escapeHtml(source.name)}</span>`}<span class="table-subtitle">${escapeHtml(source.url || t("Local snapshots"))}</span></td>
            <td><span class="status-badge">${escapeHtml(humanize(source.type, "Snapshot"))}</span></td>
            <td>${source.cards}</td>
            <td><span class="table-subtitle">${escapeHtml(source.revision || t("Not available"))}</span></td>
            <td>${escapeHtml(formatDate(source.lastSeen))}</td>
          </tr>
        `).join("")}</tbody>
      </table>`;
  }

  function renderJobs() {
    const surface = document.getElementById("jobs-surface");
    const count = document.getElementById("jobs-count");
    if (state.loading.has("jobs")) return;
    if (state.errors.jobs) {
      count.textContent = t("Unable to load data");
      surface.innerHTML = errorState("jobs");
      bindRetryButtons(surface);
      return;
    }
    const filtered = state.jobs.filter((job) => {
      if (state.jobFilter === "all") return true;
      if (state.jobFilter === "active") return ACTIVE_JOB_STATUSES.has(job.status);
      if (state.jobFilter === "completed") return job.status === "completed";
      if (state.jobFilter === "failed") return new Set(["failed", "error", "cancelled"]).has(job.status);
      return true;
    });
    count.textContent = t("{count} jobs", { count: filtered.length });
    if (!state.jobs.length) {
      surface.innerHTML = emptyState("list-checks", "No collector jobs yet", "Discovery and ingestion runs will appear here.");
      refreshIcons();
      return;
    }
    if (!filtered.length) {
      surface.innerHTML = emptyState("list-filter", "No matching jobs", "Choose another status filter.");
      refreshIcons();
      return;
    }
    surface.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th style="width:25%">${escapeHtml(t("Title"))}</th>
          <th style="width:13%">${escapeHtml(t("Status"))}</th>
          <th style="width:16%">${escapeHtml(t("Stage"))}</th>
          <th style="width:20%">${escapeHtml(t("Progress"))}</th>
          <th style="width:10%">${escapeHtml(t("Attempts"))}</th>
          <th style="width:16%">${escapeHtml(t("Started"))}</th>
        </tr></thead>
        <tbody>${filtered.map((job) => `
          <tr>
            <td><span class="table-title">${escapeHtml(job.name || humanize(job.kind))}</span><span class="table-subtitle">${escapeHtml(job.source || humanize(job.kind))}</span></td>
            <td><span class="status-badge ${statusClass(job.status)}">${escapeHtml(humanize(job.status))}</span></td>
            <td>${escapeHtml(humanize(job.stage))}</td>
            <td><div class="progress-bar" title="${job.progress}%"><span style="width:${job.progress}%"></span></div><span class="table-subtitle">${job.total ? `${job.completed}/${job.total}` : `${job.progress}%`}</span></td>
            <td>${job.attempts}</td>
            <td>${escapeHtml(formatDate(job.startedAt, true))}</td>
          </tr>
        `).join("")}</tbody>
      </table>`;
  }

  function renderRules() {
    const surface = document.getElementById("rules-surface");
    const count = document.getElementById("rules-count");
    if (state.loading.has("watchRules")) return;
    if (state.errors.watchRules) {
      count.textContent = t("Unable to load data");
      surface.innerHTML = errorState("watchRules");
      bindRetryButtons(surface);
      return;
    }
    count.textContent = t("{count} rules", { count: state.watchRules.length });
    if (!state.watchRules.length) {
      surface.innerHTML = emptyState("radar", "No watch rules yet", "Create a rule to schedule incremental collection.", false, "watch-dialog");
      bindDialogOpeners(surface);
      refreshIcons();
      return;
    }
    surface.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th style="width:27%">${escapeHtml(t("Rule"))}</th>
          <th style="width:13%">${escapeHtml(t("Source"))}</th>
          <th style="width:18%">${escapeHtml(t("Schedule"))}</th>
          <th style="width:14%">${escapeHtml(t("Status"))}</th>
          <th style="width:14%">${escapeHtml(t("Next run"))}</th>
          <th style="width:14%">${escapeHtml(t("Last run"))}</th>
        </tr></thead>
        <tbody>${state.watchRules.map((rule) => `
          <tr>
            <td><span class="table-title">${escapeHtml(rule.name)}</span><span class="table-subtitle">${escapeHtml(rule.config || t("Unspecified"))}</span></td>
            <td><span class="status-badge">${escapeHtml(humanize(rule.kind))}</span></td>
            <td>${escapeHtml(formatInterval(rule.interval))}</td>
            <td><span class="status-badge ${rule.enabled ? "active" : "cancelled"}">${escapeHtml(t(rule.enabled ? "Enabled" : "Disabled"))}</span></td>
            <td>${escapeHtml(formatDate(rule.nextRun, true))}</td>
            <td>${escapeHtml(formatDate(rule.lastRun, true))}</td>
          </tr>
        `).join("")}</tbody>
      </table>`;
  }

  function renderControls() {
    const permissionsContent = document.getElementById("permissions-content");
    const memoryContent = document.getElementById("memory-content");
    const auditContent = document.getElementById("audit-content");
    if (!permissionsContent || !memoryContent || !auditContent) return;

    const preferences = get(state.memory, "preferences", {});
    const preferenceEntries = preferences && typeof preferences === "object" && !Array.isArray(preferences)
      ? Object.entries(preferences)
      : [];
    const domains = Array.isArray(state.permissions?.allowed_domains)
      ? state.permissions.allowed_domains
      : [];
    const controlsLoading = ["permissions", "memory", "audit"].some((resource) => state.loading.has(resource));
    document.getElementById("controls-meta").textContent = controlsLoading
      ? t("Loading controls")
      : t("{domains} domains · {preferences} preferences", {
        domains: domains.length,
        preferences: preferenceEntries.length,
      });

    if (!state.loading.has("permissions")) {
      if (state.errors.permissions) {
        permissionsContent.innerHTML = errorState("permissions");
        bindRetryButtons(permissionsContent);
      } else {
        const offline = Boolean(state.permissions?.offline);
        permissionsContent.innerHTML = `
          <div class="control-section">
            <label class="switch-control" for="offline-toggle">
              <input id="offline-toggle" type="checkbox" role="switch" ${offline ? "checked" : ""}>
              <span class="switch-track" aria-hidden="true"></span>
              <span class="switch-copy">
                <strong>${escapeHtml(t("Offline mode"))}</strong>
                <span>${escapeHtml(t(offline ? "Network collection paused" : "Network collection enabled"))}</span>
              </span>
            </label>
          </div>
          <div class="control-section">
            <div class="control-section-header">
              <h3>${escapeHtml(t("Allowed domains"))}</h3>
              <span>${escapeHtml(t("{count} domains", { count: domains.length }))}</span>
            </div>
            <div class="domain-list">
              ${domains.length
                ? domains.map((domain) => `<span class="domain-item">${escapeHtml(domain)}</span>`).join("")
                : `<span class="domain-empty">${escapeHtml(t("No domains configured"))}</span>`}
            </div>
            <form class="domain-form" id="domain-form">
              <label class="sr-only" for="domain-input">${escapeHtml(t("Domain"))}</label>
              <input id="domain-input" name="domain" type="text" placeholder="research.example.org" inputmode="url" autocomplete="off" required minlength="3" maxlength="253">
              <button class="button button-secondary" type="submit"><i data-lucide="plus" aria-hidden="true"></i><span>${escapeHtml(t("Add domain"))}</span></button>
            </form>
          </div>`;
        document.getElementById("offline-toggle").addEventListener("change", updateOfflineMode);
        document.getElementById("domain-form").addEventListener("submit", submitDomain);
        applyOfflineState();
      }
    }

    if (!state.loading.has("memory")) {
      if (state.errors.memory) {
        memoryContent.innerHTML = errorState("memory");
        bindRetryButtons(memoryContent);
      } else if (!preferenceEntries.length) {
        memoryContent.innerHTML = `<div class="control-empty"><i data-lucide="brain" aria-hidden="true"></i><span>${escapeHtml(t("No saved preferences"))}</span></div>`;
      } else {
        memoryContent.innerHTML = `
          <div class="control-section-header">
            <h3>${escapeHtml(t("Saved preferences"))}</h3>
            <span>${escapeHtml(t("{count} preferences", { count: preferenceEntries.length }))}</span>
          </div>
          <div class="preference-list">
            ${preferenceEntries.map(([key, value]) => `
              <div class="preference-row">
                <span class="preference-key" title="${escapeHtml(key)}">${escapeHtml(key)}</span>
                <span class="preference-value">${escapeHtml(formatControlValue(value))}</span>
              </div>`).join("")}
          </div>`;
      }
    }

    if (!state.loading.has("audit")) {
      const auditCount = document.getElementById("audit-count");
      if (state.errors.audit) {
        auditCount.textContent = t("Unable to load data");
        auditContent.innerHTML = errorState("audit");
        bindRetryButtons(auditContent);
      } else {
        auditCount.textContent = t("{count} events", { count: state.audit.length });
        if (!state.audit.length) {
          auditContent.innerHTML = `<div class="control-empty"><i data-lucide="scroll-text" aria-hidden="true"></i><span>${escapeHtml(t("No audit events"))}</span></div>`;
        } else {
          auditContent.innerHTML = `
            <table class="data-table">
              <thead><tr>
                <th style="width:22%">${escapeHtml(t("Event"))}</th>
                <th style="width:16%">${escapeHtml(t("Actor"))}</th>
                <th style="width:44%">${escapeHtml(t("Detail"))}</th>
                <th style="width:18%">${escapeHtml(t("Time"))}</th>
              </tr></thead>
              <tbody>${state.audit.map((event) => `
                <tr>
                  <td><span class="audit-event">${escapeHtml(humanize(get(event, ["event_type", "type", "event"], "Unknown")))}</span></td>
                  <td>${escapeHtml(displayValue(get(event, ["actor", "source"], "local-user")))}</td>
                  <td><span class="audit-detail" title="${escapeHtml(formatControlValue(get(event, ["detail", "details", "payload"], {})))}">${escapeHtml(formatControlValue(get(event, ["detail", "details", "payload"], {})))}</span></td>
                  <td>${escapeHtml(formatDate(get(event, ["created_at", "timestamp", "time"]), true))}</td>
                </tr>`).join("")}</tbody>
            </table>`;
        }
      }
    }
    refreshIcons();
  }

  function formatControlValue(value) {
    if (value === null || value === undefined) return t("Not available");
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }

  function applyOfflineState() {
    if (!state.permissions) return;
    const offline = Boolean(state.permissions.offline);
    document.body.classList.toggle("is-offline", offline);
    document.querySelectorAll('[data-open-dialog="github-dialog"], [data-open-dialog="rss-dialog"]').forEach((button) => {
      button.disabled = offline;
      button.setAttribute("aria-disabled", String(offline));
    });
  }

  async function updateOfflineMode(event) {
    const input = event.currentTarget;
    const enabled = input.checked;
    input.disabled = true;
    try {
      state.permissions = await request("/permissions/offline", {
        method: "POST",
        body: JSON.stringify({ enabled }),
      });
      delete state.errors.permissions;
      toast(t(enabled ? "Offline mode enabled." : "Offline mode disabled."));
      renderControls();
      setRuntime("online");
      await Promise.all([loadDashboard({ quiet: true }), loadAudit({ quiet: true })]);
    } catch (error) {
      toast(error.message, "error");
      renderControls();
    }
  }

  async function submitDomain(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.domain;
    const raw = input.value.trim();
    const domain = raw.replace(/^https?:\/\//i, "").split("/")[0].trim().toLowerCase();
    if (!domain) return;
    setFormPending(form, true);
    try {
      state.permissions = await request("/permissions/domains", {
        method: "POST",
        body: JSON.stringify({ domain }),
      });
      delete state.errors.permissions;
      form.reset();
      toast(t("Domain added."));
      renderControls();
      await loadAudit({ quiet: true });
    } catch (error) {
      toast(error.message, "error");
      setFormPending(form, false);
    }
  }

  function formatInterval(minutes) {
    if (minutes === 60) return t("Every hour");
    if (minutes === 360) return t("Every 6 hours");
    if (minutes === 720) return t("Every 12 hours");
    if (minutes === 1440) return t("Every day");
    if (state.locale === "zh") return `每 ${minutes} 分钟`;
    return `Every ${minutes} minutes`;
  }

  function emptyState(icon, title, message, seedAction = false, dialogId = "") {
    const action = seedAction
      ? `<button class="button button-primary" type="button" data-seed-demo><i data-lucide="database-zap" aria-hidden="true"></i><span>${escapeHtml(t("Seed demo"))}</span></button>`
      : dialogId ? `<button class="button button-primary" type="button" data-open-dialog="${escapeHtml(dialogId)}"><i data-lucide="plus" aria-hidden="true"></i><span>${escapeHtml(t("New rule"))}</span></button>` : "";
    return `<div class="empty-state"><i data-lucide="${escapeHtml(icon)}" aria-hidden="true"></i><h2>${escapeHtml(t(title))}</h2><p>${escapeHtml(t(message))}</p>${action}</div>`;
  }

  function errorState(resource) {
    return `<div class="error-state"><i data-lucide="circle-alert" aria-hidden="true"></i><h2>${escapeHtml(t("Unable to load data"))}</h2><p>${escapeHtml(t("The local API did not return this resource."))}</p><button class="button button-secondary" type="button" data-retry="${escapeHtml(resource)}">${escapeHtml(t("Try again"))}</button></div>`;
  }

  function compactError(resource) {
    return `<div class="compact-row"><div class="compact-primary"><strong>${escapeHtml(t("Unable to load data"))}</strong><span>${escapeHtml(t("The local API did not return this resource."))}</span></div><button class="text-button" type="button" data-retry="${escapeHtml(resource)}">${escapeHtml(t("Try again"))}</button></div>`;
  }

  function renderChat() {
    const messages = document.getElementById("chat-messages");
    if (!state.messages.length) {
      document.getElementById("chat-empty")?.classList.remove("is-hidden");
    } else {
      messages.innerHTML = state.messages.map((message) => `
        <article class="message ${escapeHtml(message.role)}${message.error ? " is-error" : ""}">
          <div class="message-avatar" aria-hidden="true">${message.role === "user" ? "YOU" : "OA"}</div>
          <div class="message-body">
            <span class="message-label">${escapeHtml(t(message.role === "user" ? "You" : "Sentinel"))}</span>
            <div class="message-content">${message.pending ? `<div class="typing-indicator" aria-label="${escapeHtml(t("Processing"))}"><span></span><span></span><span></span></div>` : paragraphs(message.text)}</div>
          </div>
        </article>
      `).join("");
      messages.scrollTop = messages.scrollHeight;
    }
    renderChatSources();
  }

  function paragraphs(value) {
    return String(value || "").split(/\n{2,}/).filter(Boolean).map((paragraph) => `<p>${escapeHtml(paragraph).replaceAll("\n", "<br>")}</p>`).join("");
  }

  function renderChatSources() {
    const count = document.getElementById("chat-source-count");
    const container = document.getElementById("chat-sources");
    count.textContent = t("{count} cited", { count: state.latestCitations.length });
    if (!state.latestCitations.length) {
      container.innerHTML = `<div class="rail-empty">${escapeHtml(t("Sources appear with an answer."))}</div>`;
      return;
    }
    container.innerHTML = state.latestCitations.map((source, index) => {
      const content = `<span class="evidence-index">S${index + 1}</span><strong>${escapeHtml(source.label)}</strong><span>${escapeHtml(source.excerpt || source.url || t("Open source"))}</span>`;
      return source.url
        ? `<a class="evidence-item" href="${escapeHtml(source.url)}" target="_blank" rel="noopener noreferrer">${content}</a>`
        : `<div class="evidence-item">${content}</div>`;
    }).join("");
  }

  function renderCardDetail(card) {
    if (!card) return;
    document.getElementById("card-dialog-title").textContent = card.title;
    const evidence = card.evidence.length
      ? card.evidence.map((item) => `
        <div class="detail-evidence-item">
          <strong>${escapeHtml(item.label)}</strong>
          ${item.excerpt ? `<blockquote>${escapeHtml(item.excerpt)}</blockquote>` : ""}
          ${item.url ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("Open immutable source"))}</a>` : ""}
        </div>`).join("")
      : `<p>${escapeHtml(t("No evidence snippets were returned for this card."))}</p>`;
    const content = document.getElementById("card-dialog-content");
    content.innerHTML = `
      ${card.summary ? `<p class="detail-summary">${escapeHtml(card.summary)}</p>` : ""}
      <div class="detail-metadata">
        <div class="detail-meta-item"><span>${escapeHtml(t("Family"))}</span><strong>${escapeHtml(card.family)}</strong></div>
        <div class="detail-meta-item"><span>${escapeHtml(t("Market"))}</span><strong>${escapeHtml(card.market)}</strong></div>
        <div class="detail-meta-item"><span>${escapeHtml(t("Timeframe"))}</span><strong>${escapeHtml(card.timeframe)}</strong></div>
        <div class="detail-meta-item"><span>${escapeHtml(t("License"))}</span><strong>${escapeHtml(card.license.value)}</strong></div>
      </div>
      ${card.entryLogic ? `<section class="detail-section"><h3>${escapeHtml(t("Entry logic"))}</h3><p>${escapeHtml(card.entryLogic)}</p></section>` : ""}
      ${card.exitLogic ? `<section class="detail-section"><h3>${escapeHtml(t("Exit logic"))}</h3><p>${escapeHtml(card.exitLogic)}</p></section>` : ""}
      ${card.risks ? `<section class="detail-section"><h3>${escapeHtml(t("Risk notes"))}</h3><p>${escapeHtml(card.risks)}</p></section>` : ""}
      <section class="detail-section"><h3>${escapeHtml(t("Evidence"))}</h3><div class="detail-evidence">${evidence}</div></section>
      <section class="detail-section"><h3>${escapeHtml(t("Source"))}</h3><p>${escapeHtml(card.sourceName)}${card.revision ? ` · ${escapeHtml(card.revision)}` : ""}</p>${card.sourceUrl ? `<a href="${escapeHtml(card.sourceUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(t("Open source"))}</a>` : ""}</section>
    `;
    openDialog("card-dialog");
  }

  async function openCardDetail(cardId) {
    if (!state.cardById.has(cardId)) return;
    try {
      const detail = normalizeCard(await request(`/cards/${encodeURIComponent(cardId)}`));
      state.cardById.set(cardId, detail);
      renderCardDetail(detail);
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function renderAll() {
    renderOverview();
    renderCards();
    renderSources();
    renderJobs();
    renderRules();
    renderControls();
    renderChat();
    const failures = Object.keys(state.errors).length;
    setRuntime(failures === 0 && !state.loading.size ? "online" : failures < RESOURCE_COUNT ? "partial" : "error");
    refreshIcons();
  }

  function setView(view, updateHash = true) {
    if (!document.querySelector(`[data-view-panel="${CSS.escape(view)}"]`)) view = "overview";
    state.view = view;
    document.querySelectorAll("[data-view-panel]").forEach((panel) => {
      const active = panel.dataset.viewPanel === view;
      panel.hidden = !active;
      panel.classList.toggle("is-active", active);
    });
    document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
      const active = button.dataset.view === view;
      button.classList.toggle("is-active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    if (updateHash && window.location.hash !== `#${view}`) history.pushState(null, "", `#${view}`);
    document.body.classList.remove("nav-open");
    window.scrollTo({ top: 0, behavior: "auto" });
    if (view === "chat") window.setTimeout(() => document.getElementById("chat-input").focus(), 0);
  }

  function openDialog(id) {
    const dialog = document.getElementById(id);
    if (!dialog) return;
    dialog.querySelectorAll(".form-error").forEach((error) => error.classList.add("is-hidden"));
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    refreshIcons();
  }

  function closeDialog(dialog) {
    if (!dialog) return;
    if (typeof dialog.close === "function") dialog.close();
    else dialog.removeAttribute("open");
  }

  function showFormError(form, error) {
    const container = form.querySelector(".form-error");
    if (!container) return;
    container.textContent = error.message || t("Request failed");
    container.classList.remove("is-hidden");
  }

  function setFormPending(form, pending) {
    form.querySelectorAll("button, input, select").forEach((control) => {
      if (control.type !== "button" || control.type === "submit") control.disabled = pending;
    });
    form.setAttribute("aria-busy", String(pending));
  }

  function toast(message, type = "success") {
    const container = document.getElementById("toast-region");
    const item = document.createElement("div");
    item.className = `toast ${type}`;
    item.innerHTML = `<i data-lucide="${type === "error" ? "circle-alert" : "circle-check"}" aria-hidden="true"></i><span>${escapeHtml(message)}</span>`;
    container.appendChild(item);
    refreshIcons();
    window.setTimeout(() => item.remove(), 4300);
  }

  async function seedDemo(button = null) {
    const buttons = [document.getElementById("seed-demo-button"), ...(button ? [button] : [])].filter(Boolean);
    buttons.forEach((item) => { item.disabled = true; });
    try {
      await request("/demo/seed", { method: "POST", body: JSON.stringify({}) });
      toast(t("Demo data indexed."));
      await loadAll({ quiet: true });
    } catch (error) {
      toast(error.message, "error");
    } finally {
      buttons.forEach((item) => { item.disabled = false; });
    }
  }

  async function submitGithub(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setFormPending(form, true);
    try {
      await request("/discover/github", {
        method: "POST",
        body: JSON.stringify({ query: data.get("query").trim(), limit: Number(data.get("limit")) }),
      });
      closeDialog(form.closest("dialog"));
      toast(t("GitHub discovery completed."));
      setView("jobs");
      await Promise.all([loadJobs({ quiet: true }), loadDashboard({ quiet: true })]);
    } catch (error) {
      showFormError(form, error);
    } finally {
      setFormPending(form, false);
    }
  }

  async function submitRss(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    setFormPending(form, true);
    try {
      await request("/ingest/rss", { method: "POST", body: JSON.stringify({ url: data.get("url").trim() }) });
      closeDialog(form.closest("dialog"));
      form.reset();
      toast(t("Feed ingestion completed."));
      setView("jobs");
      await Promise.all([loadJobs({ quiet: true }), loadDashboard({ quiet: true })]);
    } catch (error) {
      showFormError(form, error);
    } finally {
      setFormPending(form, false);
    }
  }

  async function submitWatch(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const kind = data.get("kind");
    const value = data.get("config_value").trim();
    const config = kind === "rss" ? { url: value } : { query: value, limit: 10 };
    setFormPending(form, true);
    try {
      await request("/watch-rules", {
        method: "POST",
        body: JSON.stringify({
          name: data.get("name").trim(),
          kind,
          config,
          interval_minutes: Number(data.get("interval_minutes")),
        }),
      });
      closeDialog(form.closest("dialog"));
      form.reset();
      syncWatchForm();
      toast(t("Watch rule created."));
      await Promise.all([loadWatchRules({ quiet: true }), loadDashboard({ quiet: true })]);
    } catch (error) {
      showFormError(form, error);
    } finally {
      setFormPending(form, false);
    }
  }

  function syncWatchForm() {
    const kind = document.getElementById("watch-kind").value;
    const label = document.getElementById("watch-config-label");
    const input = document.getElementById("watch-config-value");
    if (kind === "rss") {
      label.textContent = t("Feed URL");
      input.type = "url";
      input.placeholder = "https://example.org/feed.xml";
    } else {
      label.textContent = t("Repository query");
      input.type = "text";
      input.placeholder = "mean reversion language:python";
    }
  }

  async function submitChat(event) {
    event.preventDefault();
    const input = document.getElementById("chat-input");
    const question = input.value.trim();
    if (!question) return;
    input.value = "";
    resizeChatInput();
    state.messages.push({ role: "user", text: question });
    state.messages.push({ role: "agent", text: "", pending: true });
    renderChat();
    const submit = event.currentTarget.querySelector("button[type='submit']");
    submit.disabled = true;
    try {
      const payload = await request("/chat", {
        method: "POST",
        timeout: 90000,
        body: JSON.stringify({ question, session_id: state.sessionId }),
      });
      const answer = displayValue(get(payload, ["answer", "message", "response", "data.answer"]), "The local agent returned no answer.");
      state.messages[state.messages.length - 1] = { role: "agent", text: answer };
      state.latestCitations = normalizeEvidence(payload);
      const returnedSession = get(payload, ["session_id", "data.session_id"]);
      if (returnedSession) {
        state.sessionId = String(returnedSession);
        localStorage.setItem("oas.session", state.sessionId);
      }
    } catch (error) {
      state.messages[state.messages.length - 1] = {
        role: "agent",
        text: `${t("The agent could not answer this question.")} ${error.message}`,
        error: true,
      };
      state.latestCitations = [];
    } finally {
      submit.disabled = false;
      renderChat();
      input.focus();
    }
  }

  function resizeChatInput() {
    const input = document.getElementById("chat-input");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
  }

  function retryResource(resource) {
    const loaders = {
      dashboard: loadDashboard,
      cards: loadCards,
      jobs: loadJobs,
      watchRules: loadWatchRules,
      permissions: loadPermissions,
      memory: loadMemory,
      audit: loadAudit,
      controls: loadControls,
    };
    loaders[resource]?.();
  }

  function bindCardOpeners(container) {
    container.querySelectorAll("[data-card-id]").forEach((element) => {
      const open = () => openCardDetail(element.dataset.cardId);
      element.addEventListener("click", open);
      element.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      });
    });
  }

  function bindRetryButtons(container = document) {
    container.querySelectorAll("[data-retry]").forEach((button) => {
      button.addEventListener("click", () => retryResource(button.dataset.retry), { once: true });
    });
  }

  function bindSeedButtons(container = document) {
    container.querySelectorAll("[data-seed-demo]").forEach((button) => {
      button.addEventListener("click", () => seedDemo(button), { once: true });
    });
  }

  function bindDialogOpeners(container = document) {
    container.querySelectorAll("[data-open-dialog]").forEach((button) => {
      button.addEventListener("click", () => openDialog(button.dataset.openDialog));
    });
  }

  function bindEvents() {
    document.addEventListener("click", (event) => {
      const viewButton = event.target.closest("[data-view]");
      if (viewButton) setView(viewButton.dataset.view);
    });
    document.querySelectorAll("[data-locale]").forEach((button) => {
      button.addEventListener("click", () => switchLocale(button.dataset.locale));
    });
    bindDialogOpeners();
    document.querySelectorAll("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => closeDialog(button.closest("dialog")));
    });
    document.querySelectorAll("dialog").forEach((dialog) => {
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) closeDialog(dialog);
      });
    });
    document.getElementById("mobile-menu-button").addEventListener("click", () => document.body.classList.add("nav-open"));
    document.getElementById("sidebar-scrim").addEventListener("click", () => document.body.classList.remove("nav-open"));
    document.getElementById("mobile-refresh-button").addEventListener("click", () => loadAll({ quiet: true }));
    document.getElementById("seed-demo-button").addEventListener("click", () => seedDemo());
    document.querySelectorAll("[data-refresh]").forEach((button) => {
      button.addEventListener("click", () => retryResource(button.dataset.refresh));
    });
    document.getElementById("cards-search").addEventListener("input", renderCards);
    document.getElementById("cards-family-filter").addEventListener("change", renderCards);
    document.getElementById("cards-license-filter").addEventListener("change", renderCards);
    document.getElementById("jobs-filter").addEventListener("click", (event) => {
      const button = event.target.closest("[data-job-filter]");
      if (!button) return;
      state.jobFilter = button.dataset.jobFilter;
      document.querySelectorAll("[data-job-filter]").forEach((item) => {
        const active = item === button;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-pressed", String(active));
      });
      renderJobs();
    });
    document.getElementById("github-form").addEventListener("submit", submitGithub);
    document.getElementById("rss-form").addEventListener("submit", submitRss);
    document.getElementById("watch-form").addEventListener("submit", submitWatch);
    document.getElementById("watch-kind").addEventListener("change", syncWatchForm);
    document.getElementById("chat-form").addEventListener("submit", submitChat);
    document.getElementById("chat-input").addEventListener("input", resizeChatInput);
    document.getElementById("chat-input").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        document.getElementById("chat-form").requestSubmit();
      }
    });
    document.querySelectorAll("[data-question]").forEach((button) => {
      button.addEventListener("click", () => {
        document.getElementById("chat-input").value = t(button.dataset.question);
        resizeChatInput();
        document.getElementById("chat-form").requestSubmit();
      });
    });
    window.addEventListener("hashchange", () => setView(window.location.hash.slice(1) || "overview", false));
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) loadAll({ quiet: true });
    });
  }

  function init() {
    captureStaticStrings();
    applyStaticTranslations();
    bindEvents();
    syncWatchForm();
    setView(window.location.hash.slice(1) || "overview", false);
    refreshIcons();
    loadAll();
    window.setInterval(() => {
      if (!document.hidden) {
        loadDashboard({ quiet: true });
        loadJobs({ quiet: true });
        loadWatchRules({ quiet: true });
        if (state.view === "local-controls") loadAudit({ quiet: true });
      }
    }, 30000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

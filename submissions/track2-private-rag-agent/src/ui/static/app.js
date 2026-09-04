/* ============================================================
   Private RAG Agent — 前端逻辑
   SSE 流式对话 · 富事件渲染 · 运行轨迹面板 · GPU 监控
   ============================================================ */
(function () {
  'use strict';

  /* ---------- 全局状态 ---------- */
  const state = {
    sessionId: 'default',
    mode: 'single',
    toolsEnabled: true,
    busy: false,
    streaming: false,         // 是否正在流式生成（键盘快捷键守卫用）
    history: [],           // [{role, content(html), text, citations, verification}]
    trace: [],             // 当前消息的工具步骤
    currentMsgEl: null,    // 正在流式渲染的 assistant 消息气泡
    currentMsgText: '',
    currentCiteSeen: new Map(),
    planSteps: [],
    subCount: 0,
    lastQuery: '',          // 用户原始问题
    lastSearchQuery: '',    // 最近一次 rag_search 检索词（供来源抽屉高亮）
    abortCtrl: null,
    gpuHistory: [],        // [{util, vram, temp, power}]
  };

  /* ---------- DOM 引用 ---------- */
  const $ = (id) => document.getElementById(id);
  const chatList = $('chat-list');
  const chatScroll = $('chat-scroll');
  const emptyState = $('empty-state');
  const input = $('input');
  const sendBtn = $('send-btn');
  const traceList = $('trace-list');
  const traceEmpty = $('trace-empty');
  const sessionList = $('session-list');
  const sessionTitle = $('session-title');
  const kbList = $('kb-list');
  const kbStats = $('kb-stats');
  const gpuMetrics = $('gpu-metrics');
  const gpuChart = $('gpu-chart');
  const gpuNote = $('gpu-note');

  /* ---------- 国际化（默认英文，可在设置切换中文） ---------- */
  const I18N = {
    en: {
      'brand': 'Private RAG',
      'session.new': 'New session',
      'session.none': 'No sessions yet',
      'mode.toast': 'Multi-Agent: decompose → research → fact-check → synthesize',
      'gpu.badgeTitle': 'AMD GPU live status',
      'gpu.demoChip': 'Demo',
      'settings.title': 'System info',
      'chat.new': 'New chat',
      'kb.label': 'Knowledge base',
      'kb.import': 'Import docs',
      'kb.importTitle': 'Import documents (PDF/Word/Markdown/Excel/PPT)',
      'kb.folder': 'Scan folder',
      'kb.folderTitle': 'Select a folder and import all documents inside',
      'kb.scanAll': 'Read all',
      'kb.scanAllTitle': 'Read all supported documents on this machine',
      'kb.scanning': 'Scanning…',
      'kb.allScanning': 'Reading all local documents — this may take a few minutes…',
      'kb.folderIngested': 'Folder: {n} files · {c} chunks ingested',
      'kb.allIngested': 'Read-all done — {f} files · {c} chunks ingested',
      'kb.privacy': '100% local · works offline',
      'empty.title': 'Local Private Agent',
      'empty.sub1': 'Search your knowledge base for traceable answers.',
      'empty.sub2': 'Fully local inference — data never leaves this machine.',
      'sug1.title': 'Project overview', 'sug1.sub': 'Stack · AMD optimization · deploy',
      'sug2.title': 'Summarize doc', 'sug2.sub': 'Grounded in the knowledge base',
      'sug3.title': 'Architecture', 'sug3.sub': 'Inference / retrieval / memory',
      'sug4.title': 'Browse KB', 'sug4.sub': 'list_docs tool',
      'input.placeholder': 'Ask my knowledge base, e.g. what stack does my project use?',
      'mode.title': 'Inference mode',
      'mode.single': 'Single Agent',
      'mode.multi': 'Multi-Agent',
      'mode.parallel': 'Parallel',
      'tools.label': 'Tool calls',
      'send.title': 'Send (Enter)',
      'hint.enter': 'Enter to send',
      'hint.shift': 'Shift+Enter for newline',
      'hint.cite': 'Answers include citations',
      'tab.trace': 'Activity',
      'tab.gpu': 'GPU Monitor',
      'trace.empty1': 'After you send a question, every',
      'trace.empty2': 'agent action appears here in real time.',
      'modal.title': 'System info',
      'modal.loading': 'Loading…',
      'drawer.doc': 'Document',
      'drawer.loading': 'Loading source…',
      'tb.param': 'Args',
      'tb.result': 'Result',
      'tb.running': 'Running',
      'tb.fail': 'Failed',
      'tb.error': 'Error',
      'trust.unknown': 'Confidence pending',
      'trust.supported': 'Supported · evidence {p}%',
      'trust.partial': 'Partially supported · {p}%',
      'trust.unsupported': 'Unsupported · {p}%',
      'trust.confLabel': ' · confidence {c}',
      'trust.conf.high': 'high',
      'trust.conf.medium': 'medium',
      'trust.conf.low': 'low',
      'trust.excluded': ' · {n} sub-task(s) failed verification',
      'cite.head': 'Sources',
      'drawer.chars': '{n} chars · local KB',
      'drawer.truncated': ' (truncated)',
      'err.readDoc': 'Cannot read document: {msg}',
      'err.request': 'Request failed: {msg}',
      'err.service': 'Service error: {msg}',
      'err.unknown': 'unknown',
      'status.parallel': 'Running <em>{n}</em> sub-tasks in parallel…',
      'status.subtasks': '{n} sub-tasks',
      'status.done': 'Completed <em>{d}/{t}</em> sub-tasks…',
      'status.synth': 'Synthesizing <em>{n}</em> sub-reports…',
      'trace.research': 'Research · {name}',
      'kb.delete': 'Delete',
      'kb.removeTitle': 'Remove from knowledge base',
      'kb.removeConfirm': 'Remove {doc} from the knowledge base?',
      'kb.deleted': 'Deleted {doc}',
      'kb.deleteFail': 'Delete failed: {msg}',
      'kb.pending': 'Pending',
      'kb.toIngest': 'Import',
      'kb.empty': 'Knowledge base is empty — click "Import docs" to add documents',
      'kb.count': '{d} docs · {c} chunks',
      'kb.scanDone': 'Scan complete — {n} chunks ingested',
      'kb.scanFail': 'Scan failed: {msg}',
      'kb.ingested': '{file} → {n} chunks ingested',
      'kb.ingestFail': '{file}: {msg}',
      'kb.uploadFail': 'Upload of {file} failed: {msg}',
      'gpu.name': 'GPU name',
      'gpu.util': 'Utilization',
      'gpu.vram': 'VRAM',
      'gpu.temp': 'Temperature',
      'gpu.power': 'Power',
      'gpu.clock': 'Clock',
      'gpu.demoNote': '<b>Demo data</b> — no AMD GPU detected. Real rocm-smi metrics appear on Radeon Cloud.',
      'gpu.sourceNote': 'Source: {src} · refresh 2s',
      'modal.backend': 'Backend', 'modal.model': 'Model', 'modal.url': 'Service URL',
      'modal.retrieval': 'Retrieval', 'modal.retrievalType': 'Type', 'modal.hybrid': 'BM25 + vector', 'modal.vector': 'vector only',
      'modal.rerank': 'Rerank', 'modal.embedding': 'Embedding',
      'modal.kb': 'Knowledge base', 'modal.docs': 'Docs', 'modal.chunks': 'Chunks', 'modal.dir': 'Directory',
      'modal.gpu': 'AMD GPU', 'modal.status': 'Status', 'modal.connected': 'Connected',
      'modal.notDetected': 'Not detected', 'modal.time': 'Server time',
      'verify.head': 'Fact check',
      'verify.supported': 'Supported', 'verify.partial': 'Partially supported', 'verify.unsupported': 'Unsupported',
      'verify.excluded': 'Failed · excluded',
      'excl.no_sources': 'No retrievable sources for this sub-task; the conclusion relies on model knowledge.',
      'excl.low_grounding': 'Grounding {g} below the verification threshold — excluded from synthesis.',
      'sent.supported': 'Supported', 'sent.partial': 'Partial', 'sent.unsupported': 'Unsupported',
      'sv.toggle': 'Sentence verification',
      'lang.label': 'Language',
      'lang.en': 'English',
      'lang.zh': '中文',
    },
    zh: {
      'brand': 'Private RAG',
      'session.new': '新会话',
      'session.none': '暂无历史会话',
      'mode.toast': '多 Agent 并行：分解 → 研究 → 核查 → 汇总',
      'gpu.badgeTitle': 'AMD GPU 实时状态',
      'gpu.demoChip': '演示',
      'settings.title': '系统信息',
      'chat.new': '新建会话',
      'kb.label': '知识库',
      'kb.import': '导入文档',
      'kb.importTitle': '导入文档（PDF/Word/Markdown/Excel/PPT）',
      'kb.folder': '扫描文件夹',
      'kb.folderTitle': '选中一个文件夹，导入其中全部文档',
      'kb.scanAll': '全部读取',
      'kb.scanAllTitle': '读取本机所有受支持的文档',
      'kb.scanning': '正在扫描…',
      'kb.allScanning': '正在读取本机所有文档…可能需要几分钟',
      'kb.folderIngested': '文件夹：{n} 个文件 · {c} 片段已入库',
      'kb.allIngested': '全部读取完成 — {f} 个文件 · {c} 片段',
      'kb.privacy': '数据 100% 本地 · 断网可用',
      'empty.title': '本地私有智能体',
      'empty.sub1': '检索你的知识库，生成可追溯的回答。',
      'empty.sub2': '全程本地推理，数据不出本机。',
      'sug1.title': '项目全景', 'sug1.sub': '技术栈 · AMD 优化 · 部署',
      'sug2.title': '总结文档', 'sug2.sub': '基于知识库内容归纳',
      'sug3.title': '架构解读', 'sug3.sub': '推理 / 检索 / 记忆链路',
      'sug4.title': '盘点知识库', 'sug4.sub': 'list_docs 工具',
      'input.placeholder': '问我的知识库，例如：我的项目用了什么技术栈？',
      'mode.title': '推理模式',
      'mode.single': '单 Agent',
      'mode.multi': '多 Agent',
      'mode.parallel': '并行',
      'tools.label': '工具调用',
      'send.title': '发送 (Enter)',
      'hint.enter': 'Enter 发送',
      'hint.shift': 'Shift+Enter 换行',
      'hint.cite': '回答自动附引用来源',
      'tab.trace': '运行轨迹',
      'tab.gpu': 'GPU 监控',
      'trace.empty1': '发送问题后，这里会实时显示',
      'trace.empty2': 'Agent 的每一步动作。',
      'modal.title': '系统信息',
      'modal.loading': '加载中…',
      'drawer.doc': '文档',
      'drawer.loading': '加载原文…',
      'tb.param': '参数',
      'tb.result': '结果',
      'tb.running': '运行中',
      'tb.fail': '失败',
      'tb.error': '错误',
      'trust.unknown': '可信度待确认',
      'trust.supported': '已支撑 · 证据强度 {p}%',
      'trust.partial': '部分支撑 · {p}%',
      'trust.unsupported': '证据不足 · {p}%',
      'trust.confLabel': ' · 置信度{c}',
      'trust.conf.high': '高',
      'trust.conf.medium': '中',
      'trust.conf.low': '低',
      'trust.excluded': ' · {n} 个子任务未通过核查',
      'cite.head': '引用来源',
      'drawer.chars': '{n} 字符 · 本地知识库',
      'drawer.truncated': '（已截断）',
      'err.readDoc': '无法读取文档：{msg}',
      'err.request': '请求失败：{msg}',
      'err.service': '服务错误：{msg}',
      'err.unknown': '未知',
      'status.parallel': '并行执行 <em>{n}</em> 个子任务…',
      'status.subtasks': '{n} 个子任务',
      'status.done': '已完成 <em>{d}/{t}</em> 个子任务…',
      'status.synth': '正在综合 <em>{n}</em> 份子报告…',
      'trace.research': '研究 · {name}',
      'kb.delete': '删除',
      'kb.removeTitle': '从知识库删除',
      'kb.removeConfirm': '从知识库删除 {doc}？',
      'kb.deleted': '已删除 {doc}',
      'kb.deleteFail': '删除失败：{msg}',
      'kb.pending': '待导入',
      'kb.toIngest': '待入库',
      'kb.empty': '知识库为空，点击"导入文档"添加',
      'kb.count': '{d} 份文档 · {c} 片段',
      'kb.scanDone': '扫描目录完成，共入库 {n} 片段',
      'kb.scanFail': '扫描失败：{msg}',
      'kb.ingested': '{file} → {n} 片段已入库',
      'kb.ingestFail': '{file}：{msg}',
      'kb.uploadFail': '{file} 上传失败：{msg}',
      'gpu.name': 'GPU 名称',
      'gpu.util': '利用率',
      'gpu.vram': '显存占用',
      'gpu.temp': '温度',
      'gpu.power': '功耗',
      'gpu.clock': '核心时钟',
      'gpu.demoNote': '<b>演示数据</b> — 本机未检测到 AMD GPU。部署到 Radeon Cloud 后显示真实 rocm-smi 指标。',
      'gpu.sourceNote': '来源：{src} · 实时刷新 2s',
      'modal.backend': '后端', 'modal.model': '模型', 'modal.url': '服务地址',
      'modal.retrieval': '检索', 'modal.retrievalType': '方式', 'modal.hybrid': 'BM25 + 向量', 'modal.vector': '纯向量',
      'modal.rerank': '重排', 'modal.embedding': 'Embedding',
      'modal.kb': '知识库', 'modal.docs': '文档', 'modal.chunks': '片段', 'modal.dir': '目录',
      'modal.gpu': 'AMD GPU', 'modal.status': '状态', 'modal.connected': '已连接',
      'modal.notDetected': '未检测到', 'modal.time': '服务器时间',
      'verify.head': '事实核查',
      'verify.supported': '已支撑', 'verify.partial': '部分支撑', 'verify.unsupported': '证据不足',
      'verify.excluded': '未通过核查 · 已排除',
      'excl.no_sources': '该子任务未检索到可用来源，结论基于模型常识。',
      'excl.low_grounding': 'grounding {g} 低于核查阈值，未通过核查。',
      'sent.supported': '已支撑', 'sent.partial': '部分支撑', 'sent.unsupported': '无支撑',
      'sv.toggle': '逐句校验',
      'lang.label': '语言',
      'lang.en': 'English',
      'lang.zh': '中文',
    },
  };
  let LANG = 'en';
  try { LANG = localStorage.getItem('privrag_lang') || 'en'; } catch (e) {}
  const DICT = I18N[LANG] || I18N.en;
  function t(key, vars) {
    let s = DICT[key] !== undefined ? DICT[key] : (I18N.en[key] !== undefined ? I18N.en[key] : key);
    if (vars) for (const k in vars) s = s.split('{' + k + '}').join(vars[k]);
    return s;
  }
  function applyI18n() {
    // 静态文案（data-i18n 属性）
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      el.textContent = t(key);
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      el.setAttribute('placeholder', t(el.getAttribute('data-i18n-placeholder')));
    });
    document.documentElement.lang = LANG === 'zh' ? 'zh-CN' : 'en';
    document.title = LANG === 'zh' ? 'Private RAG Agent · 本地私有智能体' : 'Private RAG Agent · Local Private Agent';
    // 语言选择器状态
    const sel = document.getElementById('lang-select');
    if (sel) sel.value = LANG;
    // 动态面板重新渲染（GPU 标签等）
    if (typeof refreshGpu === 'function') refreshGpu();
    if (typeof loadSessions === 'function') loadSessions();
  }
  function setLang(lang) {
    LANG = lang === 'zh' ? 'zh' : 'en';
    try { localStorage.setItem('privrag_lang', LANG); } catch (e) {}
    location.reload();
  }

  /* ---------- 工具函数 ---------- */
  function escapeHtml(s) {
    return (s || '').replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }
  function escapeRegex(s) {
    return (s || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }
  function queryMarkRanges(doc, raw) {
    /* 高亮定位：查询与文档共有的 2-gram 重叠区间。
       原理与 BM25 检索一致（中文 2-gram 窗口），因此任意口语化问法
       都能标出文档里真正相关的段落，而不是要求整句逐字出现。 */
    const clean = (raw || '').replace(/[^\p{L}\p{N}]/gu, '').toLowerCase();
    if (clean.length < 2 || !doc) return null;
    const d = doc.toLowerCase();
    const grams = new Set();
    for (let i = 0; i < clean.length - 1; i++) grams.add(clean.slice(i, i + 2));
    // 统计文档 2-gram 频次，太常见的（如“系统”“进行”）不作为高亮依据
    const freq = new Map();
    for (let i = 0; i < d.length - 1; i++) {
      const g = d.slice(i, i + 2);
      freq.set(g, (freq.get(g) || 0) + 1);
    }
    const cap = Math.max(6, d.length / 250);
    const ranges = [];
    let start = -1;
    for (let i = 0; i < d.length - 1; i++) {
      const g = d.slice(i, i + 2);
      const hit = grams.has(g) && (freq.get(g) || 0) <= cap;
      if (hit) { if (start < 0) start = i; }
      else if (start >= 0) { ranges.push([start, i + 2]); start = -1; }
    }
    if (start >= 0) ranges.push([start, d.length]);
    if (!ranges.length) return null;
    // 合并相距 ≤ 12 字符的相邻区间，避免高亮碎片化
    const merged = [ranges[0]];
    for (let i = 1; i < ranges.length; i++) {
      const last = merged[merged.length - 1];
      if (ranges[i][0] - last[1] <= 12) last[1] = ranges[i][1];
      else merged.push(ranges[i]);
    }
    return merged;
  }
  function debounce(fn, ms) {
    let t; return function (...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
  }
  function fmtTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (d.toDateString() === now.toDateString()) return hm;
    if (d.getTime() > now.getTime() - 7 * 864e5) return `${d.getMonth() + 1}/${d.getDate()} ${hm}`;
    return `${d.getFullYear()}/${d.getMonth() + 1}/${d.getDate()}`;
  }
  function toast(msg, isErr = false) {
    const t = $('toast');
    t.textContent = msg;
    t.className = 'toast' + (isErr ? ' err' : '');
    t.classList.remove('hidden');
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.add('hidden'), 3200);
  }
  function api(path, opts = {}) {
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    return fetch(path, opts).then(async r => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || data.error || r.statusText);
      return data;
    });
  }

  /* ---------- Markdown 渲染 ---------- */
  function renderMarkdown(text) {
    try {
      let html = marked.parse(text || '', { breaks: true, gfm: true });
      html = DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true },
        ADD_ATTR: ['target'],
      });
      // 代码高亮
      const wrap = document.createElement('div');
      wrap.innerHTML = html;
      wrap.querySelectorAll('pre code').forEach(el => {
        try { hljs.highlightElement(el); } catch (e) {}
      });
      return wrap.innerHTML;
    } catch (e) {
      return escapeHtml(text);
    }
  }

  /* ---------- 引用提取（从 markdown 文本） ---------- */
  function extractCitations(text) {
    const set = new Set();
    const re = /\[来源[:：]?\s*([^\]\[]+?)\]/g;
    let m;
    while ((m = re.exec(text || '')) !== null) {
      let name = m[1].trim();
      name = name.replace(/[，。；,;）)\]].*$/, '');
      if (name) set.add(name);
    }
    return [...set];
  }

  /* ---------- 消息渲染 ---------- */
  function appendUserMsg(text) {
    emptyState.classList.add('hidden');
    const el = document.createElement('div');
    el.className = 'msg user';
    el.innerHTML = `
      <div class="avatar">${LANG === 'zh' ? '我' : 'You'}</div>
      <div class="bubble">${escapeHtml(text)}</div>`;
    chatList.appendChild(el);
    scrollBottom();
    return el;
  }

  function appendAssistantMsg() {
    emptyState.classList.add('hidden');
    const el = document.createElement('div');
    el.className = 'msg assistant';
    el.innerHTML = `
      <div class="avatar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 2 L21 7 L21 17 L12 22 L3 17 L3 7 Z"/></svg>
      </div>
      <div class="bubble">
        <div class="md stream"></div>
      </div>`;
    chatList.appendChild(el);
    scrollBottom();
    return el;
  }

  function renderCurrentStream() {
    if (!state.currentMsgEl) return;
    const md = state.currentMsgEl.querySelector('.md.stream');
    const cursor = state.currentMsgText.endsWith('\n') || !state.currentMsgText ? '' : '<span class="type-cursor"></span>';
    md.innerHTML = renderMarkdown(state.currentMsgText) + cursor;
    scrollBottom();
  }

  /* ---------- 运行轨迹面板 ---------- */
  function addTraceStep(name, args, status, dur) {
    traceEmpty.classList.add('hidden');
    const card = document.createElement('div');
    card.className = 'tool-step' + (status === 'running' ? '' : ' open');
    const argsJson = args ? escapeHtml(JSON.stringify(args, null, 1)) : '';
    const icon = toolIcon(name);
    card.innerHTML = `
      <div class="tool-step-head">
        ${icon}
        <span class="tool-name">${escapeHtml(name)}</span>
        <span class="tool-status">
          ${status === 'running'
            ? '<span class="st-running"></span><span class="tool-dur">' + t('tb.running') + '</span>'
            : status === 'ok'
              ? '<span class="dot st-ok"></span><span class="tool-dur">' + (dur || '') + '</span>'
              : '<span class="dot st-err"></span><span class="tool-dur">' + t('tb.fail') + '</span>'}
        </span>
      </div>
      <div class="tool-step-body">
        ${argsJson ? `<div class="tb-label">${t('tb.param')}</div><pre>${argsJson}</pre>` : ''}
        <div class="tb-label">${t('tb.result')}</div>
        <pre class="tb-result">${escapeHtml(resultPreview(status))}</pre>
      </div>`;
    card.querySelector('.tool-step-head').addEventListener('click', () => {
      card.classList.toggle('open');
    });
    traceList.appendChild(card);
    // 展开时滚动到底
    traceList.scrollTop = traceList.scrollHeight;

    function resultPreview(st) {
      if (st === 'running') return '…';
      if (st === 'err') return t('tb.error');
      return '';
    }
    return card;
  }

  function toolIcon(name) {
    const common = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">`;
    const close = `</svg>`;
    if (name.includes('rag_search'))
      return common + `<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/></svg>`;
    if (name.includes('read_doc') || name.includes('list_doc') || name.includes('summarize'))
      return common + `<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>`;
    if (name.includes('web_search'))
      return common + `<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>`;
    return common + `<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>`;
  }

  /* ---------- 规划步骤展示（主区） ---------- */
  function renderPlan(panel, steps) {
    const inner = document.createElement('div');
    inner.className = 'plan-steps';
    steps.forEach((task, i) => {
      const row = document.createElement('div');
      row.className = 'plan-step';
      row.dataset.i = i;
      row.innerHTML = `<span class="step-num">${i + 1}</span><span class="step-text">${escapeHtml(task)}</span>`;
      inner.appendChild(row);
    });
    // 顶部进度条：completed/total
    const bar = document.createElement('div');
    bar.className = 'plan-bar';
    bar.innerHTML = `<div class="plan-bar-track"><div class="plan-bar-fill" style="width:0%"></div></div><span class="plan-bar-label mono">0/${steps.length}</span>`;
    panel.appendChild(bar);
    panel.appendChild(inner);
    panel._bar = bar;
    return inner;
  }
  function updatePlanStep(panel, index, status) {
    const rows = panel.querySelectorAll('.plan-step');
    if (rows[index]) {
      rows[index].classList.remove('running');
      rows[index].classList.add(status);
    }
    if (panel._bar) {
      const done = panel.querySelectorAll('.plan-step.done').length;
      const total = panel.querySelectorAll('.plan-step').length;
      panel._bar.querySelector('.plan-bar-fill').style.width = `${Math.round(done / total * 100)}%`;
      panel._bar.querySelector('.plan-bar-label').textContent = `${done}/${total}`;
    }
  }

  /* ---------- 可信度徽标 ---------- */
  function trustPill(verification) {
    if (!verification) return '';
    const g = verification.grounding;
    let level = 'low', label = t('trust.unknown');
    if (g == null) {
      // 无可校验内容（多 Agent 全无来源等）→ 显示"待确认"，绝不渲染 NaN%
      if (verification.excluded_count > 0) {
        label = t('verify.excluded') + t('trust.excluded', { n: verification.excluded_count });
      }
      return `<div class="trust-pill low">${t('trust.unknown')}</div>`;
    }
    if (g >= 0.6) { level = 'high'; label = t('trust.supported', { p: Math.round(g * 100) }); }
    else if (g >= 0.35) { level = 'med'; label = t('trust.partial', { p: Math.round(g * 100) }); }
    else { level = 'low'; label = t('trust.unsupported', { p: Math.round(g * 100) }); }
    // 多 Agent 模式附带的整体置信度分类与排除计数（后端 done 事件新增字段）
    const conf = verification.confidence;
    if (conf && g != null) {
      const map = { high: t('trust.conf.high'), medium: t('trust.conf.medium'), low: t('trust.conf.low') };
      if (map[conf]) label += t('trust.confLabel', { c: map[conf] });
    }
    if (verification.excluded_count > 0) {
      label += t('trust.excluded', { n: verification.excluded_count });
    }
    const icons = {
      high: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>`,
      med: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 3v18M3 12h18" opacity=".8"/></svg>`,
      low: `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>`,
    };
    return `<div class="trust-pill ${level}">${icons[level]}${label}</div>`;
  }

  /* 逐句校验面板：把 grounding 的每个句子支撑度可视化（✓ 已支撑 / △ 部分 / ✗ 无） */
  function renderSentenceVerify(msgEl, verification) {
    const sents = verification.sentences;
    if (!msgEl || !sents || !sents.length) return;
    let ok = 0, partial = 0, no = 0;
    const items = sents.map(s => {
      const lv = s.level || '';
      const cls = lv === 'supported' ? 'ok' : lv === 'partial' ? 'partial' : 'no';
      if (cls === 'ok') ok++;
      else if (cls === 'partial') partial++;
      else no++;
      const mark = cls === 'ok' ? '✓' : cls === 'partial' ? '△' : '✗';
      const pct = Math.round((s.support || 0) * 100);
      return `<div class="sv-item">
        <span class="sv-badge ${cls}" title="${cls === 'ok' ? t('sent.supported') : cls === 'partial' ? t('sent.partial') : t('sent.unsupported')}">${mark}</span>
        <span class="sv-text">${escapeHtml(s.text)}</span>
        <span class="sv-score">${pct}%</span>
      </div>`;
    }).join('');
    const el = document.createElement('div');
    el.className = 'sentence-verify';
    el.innerHTML = `
      <button class="sv-toggle" type="button">
        <span style="display:flex;align-items:center;gap:7px">
          <svg class="sv-arrow" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18l6-6-6-6"/></svg>
          ${t('sv.toggle')}
        </span>
        <span class="sv-count"><span class="ok">✓ ${ok}</span><span class="partial">△ ${partial}</span><span class="no">✗ ${no}</span></span>
      </button>
      <div class="sv-body">${items}</div>`;
    el.querySelector('.sv-toggle').addEventListener('click', () => el.classList.toggle('open'));
    msgEl.querySelector('.bubble').appendChild(el);
  }

  /* ---------- 引用来源卡片 ---------- */
  function renderCitations(msgEl, sources) {
    if (!sources || !sources.length) return;
    // 去重 + 相对归一化分数（最高分 → 100%，便于视觉比较）
    const seen = new Set();
    const uniq = sources.filter(s => !seen.has(s.doc) && seen.add(s.doc));
    const maxScore = Math.max(...uniq.map(s => s.score || 0), 0.0001);
    let chips = uniq.map(s => {
      const pct = Math.max(10, Math.round((s.score / maxScore) * 100));
      return `
      <div class="cite-chip" data-doc="${escapeHtml(s.doc)}">
        <span class="cite-ic"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></span>
        <span class="cite-name">${escapeHtml(s.doc)}</span>
        <span class="cite-relevance"><span class="rel-bar"><span class="rel-fill" style="width:${pct}%"></span></span>${pct}</span>
      </div>`;
    }).join('');
    const el = document.createElement('div');
    el.className = 'citations';
    el.innerHTML = `<div class="cite-head">${t('cite.head')}</div>${chips}`;
    el.querySelectorAll('.cite-chip').forEach(chip => {
      chip.addEventListener('click', () => openDocDrawer(chip.dataset.doc));
    });
    msgEl.querySelector('.bubble').appendChild(el);
  }

  /* ---------- 来源抽屉（点击引用 → 查看原文 + 高亮） ---------- */
  async function openDocDrawer(doc) {
    const mask = $('doc-drawer-mask');
    const body = $('drawer-body');
    $('drawer-doc-name').textContent = doc;
    $('drawer-doc-meta').textContent = t('drawer.loading');
    body.innerHTML = '<div class="drawer-loading">' + t('drawer.loading') + '</div>';
    mask.classList.remove('hidden');
    try {
      const data = await api(`/api/documents/${encodeURIComponent(doc)}?limit=6000`);
      $('drawer-doc-meta').textContent = t('drawer.chars', { n: data.chars })
        + (data.truncated ? t('drawer.truncated') : '') + ' · ' + (LANG === 'zh' ? '本地知识库' : 'local KB');
      // 高亮：用「查询 2-gram ∩ 文档」重叠定位相关区间（与 BM25 检索同套 tokenization）。
      // 任意问法都能标出文档里语义相关的段落，而不是要求整句逐字匹配。
      const docText = data.content;
      const ranges = queryMarkRanges(docText,
        (state.lastSearchQuery || state.lastQuery || '').trim());
      let content;
      if (ranges) {
        let out = '', last = 0;
        for (const [s, e] of ranges) {
          out += escapeHtml(docText.slice(last, s));
          out += `<mark>${escapeHtml(docText.slice(s, e))}</mark>`;
          last = e;
        }
        out += escapeHtml(docText.slice(last));
        content = out;
      } else {
        content = escapeHtml(docText);
      }
      body.innerHTML = content || '<div class="drawer-loading">' + t('drawer.loading') + '</div>';
    } catch (e) {
      body.innerHTML = `<div class="msg-error">${escapeHtml(t('err.readDoc', { msg: e.message }))}</div>`;
    }
  }
  $('drawer-close').addEventListener('click', () => $('doc-drawer-mask').classList.add('hidden'));
  $('doc-drawer-mask').addEventListener('click', (e) => {
    if (e.target === $('doc-drawer-mask')) $('doc-drawer-mask').classList.add('hidden');
  });

  /* ---------- SSE 流式对话 ---------- */
  async function sendMessage() {
    const text = input.value.trim();
    if (!text || state.busy) return;
    state.busy = true;
    state.streaming = true;
    sendBtn.disabled = true;
    input.value = '';
    autoGrow();

    appendUserMsg(text);
    state.lastQuery = text;   // 供来源抽屉高亮
    state.lastSearchQuery = '';  // 重置，避免旧消息的检索词污染来源抽屉高亮
    state.currentMsgEl = appendAssistantMsg();
    state.currentMsgText = '';
    state.trace = [];
    state.planSteps = [];
    traceList.innerHTML = '';
    traceEmpty.classList.remove('hidden');
    // 清理当前消息的旧引用区（等 done 事件统一渲染）
    state.currentCiteSeen = new Map();

    // 取消上一个
    if (state.abortCtrl) state.abortCtrl.abort();
    state.abortCtrl = new AbortController();

    const url = `/api/chat`;
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: state.sessionId,
          mode: state.mode,
          n_workers: 3,
          tools_enabled: state.toolsEnabled,
        }),
        signal: state.abortCtrl.signal,
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buf = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // 解析 SSE 事件（可能多条粘连）
        const parts = buf.split('\n\n');
        buf = parts.pop();
        for (const part of parts) {
          const line = part.replace(/^data: ?/m, '').trim();
          if (!line) continue;
          try { handleEvent(JSON.parse(line)); } catch (e) { console.warn('bad event', e); }
        }
      }
      if (buf) {
        const line = buf.replace(/^data: ?/m, '').trim();
        if (line) { try { handleEvent(JSON.parse(line)); } catch (e) {} }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        if (state.currentMsgEl) {
          state.currentMsgEl.querySelector('.md.stream').innerHTML =
            `<div class="msg-error">${escapeHtml(t('err.request', { msg: e.message }))}</div>`;
        } else {
          toast(t('err.request', { msg: e.message }), true);
        }
      }
    } finally {
      state.busy = false;
      state.streaming = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  /* ---------- 事件处理 ---------- */
  function handleEvent(ev) {
    switch (ev.type) {
      case 'plan':
        state.planSteps = ev.steps || [];
        if (state.currentMsgEl) {
          const panel = document.createElement('div');
          panel.className = 'plan-panel';
          state.currentMsgEl.querySelector('.bubble').appendChild(panel);
          state.currentMsgEl._planPanel = panel;
          renderPlan(panel, state.planSteps);
          if (state.planSteps.length > 2) {
            state.currentMsgEl._subStatus = document.createElement('div');
            state.currentMsgEl._subStatus.className = 'status-row';
            state.currentMsgEl._subStatus.innerHTML = `<span class="status-spinner"></span><span class="status-text">${t('status.parallel', { n: state.planSteps.length })}</span>`;
            state.currentMsgEl.querySelector('.bubble').appendChild(state.currentMsgEl._subStatus);
          }
        }
        break;

      case 'plan_step_start':
        if (state.currentMsgEl && state.currentMsgEl._planPanel) {
          updatePlanStep(state.currentMsgEl._planPanel, ev.step - 1, 'running');
        }
        break;
      case 'plan_step_done':
        if (state.currentMsgEl && state.currentMsgEl._planPanel) {
          updatePlanStep(state.currentMsgEl._planPanel, ev.step - 1, 'done');
        }
        if (state.currentMsgEl && state.currentMsgEl._subStatus && ev.progress) {
          const [d, t] = ev.progress.split('/');
          state.currentMsgEl._subStatus.querySelector('.status-text').innerHTML =
            t('status.done', { d: d, t: t });
        }
        break;

      case 'synthesize':
        // 汇总阶段：更新子任务状态条文案
        if (state.currentMsgEl && state.currentMsgEl._subStatus) {
          state.currentMsgEl._subStatus.querySelector('.status-text').innerHTML =
            t('status.synth', { n: state.planSteps.length });
        }
        break;

      case 'verify':
        addTraceStep('fact_check', { sub: ev.sub_q, grounding: ev.grounding },
                     ev.flag ? 'err' : 'ok', ev.grounding != null ? `g=${ev.grounding}` : '');
        // 主对话流内也展示核查卡片（"可核查"是本项目核心卖点）。
        // 未通过核查（grounding 为 null 或低于阈值）的子报告标注"已排除"，清晰可见。
        if (state.currentMsgEl && (ev.grounding != null || ev.excluded)) {
          const vc = document.createElement('div');
          vc.className = 'verify-card' + (ev.excluded ? ' excluded' : '');
          const g = ev.grounding;
          let cls, label;
          if (ev.excluded) { cls = 'excluded'; label = t('verify.excluded'); }
          else if (g >= 0.6) { cls = 'high'; label = t('verify.supported'); }
          else if (g >= 0.35) { cls = 'med'; label = t('verify.partial'); }
          else { cls = 'low'; label = t('verify.unsupported'); }
          // 排除原因为代码（no_sources / low_grounding），按语言映射展示
          let exclText = '';
          if (ev.excluded) {
            const code = String(ev.excluded).split(':')[0];
            exclText = t('excl.' + code) || String(ev.excluded);
            if (code === 'low_grounding' && g != null) exclText = t('excl.low_grounding', { g: g.toFixed(2) });
          }
          vc.innerHTML = `
            <div class="verify-head">
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 12l2 2 4-4M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"/></svg>
              ${t('verify.head')}
            </div>
            <div class="verify-q">${escapeHtml(ev.sub_q)}</div>
            <div class="verify-result ${cls}">${label}${g != null ? ` · grounding ${g.toFixed(3)}` : ''}</div>
            ${exclText ? `<div class="verify-flag">${escapeHtml(exclText)}</div>` : ''}
            ${ev.flag ? `<div class="verify-flag">${escapeHtml(ev.flag)}</div>` : ''}`;
          state.currentMsgEl.querySelector('.bubble').appendChild(vc);
        }
        break;

      case 'tool':
        state.trace.push(ev);
        // 子 Agent 转发的事件加"研究"前缀，与主 Agent 动作区分
        addTraceStep(ev.tag === 'sub' ? t('trace.research', { name: ev.name }) : ev.name,
                     ev.args, ev.status || 'ok', ev.dur || '');
        // 记录最近一次检索词，供来源抽屉高亮
        if (ev.name === 'rag_search' && ev.args && ev.args.query) {
          state.lastSearchQuery = ev.args.query;
        }
        // 收集工具里出现的来源
        if (ev.name === 'rag_search' && ev.result) {
          const re = /\[来源[:：]?\s*([^\]\[]+?)\]/g;
          let m;
          while ((m = re.exec(ev.result)) !== null) {
            const raw = m[1].trim();
            const sc = raw.match(/相关度[:：]?\s*([\d.]+)/);
            const name = raw.split(/[\s，。；,;（）(]/)[0];
            if (name && !state.currentCiteSeen.has(name)) {
              state.currentCiteSeen.set(name, sc ? parseFloat(sc[1]) : 0.6);
            }
          }
        }
        break;

      case 'delta':
        state.currentMsgText += ev.text;
        renderCurrentStream();
        break;

      case 'error':
        if (state.currentMsgEl) {
          state.currentMsgEl.querySelector('.md.stream').innerHTML =
            `<div class="msg-error">${escapeHtml(t('err.service', { msg: ev.error || t('err.unknown') }))}</div>`;
        }
        break;

      case 'done': {
        // 收尾：移除光标、补来源卡片 + 可信度徽标
        const md = state.currentMsgEl && state.currentMsgEl.querySelector('.md.stream');
        if (md) {
          md.innerHTML = renderMarkdown(state.currentMsgText);
          // 从最终文本提取引用
          const cites = extractCitations(state.currentMsgText);
          const sources = [...state.currentCiteSeen].map(([doc, score]) => ({ doc, score }));
          // 并进去重（名称统一清洗）
          const seen = new Set(sources.map(s => s.doc));
          cites.forEach(c => {
            c = c.trim().split(/[\s，。；,;（）(]/)[0];
            if (c && !seen.has(c)) { seen.add(c); sources.push({ doc: c, score: 0.6 }); }
          });
          renderCitations(state.currentMsgEl, sources);
        }
        if (ev.verification) {
          const pill = trustPill(ev.verification);
          if (pill && state.currentMsgEl) {
            const wrap = document.createElement('div');
            wrap.innerHTML = pill;
            state.currentMsgEl.querySelector('.bubble').appendChild(wrap.firstChild);
          }
          renderSentenceVerify(state.currentMsgEl, ev.verification);
        }
        // 移除子任务状态条（"已完成 x/3 …" / "正在综合…"）
        if (state.currentMsgEl && state.currentMsgEl._subStatus) {
          state.currentMsgEl._subStatus.remove();
          state.currentMsgEl._subStatus = null;
        }
        // 清理引用当前消息对象
        state.currentMsgEl = null;
        break;
      }
    }
  }

  /* ---------- 输入框 ---------- */
  function autoGrow() {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 180) + 'px';
  }
  input.addEventListener('input', autoGrow);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  sendBtn.addEventListener('click', sendMessage);

  /* ---------- 模式切换 ---------- */
  $('mode-switch').querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      $('mode-switch').querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.mode = btn.dataset.mode;
      // 多 Agent 模式时提示
      if (state.mode === 'multi') {
        toast(t('mode.toast'));
      }
    });
  });
  $('tools-toggle').addEventListener('change', (e) => {
    state.toolsEnabled = e.target.checked;
  });

  /* ---------- 会话管理 ---------- */
  async function loadSessions() {
    try {
      const data = await api('/api/sessions');
      SESSIONS_CACHE = data.sessions || [];
      renderSessions(SESSIONS_CACHE);
    } catch (e) {}
  }
  function renderSessions(sessions) {
    sessionList.innerHTML = '';
    if (!sessions.length) {
      sessionList.innerHTML = '<div class="kb-empty" style="padding:8px">' + t('session.none') + '</div>';
      return;
    }
    sessions.forEach(s => {
      const el = document.createElement('div');
      el.className = 'session-item' + (s.id === state.sessionId ? ' active' : '');
      const isDefault = !s.title || s.title === '新会话';
      const title = isDefault ? t('session.new') : s.title;
      el.innerHTML = `
        <span class="sess-title">${escapeHtml(title)}</span>
        <span class="sess-time">${fmtTime(s.created)}</span>
        <span class="sess-del" title="${t('kb.delete')}">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>
        </span>`;
      el.querySelector('.sess-title').addEventListener('click', () => switchSession(s.id));
      el.querySelector('.sess-del').addEventListener('click', (e) => {
        e.stopPropagation();
        deleteSession(s.id);
      });
      sessionList.appendChild(el);
    });
  }
  async function switchSession(sid) {
    // 先中断在途的 SSE 请求，避免旧会话事件污染新会话
    if (state.abortCtrl) { try { state.abortCtrl.abort(); } catch (e) {} }
    state.abortCtrl = new AbortController();
    state.busy = false;
    sendBtn.disabled = false;
    state.currentMsgText = '';
    state.sessionId = sid;
    state.history = [];
    state.currentMsgEl = null;
    state.currentCiteSeen = new Map();
    chatList.innerHTML = '';
    emptyState.classList.remove('hidden');
    traceList.innerHTML = '';
    traceEmpty.classList.remove('hidden');
    // 标题
    const found = SESSIONS_CACHE.find(s => s.id === sid);
    sessionTitle.textContent = found && found.title !== '新会话' ? found.title : t('session.new');
    // 恢复历史（若存在）
    try {
      const h = await api(`/api/sessions/${encodeURIComponent(sid)}/history`);
      const msgs = h.messages || [];
      if (msgs.length) {
        emptyState.classList.add('hidden');
        msgs.forEach(m => {
          if (!m || !m.content) return;
          if (m.role === 'user') {
            appendUserMsg(String(m.content));
          } else {
            const el = appendAssistantMsg();
            const md = el.querySelector('.md.stream');
            if (md) md.innerHTML = renderMarkdown(String(m.content));
            el.classList.remove('streaming');
          }
        });
      }
    } catch (e) {}
    loadSessions();
  }
  let SESSIONS_CACHE = [];
  async function newSession() {
    try {
      const data = await api('/api/sessions', { method: 'POST' });
      await switchSession(data.session_id);
    } catch (e) {
      toast(t('err.request', { msg: e.message }), true);
    }
  }
  async function deleteSession(sid) {
    try {
      await api(`/api/sessions/${encodeURIComponent(sid)}`, { method: 'DELETE' });
      if (sid === state.sessionId) {
        await newSession();
      } else {
        loadSessions();
      }
    } catch (e) {
      toast(t('err.request', { msg: e.message }), true);
    }
  }
  $('new-chat-btn').addEventListener('click', newSession);

  /* ---------- 知识库 ---------- */
  async function loadKB() {
    try {
      const data = await api('/api/documents');
      renderKB(data);
    } catch (e) {}
  }
  function renderKB(data) {
    const indexed = data.indexed || [];
    const pending = data.pending || [];
    kbList.innerHTML = '';
    indexed.forEach(d => {
      const el = document.createElement('div');
      el.className = 'kb-item';
      el.innerHTML = `
        <span class="kb-icon"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg></span>
        <span class="kb-name" title="${escapeHtml(d.doc)}">${escapeHtml(d.doc)}</span>
        <span class="kb-chunks">${d.chunks}</span>
        <span class="kb-del" title="${t('kb.removeTitle')}">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
        </span>`;
      el.querySelector('.kb-del').addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm(t('kb.removeConfirm', { doc: d.doc }))) return;
        try {
          await api(`/api/documents/${encodeURIComponent(d.doc)}`, { method: 'DELETE' });
          toast(t('kb.deleted', { doc: d.doc }));
          loadKB();
        } catch (err) { toast(t('kb.deleteFail', { msg: err.message }), true); }
      });
      kbList.appendChild(el);
    });
    // 待导入
    pending.forEach(f => {
      const el = document.createElement('div');
      el.className = 'kb-item';
      el.style.opacity = '.6';
      el.innerHTML = `
        <span class="kb-icon"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg></span>
        <span class="kb-name" title="${t('kb.pending')}">${escapeHtml(f)}</span>
        <span class="kb-chunks">${t('kb.toIngest')}</span>`;
      el.addEventListener('click', () => ingestFileFromDir(f));
      kbList.appendChild(el);
    });
    if (!indexed.length && !pending.length) {
      kbList.innerHTML = '<div class="kb-empty">' + t('kb.empty') + '</div>';
    }
    kbStats.textContent = indexed.length ? t('kb.count', { d: indexed.length, c: indexed.reduce((a, b) => a + b.chunks, 0) }) : '';
    if (data.error) kbStats.textContent = '⚠ ' + data.error;
  }
  async function ingestFileFromDir(fname) {
    // 对已存在于 docs 目录但未入库的文件，单独导入该文件（而不是重扫整个目录）
    if (!fname) { toast(t('err.unknown'), true); return; }
    try {
      const resp = await fetch('/api/ingest_path', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: fname }),
      });
      const data = await resp.json();
      if (data.ok) {
        toast(t('kb.ingested', { file: fname, n: data.total_chunks }));
        loadKB();
      } else {
        toast(data.detail || 'error', true);
      }
    } catch (e) { toast(t('kb.scanFail', { msg: e.message }), true); }
  }

  // 上传文件
  const fileInput = $('file-input');
  $('import-btn').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async () => {
    const files = [...fileInput.files];
    fileInput.value = '';
    if (!files.length) return;
    for (const f of files) {
      const fd = new FormData();
      fd.append('file', f);
      try {
        const resp = await fetch('/api/ingest', { method: 'POST', body: fd });
        const data = await resp.json();
        if (data.ok) toast(t('kb.ingested', { file: data.file || f.name, n: data.chunks || 0 }));
        else toast(t('kb.ingestFail', { file: data.file || f.name, msg: data.note || data.detail || 'error' }), true);
      } catch (e) {
        toast(t('kb.uploadFail', { file: f.name, msg: e.message }), true);
      }
    }
    loadKB();
  });
  const folderInput = $('folder-input');
  const scanAllBtn = $('scan-all-btn');
  // ② 批量扫描：选中一个文件夹，导入其中全部文档
  $('folder-btn').addEventListener('click', () => folderInput.click());
  folderInput.addEventListener('change', async () => {
    const files = [...folderInput.files];
    folderInput.value = '';
    if (!files.length) return;
    toast(t('kb.scanning'));
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    try {
      const resp = await fetch('/api/ingest_many', { method: 'POST', body: fd });
      const data = await resp.json();
      if (data.ok) toast(t('kb.folderIngested', { n: data.count, c: data.total_chunks }));
      else toast(data.detail || 'error', true);
    } catch (e) {
      toast(e.message, true);
    }
    loadKB();
  });
  // ③ 全部读取：扫描本机所有受支持的文档
  scanAllBtn.addEventListener('click', async () => {
    scanAllBtn.disabled = true;
    toast(t('kb.allScanning'));
    try {
      const resp = await fetch('/api/ingest_all', { method: 'POST' });
      const data = await resp.json();
      if (data.ok) toast(t('kb.allIngested', { f: data.found, c: data.total_chunks }));
      else toast(data.detail || 'error', true);
    } catch (e) {
      toast(e.message, true);
    } finally {
      scanAllBtn.disabled = false;
    }
    loadKB();
  });

  /* ---------- GPU 监控 ---------- */
  const gpuCtx = gpuChart.getContext('2d');
  let gpuChartInit = false;
  function sizeGpuCanvas() {
    // 把 canvas 后备存储对齐到显示尺寸 × devicePixelRatio，避免图表被拉伸失真
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, gpuChart.clientWidth || 300);
    const h = Math.max(1, gpuChart.clientHeight || 140);
    if (gpuChart.width !== Math.round(w * dpr) || gpuChart.height !== Math.round(h * dpr)) {
      gpuChart.width = Math.round(w * dpr);
      gpuChart.height = Math.round(h * dpr);
      gpuCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
  }
  function drawGpuChart() {
    sizeGpuCanvas();
    if (gpuHistory.length < 2) {
      // 画空网格
      gpuCtx.clearRect(0, 0, gpuChart.width, gpuChart.height);
      gpuCtx.strokeStyle = '#1C2126';
      gpuCtx.lineWidth = 1;
      for (let i = 1; i < 4; i++) {
        gpuCtx.beginPath();
        gpuCtx.moveTo(0, gpuChart.height * i / 4);
        gpuCtx.lineTo(gpuChart.width, gpuChart.height * i / 4);
        gpuCtx.stroke();
      }
      return;
    }
    const w = gpuChart.width, h = gpuChart.height;
    gpuCtx.clearRect(0, 0, w, h);
    // 网格
    gpuCtx.strokeStyle = '#1C2126';
    gpuCtx.lineWidth = 1;
    for (let i = 1; i < 4; i++) {
      gpuCtx.beginPath();
      gpuCtx.moveTo(0, h * i / 4);
      gpuCtx.lineTo(w, h * i / 4);
      gpuCtx.stroke();
    }
    const draw = (key, color) => {
      const vals = gpuHistory.map(d => d[key] || 0);
      const max = Math.max(...vals, 100);
      gpuCtx.strokeStyle = color;
      gpuCtx.lineWidth = 1.6;
      gpuCtx.beginPath();
      vals.forEach((v, i) => {
        const x = (i / Math.max(1, vals.length - 1)) * w;
        const y = h - (v / max) * (h - 8) - 4;
        if (i === 0) gpuCtx.moveTo(x, y); else gpuCtx.lineTo(x, y);
      });
      gpuCtx.stroke();
    };
    draw('util', '#34D399');
    draw('vramPct', '#38BDF8');
  }

  async function refreshGpu() {
    try {
      const data = await api('/api/gpu');
      const g = data.gpus && data.gpus[0];
      if (g) {
        const util = Math.round(g.utilization || 0);
        let vramPct = 0;
        if (g.vram_util_pct != null) vramPct = Math.round(g.vram_util_pct);
        else if (g.vram_used_mb != null && g.vram_total_mb != null)
          vramPct = Math.round((g.vram_used_mb / Math.max(1, g.vram_total_mb)) * 100);
        const temp = g.temperature != null ? Math.round(g.temperature) : null;
        const power = g.power_w != null ? Math.round(g.power_w) : null;
        const clock = g.core_clock != null ? Math.round(g.core_clock) : null;

        // 顶栏徽标
        const dot = $('gpu-dot');
        if (data.available) dot.className = 'gpu-dot ok';
        else if (data.demo) dot.className = 'gpu-dot warn';
        else dot.className = 'gpu-dot';
        $('gpu-chip-label').textContent = data.available ? 'AMD GPU' : t('gpu.demoChip');
        $('gpu-metric-vram').textContent = `${vramPct}%`;
        $('gpu-metric-temp').textContent = temp != null ? `${temp}°C` : '—';

        // 右侧指标
        gpuMetrics.innerHTML = `
          <div class="gpu-metric-row">
            <span class="gm-label">${t('gpu.name')}</span>
            <span class="gm-value" style="font-size:12px;min-width:0;text-align:left;color:var(--text-tertiary)">${escapeHtml(g.name || '—')}</span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">${t('gpu.util')}</span>
            <span class="gm-value">${util}%</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${util}%;background:var(--gpu-util)"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">${t('gpu.vram')}</span>
            <span class="gm-value">${vramPct}%</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${vramPct}%;background:var(--gpu-vram)"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">${t('gpu.temp')}</span>
            <span class="gm-value" style="color:${temp != null && temp > 80 ? 'var(--gpu-temp-hot)' : 'var(--text-primary)'}">${temp != null ? temp + '°C' : '—'}</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${temp != null ? Math.min(100, temp / 100 * 100) : 0}%;background:${temp != null && temp > 80 ? 'var(--gpu-temp-hot)' : 'var(--gpu-fan)'}"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">${t('gpu.power')}</span>
            <span class="gm-value">${power != null ? power + 'W' : '—'}</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${power != null ? Math.min(100, power / 300 * 100) : 0}%;background:var(--gpu-power)"></span></span>
          </div>
          <div class="gpu-metric-row">
            <span class="gm-label">${t('gpu.clock')}</span>
            <span class="gm-value">${clock != null ? clock + 'MHz' : '—'}</span>
            <span class="gm-bar"><span class="gm-fill" style="width:${clock != null ? Math.min(100, clock / 3500 * 100) : 0}%;background:var(--gpu-clock)"></span></span>
          </div>`;
        gpuNote.innerHTML = data.demo
          ? t('gpu.demoNote')
          : t('gpu.sourceNote', { src: data.source });

        // 历史数据
        gpuHistory.push({ util, vramPct: vramPct, temp: temp || 0, power: power || 0 });
        if (gpuHistory.length > 60) gpuHistory.shift();
        drawGpuChart();
      }
    } catch (e) {}
  }

  // 面板 Tab 切换
  document.querySelectorAll('.panel-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      document.querySelectorAll('.panel-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const which = tab.dataset.tab;
      $('panel-trace').classList.toggle('hidden', which !== 'trace');
      $('panel-gpu').classList.toggle('hidden', which !== 'gpu');
      if (which === 'gpu') setTimeout(() => drawGpuChart(), 50);
    });
  });

  /* ---------- 系统信息浮层 ---------- */
  $('settings-btn').addEventListener('click', async () => {
    $('modal-mask').classList.remove('hidden');
    try {
      const d = await api('/api/health');
      const fmt = (k, v) => `<div class="hi-row"><span>${k}</span><span class="hi-val">${escapeHtml(String(v))}</span></div>`;
      $('health-info').innerHTML = `
        <div class="hi-block">
          <div class="hi-label">${t('modal.model')}</div>
          ${fmt(t('modal.backend'), d.model.backend)}${fmt(t('modal.model'), d.model.name)}${fmt(t('modal.url'), d.model.base_url)}
        </div>
        <div class="hi-block">
          <div class="hi-label">${t('modal.retrieval')}</div>
          ${fmt(t('modal.retrievalType'), d.rag.hybrid ? (LANG === 'zh' ? 'BM25 + 向量' : 'BM25 + vector') : t('modal.vector'))}${fmt(t('modal.rerank'), d.rag.rerank ? 'on' : 'off')}${fmt(t('modal.embedding'), d.embedding)}
        </div>
        <div class="hi-block">
          <div class="hi-label">${t('modal.kb')}</div>
          ${fmt(t('modal.docs'), d.rag.docs)}${fmt(t('modal.chunks'), d.rag.chunks)}${fmt(t('modal.dir'), d.rag.docs_dir)}
        </div>
        <div class="hi-block">
          <div class="hi-label">${t('modal.gpu')}</div>
          <div class="hi-row"><span>${t('modal.status')}</span><span><span class="hi-badge ${d.gpu.available ? 'on' : 'off'}">${d.gpu.available ? t('modal.connected') : t('modal.notDetected')}</span> ${d.gpu.source || ''}</span></div>
        </div>
        <div class="hi-row"><span>${t('modal.time')}</span><span class="hi-val mono">${d.time}</span></div>`;
    } catch (e) {
      $('health-info').textContent = t('modal.loading');
    }
  });
  $('modal-close').addEventListener('click', () => $('modal-mask').classList.add('hidden'));
  $('modal-mask').addEventListener('click', (e) => {
    if (e.target === $('modal-mask')) $('modal-mask').classList.add('hidden');
  });

  /* ---------- 建议示例 ---------- */
  function runSuggestion(q, kind) {
    input.value = q;
    autoGrow();
    // 复杂问题自动切多 Agent 并行模式（分解→研究→核查→汇总）。
    // 按建议卡的 kind（1 项目全景 / 3 架构解读 = 复杂）判定，而非扫描问题文字——
    // 英文界面下问题仍是中文（面向中文知识库），中文正则会失效。
    const multiKinds = new Set(['1', '3']);
    if (multiKinds.has(String(kind))) {
      const mb = $('mode-switch').querySelector('.mode-btn[data-mode="multi"]');
      $('mode-switch').querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      mb.classList.add('active');
      state.mode = 'multi';
    } else {
      const sb = $('mode-switch').querySelector('.mode-btn[data-mode="single"]');
      $('mode-switch').querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      if (sb) sb.classList.add('active');
      state.mode = 'single';
    }
    sendMessage();
  }
  const suggestionBtns = [...document.querySelectorAll('.suggestion')];
  suggestionBtns.forEach(btn => {
    btn.addEventListener('click', () => runSuggestion(btn.dataset.q, btn.dataset.k));
  });
  // 键盘快捷键 1-4 触发建议（空状态且未在输入时）
  window.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey || document.activeElement === input) return;
    if (state.streaming || !emptyState || emptyState.classList.contains('hidden')) return;
    const idx = '1234'.indexOf(e.key);
    if (idx >= 0 && suggestionBtns[idx]) runSuggestion(suggestionBtns[idx].dataset.q, suggestionBtns[idx].dataset.k);
  });

  /* ---------- 滚动 ---------- */
  let autoScroll = true;
  chatScroll.addEventListener('scroll', () => {
    const dist = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight;
    autoScroll = dist < 80;
  });
  function scrollBottom() {
    if (autoScroll) chatScroll.scrollTop = chatScroll.scrollHeight;
  }

  /* ---------- 语言切换（设置弹窗内） ---------- */
  const langSelect = document.getElementById('lang-select');
  if (langSelect) {
    langSelect.value = LANG;
    langSelect.addEventListener('change', () => setLang(langSelect.value));
  }

  /* ---------- 初始化 ---------- */
  (async function init() {
    applyI18n();
    await loadSessions();
    await loadKB();
    refreshGpu();
    // GPU 实时
    const gpuTimer = setInterval(refreshGpu, 2000);
    // 健康检查更新顶栏 GPU
    try {
      const h = await api('/api/health');
      if (h.gpu && h.gpu.available) $('gpu-chip-label').textContent = 'AMD GPU';
      else if (h.gpu && h.gpu.source === 'demo') $('gpu-chip-label').textContent = t('gpu.demoChip');
    } catch (e) {}
    input.focus();
  })();
})();

import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import {
  AssistantRuntimeProvider,
  useLocalRuntime,
  useMessage,
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ActionBarPrimitive,
  BranchPickerPrimitive,
} from '@assistant-ui/react';
import { createAdapter, uploadPaper, isMiningRequest, checkActiveTask } from './adapter';
import { renderMarkdown } from './markdown';

// ── 常量 ──
const STORAGE_KEY = 'aiquant_chat_sessions_v2';
const API_BASE = window.location.origin;

const CATEGORIES = [
  { key: 'all', label: '全部' },
  { key: 'factor', label: '因子研究' },
  { key: 'backtest', label: '回测分析' },
  { key: 'paper', label: '论文解读' },
];

const QUICK_COMMANDS = [
  { label: '挖掘 Alpha 因子', text: '挖掘沪深300横截面Alpha因子，预测未来1个月个股超额收益，月度调仓，执行3轮迭代挖掘' },
  { label: '回测结果分析', text: '分析最近一次因子挖掘的回测结果，包括IC、ICIR、年化收益等指标' },
  { label: '相关性检查', text: '检查当前因子库中各因子的相关性，找出高冗余因子' },
];

// ── 工具 ──
function generateId() {
  return 's-' + Date.now() + '-' + Math.random().toString(36).slice(2, 6);
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) { const p = JSON.parse(raw); if (p.sessions) return p; }
  } catch {}
  // 迁移旧版数据
  try {
    const old = localStorage.getItem('aiquant_chat_state_v1');
    if (old) {
      const p = JSON.parse(old);
      if (p.sessions) {
        return {
          sessions: p.sessions.map(s => ({
            id: s.id, title: s.title || '新会话', category: 'factor',
            createdAt: s.createdAt || Date.now(),
            messages: (s.messages || []).map(m => ({ role: m.role, text: m.text, ts: m.ts || Date.now() })),
          })),
          activeId: p.activeSessionId || null,
        };
      }
    }
  } catch {}
  return { sessions: [], activeId: null };
}

function saveState(sessions, activeId) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ sessions, activeId })); } catch {}
}

function detectCategory(text) {
  if (/论文|paper|研报|文献|PDF/i.test(text)) return 'paper';
  if (/回测|收益|指标|IC|ICIR|年化/i.test(text)) return 'backtest';
  return 'factor';
}

function fillComposerInput(text) {
  const el = document.querySelector('.aui-input');
  if (!el) return;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
  setter.call(el, text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.focus();
}

// ── Markdown 渲染 ──
function MdText({ text }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className="md-body" dangerouslySetInnerHTML={{ __html: html }} />;
}

// ── 空状态 ──
function EmptyState() {
  return (
    <div className="aui-empty">
      <div className="aui-empty-icon">
        <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/>
        </svg>
      </div>
      <h3 className="aui-empty-title">AI 量化助手</h3>
      <p className="aui-empty-sub">你可以：</p>
      <div className="aui-empty-grid">
        <div className="aui-empty-card"><span>📊</span><span>挖掘横截面 Alpha 因子</span></div>
        <div className="aui-empty-card"><span>📄</span><span>上传研报/论文提取因子思路</span></div>
        <div className="aui-empty-card"><span>📈</span><span>分析回测指标与收益曲线</span></div>
        <div className="aui-empty-card"><span>🧠</span><span>调用记忆库历史研究结论</span></div>
      </div>
    </div>
  );
}

// ── 消息气泡 ──
// 注意：assistant-ui 的消息通过 context 传递，components.Message 不会收到 message prop，
// 必须用 useMessage() 从上下文获取（直接读 props.message 会 undefined 崩溃导致白屏）
function MessageBubble() {
  const message = useMessage();
  const isUser = message.role === 'user';
  return (
    <MessagePrimitive.Root
      className={`aui-msg ${isUser ? 'aui-msg-user' : 'aui-msg-assistant'}`}
    >
      <div className="aui-msg-role">{isUser ? '你' : 'AI 助手'}</div>
      <MessagePrimitive.Content components={{ Text: MdText }} />
      {!isUser && (
        <div className="aui-msg-footer">
          <ActionBarPrimitive.Root className="aui-action-bar">
            <ActionBarPrimitive.Copy className="aui-act-btn" title="复制" />
            <ActionBarPrimitive.Reload className="aui-act-btn" title="重新生成" />
          </ActionBarPrimitive.Root>
          <BranchPickerPrimitive.Root className="aui-branch">
            <BranchPickerPrimitive.Previous className="aui-branch-btn" />
            <BranchPickerPrimitive.Number className="aui-branch-num" />
            <BranchPickerPrimitive.Next className="aui-branch-btn" />
          </BranchPickerPrimitive.Root>
        </div>
      )}
    </MessagePrimitive.Root>
  );
}

// ── 侧边栏 ──
function Sidebar({ sessions, activeId, category, onCategoryChange, onSwitch, onNew, onDelete, open, onToggle }) {
  const filtered = category === 'all' ? sessions : sessions.filter(s => s.category === category);
  const sorted = [...filtered].sort((a, b) => b.createdAt - a.createdAt);

  if (!open) {
    return (
      <button className="aui-sidebar-expand" onClick={onToggle} title="展开会话列表">
        ☰
      </button>
    );
  }

  return (
    <div className="aui-sidebar">
      <div className="aui-sidebar-header">
        <span className="aui-sidebar-title">会话</span>
        <button className="aui-sidebar-collapse" onClick={onToggle} title="收起">◀</button>
      </div>

      <div className="aui-cat-tabs">
        {CATEGORIES.map(c => (
          <button
            key={c.key}
            className={`aui-cat-tab ${category === c.key ? 'active' : ''}`}
            onClick={() => onCategoryChange(c.key)}
          >{c.label}</button>
        ))}
      </div>

      <button className="aui-new-chat" onClick={onNew}>+ 新建对话</button>

      <div className="aui-session-list">
        {sorted.length === 0 ? (
          <div className="aui-session-empty">暂无会话</div>
        ) : sorted.map(s => (
          <div
            key={s.id}
            className={`aui-session-item ${s.id === activeId ? 'active' : ''}`}
            onClick={() => onSwitch(s.id)}
          >
            <div className="aui-session-title">{s.title}</div>
            <div className="aui-session-meta">
              <span className="aui-session-count">{s.messages.length} 条</span>
              <button className="aui-session-del" onClick={e => onDelete(s.id, e)} title="删除">×</button>
            </div>
          </div>
        ))}
      </div>

      <div className="aui-sidebar-footer">
        <a href="#" className="aui-mem-link" onClick={e => {
          e.preventDefault();
          if (typeof window.switchPanel === 'function') window.switchPanel('memory');
        }}>🧠 记忆库</a>
      </div>
    </div>
  );
}

// ── Thread + Composer（隔离 runtime，支持 remount 刷新）──
function ChatThread({ session, onTurnComplete, onAttach, uploading }) {
  const adapter = useMemo(() => createAdapter({
    onTurnComplete: (u, a) => onTurnComplete(session.id, u, a),
  }), [session.id]);

  const initialMessages = useMemo(() =>
    session.messages.map((m, i) => {
      const msg = {
        id: m.id || `msg-${i}-${m.role}-${m.ts}`,
        role: m.role,
        content: [{ type: 'text', text: m.text }],
        createdAt: new Date(m.ts),
      };
      // assistant-ui 要求 status 字段只能用在 assistant 消息上
      if (m.role === 'assistant') {
        msg.status = { type: 'complete', reason: 'stop' };
      }
      return msg;
    }),
    [session.messages]
  );

  const runtime = useLocalRuntime(adapter, { initialMessages });
  const hasMessages = session.messages.length > 0;

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="aui-thread">
        <ThreadPrimitive.Viewport className="aui-viewport">
          {!hasMessages && <EmptyState />}
          <ThreadPrimitive.Messages components={{ Message: MessageBubble }} />
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>

      <ComposerPrimitive.Root className="aui-composer">
        <div className="aui-quick-bar">
          {QUICK_COMMANDS.map(cmd => (
            <button key={cmd.label} className="aui-quick-btn" onClick={() => fillComposerInput(cmd.text)}>
              {cmd.label}
            </button>
          ))}
        </div>
        <div className="aui-input-row">
          <button className="aui-attach-btn" onClick={onAttach} disabled={uploading} title="上传论文">
            {uploading ? '⏳' : '📎'}
          </button>
          <ComposerPrimitive.Input
            className="aui-input"
            placeholder="输入策略 idea 或问题… Enter 发送，Shift+Enter 换行"
            autoFocus
            rows={1}
          />
          <ComposerPrimitive.Send className="aui-send-btn">发送</ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

// ── 聊天区域 ──
function ChatArea({ session, onTurnComplete, onClear }) {
  const [fullscreen, setFullscreen] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [innerKey, setInnerKey] = useState(0);
  const fileRef = useRef(null);

  const handlePaper = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadPaper(file);
      const reply = result.message || result.summary || `论文 "${file.name}" 上传成功，已提取因子思路。`;
      const now = Date.now();
      onTurnComplete(session.id,
        { role: 'user', text: `📄 上传论文: ${file.name}`, ts: now },
        { role: 'assistant', text: reply, ts: now + 1 }
      );
    } catch (err) {
      const now = Date.now();
      onTurnComplete(session.id,
        { role: 'user', text: `📄 上传论文: ${file.name}`, ts: now },
        { role: 'assistant', text: `❌ 上传失败: ${err.message}`, ts: now + 1 }
      );
    } finally {
      setUploading(false);
      setInnerKey(k => k + 1);
      if (fileRef.current) fileRef.current.value = '';
    }
  }, [session.id, onTurnComplete]);

  return (
    <div className={`aui-chat-area ${fullscreen ? 'aui-fullscreen' : ''}`}>
      <div className="aui-chat-header">
        <span className="aui-chat-title">AI 量化助手</span>
        <div className="aui-chat-header-actions">
          <button className="aui-hdr-btn" onClick={() => setFullscreen(!fullscreen)} title={fullscreen ? '退出全屏' : '全屏'}>
            {fullscreen ? '◳' : '⛶'}
          </button>
          <button className="aui-hdr-btn aui-hdr-btn-text" onClick={onClear} title="清空对话">清空</button>
        </div>
      </div>

      <ChatThread
        key={innerKey}
        session={session}
        onTurnComplete={onTurnComplete}
        onAttach={() => fileRef.current?.click()}
        uploading={uploading}
      />

      <input ref={fileRef} type="file" accept=".pdf,.docx,.txt,.md" hidden onChange={handlePaper} />
    </div>
  );
}

// ── B3: 进度条组件 ──
function ProgressIndicator({ progressPct, stage, elapsedSec }) {
  if (progressPct == null || progressPct <= 0) return null;
  const pct = Math.min(Math.max(progressPct, 0), 100);
  const elapsedStr = elapsedSec != null
    ? `· ${Math.floor(elapsedSec / 60)}m ${Math.round(elapsedSec % 60)}s`
    : '';
  return (
    <div className="aui-progress-bar-container">
      <div className="aui-progress-info">
        <span className="aui-progress-stage">{stage || '处理中'}</span>
        <span className="aui-progress-pct">{pct}%</span>
        <span className="aui-progress-elapsed">{elapsedStr}</span>
      </div>
      <div className="aui-progress-track">
        <div className="aui-progress-fill" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

// ── 恢复通知条 ──
function RecoveryBanner({ taskInfo, onDismiss }) {
  if (!taskInfo) return null;
  const elapsed = taskInfo.elapsed_sec != null ? `（已运行 ${Math.round(taskInfo.elapsed_sec / 60)} 分钟）` : '';
  return (
    <div className="aui-recovery-banner">
      <span className="aui-recovery-icon">🔄</span>
      <span className="aui-recovery-text">
        发现正在运行的任务 <strong>{taskInfo.task_id}</strong> — 阶段: {taskInfo.stage || '未知'} {elapsed}
      </span>
      <span className="aui-recovery-hint">进度正在自动恢复中...</span>
      <button className="aui-recovery-close" onClick={onDismiss} title="关闭">×</button>
    </div>
  );
}

// ── 主组件 ──
export default function ChatPanel() {
  const [state, setState] = useState(loadState);
  const [category, setCategory] = useState('all');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [activeTask, setActiveTask] = useState(null);
  const [progress, setProgress] = useState({ pct: 0, stage: '', elapsed: null });

  const { sessions, activeId } = state;
  const activeSession = sessions.find(s => s.id === activeId);

  useEffect(() => { saveState(sessions, activeId); }, [sessions, activeId]);

  // ── B4: SSE 优先 + 轮询 fallback ──
  // 页面加载时检查正在运行的任务，建立 SSE 或降级轮询
  useEffect(() => {
    let cancelled = false;
    let pollTimer = null;
    let sseSource = null;
    let lastSeq = 0;

    async function checkAndSubscribe() {
      const task = await checkActiveTask();
      if (cancelled || !task) return;

      setActiveTask(task);

      // B4: 尝试 SSE 连接
      try {
        sseSource = new EventSource(`${API_BASE}/api/tasks/${task.task_id}/events`);

        sseSource.onmessage = (ev) => {
          try {
            const data = JSON.parse(ev.data);
            if (data.seq) lastSeq = Math.max(lastSeq, data.seq);
            // B3: 更新进度
            if (data.progress_pct != null) {
              setProgress({
                pct: data.progress_pct,
                stage: data.stage || '',
                elapsed: data.elapsed_sec,
              });
            }
            if (data.type === 'done' || data.type === 'error') {
              setActiveTask(null);
              setProgress({ pct: 100, stage: data.type === 'done' ? '完成' : '失败', elapsed: data.elapsed_sec });
              if (sseSource) sseSource.close();
            }
          } catch {}
        };

        sseSource.onerror = () => {
          // B4: SSE 失败 → 降级为轮询
          if (sseSource) sseSource.close();
          sseSource = null;
          console.warn('[B4] SSE 不可用，降级为 HTTP 轮询');
          startPolling(task.task_id);
        };

      } catch (e) {
        // B4: SSE 创建失败 → 直接轮询
        console.warn('[B4] SSE 创建失败，降级为轮询:', e);
        startPolling(task.task_id);
      }
    }

    // B4: 轮询 fallback 函数
    function startPolling(taskId) {
      pollTimer = setInterval(async () => {
        if (cancelled) return;
        try {
          const res = await fetch(`${API_BASE}/api/tasks/${taskId}/poll?since_seq=${lastSeq}`);
          const data = await res.json();
          if (data.events && data.events.length > 0) {
            const latest = data.events[data.events.length - 1];
            lastSeq = data.latest_seq || lastSeq;
            // B3: 更新进度
            setProgress({
              pct: data.progress_pct || 0,
              stage: data.stage || '',
              elapsed: data.elapsed_sec,
            });
          }
          if (data.status === 'completed' || data.status === 'failed') {
            setActiveTask(null);
            setProgress({ pct: 100, stage: data.status === 'completed' ? '完成' : '失败', elapsed: data.elapsed_sec });
            if (pollTimer) clearInterval(pollTimer);
          }
        } catch {}
      }, 5000); // 5s 轮询
    }

    checkAndSubscribe();
    return () => {
      cancelled = true;
      if (pollTimer) clearInterval(pollTimer);
      if (sseSource) sseSource.close();
    };
  }, []);

  // ── B1: 页面加载时从 SQLite 恢复任务历史 ──
  useEffect(() => {
    async function loadTaskHistory() {
      try {
        const res = await fetch(`${API_BASE}/api/tasks/history?limit=20`);
        const data = await res.json();
        if (data.tasks && data.tasks.length > 0) {
          // 将历史任务合并到会话列表
          setState(prev => {
            const existingIds = new Set(prev.sessions.flatMap(s =>
              s.messages.map(m => m.task_id).filter(Boolean)
            ));
            const historySessions = data.tasks
              .filter(t => !existingIds.has(t.task_id))
              .map(t => ({
                id: 'hist-' + t.task_id,
                title: t.message?.slice(0, 30) || `任务 ${t.task_id.slice(0, 8)}`,
                category: 'factor',
                createdAt: new Date(t.created_at).getTime(),
                messages: t.final_report
                  ? [{ role: 'user', text: t.message || '', ts: new Date(t.created_at).getTime() },
                     { role: 'assistant', text: t.final_report, ts: new Date(t.updated_at).getTime() }]
                  : [],
                task_id: t.task_id,
                taskStatus: t.status,
              }));
            if (historySessions.length === 0) return prev;
            return {
              ...prev,
              sessions: [...prev.sessions, ...historySessions],
            };
          });
        }
      } catch {}
    }
    loadTaskHistory();
  }, []);

  const handleNew = useCallback(() => {
    const id = generateId();
    setState(prev => ({
      sessions: [{ id, title: '新会话', category: 'factor', createdAt: Date.now(), messages: [] }, ...prev.sessions],
      activeId: id,
    }));
  }, []);

  const handleSwitch = useCallback((id) => {
    setState(prev => ({ ...prev, activeId: id }));
  }, []);

  const handleDelete = useCallback((id, e) => {
    e.stopPropagation();
    setState(prev => {
      const sessions = prev.sessions.filter(s => s.id !== id);
      const activeId = prev.activeId === id ? (sessions[0]?.id || null) : prev.activeId;
      return { sessions, activeId };
    });
  }, []);

  const handleTurnComplete = useCallback((sessionId, userMsg, assistantMsg) => {
    setState(prev => ({
      ...prev,
      sessions: prev.sessions.map(s => {
        if (s.id !== sessionId) return s;
        const title = s.messages.length === 0 ? userMsg.text.slice(0, 25) : s.title;
        const cat = s.messages.length === 0 ? detectCategory(userMsg.text) : s.category;
        return { ...s, title, category: cat, messages: [...s.messages, userMsg, assistantMsg] };
      }),
    }));
  }, []);

  const handleClear = useCallback(() => {
    if (!activeId) return;
    setState(prev => ({
      ...prev,
      sessions: prev.sessions.map(s =>
        s.id === activeId ? { ...s, messages: [], title: '新会话' } : s
      ),
    }));
  }, [activeId]);

  // 首次自动创建会话
  useEffect(() => {
    if (sessions.length === 0 && !activeId) handleNew();
  }, []);

  return (
    <div className="aui-layout">
      <Sidebar
        sessions={sessions}
        activeId={activeId}
        category={category}
        onCategoryChange={setCategory}
        onSwitch={handleSwitch}
        onNew={handleNew}
        onDelete={handleDelete}
        open={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
      />
      <div className="aui-main">
        <RecoveryBanner taskInfo={activeTask} onDismiss={() => setActiveTask(null)} />
        {activeTask && (
          <ProgressIndicator
            progressPct={progress.pct}
            stage={progress.stage}
            elapsedSec={progress.elapsed}
          />
        )}
        {activeSession ? (
          <ChatArea
            key={activeId}
            session={activeSession}
            onTurnComplete={handleTurnComplete}
            onClear={handleClear}
          />
        ) : (
          <div className="aui-no-session">
            <p>选择或创建一个会话开始</p>
            <button className="aui-new-chat" onClick={handleNew}>+ 新建会话</button>
          </div>
        )}
      </div>
    </div>
  );
}

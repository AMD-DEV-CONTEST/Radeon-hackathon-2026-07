// Agent 协作室（多 Agent 同室协作对话窗口）
// 理念来源：Buzz —— 人类与多个 Agent 处在同一个「房间」里，每个 Agent 有独立身份/角色/提示词，
// 彼此能看见对方的发言并在其之上继续推进；全过程留痕（transcript）。
// 本实现为本地化版本：不引入 Nostr/中继，直接走本地 /api/agent_rooms 契约。
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Users, Plus, Trash2, Send, Loader2, RefreshCw, X, Bot, User,
  MessageSquare, Eraser, Layers,
} from "lucide-react";
import {
  fetchAgentRooms, fetchAgentRoom, createAgentRoom, deleteAgentRoom,
  resetAgentRoom, sendAgentRoomMessage,
  type RoomSummary, type RoomDetail, type RoomMessage, type RoomAgent,
} from "./lib/api";

// 与画布 node token 同色语言，保证亮/暗双主题一致
const AGENT_COLORS = [
  "var(--color-node-ai)",
  "var(--color-node-input)",
  "var(--color-node-logic)",
  "var(--color-node-data)",
  "var(--color-node-system)",
];

interface DraftAgent { name: string; role: string; system_prompt: string; color: string }

const PRESETS: Array<{ label: string; desc: string; agents: DraftAgent[] }> = [
  {
    label: "方案评审室",
    desc: "架构师提方案 → 质检员挑风险 → 产品把关价值",
    agents: [
      { name: "架构师", role: "architect", color: AGENT_COLORS[0],
        system_prompt: "你是资深系统架构师。针对议题给出结构化方案，聚焦模块边界、数据流与扩展性。控制在 4 句以内。" },
      { name: "质检员", role: "qa", color: AGENT_COLORS[4],
        system_prompt: "你是严格的质量与风险评审员。基于上一位发言者的方案，指出最关键的 1-2 个风险或漏洞，并给出可执行的补救建议。控制在 4 句以内。" },
      { name: "产品", role: "product", color: AGENT_COLORS[2],
        system_prompt: "你是产品负责人。综合前面的技术讨论，判断对用户价值的影响并给出取舍建议。控制在 3 句以内。" },
    ],
  },
  {
    label: "红蓝对抗",
    desc: "正方论证 → 反方证伪 → 裁判裁决",
    agents: [
      { name: "正方", role: "pro", color: AGENT_COLORS[2],
        system_prompt: "你是正方辩手。为议题给出最有力的支持论证，务必具体、有依据。控制在 4 句以内。" },
      { name: "反方", role: "con", color: AGENT_COLORS[4],
        system_prompt: "你是反方辩手。针对正方刚才的论证逐点证伪，指出其假设漏洞。控制在 4 句以内。" },
      { name: "裁判", role: "judge", color: AGENT_COLORS[3],
        system_prompt: "你是中立裁判。综合双方发言，给出结论与理由，并明确指出哪一方更站得住脚。控制在 3 句以内。" },
    ],
  },
  {
    label: "写作工坊",
    desc: "作者起草 → 编辑打磨 → 事实核查",
    agents: [
      { name: "作者", role: "writer", color: AGENT_COLORS[1],
        system_prompt: "你是作者。根据议题写出初稿，语言凝练有画面感。控制在 5 句以内。" },
      { name: "编辑", role: "editor", color: AGENT_COLORS[0],
        system_prompt: "你是资深编辑。针对上一位的初稿指出结构与措辞问题，给出改写建议。控制在 4 句以内。" },
      { name: "核查员", role: "factcheck", color: AGENT_COLORS[3],
        system_prompt: "你是事实核查员。检查前文中一切可疑的事实性表述并标注存疑点。控制在 3 句以内。" },
    ],
  },
];

const fmtTime = (ts: number) => {
  try {
    const d = new Date(ts * 1000);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
  } catch { return ""; }
};

function AgentBadge({ agent }: { agent: RoomAgent }) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium"
      style={{ background: "var(--color-bg-elevated)", color: agent.color || "var(--color-text-muted)" }}>
      <Bot size={10} /> {agent.name}
    </span>
  );
}

function Bubble({ msg, colorOf }: { msg: RoomMessage; colorOf: (m: RoomMessage) => string }) {
  const isUser = msg.role === "user";
  const color = colorOf(msg);
  return (
    <div className={`flex gap-2.5 ${isUser ? "flex-row-reverse" : ""}`}>
      <div className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 mt-0.5"
        style={{ background: "var(--color-bg-elevated)", color }}>
        {isUser ? <User size={13} /> : <Bot size={13} />}
      </div>
      <div className={`max-w-[76%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-1`}>
        <div className={`flex items-center gap-2 text-[10px] ${isUser ? "flex-row-reverse" : ""}`}>
          <span className="font-semibold" style={{ color }}>{isUser ? "你" : msg.speaker}</span>
          {!isUser && msg.role && (
            <span className="text-zinc-400 dark:text-zinc-500">{msg.role}</span>
          )}
          <span className="text-zinc-300 dark:text-zinc-600">{fmtTime(msg.ts)}</span>
        </div>
        <div className="px-3 py-2 rounded-xl text-[13px] leading-relaxed whitespace-pre-wrap break-words border"
          style={{
            background: isUser ? "var(--color-accent-bg)" : "var(--color-bg-card)",
            borderColor: isUser ? "var(--color-accent-border)" : "var(--color-border-subtle)",
            color: "var(--color-text)",
            borderLeftWidth: isUser ? undefined : 3,
            borderLeftColor: isUser ? undefined : color,
          }}>
          {msg.text}
        </div>
      </div>
    </div>
  );
}

export default function AgentRoom() {
  const [rooms, setRooms] = useState<RoomSummary[]>([]);
  const [activeId, setActiveId] = useState<string>("");
  const [detail, setDetail] = useState<RoomDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [input, setInput] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [confirmDel, setConfirmDel] = useState<string>("");
  const bottomRef = useRef<HTMLDivElement>(null);

  // 建室草稿
  const [draftName, setDraftName] = useState("");
  const [draftCanvas, setDraftCanvas] = useState("");
  const [draftAgents, setDraftAgents] = useState<DraftAgent[]>([]);
  const [creating, setCreating] = useState(false);

  const loadRooms = useCallback(async () => {
    try {
      const rs = await fetchAgentRooms();
      setRooms(rs);
      setActiveId((cur) => (cur && rs.some((r) => r.id === cur) ? cur : (rs[0]?.id || "")));
    } catch (e: any) {
      setError(e?.message || "加载协作室失败");
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    if (!id) { setDetail(null); return; }
    setLoading(true);
    try {
      setDetail(await fetchAgentRoom(id));
      setError("");
    } catch (e: any) {
      setError(e?.message || "加载协作室详情失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadRooms(); }, [loadRooms]);
  useEffect(() => { loadDetail(activeId); }, [activeId, loadDetail]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [detail?.transcript.length, sending]);

  const colorOf = useCallback((m: RoomMessage): string => {
    if (m.role === "user") return "var(--color-accent)";
    const a = detail?.agents.find((x) => x.id === m.agent_id || x.name === m.speaker);
    return a?.color || "var(--color-text-muted)";
  }, [detail]);

  const openCreate = (preset?: typeof PRESETS[number]) => {
    setDraftName(preset?.label || "");
    setDraftCanvas("");
    setDraftAgents(preset ? preset.agents.map((a) => ({ ...a })) : [
      { name: "", role: "", system_prompt: "", color: AGENT_COLORS[0] },
    ]);
    setShowCreate(true);
  };

  const doCreate = async () => {
    const name = draftName.trim();
    const agents = draftAgents.filter((a) => a.name.trim());
    if (!name) { setError("请填写协作室名称"); return; }
    if (!agents.length) { setError("至少需要一个 Agent 成员"); return; }
    setCreating(true);
    try {
      const r = await createAgentRoom(name, agents, draftCanvas.trim());
      setShowCreate(false);
      await loadRooms();
      setActiveId(r.id);
      setError("");
    } catch (e: any) {
      setError(e?.message || "创建失败");
    } finally {
      setCreating(false);
    }
  };

  const doSend = async () => {
    const text = input.trim();
    if (!text || !activeId || sending) return;
    setSending(true);
    setInput("");
    // 不做乐观插入：后端返回的 transcript 已包含完整 user 消息，
    // 乐观插入会导致同一条消息出现两次。
    try {
      const updated = await sendAgentRoomMessage(activeId, text);
      setDetail(updated);
      setRooms((rs) => rs.map((r) => r.id === activeId ? { ...r, messages: updated.transcript.length } : r));
      setError("");
    } catch (e: any) {
      setError(e?.message || "发送失败");
      loadDetail(activeId);
    } finally {
      setSending(false);
    }
  };

  const doReset = async () => {
    if (!activeId) return;
    try {
      await resetAgentRoom(activeId);
      await loadDetail(activeId);
      setRooms((rs) => rs.map((r) => r.id === activeId ? { ...r, messages: 0 } : r));
    } catch (e: any) {
      setError(e?.message || "清空失败");
    }
  };

  const doDelete = async (id: string) => {
    try {
      await deleteAgentRoom(id);
      setConfirmDel("");
      if (id === activeId) { setActiveId(""); setDetail(null); }
      await loadRooms();
    } catch (e: any) {
      setError(e?.message || "删除失败");
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* 顶部工具条 */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
        <Users size={16} className="text-zinc-400" />
        <span className="text-sm font-semibold">Agent 协作室</span>
        <span className="text-[11px] text-zinc-400">多个 Agent 同处一室，看得见彼此的发言并接力推进</span>
        <div className="flex-1" />
        <button onClick={() => loadRooms()} title="刷新"
          className="p-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500">
          <RefreshCw size={13} />
        </button>
        <button onClick={() => openCreate()}
          className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium"
          style={{ background: "var(--color-accent-bg)", color: "var(--color-accent)" }}>
          <Plus size={13} /> 新建协作室
        </button>
      </div>

      {error && (
        <div className="flex items-center gap-2 text-red-500 text-xs bg-red-50 dark:bg-red-950/40 px-6 py-2 border-b border-red-200 dark:border-red-900">
          <X size={14} className="cursor-pointer shrink-0" onClick={() => setError("")} /> {error}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* 左：协作室列表 */}
        <div className="w-56 shrink-0 border-r border-zinc-200 dark:border-zinc-800 overflow-auto p-2 space-y-1">
          {rooms.length === 0 && (
            <div className="text-[11px] text-zinc-400 px-2 py-3 leading-relaxed">
              还没有协作室。<br />从下面的模板快速开一间：
            </div>
          )}
          {rooms.map((r) => (
            <div key={r.id}
              onClick={() => setActiveId(r.id)}
              className={`group px-2.5 py-2 rounded-lg cursor-pointer border text-xs ${
                r.id === activeId
                  ? "border-transparent"
                  : "border-transparent hover:bg-zinc-100 dark:hover:bg-zinc-800"
              }`}
              style={r.id === activeId ? { background: "var(--color-accent-bg)" } : undefined}>
              <div className="flex items-center gap-1.5">
                <MessageSquare size={12} className="shrink-0 text-zinc-400" />
                <span className="flex-1 truncate font-medium">{r.name}</span>
                <button onClick={(e) => { e.stopPropagation(); setConfirmDel(r.id); }}
                  className="opacity-0 group-hover:opacity-100 text-zinc-400 hover:text-red-500">
                  <Trash2 size={11} />
                </button>
              </div>
              <div className="flex items-center gap-2 mt-1 text-[10px] text-zinc-400">
                <span>{r.agent_count} 个 Agent</span>
                <span>·</span>
                <span>{r.messages} 条发言</span>
                {r.canvas_id && (
                  <span className="inline-flex items-center gap-0.5" title={`关联画布 ${r.canvas_id}`}>
                    <Layers size={9} /> 画布
                  </span>
                )}
              </div>
            </div>
          ))}

          <div className="pt-2 mt-2 border-t border-zinc-200 dark:border-zinc-800">
            <div className="text-[10px] text-zinc-400 px-2 pb-1.5">快速模板</div>
            {PRESETS.map((p) => (
              <button key={p.label} onClick={() => openCreate(p)}
                className="w-full text-left px-2.5 py-1.5 rounded-lg hover:bg-zinc-100 dark:hover:bg-zinc-800">
                <div className="text-[11px] font-medium">{p.label}</div>
                <div className="text-[10px] text-zinc-400 truncate">{p.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* 右：对话窗口 */}
        <div className="flex-1 flex flex-col min-w-0">
          {!activeId ? (
            <div className="flex-1 flex flex-col items-center justify-center gap-2 text-zinc-400">
              <Users size={28} className="opacity-40" />
              <div className="text-xs">选择或新建一个协作室，开始多 Agent 协同</div>
            </div>
          ) : (
            <>
              {/* 成员条 */}
              <div className="flex items-center gap-2 px-5 py-2 border-b border-zinc-200 dark:border-zinc-800 shrink-0 overflow-x-auto">
                <span className="text-[10px] text-zinc-400 shrink-0">在场：</span>
                {detail?.agents.map((a) => <AgentBadge key={a.id} agent={a} />)}
                {detail?.canvas_id && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px]"
                    style={{ background: "var(--color-bg-elevated)", color: "var(--color-text-muted)" }}>
                    <Layers size={10} /> 共享画布 {detail.canvas_id}
                  </span>
                )}
                <div className="flex-1" />
                <button onClick={doReset} title="清空对话"
                  className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">
                  <Eraser size={11} /> 清空
                </button>
              </div>

              {/* 消息流 */}
              <div className="flex-1 overflow-auto px-5 py-4 space-y-4">
                {loading && (
                  <div className="flex items-center gap-2 justify-center py-10 text-zinc-400 text-xs">
                    <Loader2 size={14} className="animate-spin" /> 加载中…
                  </div>
                )}
                {!loading && detail && detail.transcript.length === 0 && (
                  <div className="text-center text-[11px] text-zinc-400 py-10 leading-relaxed">
                    抛出一个议题，{detail.agents.length} 个 Agent 会依次发言，<br />
                    后发言的能看到前面所有人说了什么。
                  </div>
                )}
                {detail?.transcript.map((m, i) => (
                  <Bubble key={`${m.ts}-${i}`} msg={m} colorOf={colorOf} />
                ))}
                {sending && (
                  <div className="flex items-center gap-2 text-[11px] text-zinc-400 pl-10">
                    <Loader2 size={12} className="animate-spin" />
                    Agent 依次发言中（共 {detail?.agents.length || 0} 位）…
                  </div>
                )}
                <div ref={bottomRef} />
              </div>

              {/* 输入区 */}
              <div className="border-t border-zinc-200 dark:border-zinc-800 p-3 shrink-0">
                <div className="flex items-end gap-2">
                  <textarea
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); }
                    }}
                    disabled={sending}
                    rows={2}
                    placeholder="向全场抛出议题…（Enter 发送 / Shift+Enter 换行）"
                    className="flex-1 resize-none text-[13px] rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 outline-none focus:border-zinc-400 dark:focus:border-zinc-600"
                  />
                  <button onClick={doSend} disabled={sending || !input.trim()}
                    className="h-9 px-3.5 rounded-xl flex items-center gap-1.5 text-xs font-medium disabled:opacity-40"
                    style={{ background: "var(--color-accent-bg)", color: "var(--color-accent)" }}>
                    {sending ? <Loader2 size={13} className="animate-spin" /> : <Send size={13} />}
                    {sending ? "协作中" : "发送"}
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* 建室弹窗 */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
          onClick={() => setShowCreate(false)}>
          <div className="w-[520px] max-w-[92vw] max-h-[88vh] overflow-auto bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 shadow-2xl p-5"
            onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-4">
              <Users size={16} className="text-zinc-400" />
              <span className="text-sm font-semibold">新建协作室</span>
              <div className="flex-1" />
              <button onClick={() => setShowCreate(false)} className="text-zinc-400 hover:text-zinc-600"><X size={15} /></button>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-4">
              <div>
                <div className="text-[11px] text-zinc-400 mb-1">协作室名称</div>
                <input value={draftName} onChange={(e) => setDraftName(e.target.value)}
                  placeholder="例：方案评审室"
                  className="w-full text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-2.5 py-1.5 outline-none" />
              </div>
              <div>
                <div className="text-[11px] text-zinc-400 mb-1">关联画布 ID（选填）</div>
                <input value={draftCanvas} onChange={(e) => setDraftCanvas(e.target.value)}
                  placeholder="留空则不共享画布"
                  className="w-full text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-2.5 py-1.5 outline-none" />
              </div>
            </div>

            <div className="flex items-center gap-2 mb-2">
              <div className="text-[11px] text-zinc-400">Agent 成员</div>
              <div className="flex-1" />
              <button
                onClick={() => setDraftAgents((a) => [...a, { name: "", role: "", system_prompt: "", color: AGENT_COLORS[a.length % AGENT_COLORS.length] }])}
                className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300">
                <Plus size={11} /> 添加
              </button>
            </div>

            <div className="space-y-2 mb-4">
              {draftAgents.map((a, i) => (
                <div key={i} className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-2.5 bg-zinc-50 dark:bg-zinc-950">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: a.color }} />
                    <input value={a.name}
                      onChange={(e) => setDraftAgents((arr) => arr.map((x, j) => j === i ? { ...x, name: e.target.value } : x))}
                      placeholder="名字，例：架构师"
                      className="flex-1 text-xs rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1 outline-none" />
                    <input value={a.role}
                      onChange={(e) => setDraftAgents((arr) => arr.map((x, j) => j === i ? { ...x, role: e.target.value } : x))}
                      placeholder="角色标识"
                      className="w-24 text-xs rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1 outline-none" />
                    <button onClick={() => setDraftAgents((arr) => arr.filter((_, j) => j !== i))}
                      className="text-zinc-400 hover:text-red-500"><Trash2 size={12} /></button>
                  </div>
                  <textarea value={a.system_prompt} rows={2}
                    onChange={(e) => setDraftAgents((arr) => arr.map((x, j) => j === i ? { ...x, system_prompt: e.target.value } : x))}
                    placeholder="这个 Agent 的人设与职责（system prompt）"
                    className="w-full resize-none text-[11px] rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 outline-none" />
                  <div className="flex items-center gap-1.5 mt-1.5">
                    {AGENT_COLORS.map((c) => (
                      <button key={c} onClick={() => setDraftAgents((arr) => arr.map((x, j) => j === i ? { ...x, color: c } : x))}
                        className={`w-4 h-4 rounded-full ${a.color === c ? "ring-2 ring-offset-1 ring-zinc-400 dark:ring-offset-zinc-950" : ""}`}
                        style={{ background: c }} />
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <div className="flex items-center gap-2">
              <button onClick={doCreate} disabled={creating}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium disabled:opacity-50"
                style={{ background: "var(--color-accent-bg)", color: "var(--color-accent)" }}>
                {creating ? <Loader2 size={12} className="animate-spin" /> : <Plus size={12} />} 创建
              </button>
              <button onClick={() => setShowCreate(false)}
                className="px-3 py-1.5 rounded-lg text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">取消</button>
            </div>
          </div>
        </div>
      )}

      {/* 删除确认 */}
      {confirmDel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={() => setConfirmDel("")}>
          <div className="w-[320px] bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 shadow-2xl p-5"
            onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-semibold mb-1.5">删除协作室？</div>
            <div className="text-[11px] text-zinc-400 mb-4">该协作室的成员与全部发言记录将被移除，不可恢复。</div>
            <div className="flex items-center gap-2">
              <button onClick={() => doDelete(confirmDel)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium text-red-500 bg-red-50 dark:bg-red-950/40">删除</button>
              <button onClick={() => setConfirmDel("")}
                className="px-3 py-1.5 rounded-lg text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

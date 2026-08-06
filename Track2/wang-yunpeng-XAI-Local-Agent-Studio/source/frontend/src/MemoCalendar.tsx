// 备忘录日历（Memo Calendar）— 重复/定时工作与事件以备忘录形式在日历上显示，可拖拽调整
// 库：react-big-calendar（月/周/日/议程视图 + 拖拽） + rbc-recurrence（重复规则编辑器 + RRULE 展开）
// 设计：玻璃卡片包裹；事件 chip 用 node token 色（与全局徽章/画布同语言）；不改变全局 token 数值。
import { useCallback, useEffect, useMemo, useState } from "react"
import { Calendar, dateFnsLocalizer, type View } from "react-big-calendar"
import { format, parse, startOfWeek, getDay, addMinutes, addDays } from "date-fns"
import { zhCN } from "date-fns/locale"
import "react-big-calendar/lib/css/react-big-calendar.css"
import { expand, fromRRuleString, toRRuleString, type RecurrenceRule } from "rbc-recurrence"
import { RecurrenceEditor } from "rbc-recurrence/react"
import { CalendarDays, Plus, Trash2, Check, X, StickyNote, Flag, Download, RefreshCw, Loader2, Eye, Edit3, Image as ImageIcon } from "lucide-react"
import { fetchMemos, createMemo, updateMemo, deleteMemo, uploadFile, blobToDataUrl, type Memo } from "./lib/api"

const localizer = dateFnsLocalizer({
  format,
  parse,
  startOfWeek,
  getDay,
  locales: { "zh-CN": zhCN },
})

const NODE_BG: Record<string, string> = {
  logic: "var(--color-node-logic-bg)",
  system: "var(--color-node-system-bg)",
  input: "var(--color-node-input-bg)",
  data: "var(--color-node-data-bg)",
  ai: "var(--color-node-ai-bg)",
}
const NODE_TEXT: Record<string, string> = {
  logic: "var(--color-node-logic)",
  system: "var(--color-node-system)",
  input: "var(--color-node-input)",
  data: "var(--color-node-data)",
  ai: "var(--color-node-ai)",
}
const COLOR_LABEL: Record<string, string> = {
  logic: "逻辑/成功",
  system: "系统/危险",
  input: "输入/信息",
  data: "数据/警告",
  ai: "AI/智能",
}

const fmtDate = (d: Date) => format(d, "yyyy-MM-dd")
const fmtTime = (d: Date) => format(d, "HH:mm")
const mergeDateTime = (date: Date, time?: string) => {
  const d = new Date(date)
  if (time && /^\d{1,2}:\d{2}$/.test(time)) {
    const [h, m] = time.split(":").map(Number)
    d.setHours(h, m, 0, 0)
  } else {
    d.setHours(0, 0, 0, 0)
  }
  return d
}

function buildEvents(memos: Memo[], range: { start: Date; end: Date }): any[] {
  const out: any[] = []
  for (const m of memos) {
    if (m.rrule) {
      try {
        const rule = fromRRuleString(m.rrule)
        const occ = expand(rule, { rangeStart: range.start, rangeEnd: range.end })
        for (const o of occ) {
          const start = mergeDateTime(o.date, m.time)
          const end = m.time ? addMinutes(start, 60) : addDays(start, 1)
          out.push({ title: m.title, start, end, allDay: !m.time, memo: m, resource: m.color })
        }
      } catch {
        // 非法 RRULE 跳过，不阻断渲染
      }
    } else {
      const start = mergeDateTime(new Date(m.date + "T00:00:00"), m.time)
      const end = m.time ? addMinutes(start, 60) : addDays(start, 1)
      out.push({ title: m.title, start, end, allDay: !m.time, memo: m, resource: m.color })
    }
  }
  return out
}

function buildICS(memos: Memo[]): string {
  const lines: string[] = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//XAI//MemoCalendar//CN", "CALSCALE:GREGORIAN"]
  for (const m of memos) {
    lines.push("BEGIN:VEVENT")
    lines.push("UID:" + m.id + "@xai")
    lines.push("SUMMARY:" + (m.title || "").replace(/\n/g, " "))
    if (m.notes) lines.push("DESCRIPTION:" + m.notes.replace(/\n/g, " "))
    if (m.rrule) {
      const dt = mergeDateTime(new Date(m.date + "T00:00:00"), m.time)
      lines.push("DTSTART:" + format(dt, "yyyyMMdd'T'HHmmss"))
      lines.push("RRULE:" + m.rrule.replace(/^RRULE:/, ""))
    } else {
      const s = mergeDateTime(new Date(m.date + "T00:00:00"), m.time)
      const e = m.time ? addMinutes(s, 60) : addDays(s, 1)
      lines.push("DTSTART:" + format(s, "yyyyMMdd'T'HHmmss"))
      lines.push("DTEND:" + format(e, "yyyyMMdd'T'HHmmss"))
    }
    lines.push("END:VEVENT")
  }
  lines.push("END:VCALENDAR")
  return lines.join("\r\n")
}

const PRIORITY_OPTS: Array<Memo["priority"]> = ["low", "mid", "high"]
const COLOR_OPTS = Object.keys(NODE_BG) as Array<Memo["color"]>

export default function MemoCalendar() {
  const [memos, setMemos] = useState<Memo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [view, setView] = useState<View>("month")
  const [range, setRange] = useState<{ start: Date; end: Date }>({
    start: startOfWeek(new Date(), { weekStartsOn: 1 }),
    end: addDays(startOfWeek(new Date(), { weekStartsOn: 1 }), 34),
  })
  const [editing, setEditing] = useState<Memo | null>(null)
  const [showEditor, setShowEditor] = useState(false)
  const [notesPreview, setNotesPreview] = useState(false) // Markdown 预览模式
  const [notesAttachment, setNotesAttachment] = useState<{ name: string; uploading: boolean; ref?: string } | null>(null)

  // 粘贴图片到备注
  const handleNotesPaste = async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (item.kind === "file" && item.type.startsWith("image/")) {
        e.preventDefault()
        const file = item.getAsFile()
        if (file && editing) {
          const name = file.name || `paste_${Date.now()}.png`
          setNotesAttachment({ name, uploading: true })
          try {
            const result = await uploadFile(file)
            const mdImg = `\n![${name}](${result.ref})\n`
            setEditing({ ...editing, notes: (editing.notes || "") + mdImg })
            setNotesAttachment(null)
          } catch (err) {
            setNotesAttachment({ name, uploading: false })
          }
        }
      }
    }
  }

  const load = useCallback(() => {
    setLoading(true)
    setError("")
    fetchMemos().then(setMemos).catch((e) => setError(e?.message || "加载失败")).finally(() => setLoading(false))
  }, [])
  useEffect(load, [])

  const events = useMemo(() => buildEvents(memos, range), [memos, range])

  const openNew = (date?: Date) => {
    const d = date || new Date()
    setEditing({
      id: "", title: "", notes: "", date: fmtDate(d), time: "", allDay: true,
      rrule: undefined, done: false, priority: "mid", color: "logic",
    })
    setShowEditor(true)
  }
  const openEdit = (m: Memo) => {
    setEditing({ ...m, allDay: m.allDay ?? !m.time })
    setShowEditor(true)
  }
  const closeEditor = () => { setShowEditor(false); setEditing(null) }

  const save = async () => {
    if (!editing) return
    const payload: Partial<Memo> = {
      title: editing.title,
      notes: editing.notes,
      date: editing.date,
      time: editing.allDay ? undefined : editing.time || "09:00",
      allDay: editing.allDay,
      rrule: editing.rrule || undefined,
      done: editing.done,
      priority: editing.priority,
      color: editing.color,
    }
    try {
      if (editing.id) {
        await updateMemo(editing.id, payload)
      } else {
        await createMemo(payload)
      }
      closeEditor()
      load()
    } catch (e: any) {
      setError(e?.message || "保存失败")
    }
  }
  const remove = async () => {
    if (!editing?.id) return
    try { await deleteMemo(editing.id); closeEditor(); load() } catch (e: any) { setError(e?.message || "删除失败") }
  }

  const onEventDrop = async ({ event, start }: any) => {
    const m: Memo = event.memo
    if (!m?.id) return
    try {
      await updateMemo(m.id, { date: fmtDate(start), time: m.time ? fmtTime(start) : undefined })
      load()
    } catch (e: any) { setError(e?.message || "改期失败") }
  }
  const onEventResize = async ({ event, start }: any) => {
    const m: Memo = event.memo
    if (!m?.id) return
    try { await updateMemo(m.id, { date: fmtDate(start), time: m.time ? fmtTime(start) : undefined }); load() } catch {}
  }

  const exportICS = () => {
    const blob = new Blob([buildICS(memos)], { type: "text/calendar;charset=utf-8" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url; a.download = "xai-memos.ics"; a.click()
    URL.revokeObjectURL(url)
  }

  const eventPropGetter = (event: any) => {
    const c = (event.memo?.color as string) || "logic"
    const done = event.memo?.done
    return {
      style: {
        backgroundColor: NODE_BG[c] || NODE_BG.logic,
        color: NODE_TEXT[c] || NODE_TEXT.logic,
        border: "none",
        borderRadius: 8,
        padding: "2px 6px",
        fontSize: 12,
        opacity: done ? 0.5 : 1,
        textDecoration: done ? "line-through" : "none",
      } as React.CSSProperties,
    }
  }

  return (
    <main className="flex-1 overflow-hidden flex flex-col bg-zinc-50 dark:bg-zinc-950 memo-calendar">
      {/* 标题栏 */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shrink-0">
        <CalendarDays size={18} />
        <h2 className="text-lg font-semibold">备忘录日历</h2>
        <span className="text-[11px] text-zinc-400 ml-1">重复 / 定时工作 · {memos.length} 条</span>
        <button onClick={load} title="刷新" className="ml-auto p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400">
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
        </button>
        <button onClick={exportICS} title="导出 iCal" className="p-1.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400" disabled={!memos.length}>
          <Download size={14} />
        </button>
        <button onClick={() => openNew()} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-blue-500 text-white hover:bg-blue-600 transition-colors">
          <Plus size={13} /> 新建备忘录
        </button>
      </div>

      {error && <div className="flex items-center gap-2 text-red-500 text-xs bg-red-50 dark:bg-red-950/40 px-6 py-2 border-b border-red-200 dark:border-red-900"><X size={14} /> {error}</div>}

      {/* 日历主体 */}
      <div className="flex-1 overflow-auto p-4">
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 p-3 h-full">
          {loading ? (
            <div className="flex items-center gap-2 justify-center py-20 text-zinc-400 text-xs"><Loader2 size={14} className="animate-spin" /> 加载备忘录…</div>
          ) : (
            <Calendar
              localizer={localizer}
              events={events}
              view={view}
              onView={setView}
              views={["month", "week", "day", "agenda"]}
              startAccessor="start"
              endAccessor="end"
              onRangeChange={(r: any) => {
                const start = r.start || (Array.isArray(r) ? r[0] : new Date())
                const end = r.end || (Array.isArray(r) ? r[r.length - 1] : addDays(new Date(), 1))
                setRange({ start, end })
              }}
              onSelectEvent={(e: any) => openEdit(e.memo as Memo)}
              onSelectSlot={(s: any) => openNew(s.start)}
              onEventDrop={onEventDrop}
              onEventResize={onEventResize}
              selectable
              popup
              eventPropGetter={eventPropGetter}
              messages={{
                month: "月", week: "周", day: "日", agenda: "议程",
                today: "今天", previous: "‹", next: "›",
                showMore: (n: number) => `+${n} 条`,
              }}
              style={{ height: "100%", minHeight: 520 }}
            />
          )}
        </div>
      </div>

      {/* 编辑器弹层 */}
      {showEditor && editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" onClick={closeEditor}>
          <div className="w-[460px] max-w-[92vw] max-h-[88vh] overflow-auto bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 shadow-2xl p-5" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 mb-4">
              <StickyNote size={16} className="text-blue-500" />
              <span className="text-sm font-semibold">{editing.id ? "编辑备忘录" : "新建备忘录"}</span>
              <button onClick={closeEditor} className="ml-auto p-1 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-400"><X size={16} /></button>
            </div>

            <label className="block text-[11px] text-zinc-400 mb-1">标题</label>
            <input value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })}
              className="w-full text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 outline-none focus:border-blue-400 mb-3" placeholder="例如：每周一同步记忆注入" />

            <div className="flex items-center gap-1 mb-1">
              <label className="text-[11px] text-zinc-400 flex-1">备注（支持 Markdown / 粘贴图片）</label>
              <button
                type="button"
                onClick={() => setNotesPreview(!notesPreview)}
                title={notesPreview ? "切换编辑" : "切换预览"}
                className="p-1 rounded text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 text-[10px] flex items-center gap-1"
              >
                {notesPreview ? <><Edit3 size={11} /> 编辑</> : <><Eye size={11} /> 预览</>}
              </button>
            </div>
            {notesPreview ? (
              <div className="w-full min-h-[80px] text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 mb-3 prose prose-sm dark:prose-invert max-w-none overflow-auto"
                dangerouslySetInnerHTML={{
                  __html: (editing.notes || "").replace(/!\[([^\]]*)\]\(@file:([^)]+)\)/g, '<img src="/api/file/preview/$2" alt="$1" style="max-width:100%;border-radius:8px;margin:4px 0"/>')
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                    .replace(/\*(.+?)\*/g, '<em>$1</em>')
                    .replace(/`(.+?)`/g, '<code style="background:rgba(124,58,237,0.1);padding:1px 4px;border-radius:3px;font-size:12px">$1</code>')
                    .replace(/\n/g, '<br/>')
                }}
              />
            ) : (
              <textarea value={editing.notes || ""} onChange={(e) => setEditing({ ...editing, notes: e.target.value })}
                onPaste={handleNotesPaste}
                rows={3} className="w-full text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 outline-none focus:border-blue-400 mb-1 resize-y font-mono" placeholder="支持 Markdown 语法。可直接粘贴截图…" />
            )}
            {notesAttachment && (
              <div className="flex items-center gap-2 text-[11px] mb-3 text-zinc-400">
                <ImageIcon size={11} className={notesAttachment.uploading ? "animate-pulse text-blue-400" : ""} />
                {notesAttachment.name}
                {notesAttachment.uploading ? " 上传中…" : ""}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">日期</label>
                <input type="date" value={editing.date} onChange={(e) => setEditing({ ...editing, date: e.target.value })}
                  className="w-full text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 outline-none focus:border-blue-400" />
              </div>
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">时间（留空=全天）</label>
                <input type="time" value={editing.time || ""} disabled={editing.allDay} onChange={(e) => setEditing({ ...editing, time: e.target.value })}
                  className="w-full text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 outline-none focus:border-blue-400 disabled:opacity-40" />
              </div>
            </div>

            <div className="flex items-center gap-4 mb-3">
              <label className="flex items-center gap-1.5 text-xs text-zinc-500 cursor-pointer">
                <input type="checkbox" checked={!!editing.allDay} onChange={(e) => setEditing({ ...editing, allDay: e.target.checked })} className="accent-blue-500" /> 全天
              </label>
              <label className="flex items-center gap-1.5 text-xs text-zinc-500 cursor-pointer">
                <input type="checkbox" checked={!!editing.done} onChange={(e) => setEditing({ ...editing, done: e.target.checked })} className="accent-emerald-500" /> 已完成
              </label>
            </div>

            <div className="grid grid-cols-2 gap-3 mb-3">
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1"><Flag size={11} className="inline" /> 优先级</label>
                <select value={editing.priority} onChange={(e) => setEditing({ ...editing, priority: e.target.value as Memo["priority"] })}
                  className="w-full text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 outline-none">
                  {PRIORITY_OPTS.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-[11px] text-zinc-400 mb-1">颜色</label>
                <select value={editing.color} onChange={(e) => setEditing({ ...editing, color: e.target.value as Memo["color"] })}
                  className="w-full text-sm rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1.5 outline-none">
                  {COLOR_OPTS.map((c) => <option key={c} value={c}>{COLOR_LABEL[c]}</option>)}
                </select>
              </div>
            </div>

            {/* 重复规则编辑器 */}
            <div className="mb-2">
              <label className="flex items-center gap-1.5 text-xs text-zinc-500 cursor-pointer mb-2">
                <input type="checkbox" checked={!!editing.rrule} onChange={(e) => setEditing({ ...editing, rrule: e.target.checked ? "FREQ=WEEKLY;BYDAY=MO" : undefined })} className="accent-blue-500" /> 重复
              </label>
              {editing.rrule !== undefined && (
                <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 p-2 bg-zinc-50 dark:bg-zinc-950">
                  <RecurrenceEditor
                    initialRule={editing.rrule ? safeRule(editing.rrule) : { startDate: new Date(editing.date), interval: 1, period: "week", end: { type: "never" } }}
                    onValidChange={(rule: RecurrenceRule) => setEditing({ ...editing, rrule: toRRuleString(rule) })}
                  />
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 mt-4">
              {editing.id && (
                <button onClick={remove} className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs text-red-600 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"><Trash2 size={13} /> 删除</button>
              )}
              <button onClick={closeEditor} className="ml-auto px-3 py-1.5 rounded-lg text-xs text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800">取消</button>
              <button onClick={save} disabled={!editing.title.trim()} className="flex items-center gap-1 px-4 py-1.5 rounded-lg text-xs font-medium bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 transition-colors"><Check size={13} /> 保存</button>
            </div>
          </div>
        </div>
      )}
    </main>
  )
}

// 把存储的 RRULE 字符串安全转成 RecurrenceRule（用于编辑器回填）
function safeRule(rrule: string): RecurrenceRule {
  try { return fromRRuleString(rrule) } catch { return { startDate: new Date(), interval: 1, period: "week", end: { type: "never" } } }
}

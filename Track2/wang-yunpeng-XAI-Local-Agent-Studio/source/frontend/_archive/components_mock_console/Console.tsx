import { useState } from 'react'
import { useStore } from '../store'
import type { NodeKind } from '../blueprint'
import { NODE_META, classifyIntent } from '../blueprint'

function Bar({ value, color }: { value: number; color: string }) {
  return (
    <div className="bar">
      <div className="bar-fill" style={{ width: `${Math.min(100, value * 100)}%`, background: color }} />
    </div>
  )
}

export function Console() {
  const s = useStore()
  const [intentText, setIntentText] = useState('帮我重构这个 Python 仓库里的 bug')
  const intent = classifyIntent(intentText)
  const routed: NodeKind = (intent.route in NODE_META ? (intent.route as NodeKind) : 'agent')
  const routedColor = NODE_META[routed].color
  const statusColor: Record<string, string> = {
    working: '#16a34a', idle: '#94a3b8', busy: '#d97706', offline: '#cbd5e1',
  }
  return (
    <aside className="console">
      <div className="console-title">🛰️ XAI 统一调度台</div>
      <div className="console-sub">底座 = Grok · 模型无关</div>

      <section className="panel">
        <div className="panel-h">数字员工花名册</div>
        {s.agents.map((a) => (
          <div className="agent" key={a.id}>
            <span className="dot" style={{ background: statusColor[a.status] }} />
            <div className="agent-main">
              <div className="agent-name">{a.name}</div>
              <div className="agent-role">{a.role} · {a.tasks} 任务 · {a.runtime}</div>
              <Bar value={a.efficiency} color="#2563eb" />
            </div>
            <div className="agent-eff">{Math.round(a.efficiency * 100)}%</div>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="panel-h">模型路由状态</div>
        {s.models.map((m) => (
          <div className={'model ' + (m.active ? 'model-on' : '')} key={m.name}>
            <div className="model-name">{m.name} {m.active && <span className="tag">active</span>}</div>
            <div className="model-meta">能力 {m.capability} · 成本 {m.cost} · {m.latency}ms</div>
            <Bar value={m.capability} color="#0891b2" />
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="panel-h">知识库 / 记忆</div>
        <div className="kv"><span>本地块</span><b>{s.kb.chunks}</b></div>
        <div className="kv"><span>检索命中</span><b>{s.kb.hits}</b></div>
        <div className="kv"><span>短期/中期/长期/技能</span><b>{s.kb.mem.short}/{s.kb.mem.medium}/{s.kb.mem.long}/{s.kb.mem.skill}</b></div>
      </section>

      <section className="panel">
        <div className="panel-h">审批队列 (Guardian)</div>
        {s.guardianQueue.length === 0 && <div className="empty">无待审动作</div>}
        {s.guardianQueue.map((g) => (
          <div className="guard" key={g.id}>
            <span className="guard-lvl">P0</span>
            <div className="guard-main">
              <div>{g.action}</div>
              <div className="guard-st">{g.id} · {g.status}</div>
            </div>
          </div>
        ))}
      </section>

      <section className="panel">
        <div className="panel-h">长任务进度 (Runner)</div>
        <div className="kv"><span>目标</span><b>{s.runner.goal}</b></div>
        <Bar value={s.runner.total ? s.runner.current / s.runner.total : 0} color="#16a34a" />
        <div className="kv"><span>里程碑</span><b>{s.runner.current}/{s.runner.total} {s.runner.done ? '✅' : ''}</b></div>
      </section>

      <section className="panel">
        <div className="panel-h">可观测</div>
        <div className="kv"><span>请求/延迟/错误</span><b>{s.observability.requests} · {s.observability.latency}ms · {s.observability.errors}</b></div>
        <div className="kv"><span>Token</span><b>{s.observability.tokens.toLocaleString()}</b></div>
        <div className="kv"><span>Brier 校准</span><b>{s.observability.brier}</b></div>
      </section>

      <section className="panel">
        <div className="panel-h">自进化 (Distill/GEPA)</div>
        <div className="kv"><span>技能库</span><b>{s.distill.skills}</b></div>
        <div className="kv"><span>上次进化命中</span><b>{Math.round(s.distill.lastHit * 100)}%</b></div>
        <div className="kv"><span>待人工复审</span><b>{s.distill.pendingReview}</b></div>
      </section>

      <section className="panel">
        <div className="panel-h">意图识别 (Intent Router)</div>
        <textarea className="intent-input" value={intentText} onChange={(e) => setIntentText(e.target.value)} rows={2} />
        <div className="intent-out">
          <span className="tag" style={{ background: routedColor }}>{intent.label}</span>
          <span className="intent-conf">置信 {Math.round(intent.conf * 100)}%</span>
        </div>
        <div className="kv"><span>分发引擎</span><b>{intent.route}</b></div>
      </section>

      <section className="panel">
        <div className="panel-h">全局统一记忆池 (痛点1)</div>
        <div className="memgrid">
          {Object.entries(s.memoryPool).map(([k, v]) => (
            <div className="memcell" key={k}><b>{v}</b><span>{k}</span></div>
          ))}
        </div>
        <div className="kv"><span>引擎标签去割裂</span><b>跨引擎共享读写 ✅</b></div>
      </section>

      <section className="panel">
        <div className="panel-h">权限分级 (痛点3)</div>
        <div className="kv"><span>VIEWER</span><b>只读</b></div>
        <div className="kv"><span>OPERATOR</span><b>常规执行</b></div>
        <div className="kv"><span>ADMIN</span><b>高危/系统级审批</b></div>
        <div className="kv"><span>高危删除/系统修改</span><b>二次确认拦截 ✅</b></div>
      </section>
    </aside>
  )
}

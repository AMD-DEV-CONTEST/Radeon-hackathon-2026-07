import { useStore } from '../store'
import { NODE_META } from '../blueprint'

function CapRow({ name, module, ok, detail }: { name: string; module: string; ok: boolean; detail: string }) {
  return (
    <div className="cap">
      <span className={'cap-led ' + (ok ? 'on' : 'off')} />
      <div className="cap-main">
        <div className="cap-name">{name} <span className="cap-mod">{module}</span></div>
        <div className="cap-detail">{detail}</div>
      </div>
    </div>
  )
}

export function Inspector() {
  const s = useStore()
  const meta = s.selectedNodeMeta
  const nodeMeta = meta ? NODE_META[meta.kind] : null
  const running = s.runStatus === 'running'

  return (
    <aside className="inspector">
      <div className="panel-h">检查器</div>
      {meta && nodeMeta ? (
        <section className="panel sel-node" style={{ borderColor: nodeMeta.color }}>
          <div className="sel-head" style={{ background: nodeMeta.color }}>
            {nodeMeta.icon} {nodeMeta.label}
          </div>
          <div className="kv"><span>节点ID</span><b>{s.selectedNode}</b></div>
          <div className="kv"><span>名称</span><b>{meta.label}</b></div>
          <div className="kv"><span>模块</span><b>{nodeMeta.module}</b></div>
          <div className="kv"><span>状态</span><b>{meta.status}</b></div>
          <div className="sel-desc">{nodeMeta.desc}</div>
        </section>
      ) : (
        <div className="empty">点击画布节点查看详情</div>
      )}

      <section className="panel">
        <div className="panel-h">能力状态（实时）</div>
        <CapRow name="Guardian 审批" module="P0 闸门" ok={!running || s.guardianQueue.length >= 0} detail={`待审 ${s.guardianQueue.length} · 治理策略生效`} />
        <CapRow name="Reason 思考" module="P0.5" ok detail="推理预算/协议/自精炼/多轨迹 就绪" />
        <CapRow name="Meta 校准" module="P10" ok={s.observability.brier < 0.2} detail={`Brier ${s.observability.brier} · L8 四维审计`} />
        <CapRow name="Runner 长任务" module="§10" ok={!s.runner.done} detail={`里程碑 ${s.runner.current}/${s.runner.total}`} />
        <CapRow name="KB 记忆" module="RAG" ok detail={`块 ${s.kb.chunks} · 命中 ${s.kb.hits}`} />
        <CapRow name="Orchestrator" module="P6/7" ok detail={`数字员工 ${s.agents.length} · 消息总线`} />
        <CapRow name="Distill 自进化" module="P9 GEPA" ok detail={`技能 ${s.distill.skills} · 待复审 ${s.distill.pendingReview}`} />
      </section>

      <section className="panel">
        <div className="panel-h">A2UI 事件类型</div>
        <div className="chips">
          {['thinking', 'tool_call', 'tool_result', 'interrupt', 'progress', 'agent_switch', 'done'].map((t) => (
            <span className={'chip chip-' + t} key={t}>{t}</span>
          ))}
        </div>
      </section>
    </aside>
  )
}

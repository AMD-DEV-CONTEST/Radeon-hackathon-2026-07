// 实时状态 widget (节点④ 右栏) —— 从 App.tsx 抽出，叠加 OllamaFLOW 风格 3D
// 3D 实现见 effects.css：.xai-3d-stage / .xai-3d / .xai-3d-edge / .xai-3d-card
// 仅使用 var(--color-*)/var(--glass-*) 令牌，双主题、尊重 prefers-reduced-motion。

interface SystemStatus {
  xai_engine: string;
  model: string;
  pending_approvals: number;
  [k: string]: any;
}

interface Props {
  status: SystemStatus | null;
  memInfo: { layers: number; total: number } | null;
  sysHealth?: any;
  sysSandbox?: any;
  sysErrors?: any;
}

export default function StatusWidget({ status, memInfo, sysHealth, sysSandbox, sysErrors }: Props) {
  const cards: [string, string][] = [
    ["系统", status?.xai_engine || "connecting"],
    ["记忆", memInfo ? `${memInfo.layers}层 · ${memInfo.total}条` : "加载中…"],
    ["Guardian", `${status?.pending_approvals ?? 0} 待审批`],
    ["模型", status?.model || "-"],
    ["沙箱", sysSandbox?.effective || (sysHealth?.healthy ? "已就绪" : "—")],
    ["系统错误", `${sysErrors?.count ?? 0} 条`],
  ];

  const subsystems: [string, boolean | undefined][] = [
    ["Hermes", (status as any)?.hermes?.ok],
    ["OpenClaw", (status as any)?.openclaw?.ok],
    ["Memory", (status as any)?.memory?.ok],
    ["引擎", status?.xai_engine === "running"],
  ];

  return (
    <div className="xai-3d-stage">
      <div className="text-[10px] uppercase tracking-wider text-zinc-400 mb-3">实时状态</div>
      <div className="space-y-2 text-xs">
        {cards.map(([title, sub]) => (
          <div key={title} className="xai-3d xai-3d-edge xai-3d-card">
            <div className="font-medium">{title}</div>
            <div className="text-zinc-400 text-[10px] mt-0.5">{sub}</div>
          </div>
        ))}
      </div>

      <div className="text-[10px] uppercase tracking-wider text-zinc-400 mt-4 mb-2">子系统</div>
      <div className="space-y-1 text-[10px] text-zinc-400">
        {subsystems.map(([name, ok]) => (
          <div key={String(name)} className="xai-3d xai-3d-edge xai-3d-row flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full shrink-0"
              style={{ background: ok ? "var(--color-node-logic)" : "var(--color-text-subtle)" }}
            />
            {name} {ok ? "正常" : "未知"}
          </div>
        ))}
      </div>
    </div>
  );
}

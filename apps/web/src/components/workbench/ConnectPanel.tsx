/**
 * T2-2 · 通用工作台 · ConnectPanel
 *
 * 每台机型都需要"连接"这一步。此面板读 manifest.transport 与 manifest.service，
 * 渲染连接配置（端口、host、SDK 路径等）和健康检查结果。
 *
 * 当前阶段：占位实现，只展示 manifest 里的 transport / service 元数据。
 * 下一步：接入 useRobotRuntimeState + getRobotHealth，做成可交互的连接面板。
 *
 * 见 progress/M28-consolidation-execution-plan.md T2-2。
 */
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../ui/card'
import type { WorkbenchPanelProps } from './panelRegistry'
import { matchByCapabilityTag, registerWorkbenchPanel } from './panelRegistry'

function ConnectPanel({ manifest }: WorkbenchPanelProps) {
  const transport = manifest.transport
  const service = manifest.service

  return (
    <Card className="bg-card/60">
      <CardHeader>
        <CardTitle className="text-base">连接 {manifest.display_name}</CardTitle>
        <CardDescription>
          根据 manifest 里的 transport 与 service 配置，把机器人接到本机或远端 Host。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-xs">
        {transport && (
          <div className="rounded-lg border border-border/70 p-3">
            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Transport
            </div>
            <div className="mt-1 font-mono text-sm">{transport.kind}</div>
            {transport.ports && (
              <ul className="mt-2 space-y-0.5 text-[11px] text-muted-foreground">
                {Object.entries(transport.ports).map(([k, v]) => (
                  <li key={k}>
                    <span className="text-foreground">{k}</span>: <code>{v}</code>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        {service && (
          <div className="rounded-lg border border-border/70 p-3">
            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              Service
            </div>
            <div className="mt-1 font-mono text-sm">{service.kind}</div>
            {service.host && (
              <div className="mt-1 text-[11px] text-muted-foreground">
                host: <code>{service.host}</code>
                {service.port != null && <>:{service.port}</>}
              </div>
            )}
            {service.sdk_path && (
              <div className="mt-1 text-[11px] text-muted-foreground">
                sdk: <code>{service.sdk_path}</code>
              </div>
            )}
          </div>
        )}
        <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-[11px] text-amber-200/80">
          通用工作台框架已就位，但 ConnectPanel 仍是占位。LeKiwi 现有页面 (RobotLeKiwi.tsx) 继续可用，
          待面板逐个迁移完成后再切换。
        </div>
      </CardContent>
    </Card>
  )
}

registerWorkbenchPanel({
  id: 'connect',
  title: '连接',
  // connect 面板永远渲染，matches 返回 true；panelsForManifest 也会强制包含。
  matches: matchByCapabilityTag('connect'),
  component: ConnectPanel,
  order: 10,
})

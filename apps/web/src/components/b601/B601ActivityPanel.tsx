/**
 * B601 操作透明面板 — 用户有权知道平台在后台做了什么（对应 Seeed Wiki / MotorBridge 官方流程）。
 */
import { Activity, Volume2 } from 'lucide-react'
import { cn } from '../../lib/utils'

export interface B601ActivityEntry {
  id: string
  time: string
  label: string
  detail: string
  /** 可能听到电机短促声（enable / 自检） */
  audible?: boolean
}

export const B601_ACTION_GUIDE: Record<
  string,
  { label: string; detail: string; audible?: boolean; wiki?: string }
> = {
  health_poll: {
    label: '状态检测',
    detail: '只读检查从臂链路、主臂 USB 与电机在线数，不会动电机。',
  },
  can_up: {
    label: 'CAN 总线配置',
    detail: '把 PCAN-USB 的 can0 设为 1 Mbps（与 Seeed 入门 Wiki 相同），不涉及关节力矩。',
  },
  recover: {
    label: '检查从臂',
    detail:
      'RS 会走官方 recover；DM 默认只读扫描 1~7 号电机。约 10 秒内应开始遥操，否则电机会自动卸力。',
    audible: true,
  },
  teleop_start: {
    label: '启动遥操',
    detail:
      '官方遥操栈：connect → configure()（先卸力再逐关节上电，约十秒）→ 进入跟随。此时从臂有力矩，可动主臂。',
    audible: true,
  },
  teleop_stop: {
    label: '停止遥操',
    detail: '先优雅停止遥操进程，再对 7 关节执行卸力，从臂应可手推。',
    audible: true,
  },
  disable: {
    label: '从臂卸力',
    detail: '官方 disable 命令，与遥操 disconnect 相同，从臂应可手推。',
    audible: true,
  },
  record_start: {
    label: '开始录制',
    detail: '启动官方录数 CLI，在遥操同时把关节与相机画面写入本地数据集。',
    audible: true,
  },
  calibrate_start: {
    label: '开始校准',
    detail: '启动官方校准 CLI。按日志提示把臂移到零点后点「继续」。',
  },
  urdf_mesh_fail: {
    label: '3D 零件加载失败',
    detail: '某个 STL 未返回 200，Stage 会用红色标记。请检查 Local Agent 是否用 --http 启动且 URDF 资产完整。',
  },
}

interface Props {
  entries: B601ActivityEntry[]
  className?: string
}

export function B601ActivityPanel({ entries, className }: Props) {
  return (
    <div
      className={cn(
        'rounded-lg border border-white/10 bg-black/30 p-3 text-xs space-y-2',
        className,
      )}
    >
      <div className="flex items-center gap-2 font-medium text-[hsl(var(--foreground))]/90">
        <Activity className="h-3.5 w-3.5 text-[hsl(var(--primary))]" />
        正在发生什么
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        底层与 Seeed 官方栈一致。带
        <Volume2 className="mx-0.5 inline h-3 w-3 text-amber-400" />
        标记的操作可能听到电机声。
      </p>
      {entries.length === 0 ? (
        <p className="text-[11px] text-muted-foreground/70">暂无近期操作 — 点按钮后这里会显示说明。</p>
      ) : (
        <ul className="max-h-36 space-y-2 overflow-y-auto">
          {[...entries].reverse().map((e) => (
            <li key={e.id} className="border-l-2 border-[hsl(var(--primary))]/40 pl-2">
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-muted-foreground">{e.time}</span>
                {e.audible && <Volume2 className="h-3 w-3 text-amber-400" aria-label="可能有电机声" />}
                <span className="font-medium">{e.label}</span>
              </div>
              <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">{e.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function makeActivityEntry(
  key: keyof typeof B601_ACTION_GUIDE,
  extra?: string,
): B601ActivityEntry {
  const g = B601_ACTION_GUIDE[key]
  const now = new Date()
  const time = now.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  return {
    id: `${key}-${now.getTime()}`,
    time,
    label: g.label,
    detail: extra ? `${g.detail} ${extra}` : g.detail,
    audible: g.audible,
  }
}

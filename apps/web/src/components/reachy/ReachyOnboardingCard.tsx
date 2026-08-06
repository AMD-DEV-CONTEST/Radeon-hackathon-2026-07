/**
 * Reachy Mini 入门卡 — 未连接时顶栏显眼展示。
 * 内容整理自 Seeed Wiki，只留用户立刻用得上的几条。
 */
import { useState } from 'react'
import { ExternalLink, Power, Usb, X, Zap } from 'lucide-react'
import { Button } from '../ui/button'

const DISMISS_KEY = 'botversex_reachy_onboarding_dismissed_v1'

interface Props {
  daemonOnline: boolean
  virtualActive: boolean
  onStartDaemon: () => void
  onStartVirtual: () => void
  daemonBusy?: boolean
  virtualBusy?: boolean
}

export function ReachyOnboardingCard({
  daemonOnline,
  virtualActive,
  onStartDaemon,
  onStartVirtual,
  daemonBusy,
  virtualBusy,
}: Props) {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === '1'
    } catch {
      return false
    }
  })

  if (daemonOnline || virtualActive || dismissed) return null

  const dismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, '1')
    } catch {
      /* ignore */
    }
    setDismissed(true)
  }

  return (
    <div className="relative rounded-xl border border-violet-500/30 bg-violet-500/5 px-4 py-3">
      <button
        type="button"
        onClick={dismiss}
        className="absolute right-2 top-2 rounded p-1 text-muted-foreground hover:bg-white/5 hover:text-foreground"
        aria-label="关闭入门提示"
      >
        <X className="h-4 w-4" />
      </button>

      <div className="pr-8 space-y-3">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Reachy Mini 怎么用（Lite）</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            整理自 Seeed 官方入门 · 你们这台是外接电脑 + USB 版
          </p>
        </div>

        <ol className="space-y-2 text-sm">
          <li className="flex gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-500/20 text-[11px] font-medium text-violet-200">
              1
            </span>
            <span>
              <Zap className="mr-1 inline h-3.5 w-3.5 text-amber-300" />
              <strong className="text-foreground">打开本体电源</strong>
              <span className="text-muted-foreground"> — 只插 USB 不够，不开电会报找不到电机</span>
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-500/20 text-[11px] font-medium text-violet-200">
              2
            </span>
            <span>
              <Usb className="mr-1 inline h-3.5 w-3.5 text-sky-300" />
              <strong className="text-foreground">USB 插进电脑</strong>
              <span className="text-muted-foreground"> — Lite 没有 WiFi，必须有线</span>
            </span>
          </li>
          <li className="flex gap-2">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-violet-500/20 text-[11px] font-medium text-violet-200">
              3
            </span>
            <span>
              <Power className="mr-1 inline h-3.5 w-3.5 text-emerald-300" />
              <strong className="text-foreground">点右上角「启动机器人」</strong>
              <span className="text-muted-foreground"> — 然后就能播动作 / 对话</span>
            </span>
          </li>
        </ol>

        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={onStartDaemon} disabled={daemonBusy}>
            <Power className="h-3.5 w-3.5" />
            {daemonBusy ? '启动中…' : '启动机器人'}
          </Button>
          <Button size="sm" variant="outline" onClick={onStartVirtual} disabled={virtualBusy}>
            没机器？先虚拟模式
          </Button>
          <a
            href="https://wiki.seeedstudio.com/cn/reachymini_getting_started/"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-violet-300 hover:underline"
          >
            Seeed 完整 Wiki
            <ExternalLink className="h-3 w-3" />
          </a>
        </div>

        <p className="text-[11px] text-muted-foreground leading-relaxed">
          它有：6 轴头 + 身体转 + 两根天线 · 4 麦克风 · 5W 喇叭 · 广角摄像头。
          完整版才有树莓派 / WiFi / 电池——你这台 Lite 不用管那些。
        </p>
      </div>
    </div>
  )
}

import { useCallback, useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '../ui/button'
import {
  b601Ros2GripperClose,
  b601Ros2GripperOpen,
  b601Ros2Launch,
  b601Ros2Status,
  b601Ros2Stop,
  getB601Ros2Health,
  type Ros2Health,
} from '../../lib/b601Ros2Api'

interface Props {
  busy: boolean
  teleopRunning: boolean
  onBusy: (v: boolean) => void
  onBringupChange?: (running: boolean) => void
}

/** 仅在本机已装 ROS2 时显示 — 避免未安装用户看到一堆英文。 */
export function B601Ros2Panel({ busy, teleopRunning, onBusy, onBringupChange }: Props) {
  const [health, setHealth] = useState<Ros2Health | null>(null)
  const [bringup, setBringup] = useState(false)
  const [useRviz, setUseRviz] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const h = await getB601Ros2Health()
      setHealth(h)
      const running = Boolean(h.bringup_running)
      setBringup(running)
      onBringupChange?.(running)
    } catch {
      setHealth(null)
    }
  }, [onBringupChange])

  useEffect(() => {
    void refresh()
    const t = setInterval(() => void refresh(), 5000)
    return () => clearInterval(t)
  }, [refresh])

  if (!health?.ready) {
    return null
  }

  const launch = async () => {
    onBusy(true)
    setMsg(null)
    try {
      await b601Ros2Launch({ use_rviz: useRviz })
      setBringup(true)
      onBringupChange?.(true)
      setMsg('ROS2 控制栈已启动')
      await refresh()
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '启动失败')
    } finally {
      onBusy(false)
    }
  }

  const stop = async () => {
    onBusy(true)
    try {
      await b601Ros2Stop()
      setBringup(false)
      onBringupChange?.(false)
      setMsg('已停止 ROS2 控制栈')
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '停止失败')
    } finally {
      onBusy(false)
    }
  }

  return (
    <div className="space-y-3 text-xs border-t border-white/10 pt-3">
      <div>
        <h3 className="text-sm font-medium text-foreground">ROS2 扩展（可选）</h3>
        <p className="mt-1 text-muted-foreground leading-relaxed">
          给熟悉 ROS2 / MoveIt 的用户。大多数人用「自动到位」页的 SDK 即可。
        </p>
      </div>

      {teleopRunning && <p className="text-amber-200">请先停止遥操。</p>}

      <label className="flex items-center gap-2 text-muted-foreground">
        <input type="checkbox" checked={useRviz} onChange={(e) => setUseRviz(e.target.checked)} />
        同时打开 RViz 可视化
      </label>

      <div className="flex gap-2">
        {!bringup ? (
          <Button size="sm" className="flex-1" disabled={busy || teleopRunning} onClick={() => void launch()}>
            {busy ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
            启动 ROS2
          </Button>
        ) : (
          <Button size="sm" variant="destructive" className="flex-1" disabled={busy} onClick={() => void stop()}>
            停止 ROS2
          </Button>
        )}
      </div>

      {bringup && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => void b601Ros2GripperOpen()}>
            夹爪张开
          </Button>
          <Button size="sm" variant="outline" onClick={() => void b601Ros2GripperClose()}>
            夹爪闭合
          </Button>
        </div>
      )}

      {msg && <p className="text-muted-foreground">{msg}</p>}
    </div>
  )
}

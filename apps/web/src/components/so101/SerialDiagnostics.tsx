/**
 * SO-101 串口诊断（U4）：端口枚举 → 波特率探测 → ID 扫描 → 日志导出。
 *
 * 背景（docs/strategy/2026-08-06-first-move-experience.md · U4）：
 * 「插上 USB 扫不到舵机」是最高频真实故障（供电不足/驱动/USB 芯片/ID 冲突），
 * WebSerial 里无法远程诊断——这个面板把诊断搬到浏览器内，日志可导出给支持团队。
 *
 * 用法：可独立使用；若主连接占用端口，先调 onRelease() 释放再诊断。
 */
import { useCallback, useRef, useState } from 'react'
import { Bug, Download, Loader2, Usb } from 'lucide-react'
import { Button } from '../ui/button'
import {
  FeetechProtocol,
  FeetechSerialPort,
  isWebSerialSupported,
  txRxResultText,
} from '../../lib/webserial'

interface SerialDiagnosticsProps {
  /** 释放主连接（若占用同一端口）；无占用时可为空 */
  onRelease?: () => Promise<void>
}

const PROBE_BAUDS = [1_000_000, 115_200, 9_600]
const PROBE_IDS = [1, 2, 3, 4, 5, 6, 7]

export function SerialDiagnostics({ onRelease }: SerialDiagnosticsProps) {
  const [running, setRunning] = useState(false)
  const [lines, setLines] = useState<string[]>([])
  const linesRef = useRef<string[]>([])

  const log = useCallback((line: string) => {
    linesRef.current.push(line)
    setLines([...linesRef.current])
  }, [])

  const run = useCallback(async () => {
    if (running) return
    setRunning(true)
    linesRef.current = []
    setLines([])
    try {
      log(`— BotverseX 串口诊断 ${new Date().toISOString()} —`)
      log(`UA: ${navigator.userAgent}`)
      log(`WebSerial: ${isWebSerialSupported() ? '支持' : '不支持（需 Chrome/Edge）'}`)

      // 1. 端口枚举（已授权列表）
      const granted = await navigator.serial!.getPorts()
      log(`已授权端口: ${granted.length} 个`)
      for (const p of granted) {
        const info = p.getInfo()
        log(
          `  - vendor=${info.usbVendorId != null ? '0x' + info.usbVendorId.toString(16) : '?'}` +
            ` product=${info.usbProductId != null ? '0x' + info.usbProductId.toString(16) : '?'}`,
        )
      }

      // 2. 释放主连接，避免端口占用
      if (onRelease) await onRelease()

      // 3. 授权一个端口（用户手势），然后多波特率探测
      log('弹出设备选择框，请选择机械臂串口…')
      const nativePort = await navigator.serial!.requestPort().catch(() => null)
      if (!nativePort) {
        log('已取消选择。')
        return
      }
      const info = nativePort.getInfo()
      log(
        `选中端口: vendor=${info.usbVendorId != null ? '0x' + info.usbVendorId.toString(16) : '?'}` +
          ` product=${info.usbProductId != null ? '0x' + info.usbProductId.toString(16) : '?'}`,
      )

      const protocol = new FeetechProtocol()
      for (const baud of PROBE_BAUDS) {
        const port = new FeetechSerialPort(baud)
        port.attachGrantedPort(nativePort)
        const opened = await port.open()
        if (!opened) {
          log(`波特率 ${baud}: 打开失败（可能被占用）`)
          continue
        }
        const found: number[] = []
        for (const id of PROBE_IDS) {
          const r = await protocol.ping(port, id)
          if (r.error === 0) {
            found.push(id)
            log(`波特率 ${baud} · ID ${id}: 在线（型号 ${r.model}）`)
          }
        }
        if (found.length === 0) {
          log(`波特率 ${baud}: 无舵机响应（${txRxResultText(-6)}）`)
        } else {
          log(`波特率 ${baud}: 扫到 ${found.length} 个舵机 ${found.join(',')}`)
        }
        await port.close()
      }

      // 4. 结论
      log('— 诊断完成。导出发给支持团队，或按提示排查供电/USB/占用 —')
    } catch (e) {
      log(`诊断异常: ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setRunning(false)
    }
  }, [onRelease, running, log])

  const exportLog = useCallback(() => {
    const blob = new Blob([linesRef.current.join('\n')], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `botversex-serial-diag-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }, [])

  return (
    <div className="rounded-xl border border-white/10 bg-black/20 p-4 text-xs leading-relaxed">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={() => void run()} disabled={running} variant="outline" size="sm">
          {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Bug className="h-3.5 w-3.5" />}
          {running ? '诊断中…' : '一键诊断'}
        </Button>
        <Button onClick={exportLog} disabled={lines.length === 0} variant="ghost" size="sm">
          <Download className="h-3.5 w-3.5" />
          导出日志
        </Button>
        <span className="flex items-center gap-1 text-[11px] text-stone-500">
          <Usb className="h-3 w-3" />
          会依次探测 1M / 115200 / 9600 波特率，约 20 秒
        </span>
      </div>
      {lines.length > 0 && (
        <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-white/5 bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-stone-300">
          {lines.join('\n')}
        </pre>
      )}
    </div>
  )
}

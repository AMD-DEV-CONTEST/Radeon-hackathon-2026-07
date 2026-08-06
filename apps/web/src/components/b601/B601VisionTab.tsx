import { useCallback, useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, Loader2, RefreshCw, Save } from 'lucide-react'
import { Button } from '../ui/button'
import {
  getB601Cameras,
  loadB601CameraPrefs,
  saveB601CameraPrefs,
  type B601CameraDevice,
  type B601CameraPrefs,
} from '../../lib/b601Api'

interface Props {
  active?: boolean
  onPreviewChange?: (url: string | null) => void
  onPrefsChange?: (prefs: B601CameraPrefs) => void
}

function streamUrl(device: number, key: number) {
  return `/api/camera/mjpeg?device=${device}&w=640&h=480&fps=15&quality=75&_=${key}`
}

export function B601VisionTab({ active = true, onPreviewChange, onPrefsChange }: Props) {
  const initial = loadB601CameraPrefs()
  const [devices, setDevices] = useState<B601CameraDevice[]>([])
  const [front, setFront] = useState(initial.front)
  const [side, setSide] = useState(initial.side)
  const [top, setTop] = useState<number | null>(initial.top)
  const [previewOn, setPreviewOn] = useState(false)
  const [previewTarget, setPreviewTarget] = useState<'front' | 'side' | 'top'>('front')
  const [previewError, setPreviewError] = useState(false)
  const [streamKey, setStreamKey] = useState(0)
  const [probing, setProbing] = useState(false)
  const [savedHint, setSavedHint] = useState<string | null>(null)

  const previewDevice = previewTarget === 'front' ? front : previewTarget === 'side' ? side : top
  const url = useMemo(
    () => (previewOn && previewDevice != null ? streamUrl(previewDevice, streamKey) : null),
    [previewDevice, previewOn, streamKey],
  )

  const refreshDevices = useCallback(async () => {
    setProbing(true)
    try {
      const list = await getB601Cameras()
      setDevices(list)
      const readable = list.filter((d) => d.readable).map((d) => d.index)
      if (readable.length > 0) {
        const nextFront = readable.includes(front) ? front : readable[0]
        const nextSide =
          readable.find((i) => i !== nextFront) ??
          (readable.includes(side) ? side : readable[Math.min(1, readable.length - 1)])
        const nextTop =
          top != null && readable.includes(top)
            ? top
            : readable.find((i) => i !== nextFront && i !== nextSide) ?? null
        setFront(nextFront)
        setSide(nextSide)
        setTop(nextTop)
      }
      setPreviewError(false)
      setStreamKey((k) => k + 1)
    } catch {
      setDevices([])
    } finally {
      setProbing(false)
    }
  }, [front, side, top])

  useEffect(() => {
    void refreshDevices()
    // only on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!active || !previewOn) {
      onPreviewChange?.(null)
      return undefined
    }
    setPreviewError(false)
    return undefined
  }, [active, previewOn, previewDevice, onPreviewChange])

  useEffect(() => {
    if (!active) {
      setPreviewOn(false)
      onPreviewChange?.(null)
    }
  }, [active, onPreviewChange])

  const save = () => {
    const prefs = saveB601CameraPrefs(front, side, top)
    onPrefsChange?.(prefs)
    setSavedHint(
      `已保存：正面 Cam ${prefs.front} · 侧面 Cam ${prefs.side}` +
        (prefs.top == null ? '' : ` · 顶部 Cam ${prefs.top}`),
    )
    window.setTimeout(() => setSavedHint(null), 2500)
  }

  const options = devices.length
    ? devices
    : [
        { index: 0, path: '/dev/video0', readable: true },
        { index: 2, path: '/dev/video2', readable: false },
        { index: 4, path: '/dev/video4', readable: true },
        { index: 6, path: '/dev/video6', readable: true },
      ]

  const selected = [front, side, ...(top == null ? [] : [top])]
  const busByIndex = new Map(
    devices.filter((d) => d.usb_bus).map((d) => [d.index, d.usb_bus as string]),
  )
  const busGroups = new Map<string, number[]>()
  for (const idx of selected) {
    const bus = busByIndex.get(idx)
    if (!bus) continue
    const list = busGroups.get(bus) ?? []
    list.push(idx)
    busGroups.set(bus, list)
  }
  const busConflict = [...busGroups.entries()].filter(([, ids]) => ids.length > 1)

  const busLabel = (d: B601CameraDevice) => {
    if (!d.usb_bus) return ''
    const short = d.usb_bus.replace(/^pci-0000:/, '')
    return ` · USB ${short}`
  }

  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-muted-foreground">
        选好<strong className="font-normal text-foreground/80">正面 + 侧面</strong>
        （可选顶部），保存后「数据」采集和「部署」推理都会用这两路。预览确认画面无误再继续。
      </p>

      {busConflict.length > 0 && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-100">
          USB 冲突：
          {busConflict.map(([bus, ids]) => (
            <span key={bus}>
              Cam {ids.join(' + ')} 在同一总线（{bus.replace(/^pci-0000:/, '')}）
            </span>
          ))}
          。请把其中一路换到主板另一组 USB 口；或先保存可用组合 Cam 8+4 / Cam 6+4。
        </div>
      )}

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <label className="space-y-1 text-xs">
          <span className="font-medium">正面 front</span>
          <select
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-sm"
            value={front}
            onChange={(e) => setFront(Number(e.target.value))}
          >
            {options.map((d) => (
              <option key={`f-${d.index}`} value={d.index} disabled={!d.readable}>
                Cam {d.index}{d.name ? ` · ${d.name}` : ''}{busLabel(d)}
                {d.busy ? ' · 被占用' : d.readable ? '' : ' · 不可读'}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs">
          <span className="font-medium">侧面 side</span>
          <select
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-sm"
            value={side}
            onChange={(e) => setSide(Number(e.target.value))}
          >
            {options.map((d) => (
              <option key={`s-${d.index}`} value={d.index} disabled={!d.readable}>
                Cam {d.index}{d.name ? ` · ${d.name}` : ''}{busLabel(d)}
                {d.busy ? ' · 被占用' : d.readable ? '' : ' · 不可读'}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1 text-xs">
          <span className="font-medium">顶部 top（可选第三路）</span>
          <select
            className="w-full rounded-md border border-white/10 bg-black/30 px-2 py-1.5 text-sm"
            value={top ?? ''}
            onChange={(e) => setTop(e.target.value === '' ? null : Number(e.target.value))}
          >
            <option value="">不使用第三路</option>
            {options.map((d) => (
              <option key={`t-${d.index}`} value={d.index} disabled={!d.readable}>
                Cam {d.index}{d.name ? ` · ${d.name}` : ''}{busLabel(d)}
                {d.busy ? ' · 被占用' : d.readable ? '' : ' · 不可读'}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button size="sm" onClick={save}>
          <Save className="mr-1 h-3.5 w-3.5" />
          保存相机配置
        </Button>
        <Button
          size="sm"
          variant={previewOn ? 'secondary' : 'outline'}
          onClick={() => setPreviewOn((v) => !v)}
        >
          {previewOn ? <EyeOff className="mr-1 h-3.5 w-3.5" /> : <Eye className="mr-1 h-3.5 w-3.5" />}
          {previewOn ? '关闭预览' : '打开预览'}
        </Button>
        <Button size="sm" variant="ghost" disabled={probing} onClick={() => void refreshDevices()}>
          {probing ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <RefreshCw className="mr-1 h-3 w-3" />}
          重新检测
        </Button>
      </div>

      {savedHint && <p className="text-[11px] text-emerald-300">{savedHint}</p>}

      {previewOn && (
        <div className="flex gap-1">
          {(['front', 'side', ...(top == null ? [] : ['top'])] as const).map((t) => (
            <button
              key={t}
              type="button"
              className={`rounded px-2 py-1 text-[11px] ${
                previewTarget === t ? 'bg-sky-500/30 text-sky-100' : 'bg-white/5 text-muted-foreground'
              }`}
              onClick={() => {
                setPreviewTarget(t)
                setStreamKey((k) => k + 1)
              }}
            >
              {t === 'front'
                ? `正面 Cam ${front}`
                : t === 'side'
                  ? `侧面 Cam ${side}`
                  : `顶部 Cam ${top}`}
            </button>
          ))}
        </div>
      )}

      <div className="relative aspect-video overflow-hidden rounded-lg border border-white/10 bg-black/40">
        {previewOn && url && !previewError ? (
          <img
            src={url}
            alt="相机预览"
            className="h-full w-full object-cover"
            onLoad={() => {
              setPreviewError(false)
              // Keep a single V4L2 reader. Rendering the same URL again in the
              // 3D stage would open a second capture and make USB cameras busy.
              onPreviewChange?.(null)
            }}
            onError={() => {
              setPreviewError(true)
              onPreviewChange?.(null)
            }}
          />
        ) : (
          <p className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
            {previewOn && previewError
              ? `Cam ${previewDevice ?? '-'} 不可用 — 若标记“被占用”，请先关闭 Discord/相机软件`
              : '打开预览确认画面后点「保存相机配置」'}
          </p>
        )}
      </div>

      <p className="text-[10px] leading-relaxed text-muted-foreground">
        本机实测：Cam 6 与 Cam 8 在同一 USB 控制器，不能同时录；Cam 4 在另一路。想录三路请把 6 或 8
        换到另一组 USB 口。保存后写入 observation.images.front/side/top。
      </p>
    </div>
  )
}

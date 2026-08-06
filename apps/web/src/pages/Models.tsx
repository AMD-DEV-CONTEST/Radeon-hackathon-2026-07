import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Brain, GitCompareArrows, RefreshCw } from 'lucide-react'
import { Button } from '../components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Badge } from '../components/ui/badge'

interface LocalModel {
  model_key: string
  algo: string
  dataset_id: string | null
  path: string
  metrics?: Record<string, unknown>
  hparams?: Record<string, unknown>
}

interface ListResp {
  total: number
  items: LocalModel[]
  storage_root?: string
}

function fmtBytes(n?: number | null): string {
  if (n == null || !Number.isFinite(n)) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function Models() {
  const [items, setItems] = useState<LocalModel[]>([])
  const [storageRoot, setStorageRoot] = useState<string>('')
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setErr(null)
    try {
      const r = await fetch('/api/inference/models')
      if (!r.ok) throw new Error(`${r.status}`)
      const data = (await r.json()) as ListResp
      setItems(data.items)
      setStorageRoot(data.storage_root ?? '')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Models</h1>
          <p className="text-muted-foreground mt-1">本地已训练 checkpoint. 与原始 dataset 对比可进入 Compare 页.</p>
          {storageRoot && (
            <p className="text-[11px] text-muted-foreground font-mono mt-1">{storageRoot}</p>
          )}
        </div>
        <Button onClick={load} variant="outline" disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {err && (
        <div className="px-4 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-red-300 text-sm">{err}</div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total</p>
                <p className="text-3xl font-bold">{items.length}</p>
              </div>
              <div className="h-10 w-10 rounded-xl bg-primary/10 flex items-center justify-center">
                <Brain className="h-5 w-5 text-primary" />
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div>
              <p className="text-sm text-muted-foreground">最新算法</p>
              <p className="text-lg font-mono">{items[0]?.algo ?? '—'}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-6">
            <div>
              <p className="text-sm text-muted-foreground">最近训练集</p>
              <p className="text-lg font-mono truncate">{items[0]?.dataset_id ?? '—'}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-base">Checkpoints</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {items.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">
              还没有本地模型. 去 <Link className="underline text-primary" to="/training">Training</Link> 发起一次训练.
            </div>
          ) : (
            <div className="divide-y">
              {items.map((m) => {
                const metrics = (m.metrics ?? {}) as Record<string, number | undefined>
                const rmse = typeof metrics.final_val_rmse_delta === 'number' ? metrics.final_val_rmse_delta : undefined
                const samples = typeof metrics.samples === 'number' ? metrics.samples : undefined
                const ckptSize = (m as unknown as { size_bytes?: number }).size_bytes
                return (
                  <div key={m.model_key} className="px-4 py-3 flex items-center gap-3 hover:bg-muted/30">
                    <Brain className="h-5 w-5 text-primary" />
                    <div className="flex-1 min-w-0">
                      <div className="font-mono text-sm truncate">{m.model_key}</div>
                      <div className="flex gap-3 text-xs text-muted-foreground font-mono">
                        <span>algo: {m.algo}</span>
                        {m.dataset_id && <span>dataset: {m.dataset_id}</span>}
                        {rmse != null && <span>rmse: {rmse.toExponential(3)}</span>}
                        {samples != null && <span>samples: {samples}</span>}
                        {ckptSize != null && <span>size: {fmtBytes(ckptSize)}</span>}
                      </div>
                    </div>
                    <Badge variant="outline" className="text-[10px]">{m.algo}</Badge>
                    {m.dataset_id && (
                      <Link to={`/datasets/${encodeURIComponent(m.dataset_id)}/compare/${encodeURIComponent(m.model_key)}`}>
                        <Button size="sm" variant="outline">
                          <GitCompareArrows className="h-4 w-4 mr-1" />
                          Compare
                        </Button>
                      </Link>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

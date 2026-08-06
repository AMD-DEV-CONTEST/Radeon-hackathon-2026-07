/**
 * Module-level random motion loop — survives tab / route changes until explicit stop().
 *
 * Pool = official HF emotions + dances libraries (same as 官方动作库 panel).
 */
import {
  listKnownReachyRecordedDatasets,
  listReachyRecordedMoves,
} from './reachyApi'
import { reachyMotionPlaybackStore } from './reachyMotionPlaybackStore'

const EMOTIONS_DS = 'pollen-robotics/reachy-mini-emotions-library'
const DANCES_DS = 'pollen-robotics/reachy-mini-dances-library'
const RANDOM_INTERVAL_MS = 10_000
const BUSY_RETRY_MS = 1_000

export interface RandomPoolItem {
  dataset: string
  move: string
  kind: string
}

export interface RandomMotionSnapshot {
  active: boolean
  loading: boolean
  error: string | null
  poolSize: number
  currentMove: string | null
}

function pickRandom(pool: RandomPoolItem[], avoidMove?: string | null): RandomPoolItem {
  if (pool.length <= 1) return pool[0]
  for (let i = 0; i < 3; i += 1) {
    const item = pool[Math.floor(Math.random() * pool.length)]
    if (!avoidMove || item.move !== avoidMove) return item
  }
  return pool[Math.floor(Math.random() * pool.length)]
}

class ReachyRandomMotionStore {
  private active = false
  private loading = false
  private error: string | null = null
  private poolSize = 0
  private pool: RandomPoolItem[] = []
  private lastMove: string | null = null
  private playbackMove: string | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private readonly listeners = new Set<() => void>()
  private snapshot: RandomMotionSnapshot = {
    active: false,
    loading: false,
    error: null,
    poolSize: 0,
    currentMove: null,
  }

  constructor() {
    reachyMotionPlaybackStore.registerOnPlaybackEnded(() => {
      if (!this.active) return
      this.scheduleNext(RANDOM_INTERVAL_MS)
    })
    reachyMotionPlaybackStore.subscribe(() => {
      if (!this.active) return
      const move = reachyMotionPlaybackStore.getSnapshot().currentMove
      if (move === this.playbackMove) return
      this.playbackMove = move
      this.emit()
    })
  }

  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb)
    return () => this.listeners.delete(cb)
  }

  private refreshSnapshot(): void {
    const currentMove = this.active ? (this.playbackMove ?? this.lastMove) : null
    const s = this.snapshot
    if (
      s.active === this.active &&
      s.loading === this.loading &&
      s.error === this.error &&
      s.poolSize === this.poolSize &&
      s.currentMove === currentMove
    ) {
      return
    }
    this.snapshot = {
      active: this.active,
      loading: this.loading,
      error: this.error,
      poolSize: this.poolSize,
      currentMove,
    }
  }

  getSnapshot = (): RandomMotionSnapshot => {
    this.refreshSnapshot()
    return this.snapshot
  }

  getActive = (): boolean => this.active

  private emit() {
    this.refreshSnapshot()
    for (const cb of this.listeners) cb()
  }

  private clearTimer() {
    if (this.timer !== null) {
      window.clearTimeout(this.timer)
      this.timer = null
    }
  }

  private scheduleNext(delayMs: number) {
    this.clearTimer()
    this.timer = window.setTimeout(() => {
      void this.tick()
    }, delayMs)
  }

  private async tick() {
    if (!this.active) return
    if (reachyMotionPlaybackStore.isBusy()) {
      this.scheduleNext(BUSY_RETRY_MS)
      return
    }
    if (!this.pool.length) {
      this.error = '官方库暂无动作'
      this.active = false
      this.emit()
      return
    }
    const item = pickRandom(this.pool, this.lastMove)
    this.lastMove = item.move
    this.playbackMove = item.move
    this.error = null
    this.emit()
    try {
      await reachyMotionPlaybackStore.playRecordedMove({
        dataset: item.dataset,
        move: item.move,
        source: 'random',
      })
    } catch (e) {
      this.error = (e as Error).message
      this.emit()
      if (this.active) this.scheduleNext(RANDOM_INTERVAL_MS)
    }
  }

  private async loadPool(): Promise<RandomPoolItem[]> {
    const known = await listKnownReachyRecordedDatasets()
    const datasets = known.datasets ?? []
    const emotionsDs =
      datasets.find((d) => d.dataset === EMOTIONS_DS || d.kind === 'emotions')?.dataset ??
      EMOTIONS_DS
    const dancesDs =
      datasets.find((d) => d.dataset === DANCES_DS || d.kind === 'dances')?.dataset ?? DANCES_DS

    const [emotions, dances] = await Promise.all([
      listReachyRecordedMoves(emotionsDs).catch(() => [] as string[]),
      listReachyRecordedMoves(dancesDs).catch(() => [] as string[]),
    ])

    return [
      ...emotions.map((move) => ({ dataset: emotionsDs, move, kind: 'emotions' })),
      ...dances.map((move) => ({ dataset: dancesDs, move, kind: 'dances' })),
    ]
  }

  stop = () => {
    this.active = false
    this.playbackMove = null
    this.clearTimer()
    this.error = null
    this.emit()
  }

  start = async (daemonOnline: boolean) => {
    if (!daemonOnline) {
      this.error = '请先启动机器人（或确认守护进程已在运行）'
      this.emit()
      return
    }
    this.loading = true
    this.error = null
    this.emit()
    try {
      const pool = await this.loadPool()
      if (!pool.length) {
        this.error = '官方库暂无动作（请确认 HF 缓存已就绪）'
        return
      }
      this.pool = pool
      this.poolSize = pool.length
      this.lastMove = null
      this.playbackMove = null
      this.active = true
      await this.tick()
    } catch (e) {
      this.error = (e as Error).message
      this.active = false
    } finally {
      this.loading = false
      this.emit()
    }
  }
}

export const reachyRandomMotionStore = new ReachyRandomMotionStore()

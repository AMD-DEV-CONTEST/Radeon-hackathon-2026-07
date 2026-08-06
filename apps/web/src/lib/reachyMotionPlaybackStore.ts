/**
 * Module-level playback coordinator for Reachy Mini motion tab.
 * Survives React unmount (tab switch / route leave) so random loop keeps running.
 */
import {
  getReachyMoveJson,
  playLocalMove,
  playReachyRecordedMove,
} from './reachyApi'

export type PlaybackSource = 'random' | 'manual-official' | 'manual-custom'

export interface PlaybackEndedEvent {
  source: PlaybackSource
  move: string
}

interface PlayRecordedOpts {
  dataset: string
  move: string
  source: PlaybackSource
  estimatedDurationSec?: number
}

interface PlayLocalOpts {
  moveName: string
  source: 'manual-custom' | 'random'
  /** JSON category for duration lookup: custom | dances | emotions */
  category?: string
  estimatedDurationSec?: number
}

export interface PlaybackSnapshot {
  busy: boolean
  currentMove: string | null
  currentSource: PlaybackSource | null
}

const DEFAULT_HF_DURATION_S = 4

class ReachyMotionPlaybackStore {
  private busy = false
  private currentMove: string | null = null
  private currentSource: PlaybackSource | null = null
  private releaseTimer: ReturnType<typeof setTimeout> | null = null
  private playbackGen = 0
  private readonly endedListeners = new Set<(event: PlaybackEndedEvent) => void>()
  private readonly listeners = new Set<() => void>()
  private snapshot: PlaybackSnapshot = {
    busy: false,
    currentMove: null,
    currentSource: null,
  }

  subscribe = (cb: () => void): (() => void) => {
    this.listeners.add(cb)
    return () => this.listeners.delete(cb)
  }

  private refreshSnapshot(): void {
    const s = this.snapshot
    if (
      s.busy === this.busy &&
      s.currentMove === this.currentMove &&
      s.currentSource === this.currentSource
    ) {
      return
    }
    this.snapshot = {
      busy: this.busy,
      currentMove: this.currentMove,
      currentSource: this.currentSource,
    }
  }

  getSnapshot = (): PlaybackSnapshot => {
    this.refreshSnapshot()
    return this.snapshot
  }

  isBusy = (): boolean => this.busy

  registerOnPlaybackEnded = (cb: (event: PlaybackEndedEvent) => void): (() => void) => {
    this.endedListeners.add(cb)
    return () => this.endedListeners.delete(cb)
  }

  private emit() {
    this.refreshSnapshot()
    for (const cb of this.listeners) cb()
  }

  private clearReleaseTimer() {
    if (this.releaseTimer !== null) {
      window.clearTimeout(this.releaseTimer)
      this.releaseTimer = null
    }
  }

  private releaseOccupancy(gen: number, source: PlaybackSource, move: string) {
    if (gen !== this.playbackGen) return
    this.clearReleaseTimer()
    this.busy = false
    this.currentMove = null
    this.currentSource = null
    this.emit()
    for (const cb of this.endedListeners) {
      try {
        cb({ source, move })
      } catch {
        /* listener error */
      }
    }
  }

  private occupy(source: PlaybackSource, move: string, estimatedDurationSec: number): number {
    this.playbackGen += 1
    const gen = this.playbackGen
    this.clearReleaseTimer()
    this.busy = true
    this.currentMove = move
    this.currentSource = source
    this.emit()
    this.releaseTimer = window.setTimeout(() => {
      this.releaseOccupancy(gen, source, move)
    }, Math.max(0.5, estimatedDurationSec) * 1000)
    return gen
  }

  playRecordedMove = async (opts: PlayRecordedOpts): Promise<void> => {
    const duration = opts.estimatedDurationSec ?? DEFAULT_HF_DURATION_S
    const gen = this.occupy(opts.source, opts.move, duration)
    try {
      await playReachyRecordedMove(opts.dataset, opts.move)
    } catch (err) {
      this.releaseOccupancy(gen, opts.source, opts.move)
      throw err
    }
  }

  playLocalMove = async (opts: PlayLocalOpts): Promise<void> => {
    let duration = opts.estimatedDurationSec ?? DEFAULT_HF_DURATION_S
    if (!opts.estimatedDurationSec) {
      const categories = opts.category
        ? [opts.category]
        : ['custom', 'dances', 'emotions']
      for (const category of categories) {
        try {
          const moveJson = await getReachyMoveJson(category, opts.moveName)
          const times = moveJson.time ?? []
          if (times.length) {
            duration = Math.max(times[times.length - 1], 0.1)
            break
          }
        } catch {
          /* try next category */
        }
      }
    }
    const gen = this.occupy(opts.source, opts.moveName, duration)
    try {
      await playLocalMove(opts.moveName)
    } catch (err) {
      this.releaseOccupancy(gen, opts.source, opts.moveName)
      throw err
    }
  }
}

export const reachyMotionPlaybackStore = new ReachyMotionPlaybackStore()

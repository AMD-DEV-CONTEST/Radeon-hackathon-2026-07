/**
 * M9.2 — SetupProvider
 *
 * Small reducer + localStorage-persisted context that drives the SO-101
 * onboarding wizard.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from 'react'
import {
  SO101_STEPS,
  stepsForRuntime,
  type CameraChoice,
  type PortChoice,
  type SetupState,
  type SetupStepId,
  type SetupStepMeta,
  canJumpTo as _canJumpTo,
  firstIncomplete,
  makeInitialSetupState,
  storageKey,
} from '../../lib/setup-types'

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

type Action =
  | { type: 'GO_TO'; step: SetupStepId }
  | { type: 'MARK_COMPLETE'; step: SetupStepId; complete: boolean }
  | { type: 'SET_CAMERA'; camera: CameraChoice | null }
  | { type: 'SET_FOLLOWER_PORT'; port: PortChoice | null }
  | { type: 'SET_LEADER_PORT'; port: PortChoice | null }
  | { type: 'SET_LAST_DATASET'; datasetId: string | null }
  | { type: 'SET_LAST_MODEL'; modelKey: string | null }
  | { type: 'RESET' }
  | { type: 'HYDRATE'; state: SetupState }

function connectComplete(state: Pick<SetupState, 'camera' | 'followerPort' | 'leaderPort'>): boolean {
  return state.camera !== null && state.followerPort !== null && state.leaderPort !== null
}

function normalizeHydratedState(runtimeId: string, raw: Partial<SetupState>): SetupState {
  const steps = stepsForRuntime(runtimeId)
  const fresh = makeInitialSetupState(runtimeId)
  const rawStep = raw.currentStep
  let currentStep: SetupStepId = firstIncomplete(fresh)
  if (rawStep === 'camera' || rawStep === 'arm') {
    currentStep = 'connect'
  } else if (rawStep === 'train' || rawStep === 'inference') {
    currentStep = 'run'
  } else if (rawStep && steps.some((s) => s.id === rawStep)) {
    currentStep = rawStep
  }

  const completed = {
    ...fresh.completed,
    ...(raw.completed ?? {}),
  }

  const hydrated: SetupState = {
    ...fresh,
    ...raw,
    runtimeId,
    currentStep,
    completed,
  }

  const isConnected = connectComplete(hydrated)
  hydrated.completed = {
    ...completed,
    camera: hydrated.camera !== null,
    arm: hydrated.followerPort !== null && hydrated.leaderPort !== null,
    connect: isConnected,
    run: completed.run || completed.inference,
  }

  return hydrated
}

function reducer(state: SetupState, action: Action): SetupState {
  switch (action.type) {
    case 'GO_TO':
      return { ...state, currentStep: action.step }
    case 'MARK_COMPLETE':
      return {
        ...state,
        completed: {
          ...state.completed,
          [action.step]: action.complete,
          ...(action.step === 'run' ? { inference: action.complete } : {}),
        },
      }
    case 'SET_CAMERA': {
      const next = { ...state, camera: action.camera }
      return {
        ...next,
        completed: {
          ...state.completed,
          camera: action.camera !== null,
          connect: connectComplete(next),
        },
      }
    }
    case 'SET_FOLLOWER_PORT': {
      const next = { ...state, followerPort: action.port }
      return {
        ...next,
        completed: {
          ...state.completed,
          arm: next.followerPort !== null && next.leaderPort !== null,
          connect: connectComplete(next),
        },
      }
    }
    case 'SET_LEADER_PORT': {
      const next = { ...state, leaderPort: action.port }
      return {
        ...next,
        completed: {
          ...state.completed,
          arm: next.followerPort !== null && next.leaderPort !== null,
          connect: connectComplete(next),
        },
      }
    }
    case 'SET_LAST_DATASET':
      return {
        ...state,
        lastDatasetId: action.datasetId,
        completed: { ...state.completed, record: action.datasetId !== null },
      }
    case 'SET_LAST_MODEL':
      return {
        ...state,
        lastModelKey: action.modelKey,
        completed: {
          ...state.completed,
          train: action.modelKey !== null ? true : state.completed.train,
        },
      }
    case 'RESET':
      return makeInitialSetupState(state.runtimeId)
    case 'HYDRATE':
      return normalizeHydratedState(state.runtimeId, action.state)
    default:
      return state
  }
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

interface SetupContextValue {
  state: SetupState
  stepIndex: number
  steps: SetupStepMeta[]
  goTo: (step: SetupStepId) => void
  goNext: () => void
  goPrev: () => void
  markComplete: (step: SetupStepId, complete?: boolean) => void
  setCamera: (camera: CameraChoice | null) => void
  setFollowerPort: (port: PortChoice | null) => void
  setLeaderPort: (port: PortChoice | null) => void
  setLastDataset: (datasetId: string | null) => void
  setLastModel: (modelKey: string | null) => void
  reset: () => void
  canJumpTo: (target: SetupStepId) => boolean
}

const SetupContext = createContext<SetupContextValue | null>(null)

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface SetupProviderProps {
  runtimeId: string
  children: ReactNode
}

export function SetupProvider({ runtimeId, children }: SetupProviderProps) {
  const steps = useMemo(() => stepsForRuntime(runtimeId), [runtimeId])
  const [state, dispatch] = useReducer(
    reducer,
    runtimeId,
    (rid) => {
      // Lazy init: try to hydrate from localStorage before reducer starts.
      const fresh = makeInitialSetupState(rid)
      if (typeof window === 'undefined') return fresh
      try {
        const raw = window.localStorage.getItem(storageKey(rid))
        if (!raw) return fresh
        const parsed = JSON.parse(raw) as Partial<SetupState>
        return normalizeHydratedState(rid, parsed)
      } catch {
        return fresh
      }
    },
  )

  // Persist every change.
  useEffect(() => {
    try {
      window.localStorage.setItem(storageKey(runtimeId), JSON.stringify(state))
    } catch {
      /* storage disabled — non-fatal */
    }
  }, [runtimeId, state])

  // If the persisted currentStep is out of sync (e.g. removed from config),
  // bounce the user to the first incomplete step on mount.
  useEffect(() => {
    const valid = steps.some((s) => s.id === state.currentStep)
    if (!valid) {
      dispatch({ type: 'GO_TO', step: firstIncomplete(state) })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const stepIndex = useMemo(
    () => Math.max(0, steps.findIndex((s) => s.id === state.currentStep)),
    [state.currentStep, steps],
  )

  const goTo = useCallback((step: SetupStepId) => dispatch({ type: 'GO_TO', step }), [])
  const goNext = useCallback(() => {
    const idx = steps.findIndex((s) => s.id === state.currentStep)
    if (idx >= 0 && idx < steps.length - 1) {
      dispatch({ type: 'GO_TO', step: steps[idx + 1].id })
    }
  }, [state.currentStep, steps])
  const goPrev = useCallback(() => {
    const idx = steps.findIndex((s) => s.id === state.currentStep)
    if (idx > 0) {
      dispatch({ type: 'GO_TO', step: steps[idx - 1].id })
    }
  }, [state.currentStep, steps])

  const markComplete = useCallback(
    (step: SetupStepId, complete = true) =>
      dispatch({ type: 'MARK_COMPLETE', step, complete }),
    [],
  )
  const setCamera = useCallback(
    (camera: CameraChoice | null) => dispatch({ type: 'SET_CAMERA', camera }),
    [],
  )
  const setFollowerPort = useCallback(
    (port: PortChoice | null) => dispatch({ type: 'SET_FOLLOWER_PORT', port }),
    [],
  )
  const setLeaderPort = useCallback(
    (port: PortChoice | null) => dispatch({ type: 'SET_LEADER_PORT', port }),
    [],
  )
  const setLastDataset = useCallback(
    (datasetId: string | null) => dispatch({ type: 'SET_LAST_DATASET', datasetId }),
    [],
  )
  const setLastModel = useCallback(
    (modelKey: string | null) => dispatch({ type: 'SET_LAST_MODEL', modelKey }),
    [],
  )
  const reset = useCallback(() => dispatch({ type: 'RESET' }), [])
  const canJumpTo = useCallback(
    (target: SetupStepId) => _canJumpTo(state, target),
    [state],
  )

  const value: SetupContextValue = {
    state,
    stepIndex,
    steps,
    goTo,
    goNext,
    goPrev,
    markComplete,
    setCamera,
    setFollowerPort,
    setLeaderPort,
    setLastDataset,
    setLastModel,
    reset,
    canJumpTo,
  }

  return <SetupContext.Provider value={value}>{children}</SetupContext.Provider>
}

export function useSetup(): SetupContextValue {
  const ctx = useContext(SetupContext)
  if (!ctx) throw new Error('useSetup must be used within <SetupProvider>')
  return ctx
}

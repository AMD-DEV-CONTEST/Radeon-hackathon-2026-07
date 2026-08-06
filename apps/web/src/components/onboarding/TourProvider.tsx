import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  GETTING_STARTED_TOUR,
  TOURS,
  buildEffectiveSteps,
  type TourDefinition,
  type TourPath,
  type TourStep,
} from './tours'

interface TourContextValue {
  active: boolean
  tour: TourDefinition | null
  currentStep: TourStep | null
  stepIndex: number
  stepCount: number
  userPath: TourPath | null
  startTour: (tourId?: string) => void
  choosePath: (path: TourPath) => void
  next: () => void
  prev: () => void
  skip: () => void
  complete: () => void
}

const TourContext = createContext<TourContextValue | null>(null)

export function useTour() {
  const ctx = useContext(TourContext)
  if (!ctx) throw new Error('useTour must be used within TourProvider')
  return ctx
}

export function useTourOptional() {
  return useContext(TourContext)
}

function isTourDone(storageKey: string) {
  try {
    return localStorage.getItem(storageKey) === 'done'
  } catch {
    return false
  }
}

function markTourDone(storageKey: string) {
  try {
    localStorage.setItem(storageKey, 'done')
  } catch {
    /* private browsing */
  }
}

export function TourProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const [tourId, setTourId] = useState<string | null>(null)
  const [stepIndex, setStepIndex] = useState(0)
  const [userPath, setUserPath] = useState<TourPath | null>(null)
  const [pendingRoute, setPendingRoute] = useState<string | null>(null)

  const tour = tourId ? (TOURS[tourId] ?? null) : null
  const active = tour !== null

  const effectiveSteps = useMemo(
    () => (tour ? buildEffectiveSteps(tour.steps, userPath) : []),
    [tour, userPath],
  )

  const complete = useCallback(() => {
    if (tour) markTourDone(tour.storageKey)
    setTourId(null)
    setStepIndex(0)
    setUserPath(null)
    setPendingRoute(null)
  }, [tour])

  const startTour = useCallback(
    (id = GETTING_STARTED_TOUR.id) => {
      setTourId(id)
      setStepIndex(0)
      setUserPath(null)
      const def = TOURS[id]
      const firstRoute = def?.steps[0]?.route ?? '/robots'
      if (location.pathname !== firstRoute) {
        setPendingRoute(firstRoute)
        navigate(firstRoute)
      } else {
        setPendingRoute(null)
      }
    },
    [location.pathname, navigate],
  )

  const skip = complete

  const navigateForStep = useCallback(
    (step: (typeof effectiveSteps)[number] | undefined) => {
      if (step?.route && location.pathname !== step.route) {
        setPendingRoute(step.route)
        navigate(step.route)
      }
    },
    [location.pathname, navigate],
  )

  const next = useCallback(() => {
    if (!tour || effectiveSteps.length === 0) return
    const current = effectiveSteps[stepIndex]
    if (current?.kind === 'choice' && !userPath) return

    if (stepIndex >= effectiveSteps.length - 1) {
      complete()
      return
    }
    const nextIdx = stepIndex + 1
    navigateForStep(effectiveSteps[nextIdx])
    setStepIndex(nextIdx)
  }, [tour, effectiveSteps, stepIndex, userPath, navigateForStep, complete])

  const prev = useCallback(() => {
    if (!tour || stepIndex <= 0) return
    const prevIdx = stepIndex - 1
    navigateForStep(effectiveSteps[prevIdx])
    setStepIndex(prevIdx)
  }, [tour, stepIndex, effectiveSteps, navigateForStep])

  const choosePath = useCallback(
    (path: TourPath) => {
      setUserPath(path)
      if (path === 'browse') {
        complete()
        navigate('/robots/reachy_mini?guide=virtual')
        return
      }
      setStepIndex(2)
      const third = buildEffectiveSteps(tour!.steps, path)[2]
      navigateForStep(third)
    },
    [tour, navigateForStep, complete, navigate],
  )

  useEffect(() => {
    const onStart = () => startTour()
    window.addEventListener('botversex:start-tour', onStart)
    return () => window.removeEventListener('botversex:start-tour', onStart)
  }, [startTour])

  useEffect(() => {
    const onDismiss = () => {
      if (tourId) complete()
    }
    window.addEventListener('botversex:dismiss-guides', onDismiss)
    return () => window.removeEventListener('botversex:dismiss-guides', onDismiss)
  }, [tourId, complete])

  useEffect(() => {
    if (tourId) return
    const path = location.pathname
    if (path !== '/robots' && path !== '/') return
    if (isTourDone(GETTING_STARTED_TOUR.storageKey)) return
    const t = window.setTimeout(() => startTour(), 1200)
    return () => clearTimeout(t)
  }, [location.pathname, tourId, startTour])

  useEffect(() => {
    if (pendingRoute && location.pathname === pendingRoute) {
      setPendingRoute(null)
    }
  }, [location.pathname, pendingRoute])

  const currentStep = effectiveSteps[stepIndex] ?? null

  const value = useMemo<TourContextValue>(
    () => ({
      active,
      tour,
      currentStep,
      stepIndex,
      stepCount: effectiveSteps.length,
      userPath,
      startTour,
      choosePath,
      next,
      prev,
      skip,
      complete,
    }),
    [
      active,
      tour,
      currentStep,
      stepIndex,
      effectiveSteps.length,
      userPath,
      startTour,
      choosePath,
      next,
      prev,
      skip,
      complete,
    ],
  )

  return <TourContext.Provider value={value}>{children}</TourContext.Provider>
}

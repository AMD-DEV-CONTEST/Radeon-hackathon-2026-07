// router.tsx — minimal History API route controller (Todo 9, no routing dependency).
//
// Routes:
//   /garden                          garden view
//   /upload                          upload view
//   /processing/:runId               extraction run status
//   /skills/:skillId                 skill detail
//   /skills/:skillId/source/:materialId  source document viewer
//   /skills/:skillId/learn           learning session
//   /skills/:skillId/assessment      first assessment
//   /skills/:skillId/review          due review
//
// Behavior: popstate, refresh/deep-link recovery (pathname parsed on mount),
// invalid-ID routes render an accessible recovery state, and a mobile
// navigation pattern removes fixed-sidebar overflow.

export type Route =
  | { name: "garden" }
  | { name: "upload" }
  | { name: "processing"; runId: string }
  | { name: "skill"; skillId: string }
  | { name: "source"; skillId: string; materialId: string }
  | { name: "learn"; skillId: string }
  | { name: "assessment"; skillId: string }
  | { name: "review"; skillId: string }
  | { name: "invalid"; path: string }

const SEG = String.raw`([^/]+)`

function parse(path: string): Route {
  const p = path.replace(/^\/+|\/+$/g, "")
  if (p === "" || p === "garden") return { name: "garden" }
  if (p === "upload") return { name: "upload" }
  let m = p.match(new RegExp(`^processing/${SEG}$`))
  if (m) return { name: "processing", runId: decodeURIComponent(m[1]) }
  m = p.match(new RegExp(`^skills/${SEG}/source/${SEG}$`))
  if (m) return { name: "source", skillId: decodeURIComponent(m[1]), materialId: decodeURIComponent(m[2]) }
  m = p.match(new RegExp(`^skills/${SEG}/learn$`))
  if (m) return { name: "learn", skillId: decodeURIComponent(m[1]) }
  m = p.match(new RegExp(`^skills/${SEG}/assessment$`))
  if (m) return { name: "assessment", skillId: decodeURIComponent(m[1]) }
  m = p.match(new RegExp(`^skills/${SEG}/review$`))
  if (m) return { name: "review", skillId: decodeURIComponent(m[1]) }
  m = p.match(new RegExp(`^skills/${SEG}$`))
  if (m) return { name: "skill", skillId: decodeURIComponent(m[1]) }
  return { name: "invalid", path: p }
}

export function toPath(route: Route): string {
  switch (route.name) {
    case "garden": return "/garden"
    case "upload": return "/upload"
    case "processing": return `/processing/${route.runId}`
    case "skill": return `/skills/${route.skillId}`
    case "source": return `/skills/${route.skillId}/source/${route.materialId}`
    case "learn": return `/skills/${route.skillId}/learn`
    case "assessment": return `/skills/${route.skillId}/assessment`
    case "review": return `/skills/${route.skillId}/review`
    case "invalid": return `/${route.path}`
  }
}

function idOf(route: Route): number | null {
  const s = "skillId" in route ? route.skillId : "runId" in route ? route.runId : ""
  const n = Number(s)
  return Number.isInteger(n) && n > 0 ? n : null
}

export interface Router {
  route: Route
  skillId: number | null   // valid numeric skill id for skill-ish routes
  runId: number | null     // valid numeric run id for processing route
  materialId: number | null  // valid numeric material id for source route
  navigate: (route: Route, opts?: { replace?: boolean }) => void
  subscribe: (fn: () => void) => () => void
}

export function createRouter(): Router {
  let listeners: (() => void)[] = []
  const notify = () => listeners.forEach((l) => l())

  window.addEventListener("popstate", notify)

  return {
    get route() {
      return parse(window.location.pathname)
    },
    get skillId() {
      const r = parse(window.location.pathname)
      return r.name === "skill" || r.name === "source" || r.name === "learn" ||
             r.name === "assessment" || r.name === "review"
        ? idOf(r)
        : null
    },
    get runId() {
      const r = parse(window.location.pathname)
      return r.name === "processing" ? idOf(r) : null
    },
    get materialId() {
      const r = parse(window.location.pathname)
      return r.name === "source" && "materialId" in r ? Number(r.materialId) : null
    },
    navigate(route, opts) {
      const url = toPath(route)
      if (opts?.replace) window.history.replaceState({}, "", url)
      else window.history.pushState({}, "", url)
      notify()
    },
    subscribe(fn: () => void) {
      listeners.push(fn)
      return () => {
        listeners = listeners.filter((l) => l !== fn)
      }
    },
  }
}

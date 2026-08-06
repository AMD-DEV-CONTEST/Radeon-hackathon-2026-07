// API client for the Learning Companion backend (same-origin via Vite proxy / FastAPI)

export interface Skill {
  id: number
  name: string
  description: string
  growth_value: number
  decay_rate: number
  status: "萌芽" | "生长中" | "成熟" | "衰退"
  last_reviewed_at: string | null
  card_count?: number
}

export interface Card {
  id: number
  skill_id: number
  content: string
  source_material: string
  mastery_level: number
  last_reviewed_at: string | null
}

export interface TranscriptEntry {
  role: "ai" | "user"
  stage?: string
  card_id?: number
  content: string
  judgment?: { mastery_level: number; needs_retry: boolean }
}

export interface ReviewSession {
  id: number
  skill_id: number
  status: string
  card_index: number
  total_cards: number
  phase: string
  retries: number
  judged: Record<string, unknown>
  user_override: boolean
  transcript: TranscriptEntry[]
  created_at: string
  completed_at: string | null
}

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

const FETCH_TIMEOUT_MS = 15_000

/** fetch with a hard timeout: a hung tunnel request surfaces as an Error
 *  (caught by pages -> shows recovery state) instead of an infinite spinner. */
async function jf(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS)
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

export const api = {
  async listSkills(): Promise<Skill[]> {
    const d = await j<{ skills: Skill[] }>(await jf("/api/skills"))
    return d.skills
  },
  async createSkill(name: string, description = ""): Promise<Skill> {
    return j(await jf("/api/skills", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description }),
    }))
  },
  async getSkill(id: number) {
    return j<{ [k: string]: unknown }>(await jf(`/api/skills/${id}`))
  },
  async extract(skillId: number, text: string, runFull = false) {
    return j(await jf("/api/extract", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ skill_id: skillId, text, run_full: runFull }),
    }))
  },
  async startReview(skillId: number) {
    return j<{ ok: boolean; resumed: boolean; session: ReviewSession; error?: string }>(
      await jf("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_id: skillId }),
      }),
    )
  },
  async reviewMessage(sessionId: number, message: string) {
    return j(await jf(`/api/review/${sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }))
  },
  async reviewOverride(sessionId: number) {
    return j(await jf(`/api/review/${sessionId}/override`, { method: "POST" }))
  },
  async reviewComplete(sessionId: number) {
    return j(await jf(`/api/review/${sessionId}/complete`, { method: "POST" }))
  },
  async reviewAbandon(sessionId: number) {
    return j(await jf(`/api/review/${sessionId}/abandon`, { method: "POST" }))
  },
  async stats() {
    return j<Record<string, number>>(await jf("/api/stats"))
  },
  // ---- Todo 8/9: typed target-schema endpoints ----
  async createMaterial(skillIdOrName: number | string, text: string, filename = "") {
    const body = typeof skillIdOrName === "number"
      ? { skill_id: skillIdOrName, text, filename }
      : { skill_name: skillIdOrName, text, filename }
    return j<{ material_id: number; created: boolean; run_id: number; status: string; skill_id: number }>(
      await jf("/api/materials", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    )
  },
  async getMaterial(materialId: number) {
    return j<{ id: number; skill_id: number; raw_text: string; filename: string; created_at: string }>(
      await jf(`/api/materials/${materialId}`),
    )
  },
  async getExtractionRun(runId: number) {
    return j<Record<string, unknown>>(await jf(`/api/extraction-runs/${runId}`))
  },
  async retryExtractionRun(runId: number) {
    return j(await jf(`/api/extraction-runs/${runId}/retry`, { method: "POST" }))
  },
  async deleteExtractionRun(runId: number) {
    return j(await jf(`/api/extraction-runs/${runId}`, { method: "DELETE" }))
  },
  async deleteSkill(skillId: number) {
    return j(await jf(`/api/skills/${skillId}`, { method: "DELETE" }))
  },
  async getUnit(unitId: number) {
    return j<Record<string, unknown>>(await jf(`/api/units/${unitId}`))
  },
  async getSkillUnits(skillId: number) {
    return j<{ units: { id: number; skill_id: number; content: string; source_quote?: string | null;
                        key_points?: string[]; example?: string | null; pitfall?: string | null;
                        status: string }[] }>(await jf(`/api/skills/${skillId}/units`))
  },
  async getSkillRuns(skillId: number) {
    return j<{ runs: { id: number; material_id: number; status: string; model?: string | null;
                       error_detail?: string | null; retries?: number; created_at?: string;
                       material_text?: string }[] }>(await jf(`/api/skills/${skillId}/runs`))
  },
  async listSessions() {
    return j<{ sessions: Record<string, unknown>[] }>(await jf("/api/sessions"))
  },
  async startLearningSession(skillId: number, idempotencyKey?: string) {
    return j<{ session: { id: number }; units: unknown[]; resumed: boolean }>(
      await jf("/api/learning-sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_id: skillId, idempotency_key: idempotencyKey }),
      }),
    )
  },
  async submitAssessment(sessionId: number, unitId: number, idempotencyKey: string, recall: string) {
    return j<{ attempt: { score?: number; status?: string }; progress?: unknown }>(
      await jf("/api/assessment", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, unit_id: unitId, idempotency_key: idempotencyKey, recall }),
      }),
    )
  },
  async startReviewSession(skillId: number) {
    return j<{ session: { id: number }; units: unknown[] }>(
      await jf("/api/review-sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skill_id: skillId }),
      }),
    )
  },
  async submitReview(sessionId: number, unitId: number, idempotencyKey: string, recall: string) {
    return j<{ attempt: { score?: number; status?: string; needs_retry?: number }; progress?: unknown }>(
      await jf(`/api/review/${sessionId}/submit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ unit_id: unitId, idempotency_key: idempotencyKey, recall }),
      }),
    )
  },
  async overrideReview(sessionId: number, unitId: number) {
    return j(await jf(`/api/sessions/${sessionId}/override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit_id: unitId }),
    }))
  },
  async abandonSession(sessionId: number) {
    return j(await jf(`/api/sessions/${sessionId}/abandon`, { method: "POST" }))
  },
  async garden(skillId: number) {
    return j<{ skill_id: number; name?: string; growth_value: number; status: string }>(await jf(`/api/garden/${skillId}`))
  },
  async gardenList() {
    return j<{ gardens: { skill_id: number; name: string; growth_value: number; status: string;
                          learned_verified: number; total_verified: number; overdue_count: number }[] }>(
      await jf("/api/garden"))
  },
  async adminDrain() {
    return j<{ state: string; in_flight: number }>(await jf("/api/admin/drain", { method: "POST" }))
  },
  async adminUndrain() {
    return j<{ state: string; in_flight: number }>(await jf("/api/admin/undrain", { method: "POST" }))
  },
}

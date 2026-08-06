/**
 * Skills page — M7 Skills basic functionality line.
 *
 * Four sections:
 *   1. Skill Registry — loaded from GET /api/v1/skills (not hardcoded anymore)
 *   2. Registered Runtimes — from /api/v1/skills/runtimes (with compat filter)
 *   3. My Installations — install / enable / configure / run (Phases 2-4)
 *   4. Recent Runs — status + log excerpt (Phase 4)
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity, AlertTriangle, Bot, CheckCircle2, ChevronRight, Cpu, Loader2,
  Play, Power, RefreshCw, Settings, Trash2, XCircle, Zap,
} from 'lucide-react'

import { Button } from '../components/ui/button'
import { Card, CardContent } from '../components/ui/card'
import { Badge } from '../components/ui/badge'
import { cn } from '../lib/utils'
import {
  deleteInstallation,
  getRun,
  installSkill,
  listInstallations,
  listRuns,
  listRuntimesWithSkills,
  listSkills,
  patchInstallation,
  runSkill,
  type RuntimeWithSkills,
  type Skill,
  type SkillInstallation,
  type SkillRun,
} from '../lib/skillsApi'
import { SkillConfigModal } from '../components/skills/SkillConfigModal'
import { useAuth } from '../lib/authContext'

/* ── helpers ─────────────────────────────────────────────────────────────── */

function runStatusColor(s: SkillRun['status']) {
  switch (s) {
    case 'running':
    case 'queued':
      return 'text-amber-400 border-amber-500/40 bg-amber-500/10'
    case 'succeeded':
      return 'text-green-400 border-green-500/40 bg-green-500/10'
    case 'failed':
      return 'text-red-400 border-red-500/40 bg-red-500/10'
    default:
      return 'text-muted-foreground border-[hsl(var(--border))]'
  }
}

/* ── main page ───────────────────────────────────────────────────────────── */

export function Skills() {
  const { user, token } = useAuth()
  const canPublish = user?.entitlements?.limits.can_publish_paid_skills ?? false
  const [skills, setSkills] = useState<Skill[]>([])
  const [runtimes, setRuntimes] = useState<RuntimeWithSkills[]>([])
  const [installations, setInstallations] = useState<SkillInstallation[]>([])
  const [runs, setRuns] = useState<SkillRun[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [filterRuntime, setFilterRuntime] = useState<string>('all')
  const [modalState, setModalState] = useState<
    | null
    | {
        skill: Skill
        runtimeId: string
        runtimeRobotType?: string
        existing?: SkillInstallation
      }
  >(null)

  const [busyInstall, setBusyInstall] = useState<string | null>(null)
  const [busyRun, setBusyRun] = useState<string | null>(null)

  const skillsById = useMemo(() => {
    const m = new Map<string, Skill>()
    for (const s of skills) m.set(s.skill_id, s)
    return m
  }, [skills])

  const runtimesById = useMemo(() => {
    const m = new Map<string, RuntimeWithSkills>()
    for (const r of runtimes) m.set(r.runtime_id, r)
    return m
  }, [runtimes])

  const refreshAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [sk, rt] = await Promise.all([
        listSkills(),
        listRuntimesWithSkills(),
      ])
      setSkills(sk.skills)
      setRuntimes(rt.runtimes)
      if (token) {
        const [inst, rn] = await Promise.all([
          listInstallations(),
          listRuns({ limit: 20 }),
        ])
        setInstallations(inst.installations)
        setRuns(rn.runs)
      } else {
        setInstallations([])
        setRuns([])
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    refreshAll()
  }, [refreshAll])

  // Poll running runs until they settle (Phase 4 "status query").
  useEffect(() => {
    const running = runs.filter((r) => r.status === 'running' || r.status === 'queued')
    if (running.length === 0) return
    const tick = setInterval(async () => {
      try {
        const updates = await Promise.all(
          running.map((r) => getRun(r.run_id).catch(() => null)),
        )
        setRuns((prev) =>
          prev.map((r) => {
            const u = updates.find((x) => x && x.run_id === r.run_id)
            return u ?? r
          }),
        )
      } catch {
        /* noop */
      }
    }, 1500)
    return () => clearInterval(tick)
  }, [runs])

  /* ── mutations ─────────────────────────────────────────────────────────── */

  const handleQuickInstall = async (skill: Skill, runtime: RuntimeWithSkills) => {
    if (!token) {
      setError('Log in to install and run skills. You can browse the full registry without an account.')
      return
    }
    const needsParams = (skill.params_schema || []).some((p) => p.required)
    if (needsParams) {
      setModalState({ skill, runtimeId: runtime.runtime_id, runtimeRobotType: runtime.robot_type })
      return
    }
    setBusyInstall(`${skill.skill_id}:${runtime.runtime_id}`)
    try {
      const inst = await installSkill(skill.skill_id, {
        runtime_id: runtime.runtime_id,
        runtime_robot_type: runtime.robot_type,
        enabled: true,
      })
      setInstallations((prev) => {
        const without = prev.filter((p) => p.id !== inst.id)
        return [inst, ...without]
      })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyInstall(null)
    }
  }

  const handleToggleEnable = async (inst: SkillInstallation) => {
    if (!token) return
    try {
      const next = await patchInstallation(inst.id, { enabled: !inst.enabled })
      setInstallations((prev) => prev.map((p) => (p.id === inst.id ? next : p)))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleUninstall = async (inst: SkillInstallation) => {
    if (!token) return
    if (!confirm(`Uninstall ${inst.skill_id} from ${inst.runtime_id}?`)) return
    try {
      await deleteInstallation(inst.id)
      setInstallations((prev) => prev.filter((p) => p.id !== inst.id))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const handleRun = async (inst: SkillInstallation) => {
    if (!token) return
    setBusyRun(inst.id)
    try {
      const run = await runSkill(inst.skill_id, { runtime_id: inst.runtime_id })
      setRuns((prev) => [run, ...prev].slice(0, 50))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusyRun(null)
    }
  }

  /* ── filtering ─────────────────────────────────────────────────────────── */

  const filteredSkills = useMemo(() => {
    if (filterRuntime === 'all') return skills
    const rt = runtimesById.get(filterRuntime)
    if (!rt) return skills
    return skills.filter(
      (s) => s.robot_type === rt.robot_type || s.compatible_types.includes(rt.robot_type),
    )
  }, [skills, filterRuntime, runtimesById])

  /* ── render ────────────────────────────────────────────────────────────── */

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Skills</h1>
          <p className="text-muted-foreground mt-1">
            Discover, install, configure, and run robot skills — the atomic units of behavior in BotverseX.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {canPublish && (
            <Link
              to="/skills#marketplace"
              className="inline-flex h-8 items-center rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground shadow hover:bg-primary/90"
            >
              上架 Skill
            </Link>
          )}
          <Button variant="outline" size="sm" onClick={refreshAll} disabled={loading}>
            {loading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <RefreshCw className="h-3.5 w-3.5" />
            )}
            <span className="ml-1.5">Refresh</span>
          </Button>
        </div>
      </div>

      {error && (
        <div className="border border-red-500/40 bg-red-500/10 text-red-300 px-3 py-2 rounded-md text-sm flex items-start gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* ── Section 1: Registry ───────────────────────────────────────────── */}
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Zap className="h-5 w-5 text-amber-500" />
            Skill Registry
            <Badge variant="outline" className="text-xs">{skills.length}</Badge>
          </h2>
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">Filter by runtime:</span>
            <select
              value={filterRuntime}
              onChange={(e) => setFilterRuntime(e.target.value)}
              className="h-7 px-2 rounded-md border border-[hsl(var(--border))] bg-transparent text-xs"
            >
              <option value="all">All</option>
              {runtimes.map((rt) => (
                <option key={rt.runtime_id} value={rt.runtime_id}>
                  {rt.display_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {loading && skills.length === 0 ? (
          <p className="text-sm text-muted-foreground">Loading skills...</p>
        ) : filteredSkills.length === 0 ? (
          <p className="text-sm text-muted-foreground">No skills match this filter.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {filteredSkills.map((skill) => {
              const compatRuntimes = runtimes.filter(
                (rt) =>
                  skill.robot_type === rt.robot_type ||
                  skill.compatible_types.includes(rt.robot_type),
              )
              const installedRuntimes = new Set(
                installations.filter((i) => i.skill_id === skill.skill_id).map((i) => i.runtime_id),
              )
              return (
                <Card key={skill.skill_id}>
                  <CardContent className="p-5 space-y-3">
                    <div className="flex items-start gap-3">
                      <div className="h-10 w-10 rounded-lg bg-amber-500/10 flex items-center justify-center shrink-0">
                        <Zap className="h-5 w-5 text-amber-500" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                          <h3 className="font-semibold">{skill.verb}</h3>
                          <Badge variant="outline" className="text-xs font-mono">
                            {skill.skill_id}
                          </Badge>
                        </div>
                        {skill.description && (
                          <p className="text-sm text-muted-foreground line-clamp-2">
                            {skill.description}
                          </p>
                        )}
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      <span className="text-muted-foreground">Types:</span>
                      {skill.compatible_types.map((t) => (
                        <Badge key={t} variant="secondary" className="text-xs">
                          {t}
                        </Badge>
                      ))}
                    </div>

                    <div className="pt-2 border-t space-y-1.5">
                      <p className="text-xs text-muted-foreground">
                        Compatible runtimes ({compatRuntimes.length})
                      </p>
                      {compatRuntimes.length === 0 ? (
                        <p className="text-xs text-muted-foreground italic">No connected runtimes match.</p>
                      ) : (
                        <div className="space-y-1">
                          {compatRuntimes.map((rt) => {
                            const installed = installedRuntimes.has(rt.runtime_id)
                            const key = `${skill.skill_id}:${rt.runtime_id}`
                            return (
                              <div
                                key={rt.runtime_id}
                                className="flex items-center justify-between gap-2 text-xs"
                              >
                                <span className="truncate">
                                  <Cpu className="inline h-3 w-3 mr-1 text-primary" />
                                  {rt.display_name}
                                </span>
                                {installed ? (
                                  <Badge variant="default" className="text-[10px] h-5 px-2">
                                    Installed
                                  </Badge>
                                ) : (
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    className="h-6 text-[11px] px-2"
                                    disabled={!token || busyInstall === key}
                                    onClick={() => handleQuickInstall(skill, rt)}
                                  >
                                    {busyInstall === key ? (
                                      <Loader2 className="h-3 w-3 animate-spin" />
                                    ) : !token ? (
                                      'Log in'
                                    ) : (
                                      'Install'
                                    )}
                                  </Button>
                                )}
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </section>

      {/* ── Section 2: Runtimes ───────────────────────────────────────────── */}
      <section>
        <h2 className="text-xl font-semibold flex items-center gap-2 mb-4">
          <Cpu className="h-5 w-5" />
          Registered Runtimes
          <Badge variant="outline" className="text-xs">{runtimes.length}</Badge>
        </h2>
        {runtimes.length === 0 && !loading ? (
          <Card>
            <CardContent className="p-6 text-center text-sm text-muted-foreground">
              <Bot className="h-6 w-6 mx-auto mb-2 opacity-50" />
              No runtimes reachable. Ensure the realtime service is running on :8002.
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {runtimes.map((rt) => (
              <Card key={rt.runtime_id}>
                <CardContent className="p-5 space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                      <Cpu className="h-5 w-5 text-primary" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-sm">{rt.display_name}</h3>
                      <p className="text-xs text-muted-foreground font-mono">{rt.runtime_id}</p>
                    </div>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Joints</span>
                    <span className="font-medium">{rt.joint_count} DoF</span>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Compatible skills</span>
                    <Badge variant="secondary" className="text-[10px]">
                      {rt.compatible_skill_ids.length}
                    </Badge>
                  </div>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">Telemetry</span>
                    <Badge variant={rt.supports_telemetry ? 'default' : 'secondary'} className="text-[10px]">
                      {rt.supports_telemetry ? 'Yes' : 'No'}
                    </Badge>
                  </div>
                  <div className="pt-2 border-t flex items-center justify-end">
                    <Link to="/robots">
                      <Button variant="ghost" size="sm" className="h-7 text-xs gap-1">
                        Details <ChevronRight className="h-3.5 w-3.5" />
                      </Button>
                    </Link>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      {/* ── Section 3: My Installations ───────────────────────────────────── */}
      <section>
        <h2 className="text-xl font-semibold flex items-center gap-2 mb-4">
          <Settings className="h-5 w-5" />
          My Installations
          <Badge variant="outline" className="text-xs">{installations.length}</Badge>
        </h2>
        {!token ? (
          <Card>
            <CardContent className="p-6 text-center text-sm text-muted-foreground space-y-3">
              <p>Log in to install, configure, and manage skills for your robots.</p>
              <Link to="/login" className="inline-flex">
                <Button size="sm">Log in to manage skills</Button>
              </Link>
            </CardContent>
          </Card>
        ) : installations.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-center text-sm text-muted-foreground">
              You haven't installed any skills yet. Scroll up to the registry and click <span className="font-medium">Install</span>.
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {installations.map((inst) => {
              const skill = skillsById.get(inst.skill_id)
              const rt = runtimesById.get(inst.runtime_id)
              const hasErrors =
                skill !== undefined &&
                (skill.params_schema || []).some((p) => {
                  if (!p.required) return false
                  const v = (inst.params as Record<string, unknown>)[p.key]
                  return v === undefined || v === null || v === ''
                })
              return (
                <Card key={inst.id}>
                  <CardContent className="p-4 flex items-center gap-3 flex-wrap">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium">{skill?.verb || inst.skill_id}</span>
                        <Badge variant="outline" className="text-[10px] font-mono">
                          {inst.skill_id}
                        </Badge>
                        <span className="text-xs text-muted-foreground">on</span>
                        <Badge variant="secondary" className="text-[10px]">
                          <Cpu className="h-3 w-3 mr-1" />
                          {rt?.display_name || inst.runtime_id}
                        </Badge>
                        {inst.enabled ? (
                          <Badge className="text-[10px]" variant="default">
                            enabled
                          </Badge>
                        ) : (
                          <Badge className="text-[10px]" variant="secondary">
                            disabled
                          </Badge>
                        )}
                        {hasErrors && (
                          <Badge variant="destructive" className="text-[10px] gap-1">
                            <AlertTriangle className="h-3 w-3" />
                            Needs config
                          </Badge>
                        )}
                      </div>
                      {skill?.description && (
                        <p className="text-xs text-muted-foreground mt-1 truncate">
                          {skill.description}
                        </p>
                      )}
                    </div>

                    <div className="flex items-center gap-1">
                      <Button
                        size="sm"
                        variant="outline"
                        className="h-8 text-xs"
                        onClick={() => handleToggleEnable(inst)}
                      >
                        <Power className="h-3.5 w-3.5 mr-1" />
                        {inst.enabled ? 'Disable' : 'Enable'}
                      </Button>
                      {skill && (
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-8 text-xs"
                          onClick={() =>
                            setModalState({
                              skill,
                              runtimeId: inst.runtime_id,
                              runtimeRobotType: rt?.robot_type,
                              existing: inst,
                            })
                          }
                        >
                          <Settings className="h-3.5 w-3.5 mr-1" />
                          Configure
                        </Button>
                      )}
                      <Button
                        size="sm"
                        className="h-8 text-xs"
                        disabled={!inst.enabled || hasErrors || busyRun === inst.id}
                        onClick={() => handleRun(inst)}
                      >
                        {busyRun === inst.id ? (
                          <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                        ) : (
                          <Play className="h-3.5 w-3.5 mr-1" />
                        )}
                        Run
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 w-8 p-0"
                        onClick={() => handleUninstall(inst)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </section>

      {/* ── Section 4: Recent Runs ────────────────────────────────────────── */}
      <section>
        <h2 className="text-xl font-semibold flex items-center gap-2 mb-4">
          <Activity className="h-5 w-5" />
          Recent Runs
          <Badge variant="outline" className="text-xs">{runs.length}</Badge>
        </h2>
        {!token ? (
          <Card>
            <CardContent className="p-6 text-center text-sm text-muted-foreground space-y-3">
              <p>Log in to see your recent skill runs and execution history.</p>
              <Link to="/login" className="inline-flex">
                <Button size="sm">Log in to view runs</Button>
              </Link>
            </CardContent>
          </Card>
        ) : runs.length === 0 ? (
          <Card>
            <CardContent className="p-6 text-center text-sm text-muted-foreground">
              No runs yet. Install a skill and press <span className="font-medium">Run</span>.
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {runs.map((r) => {
              const skill = skillsById.get(r.skill_id)
              const badgeCls = runStatusColor(r.status)
              const icon =
                r.status === 'succeeded' ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : r.status === 'failed' ? (
                  <XCircle className="h-3.5 w-3.5" />
                ) : (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                )
              return (
                <Card key={r.run_id}>
                  <CardContent className="p-3 flex items-start gap-3">
                    <div
                      className={cn(
                        'h-7 px-2 rounded-md border flex items-center gap-1 text-xs self-start',
                        badgeCls,
                      )}
                    >
                      {icon}
                      {r.status}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm">{skill?.verb || r.verb}</span>
                        <Badge variant="outline" className="text-[10px] font-mono">
                          {r.skill_id}
                        </Badge>
                        <span className="text-xs text-muted-foreground">on</span>
                        <Badge variant="secondary" className="text-[10px]">
                          {r.runtime_id}
                        </Badge>
                      </div>
                      {r.log_excerpt && (
                        <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                          {r.log_excerpt}
                        </p>
                      )}
                      {r.error_msg && (
                        <p className="text-xs text-red-400 mt-1 line-clamp-2">
                          {r.error_msg}
                        </p>
                      )}
                    </div>
                    <div className="text-[10px] text-muted-foreground font-mono shrink-0">
                      {r.started_at?.slice(11, 19)}
                    </div>
                  </CardContent>
                </Card>
              )
            })}
          </div>
        )}
      </section>

      {/* Config modal */}
      {modalState && (
        <SkillConfigModal
          isOpen
          onClose={() => setModalState(null)}
          skill={modalState.skill}
          runtimeId={modalState.runtimeId}
          runtimeRobotType={modalState.runtimeRobotType}
          existing={modalState.existing}
          onSaved={(inst) => {
            setInstallations((prev) => {
              const without = prev.filter((p) => p.id !== inst.id)
              return [inst, ...without]
            })
          }}
        />
      )}
    </div>
  )
}

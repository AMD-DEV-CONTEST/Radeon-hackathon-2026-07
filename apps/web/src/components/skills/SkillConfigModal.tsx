/**
 * SkillConfigModal — Phase 3 of Skills basic line.
 *
 * Renders a params form from `skill.params_schema`, validates on the client
 * (lightweight mirror of server-side validate_params), and saves via the
 * installations API. Reused for both "Install" (no existing installation)
 * and "Configure" (existing installation) flows.
 */
import { useEffect, useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'

import { Button } from '../ui/button'
import { Modal } from '../ui/modal'
import {
  installSkill,
  patchInstallation,
  type Skill,
  type SkillInstallation,
} from '../../lib/skillsApi'

interface Props {
  isOpen: boolean
  onClose: () => void
  skill: Skill
  runtimeId: string
  runtimeRobotType?: string
  existing?: SkillInstallation
  onSaved: (inst: SkillInstallation) => void
}

function coerceDefault(schema: Skill['params_schema']): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const entry of schema || []) {
    if (entry.default !== undefined) out[entry.key] = entry.default
  }
  return out
}

function validateLocal(
  skill: Skill,
  values: Record<string, unknown>,
): Record<string, string> {
  const errs: Record<string, string> = {}
  for (const entry of skill.params_schema || []) {
    const v = values[entry.key]
    const empty = v === undefined || v === null || v === ''
    if (empty) {
      if (entry.required) errs[entry.key] = `${entry.label} is required`
      continue
    }
    if (entry.type === 'number') {
      const n = Number(v)
      if (Number.isNaN(n)) {
        errs[entry.key] = `${entry.label} must be a number`
        continue
      }
      if (entry.min !== undefined && n < entry.min)
        errs[entry.key] = `${entry.label} must be ≥ ${entry.min}`
      if (entry.max !== undefined && n > entry.max)
        errs[entry.key] = `${entry.label} must be ≤ ${entry.max}`
    } else if (entry.type === 'enum') {
      if (!(entry.options || []).includes(String(v)))
        errs[entry.key] = `${entry.label} must be one of: ${(entry.options || []).join(', ')}`
    }
  }
  return errs
}

export function SkillConfigModal({
  isOpen,
  onClose,
  skill,
  runtimeId,
  runtimeRobotType,
  existing,
  onSaved,
}: Props) {
  const initial = useMemo(() => {
    if (existing?.params) return { ...coerceDefault(skill.params_schema), ...existing.params }
    return coerceDefault(skill.params_schema)
  }, [skill, existing])

  const [values, setValues] = useState<Record<string, unknown>>(initial)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)

  useEffect(() => {
    if (isOpen) {
      setValues(initial)
      setErrors({})
      setServerError(null)
    }
  }, [isOpen, initial])

  const setField = (key: string, v: unknown) => {
    setValues((prev) => ({ ...prev, [key]: v }))
  }

  const handleSave = async () => {
    const clientErrors = validateLocal(skill, values)
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors)
      return
    }
    setErrors({})
    setSaving(true)
    setServerError(null)
    try {
      let inst: SkillInstallation
      if (existing) {
        inst = await patchInstallation(existing.id, { params: values })
      } else {
        inst = await installSkill(skill.skill_id, {
          runtime_id: runtimeId,
          runtime_robot_type: runtimeRobotType,
          params: values,
          enabled: true,
        })
      }
      onSaved(inst)
      onClose()
    } catch (e) {
      setServerError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const schema = skill.params_schema || []
  const title = existing
    ? `Configure ${skill.verb}`
    : `Install ${skill.verb} on ${runtimeId}`

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={title} className="max-w-lg">
      <div className="space-y-4">
        <div className="text-xs text-muted-foreground">
          <span className="font-mono">{skill.skill_id}</span>
          {skill.description && <span> · {skill.description}</span>}
        </div>

        {schema.length === 0 && (
          <p className="text-sm text-muted-foreground italic">
            This skill has no configurable parameters.
          </p>
        )}

        {schema.map((entry) => {
          const v = values[entry.key]
          const err = errors[entry.key]
          const id = `skill-param-${entry.key}`
          return (
            <div key={entry.key} className="space-y-1">
              <label htmlFor={id} className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
                {entry.label}
                {entry.required && <span className="text-red-400">*</span>}
                <span className="font-mono text-[10px] text-muted-foreground/60">({entry.type})</span>
              </label>
              {entry.type === 'enum' ? (
                <select
                  id={id}
                  value={String(v ?? '')}
                  onChange={(e) => setField(entry.key, e.target.value)}
                  className="w-full h-9 px-3 rounded-md border border-[hsl(var(--border))] bg-transparent text-sm"
                >
                  <option value="">—</option>
                  {(entry.options || []).map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              ) : entry.type === 'bool' ? (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    id={id}
                    type="checkbox"
                    checked={Boolean(v)}
                    onChange={(e) => setField(entry.key, e.target.checked)}
                  />
                  <span className="text-muted-foreground">enabled</span>
                </label>
              ) : entry.type === 'number' ? (
                <input
                  id={id}
                  type="number"
                  value={v === undefined || v === null ? '' : String(v)}
                  min={entry.min}
                  max={entry.max}
                  onChange={(e) =>
                    setField(entry.key, e.target.value === '' ? '' : Number(e.target.value))
                  }
                  className="w-full h-9 px-3 rounded-md border border-[hsl(var(--border))] bg-transparent text-sm"
                />
              ) : (
                <input
                  id={id}
                  type="text"
                  value={v === undefined || v === null ? '' : String(v)}
                  onChange={(e) => setField(entry.key, e.target.value)}
                  className="w-full h-9 px-3 rounded-md border border-[hsl(var(--border))] bg-transparent text-sm"
                />
              )}
              {err && <p className="text-xs text-red-400">{err}</p>}
            </div>
          )
        })}

        {serverError && (
          <p className="text-xs text-red-400 border border-red-500/30 bg-red-500/10 rounded px-2 py-1.5">
            {serverError}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
            {existing ? 'Save' : 'Install'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

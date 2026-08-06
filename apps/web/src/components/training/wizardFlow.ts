import type { WizardStep } from './types'

export const WIZARD_FLOW: WizardStep[] = ['data', 'goal', 'prepare', 'confirm']

export function wizardPrevious(step: WizardStep): WizardStep | null {
  const i = WIZARD_FLOW.indexOf(step)
  if (i <= 0) return null
  return WIZARD_FLOW[i - 1] ?? null
}

export function wizardNext(step: WizardStep): WizardStep | null {
  const i = WIZARD_FLOW.indexOf(step)
  if (i < 0 || i >= WIZARD_FLOW.length - 1) return null
  return WIZARD_FLOW[i + 1] ?? null
}

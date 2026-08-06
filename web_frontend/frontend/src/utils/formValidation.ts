import type { FormInst, FormItemRule } from 'naive-ui'

type RuleTrigger = 'blur' | 'change' | 'input'

export function requiredTextRule(
  message: string,
  trigger: RuleTrigger | RuleTrigger[] = ['input', 'blur'],
): FormItemRule {
  return {
    required: true,
    trigger,
    validator: (_rule, value) => (
      typeof value === 'string' && value.trim().length > 0
        ? true
        : new Error(message)
    ),
  }
}

export function requiredValueRule(
  message: string,
  trigger: RuleTrigger | RuleTrigger[] = 'change',
): FormItemRule {
  return {
    required: true,
    trigger,
    validator: (_rule, value) => (
      value !== null
      && value !== undefined
      && (typeof value !== 'string' || value.trim().length > 0)
        ? true
        : new Error(message)
    ),
  }
}

export function requiredArrayRule(
  message: string,
  trigger: RuleTrigger | RuleTrigger[] = 'change',
): FormItemRule {
  return {
    required: true,
    type: 'array',
    trigger,
    validator: (_rule, value) => (
      Array.isArray(value) && value.length > 0
        ? true
        : new Error(message)
    ),
  }
}

export function requiredHttpUrlRule(
  requiredMessage: string,
  invalidMessage: string,
): FormItemRule {
  return {
    required: true,
    trigger: ['input', 'blur'],
    validator: (_rule, value) => {
      const text = typeof value === 'string' ? value.trim() : ''
      if (!text) return new Error(requiredMessage)
      try {
        const url = new URL(text)
        return url.protocol === 'http:' || url.protocol === 'https:'
          ? true
          : new Error(invalidMessage)
      } catch {
        return new Error(invalidMessage)
      }
    },
  }
}

export async function validateForm(form: FormInst | null | undefined): Promise<boolean> {
  if (!form) return false
  try {
    await form.validate()
    return true
  } catch {
    return false
  }
}

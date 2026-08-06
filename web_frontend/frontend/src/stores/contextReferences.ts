import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { ContextReferenceInput } from '@/types/protocol'
import { MAX_RUNTIME_ATTACHMENTS } from '@/utils/attachments'

export const useContextReferenceStore = defineStore('contextReferences', () => {
  const activeScope = ref('global')
  const referencesByScope = ref<Record<string, ContextReferenceInput[]>>({})
  const activeReferences = computed(() => referencesByScope.value[activeScope.value] || [])

  function activate(scope: string): void {
    activeScope.value = normalizedScope(scope)
  }

  function add(reference: ContextReferenceInput, scope = activeScope.value): boolean {
    const key = normalizedScope(scope)
    const current = referencesByScope.value[key] || []
    const signature = referenceSignature(reference)
    if (current.some(item => referenceSignature(item) === signature)) return false
    if (current.length >= MAX_RUNTIME_ATTACHMENTS) return false
    referencesByScope.value = {
      ...referencesByScope.value,
      [key]: [...current, reference],
    }
    return true
  }

  function remove(index: number, scope = activeScope.value): void {
    const key = normalizedScope(scope)
    const current = referencesByScope.value[key] || []
    referencesByScope.value = {
      ...referencesByScope.value,
      [key]: current.filter((_item, itemIndex) => itemIndex !== index),
    }
  }

  function clear(scope = activeScope.value): void {
    const key = normalizedScope(scope)
    referencesByScope.value = { ...referencesByScope.value, [key]: [] }
  }

  function references(scope = activeScope.value): ContextReferenceInput[] {
    return referencesByScope.value[normalizedScope(scope)] || []
  }

  return { activeScope, activeReferences, activate, add, remove, clear, references }
})

function normalizedScope(scope: string): string {
  return String(scope || '').trim() || 'global'
}

function referenceSignature(reference: ContextReferenceInput): string {
  return [reference.source_kind, reference.name, reference.content || ''].join('\u0000')
}

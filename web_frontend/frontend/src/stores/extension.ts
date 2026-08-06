/**
 * Extension Store
 * 管理 MCP 服务器和 Skill 扩展
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ExtensionItemView, ToolPermissionsView } from '@/types/protocol'

export const useExtensionStore = defineStore('extension', () => {
  const items = ref<ExtensionItemView[]>([])
  const testResult = ref<any | null>(null)
  const toolPermissions = ref<ToolPermissionsView | null>(null)
  const skillHubResult = ref<any | null>(null)
  const bindings = ref<{ mcp_server_ids: string[]; skill_ids: string[] }>({
    mcp_server_ids: [],
    skill_ids: [],
  })

  const mcpItems = computed(() => {
    return items.value.filter((item) => item.kind === 'mcp')
  })

  const skillItems = computed(() => {
    return items.value.filter((item) => item.kind === 'skill')
  })

  function setItems(newItems: ExtensionItemView[]): void {
    items.value = newItems
  }

  function setTestResult(result: any): void {
    testResult.value = result
  }

  function setToolPermissions(value: ToolPermissionsView | null): void {
    toolPermissions.value = value
  }

  function setSkillHubResult(value: any | null): void {
    skillHubResult.value = value
  }

  function setBindings(value: any): void {
    bindings.value = {
      mcp_server_ids: Array.isArray(value?.mcp_server_ids) ? value.mcp_server_ids.map(String) : [],
      skill_ids: Array.isArray(value?.skill_ids) ? value.skill_ids.map(String) : [],
    }
  }

  function reset(): void {
    items.value = []
    testResult.value = null
    toolPermissions.value = null
    skillHubResult.value = null
    setBindings(null)
  }

  return {
    items,
    testResult,
    toolPermissions,
    skillHubResult,
    bindings,
    mcpItems,
    skillItems,
    setItems,
    setTestResult,
    setToolPermissions,
    setSkillHubResult,
    setBindings,
    reset,
  }
})

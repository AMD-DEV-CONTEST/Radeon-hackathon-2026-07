<template>
  <div class="agent-package-list">
    <div class="list-header">
      <n-input
        v-model:value="searchQuery"
        :placeholder="t('agents.searchPlaceholder')"
        clearable
      >
        <template #prefix>
          <n-icon><Search /></n-icon>
        </template>
      </n-input>

      <n-space>
        <n-button
          v-if="selectedCount > 0"
          :loading="busyAction === 'delete'"
          @click="confirmDeletePackages(selectedPackages)"
        >
          {{ t('agents.deleteSelected', { count: selectedCount }) }}
        </n-button>
        <n-select
          v-model:value="filterStatus"
          :options="statusOptions"
          :placeholder="t('common.status')"
          style="width: 120px"
        />
        <n-button @click="handleRefresh">
          <template #icon>
            <n-icon><Refresh /></n-icon>
          </template>
          {{ t('common.refresh') }}
        </n-button>
      </n-space>
    </div>

    <div class="list-content">
      <n-empty
        v-if="filteredPackages.length === 0"
        :description="t('agents.empty')"
        class="manager-empty"
      >
        <template #icon>
          <n-icon size="56" class="manager-empty-icon">
            <Rocket />
          </n-icon>
        </template>
      </n-empty>

      <div v-else class="package-grid">
        <n-card
          v-for="pkg in filteredPackages"
          :key="pkg.package_id"
          hoverable
          class="package-card"
        >
          <div class="package-header">
            <n-checkbox
              class="package-select"
              :checked="selectedPackageIds.has(pkg.package_id)"
              :disabled="!isPackageDeletable(pkg)"
              @click.stop
              @update:checked="(checked) => setPackageSelected(pkg, checked)"
            />
            <n-avatar
              :size="44"
              :style="{ background: getPackageColor(pkg) }"
              class="package-avatar"
            >
              {{ getPackageInitial(pkg) }}
            </n-avatar>
            <div class="package-info">
              <n-text strong class="package-name">
                {{ pkg.agent_name || pkg.name || pkg.package_id }}
              </n-text>
              <div v-if="pkg.is_builtin || pkg.runtime_pattern_id" class="package-tags">
                <n-tag v-if="pkg.is_builtin" size="small" :bordered="false">
                  {{ t('agents.builtin') }}
                </n-tag>
                <n-tag v-if="pkg.runtime_pattern_id" size="small" :bordered="false">
                  {{ runtimePatternLabel(pkg.runtime_pattern_id) }}
                </n-tag>
              </div>
              <n-text depth="3" class="package-desc">
                {{ pkg.agent_description || t('common.noDescription') }}
              </n-text>
            </div>
          </div>

          <n-divider style="margin: 12px 0" />

          <div class="package-stats">
            <div class="stat-item">
              <n-icon size="14" class="stat-icon"><Build /></n-icon>
              <span class="stat-text">{{ t('agents.tools', { count: pkg.tool_count || 0 }) }}</span>
            </div>
            <div class="stat-item">
              <n-icon size="14" class="stat-icon"><ChatbubbleEllipses /></n-icon>
              <span class="stat-text">{{ t('agents.sessions', { count: pkg.session_count || 0 }) }}</span>
            </div>
          </div>

          <div class="package-actions">
            <n-button size="small" @click="handleViewDetails(pkg)">
              {{ t('common.details') }}
            </n-button>
            <n-button
              v-if="isPackageReady(pkg)"
              size="small"
              :loading="isInstanceBusy(pkg)"
              @click.stop="handleShutdownInstance(pkg)"
            >
              {{ t('common.close') }}
            </n-button>
            <n-button
              v-else
              size="small"
              :loading="isInstanceBusy(pkg) || isInstanceInitializing(pkg)"
              :disabled="isInstanceInitializing(pkg)"
              @click.stop="handleInitializeInstance(pkg)"
            >
              {{ t('agents.initialize') }}
            </n-button>
            <n-button
              size="small"
              type="primary"
              :disabled="!isPackageReady(pkg)"
              @click.stop="handleRun(pkg)"
            >
              {{ t('agents.run') }}
            </n-button>
            <n-dropdown :options="getPackageActions(pkg)" @select="(key) => handleAction(key, pkg)">
              <n-button size="small" quaternary circle>
                <n-icon><EllipsisHorizontal /></n-icon>
              </n-button>
            </n-dropdown>
          </div>

          <div class="package-footer">
            <n-tag v-if="pkg.status" size="small" :type="getStatusType(pkg.status)">
              {{ pkg.status }}
            </n-tag>
            <n-tag size="small" :type="getInstanceStatusType(pkg)">
              {{ instanceStatusLabel(pkg) }}
            </n-tag>
            <n-text depth="3" style="font-size: 11px">
              {{ formatTime(pkg.updated_at) }}
            </n-text>
          </div>
        </n-card>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAvatar,
  NButton,
  NCard,
  NCheckbox,
  NDivider,
  NDropdown,
  NEmpty,
  NIcon,
  NInput,
  NSelect,
  NSpace,
  NTag,
  NText,
  useDialog,
} from 'naive-ui'
import { Search, Refresh, Build, ChatbubbleEllipses, EllipsisHorizontal, Rocket } from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'
import { useUiStore } from '@/stores/ui'
import { useCommand } from '@/composables/useCommand'
import { useAgentSessionNavigation } from '@/composables/agent/useAgentSessionNavigation'
import type { AgentPackageView } from '@/stores/agent'
import {
  formatPackageDate,
  instanceStatusLabel as packageInstanceStatusLabel,
  instanceStatusType as packageInstanceStatusType,
  isInstanceInitializing as packageInstanceInitializing,
  isPackageReady as packageInstanceReady,
  packageColor as getPackageColor,
  packageDisplayName,
  packageInitial as getPackageInitial,
  statusType as getStatusType,
} from './agentPackagePresentation'

const agentStore = useAgentStore()
const router = useRouter()
const uiStore = useUiStore()
const commands = useCommand()
const { openPackageAgentChat } = useAgentSessionNavigation()
const dialog = useDialog()
const { locale, t } = useI18n()

const searchQuery = ref('')
const filterStatus = ref('')
const selectedPackageIds = ref<Set<string>>(new Set())
const busyAction = ref<'delete' | 'export' | 'instance' | null>(null)
const busyInstancePackageId = ref<string | null>(null)

const statusOptions = computed(() => [
  { label: t('common.all'), value: '' },
  { label: t('agents.statusReady'), value: 'ready' },
  { label: t('agents.statusRunning'), value: 'running' },
])

const filteredPackages = computed(() => {
  let packages = agentStore.agentPackages

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    packages = packages.filter(
      (p) =>
        p.agent_name?.toLowerCase().includes(query) ||
        p.name?.toLowerCase().includes(query) ||
        p.agent_description?.toLowerCase().includes(query)
    )
  }

  if (filterStatus.value) {
    packages = packages.filter((p) => p.status === filterStatus.value)
  }

  return packages
})
const selectedPackages = computed(() => {
  return agentStore.agentPackages.filter(
    (pkg) => selectedPackageIds.value.has(pkg.package_id) && isPackageDeletable(pkg),
  )
})

function runtimePatternLabel(patternId: string): string {
  return {
    react_agent: 'ReAct',
    plan_and_execute: 'Plan and Execute',
  }[patternId] || patternId
}
const selectedCount = computed(() => selectedPackages.value.length)

function handleRefresh() {
  commands.listAgentPackages()
  commands.listAgentPackageInstances()
}

function handleViewDetails(pkg: AgentPackageView) {
  agentStore.selectPackage(pkg.package_id)
  void router.push({ name: 'AgentDetail', params: { packageId: pkg.package_id } })
}

function handleRun(pkg: AgentPackageView) {
  if (!isPackageReady(pkg)) {
    uiStore.addNotification({
      type: 'warning',
      title: t('agents.instanceNotReadyTitle'),
      message: t('agents.instanceNotReadyMessage'),
      duration: 3000,
    })
    return
  }
  void openPackageAgentChat(pkg.package_id)
}

async function handleInitializeInstance(pkg: AgentPackageView) {
  if (busyAction.value) return
  busyAction.value = 'instance'
  busyInstancePackageId.value = pkg.package_id
  try {
    await commands.initializeAgentPackage(pkg.package_id)
  } finally {
    busyAction.value = null
    busyInstancePackageId.value = null
  }
}

async function handleShutdownInstance(pkg: AgentPackageView) {
  if (busyAction.value) return
  busyAction.value = 'instance'
  busyInstancePackageId.value = pkg.package_id
  try {
    await commands.shutdownAgentPackageInstance(pkg.package_id)
  } finally {
    busyAction.value = null
    busyInstancePackageId.value = null
  }
}

function handleAction(key: string, pkg: AgentPackageView) {
  switch (key) {
    case 'delete':
      if (!isPackageDeletable(pkg)) return
      confirmDeletePackages([pkg])
      break
    case 'export':
      if (!isPackageExportable(pkg)) return
      void handleExport(pkg)
      break
  }
}

function getPackageActions(pkg: AgentPackageView) {
  return [
    { label: t('common.export'), key: 'export', disabled: !isPackageExportable(pkg) },
    { label: t('common.delete'), key: 'delete', disabled: !isPackageDeletable(pkg) },
  ]
}

function isPackageDeletable(pkg: AgentPackageView): boolean {
  return pkg.capabilities?.deletable !== false
}

function isPackageExportable(pkg: AgentPackageView): boolean {
  return pkg.capabilities?.exportable !== false
}

function setPackageSelected(pkg: AgentPackageView, checked: boolean) {
  if (!isPackageDeletable(pkg)) return
  const next = new Set(selectedPackageIds.value)
  if (checked) {
    next.add(pkg.package_id)
  } else {
    next.delete(pkg.package_id)
  }
  selectedPackageIds.value = next
}

function confirmDeletePackages(packages: AgentPackageView[]) {
  const targets = packages.filter((pkg) => pkg.package_id && isPackageDeletable(pkg))
  if (targets.length === 0 || busyAction.value) return
  const names = targets.map((pkg) => packageDisplayName(pkg, t)).join('、')
  dialog.warning({
    title: targets.length > 1 ? t('agents.confirmBulkDeleteTitle') : t('agents.confirmDeleteTitle'),
    content: t('agents.confirmDeleteContent', { names }),
    positiveText: targets.length > 1 ? t('agents.confirmBulkPositive', { count: targets.length }) : t('common.delete'),
    negativeText: t('common.cancel'),
    onPositiveClick: () => {
      void deletePackages(targets)
    },
  })
}

async function deletePackages(packages: AgentPackageView[]) {
  busyAction.value = 'delete'
  let deleted = 0
  try {
    for (const pkg of packages) {
      const event = await commands.deleteAgentPackage(pkg.package_id)
      if (event) {
        deleted += 1
        setPackageSelected(pkg, false)
      }
    }
    if (deleted > 0) {
      uiStore.addNotification({
        type: 'success',
        title: t('agents.deleteCompleteTitle'),
        message: t('agents.deleteCompleteMessage', { count: deleted }),
        duration: 3000,
      })
    }
  } finally {
    busyAction.value = null
  }
}

async function handleExport(pkg: AgentPackageView) {
  if (busyAction.value) return
  busyAction.value = 'export'
  try {
    await commands.exportAgentPackage(pkg)
  } finally {
    busyAction.value = null
  }
}

function packageInstance(pkg: AgentPackageView) {
  return agentStore.packageInstance(pkg.package_id)
}

function isPackageReady(pkg: AgentPackageView): boolean {
  return packageInstanceReady(packageInstance(pkg))
}

function isInstanceInitializing(pkg: AgentPackageView): boolean {
  return packageInstanceInitializing(packageInstance(pkg))
}

function isInstanceBusy(pkg: AgentPackageView): boolean {
  return busyAction.value === 'instance' && busyInstancePackageId.value === pkg.package_id
}

function instanceStatusLabel(pkg: AgentPackageView): string {
  return packageInstanceStatusLabel(packageInstance(pkg), t)
}

function formatTime(timestamp: string | null): string {
  return formatPackageDate(timestamp, locale.value, t)
}

function getInstanceStatusType(pkg: AgentPackageView): 'default' | 'success' | 'warning' | 'error' | 'info' {
  return packageInstanceStatusType(packageInstance(pkg))
}

onMounted(() => {
  handleRefresh()
})
</script>

<style scoped>
.agent-package-list {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: var(--app-space-xl);
  max-width: var(--app-content-max-width);
  width: 100%;
  margin: 0 auto;
}

.list-header {
  display: flex;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-xl);
  flex-wrap: wrap;
}

.list-content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  margin: 0 calc(var(--app-space-xs) * -1);
  padding: 0 var(--app-space-xs) var(--app-space-lg);
}

.package-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--app-space-lg);
}

.package-card {
  transition: transform var(--app-transition-spring), box-shadow var(--app-transition-base);
  border-radius: var(--app-radius-lg);
  animation: app-fade-in-up 0.5s var(--app-transition-spring) both;
  position: relative;
  will-change: transform;
}

.package-card:nth-child(1) { animation-delay: 0.08s; }
.package-card:nth-child(2) { animation-delay: 0.16s; }
.package-card:nth-child(3) { animation-delay: 0.24s; }
.package-card:nth-child(4) { animation-delay: 0.32s; }
.package-card:nth-child(5) { animation-delay: 0.40s; }
.package-card:nth-child(6) { animation-delay: 0.48s; }
.package-card:nth-child(n+7) { animation-delay: 0.56s; }

.package-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--app-shadow-lg);
}

.package-card:active {
  transform: translateY(-2px) scale(0.98);
  transition-duration: 0.12s;
}

.package-header {
  display: flex;
  gap: var(--app-space-md);
  align-items: flex-start;
}

.package-select {
  margin-top: 2px;
  flex-shrink: 0;
}

.package-avatar {
  flex-shrink: 0;
}

.package-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xxs);
  min-width: 0;
}

.package-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--app-space-xs);
}

.package-name {
  display: block;
  width: 100%;
  white-space: normal;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: var(--app-leading-tight);
  color: var(--app-text-strong);
}

.package-desc {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: var(--app-font-sm);
  line-height: 1.4;
  min-height: calc(1.4em * 2);
}

.package-stats {
  display: flex;
  gap: var(--app-space-lg);
  margin: var(--app-space-md) 0;
}

.stat-item {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-xs);
  font-size: var(--app-font-sm);
  color: var(--app-text-secondary);
  line-height: 1.4;
  min-width: 0;
}

.stat-icon {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.stat-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.package-actions {
  display: flex;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
  flex-wrap: wrap;
}

.package-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
  padding-top: var(--app-space-md);
  border-top: 1px solid var(--app-divider);
  flex-wrap: wrap;
}

.manager-empty {
  margin-top: 12vh;
  animation: app-fade-in-up 0.4s cubic-bezier(0.16, 1, 0.3, 1) both;
}

.manager-empty-icon {
  display: block;
  color: var(--app-text-muted);
  opacity: 0.55;
  line-height: 1;
}

@media (max-width: 640px) {
  .agent-package-list {
    padding: var(--app-space-md);
  }
  .package-grid {
    grid-template-columns: 1fr;
    gap: var(--app-space-md);
  }
}
</style>

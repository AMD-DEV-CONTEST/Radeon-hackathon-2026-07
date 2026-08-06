<template>
  <div class="agent-detail-view">
    <header class="detail-view-header">
      <n-button quaternary class="back-button" @click="returnToList">
        <template #icon>
          <n-icon><ArrowBack /></n-icon>
        </template>
        {{ t('agents.backToList') }}
      </n-button>
      <div class="detail-view-heading">
        <h1>{{ t('agentDetail.title') }}</h1>
        <span v-if="agentPackage">{{ packageDisplayName(agentPackage, t) }}</span>
      </div>
    </header>

    <div class="detail-view-body">
      <AgentPackageDetailDrawer
        v-if="agentPackage"
        embedded
        :agent-package="agentPackage"
        :instance="packageInstance"
        @package-updated="agentStore.addPackage"
      />
      <n-empty v-else :description="t('agents.detailNotFound')" class="detail-empty">
        <template #extra>
          <n-button @click="returnToList">{{ t('agents.backToList') }}</n-button>
        </template>
      </n-empty>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NEmpty, NIcon } from 'naive-ui'
import { ArrowBack } from '@/components/icons'
import AgentPackageDetailDrawer from '@/components/agent/AgentPackageDetailDrawer.vue'
import { packageDisplayName } from '@/components/agent/agentPackagePresentation'
import { useCommand } from '@/composables/useCommand'
import { useI18n } from '@/composables/useI18n'
import { useAgentStore } from '@/stores/agent'

const route = useRoute()
const router = useRouter()
const commands = useCommand()
const agentStore = useAgentStore()
const { t } = useI18n()

const packageId = computed(() => String(route.params.packageId || '').trim())
const agentPackage = computed(() => (
  agentStore.agentPackages.find((pkg) => pkg.package_id === packageId.value) || null
))
const packageInstance = computed(() => agentStore.packageInstance(packageId.value))

watch(
  [packageId, agentPackage],
  ([currentPackageId, currentPackage]) => {
    if (currentPackageId && currentPackage) agentStore.selectPackage(currentPackageId)
  },
  { immediate: true },
)

onMounted(() => {
  commands.listAgentPackages()
  commands.listAgentPackageInstances()
})

function returnToList(): void {
  void router.push({ name: 'Agents' })
}
</script>

<style scoped>
.agent-detail-view {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--app-surface);
}

.detail-view-header {
  display: flex;
  align-items: center;
  gap: var(--app-space-lg);
  padding: var(--app-space-lg) var(--app-space-xl);
  border-bottom: 1px solid var(--app-divider);
}

.back-button {
  flex: 0 0 auto;
}

.detail-view-heading {
  min-width: 0;
}

.detail-view-heading h1 {
  margin: 0;
  color: var(--app-text-strong);
  font-size: var(--app-font-lg);
  font-weight: 600;
}

.detail-view-heading span {
  display: block;
  margin-top: var(--app-space-xxs);
  color: var(--app-text-secondary);
  overflow-wrap: anywhere;
}

.detail-view-body {
  flex: 1;
  min-height: 0;
  width: 100%;
  max-width: var(--app-content-max-width);
  margin: 0 auto;
}

.detail-empty {
  margin-top: 18vh;
}

@media (max-width: 640px) {
  .detail-view-header {
    align-items: flex-start;
    gap: var(--app-space-sm);
    padding: var(--app-space-md);
  }
}
</style>

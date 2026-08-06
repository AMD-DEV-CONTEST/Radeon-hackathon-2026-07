<template>
  <n-drawer v-model:show="show" :width="420" placement="right" @after-enter="markAllRead">
    <n-drawer-content>
      <template #header>
        <div class="drawer-header">
          <span>{{ t('scheduler.activityTitle') }}</span>
        <n-button size="small" @click="openSchedulerPage">{{ t('scheduler.manageTasks') }}</n-button>
        </div>
      </template>

      <div v-if="notices.length" class="notice-list">
        <SchedulerRunStatusCard
          v-for="notice in notices"
          :key="notice.id"
          :notice="notice"
        />
      </div>
      <n-empty v-else :description="t('scheduler.noRecentActivity')" class="empty-state" />
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NDrawer, NDrawerContent, NEmpty } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useRuntimeStore } from '@/stores/runtime'
import { useUiStore } from '@/stores/ui'
import SchedulerRunStatusCard from './SchedulerRunStatusCard.vue'

const router = useRouter()
const runtimeStore = useRuntimeStore()
const uiStore = useUiStore()
const { t } = useI18n()

const show = computed({
  get: () => uiStore.schedulerActivityDrawerOpen,
  set: (value: boolean) => {
    if (!value) uiStore.closeSchedulerActivityDrawer()
  },
})
const notices = computed(() => runtimeStore.schedulerRunNotices)

function markAllRead() {
  notices.value.forEach((notice) => runtimeStore.markSchedulerNoticeRead(notice.id))
}

function openSchedulerPage() {
  uiStore.closeSchedulerActivityDrawer()
  void router.push('/scheduler')
}
</script>

<style scoped>
.notice-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.drawer-header {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
}

.notice-list :deep(.scheduler-run-card) {
  margin: 0;
}

.empty-state {
  margin-top: 72px;
}
</style>

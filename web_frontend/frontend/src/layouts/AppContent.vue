<template>
  <div class="app-layout">
    <!-- 全局加载条 -->
    <n-loading-bar-provider>
      <AppLoadingBar />
    </n-loading-bar-provider>

    <!-- 主应用区域 -->
    <div class="app-container">
      <!-- 顶部导航 -->
      <AppHeader />

      <!-- 主内容区 -->
      <div class="app-main">
        <main class="app-content">
          <router-view v-slot="{ Component }">
            <transition name="fade" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </main>
      </div>
    </div>

    <!-- 全局通知 -->
    <n-notification-provider>
      <AppNotifications />
      <TaskNotificationManager v-if="runtimeServicesEnabled" />
    </n-notification-provider>

    <!-- 设置抽屉 -->
    <SettingsDrawer v-model:show="uiStore.settingsDrawerOpen" />

    <!-- 调试抽屉 -->
    <DebugDrawer v-model:show="uiStore.debugDrawerOpen" />

    <SchedulerActivityDrawer />

    <!-- SSE 事件流初始化 -->
    <EventStreamManager v-if="runtimeServicesEnabled" />
  </div>
</template>

<script setup lang="ts">
import { useUiStore } from '@/stores/ui'
import AppHeader from '@/components/common/AppHeader.vue'
import AppLoadingBar from '@/components/common/AppLoadingBar.vue'
import AppNotifications from '@/components/common/AppNotifications.vue'
import TaskNotificationManager from '@/components/common/TaskNotificationManager.vue'
import SettingsDrawer from '@/components/common/SettingsDrawer.vue'
import DebugDrawer from '@/components/common/DebugDrawer.vue'
import SchedulerActivityDrawer from '@/components/scheduler/SchedulerActivityDrawer.vue'
import EventStreamManager from '@/components/common/EventStreamManager.vue'

withDefaults(defineProps<{
  runtimeServicesEnabled?: boolean
}>(), {
  runtimeServicesEnabled: true,
})

const uiStore = useUiStore()
</script>

<style scoped>
.app-layout {
  height: 100vh;
  width: 100vw;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--app-surface);
  color: var(--app-text);
}

.app-container {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.app-main {
  flex: 1;
  display: flex;
  min-height: 0;
  position: relative;
}

.app-content {
  flex: 1 1 0;
  min-width: 0;
  overflow-y: auto;
  background: var(--app-surface);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

</style>

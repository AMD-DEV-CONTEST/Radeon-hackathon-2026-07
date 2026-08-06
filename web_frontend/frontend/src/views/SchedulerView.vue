<template>
  <div class="scheduler-view">
    <SchedulerManager />
  </div>
</template>

<script setup lang="ts">
import SchedulerManager from '@/components/scheduler/SchedulerManager.vue'
</script>

<style scoped>
.scheduler-view {
  height: 100%;
  background: var(--app-surface);
}
</style>

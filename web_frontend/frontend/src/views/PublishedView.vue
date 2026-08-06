<template>
  <div class="published-view">
    <AgentPackageList />
  </div>
</template>

<script setup lang="ts">
import AgentPackageList from '@/components/agent/AgentPackageList.vue'
</script>

<style scoped>
.published-view {
  height: 100%;
  background: var(--app-surface);
}
</style>

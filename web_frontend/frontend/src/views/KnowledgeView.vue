<template>
  <div class="knowledge-view">
    <KnowledgeManager />
  </div>
</template>

<script setup lang="ts">
import KnowledgeManager from '@/components/knowledge/KnowledgeManager.vue'
</script>

<style scoped>
.knowledge-view {
  height: 100%;
  background: var(--app-surface);
}
</style>

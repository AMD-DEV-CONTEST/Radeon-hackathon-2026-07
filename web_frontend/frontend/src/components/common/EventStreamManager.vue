<template>
  <div style="display: none">
    <!-- SSE 事件流管理器，无 UI -->
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useEventStream } from '@/composables/useEventStream'

// 初始化后端事件流连接
const { connect } = useEventStream()

onMounted(() => {
  connect()
})
</script>

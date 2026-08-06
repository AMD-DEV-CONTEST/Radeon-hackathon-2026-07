<template>
  <span aria-hidden="true" />
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  disposeTaskNotifications,
  initializeTaskNotifications,
} from '@/services/taskNotifications'

const router = useRouter()

onMounted(() => {
  void initializeTaskNotifications(router)
})

onBeforeUnmount(() => {
  disposeTaskNotifications()
})
</script>

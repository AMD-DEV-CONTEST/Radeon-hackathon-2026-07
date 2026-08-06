<template>
  <div>
    <!-- 使用 Naive UI 的通知系统 -->
  </div>
</template>

<script setup lang="ts">
import { h, watch } from 'vue'
import { NButton, useNotification } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'

const notification = useNotification()
const uiStore = useUiStore()
const { t } = useI18n()
const displayedNotificationIds = new Set<string>()

// 监听通知变化
watch(
  () => uiStore.notifications.map((item) => item.id).join('|'),
  (notifications) => {
    if (!notifications) return
    uiStore.notifications.forEach((item) => {
      if (displayedNotificationIds.has(item.id)) return
      displayedNotificationIds.add(item.id)
      let closeNotification: (() => void) | null = null
      const handleAction = () => {
        item.onAction?.()
        uiStore.removeNotification(item.id)
        closeNotification?.()
      }
      const notificationRef = notification[item.type]({
        title: item.title,
        content: item.message,
        duration: item.duration ?? 5000,
        action: item.onAction
          ? () => h(
              NButton,
              {
                text: true,
                size: 'small',
                onClick: handleAction,
              },
              { default: () => item.actionLabel || t('common.view') }
            )
          : undefined,
        onClose: () => {
          uiStore.removeNotification(item.id)
        },
      })
      closeNotification = notificationRef.destroy
    })
  },
  { immediate: true }
)
</script>

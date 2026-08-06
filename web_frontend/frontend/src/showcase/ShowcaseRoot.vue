<template>
  <n-config-provider
    :theme-overrides="themeOverrides"
    :locale="zhCN"
    :date-locale="dateZhCN"
  >
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
          <div class="showcase-root" :class="{ 'is-resetting': resetting }">
            <AppContent :runtime-services-enabled="false" />
          </div>
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { dateZhCN, zhCN } from 'naive-ui'
import AppContent from '@/layouts/AppContent.vue'
import { applyPaletteToRoot } from '@/theme/cssVariables'
import { createThemeOverrides } from '@/theme/naiveTheme'
import { getPalette } from '@/theme/palette'
import { useUiStore } from '@/stores/ui'
import { useShowcaseDirector } from './director'

const uiStore = useUiStore()
const palette = computed(() => getPalette(false))
const themeOverrides = computed(() => createThemeOverrides(palette.value))
const resetting = ref(false)
const director = useShowcaseDirector({
  onResetTransition: (active) => {
    resetting.value = active
  },
})

uiStore.setThemeMode('light')
applyPaletteToRoot(palette.value)
document.documentElement.dataset.theme = 'light'
document.documentElement.lang = 'zh-CN'

onMounted(() => director.start())
onBeforeUnmount(() => director.stop())
</script>

<style scoped>
.showcase-root {
  width: 100%;
  height: 100%;
  opacity: 1;
  transition: opacity 520ms ease;
  pointer-events: none;
  user-select: none;
}

.showcase-root.is-resetting {
  opacity: 0;
}
</style>

<template>
  <n-config-provider
    :theme="naiveTheme"
    :theme-overrides="themeOverrides"
    :locale="naiveLocale"
    :date-locale="naiveDateLocale"
  >
    <n-message-provider>
      <n-notification-provider>
        <n-dialog-provider>
          <n-loading-bar-provider>
            <AppContent v-if="startupStore.ready" />
            <SelectionReferenceMenu v-if="startupStore.ready" />
            <AppUpdateDialog />
            <n-modal
              :show="!startupStore.ready"
              :mask-closable="false"
              :close-on-esc="false"
              preset="card"
              class="startup-dialog"
              style="width: min(420px, calc(100vw - 32px)); max-width: 420px"
              :title="t('startup.title')"
            >
              <div class="startup-dialog-content" role="status" aria-live="polite">
                <n-spin v-if="startupStore.initializing" size="large" />
                <p>
                  {{ startupStore.initializing ? t('startup.initializing') : t('startup.failed') }}
                </p>
                <n-text v-if="startupStore.error" type="error" class="startup-error">
                  {{ startupStore.error }}
                </n-text>
                <n-button
                  v-if="startupStore.status === 'failed'"
                  type="primary"
                  @click="startupStore.retry"
                >
                  {{ t('startup.retry') }}
                </n-button>
              </div>
            </n-modal>
          </n-loading-bar-provider>
        </n-dialog-provider>
      </n-notification-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { darkTheme, dateEnUS, dateZhCN, enUS, zhCN } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'
import { routeTitleKey } from '@/i18n'
import { useI18n } from '@/composables/useI18n'
import { useUiStore } from '@/stores/ui'
import { useStartupStore } from '@/stores/startup'
import { getPalette } from '@/theme/palette'
import { applyPaletteToRoot } from '@/theme/cssVariables'
import { createThemeOverrides } from '@/theme/naiveTheme'
import AppContent from '@/layouts/AppContent.vue'
import SelectionReferenceMenu from '@/components/chat/SelectionReferenceMenu.vue'
import AppUpdateDialog from '@/components/common/AppUpdateDialog.vue'

const route = useRoute()
const { locale, t } = useI18n()
const uiStore = useUiStore()
const startupStore = useStartupStore()

const isDark = computed(() => uiStore.actualTheme === 'dark')
const palette = computed(() => getPalette(isDark.value))
const naiveTheme = computed(() => (isDark.value ? darkTheme : null))
const naiveLocale = computed(() => (locale.value === 'zh-CN' ? zhCN : enUS))
const naiveDateLocale = computed(() => (locale.value === 'zh-CN' ? dateZhCN : dateEnUS))
const themeOverrides = computed<GlobalThemeOverrides>(() => createThemeOverrides(palette.value))

// 主题变化时同步注入 CSS 变量到 :root，并给 <html> 打上主题标记
watchEffect(() => {
  applyPaletteToRoot(palette.value)
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = isDark.value ? 'dark' : 'light'
  }
})

watchEffect(() => {
  if (typeof document !== 'undefined') {
    document.title = `${t(routeTitleKey(route.name))} - ${t('app.name')}`
  }
})

</script>

<style scoped>
.startup-dialog {
  width: min(420px, calc(100vw - 32px));
}

.startup-dialog-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 12px 0 4px;
  text-align: center;
}

.startup-dialog-content p {
  margin: 0;
  color: var(--app-text-secondary);
}

.startup-error {
  max-width: 100%;
  overflow-wrap: anywhere;
}
</style>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html,
body,
#app {
  height: 100%;
  width: 100%;
  overflow: hidden;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol',
    'Noto Color Emoji';
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--app-text);
  background: var(--app-surface);
  transition: background 0.3s var(--app-transition-fluid), color 0.3s var(--app-transition-fluid);
}

/* 背景微渐变增加呼吸感 */
:root[data-theme='light'] body {
  background: linear-gradient(180deg, #fbfbfd 0%, #f5f5f7 100%);
}

:root[data-theme='dark'] body {
  background: linear-gradient(180deg, #000000 0%, #1c1c1e 100%);
}

code {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Roboto Mono', Consolas, 'Courier New', monospace;
}

/* 全局滚动条美化 */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: var(--app-border);
  border-radius: var(--app-radius-pill);
  border: 2px solid transparent;
  background-clip: padding-box;
  transition: background var(--app-transition-base);
}

::-webkit-scrollbar-thumb:hover {
  background: var(--app-border-hover);
  background-clip: padding-box;
  border: 2px solid transparent;
}

/* 平滑滚动 */
html {
  scroll-behavior: smooth;
}

::-webkit-scrollbar-corner {
  background: transparent;
}

/* 可视化焦点环，键盘导航更友好 */
:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
  border-radius: var(--app-radius-sm);
}

/* 输入框、按钮已有 Naive 样式，避免额外描边 */
.n-input:focus-visible,
.n-button:focus-visible,
.n-base-selection:focus-visible {
  outline: none;
}

/* 通用工具类 */
.app-scroll-y {
  overflow-y: auto;
  overflow-x: hidden;
}

.app-elevated {
  background: var(--app-surface-elevated);
  border: none;
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-md);
}

/* 液态玻璃卡片（无边框，纯阴影）*/
.app-glass-card {
  background: var(--app-glass-background);
  backdrop-filter: var(--app-glass-blur);
  -webkit-backdrop-filter: var(--app-glass-blur);
  border: none;
  border-radius: var(--app-radius-lg);
  box-shadow: var(--app-shadow-md);
  position: relative;
  overflow: hidden;
}

/* 不支持 backdrop-filter 时的降级 */
@supports not (backdrop-filter: blur(1px)) {
  .app-glass-card {
    background: var(--app-surface-elevated);
  }
}

/* 骨架条基础动画 */
@keyframes app-skeleton-shimmer {
  0% { background-position: -400px 0; }
  100% { background-position: 400px 0; }
}

.app-skeleton {
  background: linear-gradient(
    90deg,
    var(--app-surface-muted) 0%,
    var(--app-surface-pressed) 50%,
    var(--app-surface-muted) 100%
  );
  background-size: 400px 100%;
  animation: app-skeleton-shimmer 1.4s ease-in-out infinite;
  border-radius: var(--app-radius-md);
}

/* 全局进入动画 */
@keyframes app-fade-in-up {
  from {
    opacity: 0;
    transform: translateY(12px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@keyframes app-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}

@keyframes app-pop-in {
  0% {
    opacity: 0;
    transform: scale(0.92);
  }
  60% {
    opacity: 1;
    transform: scale(1.02);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes app-pulse-soft {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.55; }
}

/* 液态玻璃感：边框高光扫过 */
@keyframes glass-border-sweep {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* 流动渐变（streaming 状态） */
@keyframes glass-gradient-flow {
  0% {
    background-position: 0% 50%;
  }
  50% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0% 50%;
  }
}

/* streaming 光标呼吸 */
@keyframes streaming-caret-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

/* 运行状态光晕 */
@keyframes run-status-halo {
  0%, 100% {
    box-shadow: 0 0 0 0 var(--app-success);
  }
  50% {
    box-shadow: 0 0 0 4px transparent;
  }
}

.app-fade-in-up {
  animation: app-fade-in-up 0.4s var(--app-transition-spring) both;
}

.app-fade-in {
  animation: app-fade-in 0.3s var(--app-transition-fluid) both;
}

.app-pop-in {
  animation: app-pop-in 0.35s var(--app-transition-spring) both;
}

.app-pulse-soft {
  animation: app-pulse-soft 2s ease-in-out infinite;
}

/* 尊重用户的减少动画偏好 */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}

/* 按钮按压反馈 */
.n-button:active {
  transform: scale(0.96);
  transition-duration: 0.1s;
}

/* 输入框 focus glow */
.n-input:focus-within,
.n-input-number:focus-within,
.n-select:focus-within,
.n-base-selection:focus-within {
  box-shadow: 0 0 0 3px var(--app-focus-shadow) !important;
}

/* 全局 n-empty 增强 */
.n-empty {
  padding: var(--app-space-xl) var(--app-space-lg);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--app-space-md);
}

.n-empty .n-empty__icon {
  opacity: 0.5;
  margin-bottom: 0;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.n-empty .n-empty__description {
  color: var(--app-text-secondary);
  font-size: var(--app-font-md);
  line-height: var(--app-leading-normal);
  margin-top: 0;
  text-align: center;
}

.n-empty .n-empty__extra {
  margin-top: var(--app-space-sm);
}

/* 全局 Naive UI 组件圆角统一 */
.n-button {
  border-radius: var(--app-radius-md) !important;
}

.n-input,
.n-input-number,
.n-input__input-el,
.n-input__textarea-el {
  border-radius: var(--app-radius-md) !important;
}

.n-select,
.n-base-selection,
.n-base-select-menu,
.n-select-menu {
  border-radius: var(--app-radius-md) !important;
}

.n-dropdown,
.n-dropdown-menu {
  border-radius: var(--app-radius-md) !important;
}

.n-popover,
.n-modal,
.n-card {
  border-radius: var(--app-radius-lg) !important;
}

.n-tag {
  border-radius: var(--app-radius-sm) !important;
}

.n-switch {
  border-radius: var(--app-radius-pill) !important;
}

.n-checkbox,
.n-radio {
  border-radius: var(--app-radius-sm) !important;
}

.n-radio-button {
  border-radius: var(--app-radius-md) !important;
}

.soft-segmented-control.n-radio-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-muted);
}

.soft-segmented-control .n-radio-group__splitor {
  display: none !important;
}

.soft-segmented-control .n-radio-button {
  border: 0 !important;
  border-radius: calc(var(--app-radius-lg) - 5px) !important;
  background: transparent !important;
  color: var(--app-text-secondary) !important;
}

.soft-segmented-control .n-radio-button:first-child,
.soft-segmented-control .n-radio-button:last-child {
  border-left: 0 !important;
  border-right: 0 !important;
}

.soft-segmented-control .n-radio-button__state-border {
  inset: 0 !important;
  border-radius: inherit !important;
  box-shadow: none !important;
}

.soft-segmented-control .n-radio-button:not(.n-radio-button--disabled):not(.n-radio-button--checked):hover {
  background: var(--app-surface-hover) !important;
  color: var(--app-text) !important;
}

.soft-segmented-control .n-radio-button--checked {
  background: var(--app-surface) !important;
  color: var(--app-text-strong) !important;
  box-shadow: var(--app-shadow-sm);
}

.soft-segmented-control .n-radio-button--focus .n-radio-button__state-border {
  box-shadow: 0 0 0 2px var(--app-focus-shadow) !important;
}

.n-menu-item,
.n-menu-item-content {
  border-radius: var(--app-radius-md) !important;
}

.n-drawer,
.n-drawer-content {
  border-radius: var(--app-radius-lg) !important;
}

.n-badge {
  border-radius: var(--app-radius-pill) !important;
}

.n-tooltip {
  border-radius: var(--app-radius-sm) !important;
}

/* 将组件主题变量稳定映射到按钮状态，避免外层文本色覆盖基础态 */
.n-button {
  color: var(--n-text-color);
  background-color: var(--n-color);
}

.n-button:not(.n-button--disabled):focus {
  color: var(--n-text-color-focus);
  background-color: var(--n-color-focus);
}

.n-button:not(.n-button--disabled):hover {
  color: var(--n-text-color-hover);
  background-color: var(--n-color-hover);
}

.n-button:not(.n-button--disabled):active,
.n-button.n-button--pressed {
  color: var(--n-text-color-pressed);
  background-color: var(--n-color-pressed);
}

.n-button.n-button--disabled {
  color: var(--n-text-color-disabled);
  background-color: var(--n-color-disabled);
}

</style>

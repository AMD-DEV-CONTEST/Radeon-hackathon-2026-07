<template>
  <n-modal
    :show="show"
    preset="card"
    class="capability-library-modal"
    :bordered="false"
    :title="t('capabilityLibrary.title')"
    @update:show="emit('update:show', $event)"
  >
    <p class="library-intro">{{ t('capabilityLibrary.description') }}</p>

    <section class="library-section">
      <div class="section-heading">
        <span>{{ t('capabilityLibrary.agents') }}</span>
        <small>{{ t('capabilityLibrary.agentsHint') }}</small>
      </div>
      <div class="library-grid agent-grid">
        <button class="library-entry featured" type="button" @click="openRoute('Agents')">
          <n-icon size="24"><CubeOutline /></n-icon>
          <span><strong>{{ t('capabilityLibrary.localAgents') }}</strong><small>{{ t('capabilityLibrary.localAgentsHint') }}</small></span>
          <n-icon class="entry-arrow"><ArrowForward /></n-icon>
        </button>
        <button class="library-entry" type="button" @click="openRoute('Agents')">
          <n-icon size="22"><CheckmarkCircleOutline /></n-icon>
          <span><strong>{{ t('route.agents') }}</strong><small>{{ t('capabilityLibrary.publishedHint') }}</small></span>
          <n-icon class="entry-arrow"><ArrowForward /></n-icon>
        </button>
      </div>
    </section>

    <section class="library-section">
      <div class="section-heading">
        <span>{{ t('capabilityLibrary.resources') }}</span>
        <small>{{ t('capabilityLibrary.resourcesHint') }}</small>
      </div>
      <div class="library-grid resource-grid">
        <button class="library-entry compact" type="button" @click="openRoute('Extensions')">
          <n-icon size="20"><ExtensionPuzzleOutline /></n-icon>
          <span><strong>Skill & MCP</strong><small>{{ t('capabilityLibrary.extensionsHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openRoute('Knowledge')">
          <n-icon size="20"><LibraryOutline /></n-icon>
          <span><strong>{{ t('route.knowledge') }}</strong><small>{{ t('capabilityLibrary.knowledgeHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openRoute('Scheduler')">
          <n-icon size="20"><TimeOutline /></n-icon>
          <span><strong>{{ t('route.scheduler') }}</strong><small>{{ t('capabilityLibrary.schedulerHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openRoute('ModelPool')">
          <n-icon size="20"><LayersOutline /></n-icon>
          <span><strong>{{ t('route.modelPool') }}</strong><small>{{ t('capabilityLibrary.modelsHint') }}</small></span>
        </button>
        <button class="library-entry compact" type="button" @click="openRoute('Benchmarks')">
          <n-icon size="20"><SpeedometerOutline /></n-icon>
          <span><strong>{{ t('route.benchmarks') }}</strong><small>{{ t('benchmark.subtitle') }}</small></span>
        </button>
      </div>
    </section>
  </n-modal>
</template>

<script setup lang="ts">
import { NIcon, NModal } from 'naive-ui'
import {
  ArrowForward,
  CheckmarkCircleOutline,
  CubeOutline,
  ExtensionPuzzleOutline,
  LayersOutline,
  LibraryOutline,
  TimeOutline,
  SpeedometerOutline,
} from '@/components/icons'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'

defineProps<{ show: boolean }>()
const emit = defineEmits<{ 'update:show': [value: boolean] }>()
const router = useRouter()
const { t } = useI18n()

function openRoute(name: 'Agents' | 'Extensions' | 'Knowledge' | 'Scheduler' | 'ModelPool' | 'Benchmarks') {
  emit('update:show', false)
  void router.push({ name })
}
</script>

<style>
.capability-library-modal.n-card {
  width: min(760px, calc(100vw - 40px));
  border: 1px solid var(--app-border);
  border-radius: 24px;
  background: var(--app-surface);
  box-shadow: 0 30px 90px color-mix(in srgb, var(--app-text) 18%, transparent);
}
</style>

<style scoped>
.library-intro { margin: -5px 0 24px; color: var(--app-text-muted); font-size: 13px; }
.library-section + .library-section { margin-top: 26px; }
.section-heading { display: flex; align-items: baseline; gap: 10px; margin-bottom: 10px; }
.section-heading span { font-size: 12px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.section-heading small { color: var(--app-text-muted); font-size: 11px; }
.library-grid { display: grid; gap: 10px; }
.agent-grid { grid-template-columns: 1.2fr 1fr 1fr; }
.resource-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.library-entry {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  min-height: 104px;
  padding: 16px;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  background: var(--app-surface);
  color: var(--app-text);
  text-align: left;
  cursor: pointer;
  transition: transform .24s cubic-bezier(.16, 1, .3, 1), border-color .2s ease, box-shadow .24s ease;
}
.library-entry:hover { transform: translateY(-3px); border-color: var(--app-text); box-shadow: 0 14px 30px color-mix(in srgb, var(--app-text) 9%, transparent); }
.library-entry:active { transform: translateY(-1px) scale(.99); }
.library-entry.featured { background: var(--app-text); color: var(--app-surface); border-color: var(--app-text); }
.library-entry.compact { min-height: 76px; }
.library-entry span { display: grid; min-width: 0; gap: 4px; }
.library-entry strong { font-size: 13px; }
.library-entry small { color: currentColor; font-size: 11px; line-height: 1.45; opacity: .62; }
.entry-arrow { opacity: .45; transition: transform .2s ease, opacity .2s ease; }
.library-entry:hover .entry-arrow { opacity: 1; transform: translateX(3px); }
@media (max-width: 720px) { .agent-grid, .resource-grid { grid-template-columns: 1fr; } }
</style>

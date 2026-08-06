<template>
  <section class="benchmark-comparison">
    <div class="comparison-header">
      <div>
        <h3>{{ t('benchmark.comparison') }}</h3>
        <p>{{ t('benchmark.groupComparisonHint') }}</p>
      </div>
      <div class="comparison-selectors">
        <label>
          <span>{{ t('benchmark.baselineGroup') }}</span>
          <n-select v-model:value="leftGroupId" :options="groupOptions" />
        </label>
        <label>
          <span>{{ t('benchmark.optionalComparisonGroup') }}</span>
          <n-select v-model:value="rightGroupId" clearable :options="rightGroupOptions" />
        </label>
      </div>
    </div>

    <n-empty v-if="!leftGroup" :description="t('benchmark.noCompletedGroups')" />
    <template v-else>
      <div class="series-legend">
        <span v-for="series in activeSeries" :key="series.key">
          <i class="legend-swatch" :class="series.colorClass" />{{ series.label }}
        </span>
      </div>

      <section class="comparison-section">
        <h4>{{ t('benchmark.performanceAverage') }}</h4>
        <div class="comparison-chart-list">
          <article v-for="metric in performanceMetrics" :key="metric.key" class="comparison-chart">
            <div class="chart-heading">
              <strong>{{ metric.label }}</strong>
              <span>{{ directionLabel(metric) }}</span>
            </div>
            <div v-for="series in performanceSeries(metric.key)" :key="series.key" class="bar-row">
              <span class="series-name">{{ series.shortLabel }}</span>
              <div class="bar-track">
                <span class="bar-fill" :class="series.colorClass" :style="{ width: `${series.width}%` }" />
              </div>
              <strong>{{ formatWithDeviation(metric.key, series.value, series.deviation) }}</strong>
            </div>
          </article>
        </div>
      </section>

      <section class="comparison-section">
        <h4>{{ t('benchmark.qpsResults') }}</h4>
        <div class="comparison-chart-list">
          <article v-for="metric in concurrencyMetrics" :key="metric.key" class="comparison-chart">
            <div class="chart-heading">
              <strong>{{ metric.label }}</strong>
              <span>{{ t('benchmark.higherIsBetter') }}</span>
            </div>
            <div v-for="series in concurrencySeries(metric.key)" :key="series.key" class="bar-row">
              <span class="series-name">{{ series.shortLabel }}</span>
              <div class="bar-track">
                <span class="bar-fill" :class="series.colorClass" :style="{ width: `${series.width}%` }" />
              </div>
              <strong>{{ formatConcurrencyMetric(metric.key, series.value, series.deviation) }}</strong>
            </div>
          </article>
        </div>
      </section>

      <section class="comparison-section">
        <h4>{{ t('benchmark.operatorAverage') }}</h4>
        <div class="comparison-chart-list">
          <article v-for="phase in phases" :key="phase" class="comparison-chart">
            <div class="chart-heading">
              <strong>{{ phaseLabel(phase) }}</strong>
              <span>{{ t('benchmark.higherIsBetter') }}</span>
            </div>
            <div v-for="series in operatorThroughputSeries(phase)" :key="series.key" class="bar-row">
              <span class="series-name">{{ series.shortLabel }}</span>
              <div class="bar-track">
                <span class="bar-fill" :class="series.colorClass" :style="{ width: `${series.width}%` }" />
              </div>
              <strong>{{ formatThroughputWithDeviation(series.value, series.deviation) }}</strong>
            </div>
          </article>
        </div>

        <div v-for="phase in phases" :key="`${phase}-kernels`" class="kernel-section">
          <h4>{{ phaseLabel(phase) }} · {{ t('benchmark.kernelTimeComparison') }}</h4>
          <n-empty v-if="!kernelRows(phase).length" :description="t('benchmark.noComparableData')" />
          <div v-else class="kernel-chart-list">
            <article v-for="kernel in kernelRows(phase)" :key="kernel.name" class="kernel-chart">
              <n-tooltip trigger="hover">
                <template #trigger><strong>{{ kernel.displayName }}</strong></template>
                <span>{{ kernel.description }}</span>
              </n-tooltip>
              <div v-for="series in valueBars(kernel.values)" :key="series.key" class="bar-row">
                <span class="series-name">{{ series.shortLabel }}</span>
                <div class="bar-track">
                  <span class="bar-fill" :class="series.colorClass" :style="{ width: `${series.width}%` }" />
                </div>
                <strong>{{ formatKernelWithDeviation(series.value, series.deviation) }}</strong>
              </div>
            </article>
          </div>
        </div>
      </section>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NEmpty, NSelect, NTooltip } from 'naive-ui'
import { useI18n } from '@/composables/useI18n'
import type {
  BenchmarkExperimentGroup,
  BenchmarkImplementationId,
  BenchmarkOperatorKernelStat,
  BenchmarkRun,
} from '@/api/benchmarks'

type Phase = 'prefill' | 'decode'
type PerformanceMetricKey =
  | 'decode_ms'
  | 'prompt_ms'
  | 'prompt_tokens_per_second'
  | 'decode_tokens_per_second'
  | 'peak_vram_bytes'
  | 'average_gpu_utilization_percent'
  | 'prompt_cache_hit_rate'
type ConcurrencyMetricKey = 'requests_per_second' | 'output_tokens_per_second'

interface PerformanceMetric {
  key: PerformanceMetricKey
  label: string
  higherIsBetter: boolean | null
}

interface SeriesIdentity {
  key: string
  group: BenchmarkExperimentGroup
  implementation: BenchmarkImplementationId
  label: string
  shortLabel: string
  colorClass: string
}

const props = defineProps<{
  groups: BenchmarkExperimentGroup[]
  runsByGroup: Record<string, BenchmarkRun[]>
}>()
const { locale, t } = useI18n()
const leftGroupId = ref<string | null>(null)
const rightGroupId = ref<string | null>(null)
const phases: Phase[] = ['prefill', 'decode']

const completedGroups = computed(() => props.groups.filter((group) => group.status === 'completed'))
const leftGroup = computed(() => completedGroups.value.find((group) => group.group_id === leftGroupId.value) || null)
const rightGroup = computed(() => completedGroups.value.find((group) => group.group_id === rightGroupId.value) || null)
const groupOptions = computed(() => completedGroups.value.map(groupOption))
const rightGroupOptions = computed(() => completedGroups.value
  .filter((group) => group.group_id !== leftGroupId.value)
  .map(groupOption))
const activeSeries = computed<SeriesIdentity[]>(() => {
  const selected = [leftGroup.value, rightGroup.value].filter((group): group is BenchmarkExperimentGroup => Boolean(group))
  return selected.flatMap((group, groupIndex) => (['official', 'amd'] as const).map((implementation, implementationIndex) => ({
    key: `${group.group_id}:${implementation}`,
    group,
    implementation,
    label: `${group.spec.name} · ${implementationLabel(implementation)}`,
    shortLabel: `${groupIndex === 0 ? t('benchmark.baselineShort') : t('benchmark.comparisonShort')} · ${implementationLabel(implementation)}`,
    colorClass: `series-${groupIndex * 2 + implementationIndex}`,
  })))
})

const performanceMetrics = computed<PerformanceMetric[]>(() => [
  { key: 'decode_tokens_per_second', label: t('benchmark.decodeTps'), higherIsBetter: true },
  { key: 'prompt_tokens_per_second', label: t('benchmark.promptTps'), higherIsBetter: true },
  { key: 'prompt_ms', label: t('benchmark.promptEval'), higherIsBetter: false },
  { key: 'decode_ms', label: t('benchmark.decodeEval'), higherIsBetter: false },
  { key: 'prompt_cache_hit_rate', label: t('benchmark.cacheHitRate'), higherIsBetter: true },
  { key: 'peak_vram_bytes', label: t('benchmark.peakVram'), higherIsBetter: false },
  { key: 'average_gpu_utilization_percent', label: t('benchmark.averageGpu'), higherIsBetter: null },
])
const concurrencyMetrics = computed(() => [
  { key: 'requests_per_second' as const, label: 'QPS' },
  { key: 'output_tokens_per_second' as const, label: t('benchmark.aggregateOutputTps') },
])

watch(completedGroups, repairSelection, { immediate: true })
watch(leftGroupId, () => {
  if (leftGroupId.value === rightGroupId.value) rightGroupId.value = null
})

function repairSelection() {
  if (!completedGroups.value.some((group) => group.group_id === leftGroupId.value)) {
    leftGroupId.value = completedGroups.value[0]?.group_id || null
  }
  if (!completedGroups.value.some((group) => group.group_id === rightGroupId.value)) {
    rightGroupId.value = null
  }
}

function groupOption(group: BenchmarkExperimentGroup) {
  return { label: `${group.spec.name} · ${formatDate(group.created_at)}`, value: group.group_id }
}

function groupRuns(group: BenchmarkExperimentGroup, implementation: BenchmarkImplementationId, kind: BenchmarkRun['spec']['kind']) {
  const runIds = new Set(group.runs
    .filter((item) => item.implementation === implementation && item.kind === kind)
    .map((item) => item.run_id))
  return (props.runsByGroup[group.group_id] || [])
    .filter((run) => runIds.has(run.run_id) && run.status === 'completed')
}

function finiteValues(values: Array<number | null | undefined>) {
  return values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
}

function mean(values: Array<number | null | undefined>): number | null {
  const normalized = finiteValues(values)
  return normalized.length ? normalized.reduce((sum, value) => sum + value, 0) / normalized.length : null
}

function deviation(values: Array<number | null | undefined>): number | null {
  const normalized = finiteValues(values)
  if (!normalized.length) return null
  const average = normalized.reduce((sum, value) => sum + value, 0) / normalized.length
  return Math.sqrt(normalized.reduce((sum, value) => sum + (value - average) ** 2, 0) / normalized.length)
}

function performanceValues(series: SeriesIdentity, key: PerformanceMetricKey) {
  const runs = groupRuns(series.group, series.implementation, 'performance')
  if (key === 'prompt_cache_hit_rate') {
    if (series.group.spec.prompt_cache_mode === 'cold') return []
    return runs.map((run) => run.summary?.prompt_cache?.hit_rate_percent)
  }
  return runs.map((run) => run.summary?.[key]?.mean)
}

function performanceSeries(key: PerformanceMetricKey) {
  return valueBars(activeSeries.value.map((series) => {
    const values = performanceValues(series, key)
    return { series, value: mean(values), deviation: deviation(values) }
  }))
}

function concurrencySeries(key: ConcurrencyMetricKey) {
  return valueBars(activeSeries.value.map((series) => {
    const values = groupRuns(series.group, series.implementation, 'concurrency')
      .map((run) => run.concurrency?.[key])
    return { series, value: mean(values), deviation: deviation(values) }
  }))
}

function operatorThroughputSeries(phase: Phase) {
  return valueBars(activeSeries.value.map((series) => {
    const values = groupRuns(series.group, series.implementation, 'operator_analysis').map((run) => {
      const row = run.operator_analysis?.phases.find((item) => item.phase === phase)?.benchmark_rows[0]
      return typeof row?.avg_ts === 'number' ? row.avg_ts : null
    })
    return { series, value: mean(values), deviation: deviation(values) }
  }))
}

function valueBars(items: Array<{ series: SeriesIdentity; value: number | null; deviation?: number | null }>) {
  const maximum = Math.max(...items.map((item) => item.value || 0), 0)
  return items.map(({ series, value }) => ({
    ...series,
    value,
    deviation: items.find((item) => item.series.key === series.key)?.deviation || null,
    width: value === null || maximum <= 0 ? 0 : Math.max(2, value / maximum * 100),
  }))
}

function kernelRows(phase: Phase) {
  const seriesMaps = activeSeries.value.map((series) => ({
    series,
    kernels: aggregateKernels(groupRuns(series.group, series.implementation, 'operator_analysis'), phase),
  }))
  const names = new Set(seriesMaps.flatMap((entry) => [...entry.kernels.keys()]))
  return [...names].map((name) => {
    const representative = seriesMaps.map((entry) => entry.kernels.get(name)).find(Boolean)
    return {
      name,
      displayName: representative?.displayName || name,
      description: representative?.description || t('benchmark.kernelDescriptionUnavailable'),
      values: seriesMaps.map(({ series, kernels }) => {
        const kernel = kernels.get(name)
        return { series, value: kernel?.duration || null, deviation: kernel?.deviation || null }
      }),
    }
  }).sort((a, b) => Math.max(...b.values.map((item) => item.value || 0)) - Math.max(...a.values.map((item) => item.value || 0))).slice(0, 8)
}

function aggregateKernels(runs: BenchmarkRun[], phase: Phase) {
  const values = new Map<string, { displayName: string; description: string; durations: number[] }>()
  for (const run of runs) {
    const kernels = run.operator_analysis?.phases.find((item) => item.phase === phase)?.top_kernels || []
    for (const kernel of kernels) {
      const key = kernel.display_name || kernel.name
      const entry = values.get(key) || {
        displayName: key,
        description: kernelDescription(kernel),
        durations: [],
      }
      entry.durations.push(kernel.total_duration_ns)
      values.set(key, entry)
    }
  }
  return new Map([...values.entries()].map(([key, value]) => [key, {
    displayName: value.displayName,
    description: value.description,
    duration: mean(value.durations) || 0,
    deviation: deviation(value.durations) || 0,
  }]))
}

function kernelDescription(kernel: BenchmarkOperatorKernelStat) {
  return kernel.descriptions[locale.value]
    || kernel.descriptions['zh-CN']
    || kernel.descriptions['en-US']
    || t('benchmark.kernelDescriptionUnavailable')
}

function implementationLabel(value: BenchmarkImplementationId) {
  return value === 'official' ? t('benchmark.officialImplementation') : t('benchmark.amdImplementation')
}

function directionLabel(metric: PerformanceMetric) {
  if (metric.higherIsBetter === null) return t('benchmark.comparisonOnly')
  return metric.higherIsBetter ? t('benchmark.higherIsBetter') : t('benchmark.lowerIsBetter')
}

function phaseLabel(phase: Phase) {
  return phase === 'prefill' ? t('benchmark.prefillPhase') : t('benchmark.decodePhase')
}

function formatPerformanceMetric(key: PerformanceMetricKey, value: number | null) {
  if (value === null) return '—'
  if (key.endsWith('_ms')) return `${value.toFixed(1)} ms`
  if (key === 'peak_vram_bytes') return `${(value / 1024 ** 3).toFixed(2)} GiB`
  if (key.includes('percent') || key === 'prompt_cache_hit_rate') return `${value.toFixed(1)}%`
  return `${value.toFixed(2)} tok/s`
}

function formatThroughput(value: number | null) {
  return value === null ? '—' : `${value.toFixed(2)} tok/s`
}

function formatWithDeviation(key: PerformanceMetricKey, value: number | null, spread: number | null) {
  if (value === null) return '—'
  return spread === null
    ? formatPerformanceMetric(key, value)
    : `${formatPerformanceMetric(key, value)} ± ${formatPerformanceMetric(key, spread)}`
}

function formatThroughputWithDeviation(value: number | null, spread: number | null) {
  if (value === null) return '—'
  return spread === null ? formatThroughput(value) : `${formatThroughput(value)} ± ${formatThroughput(spread)}`
}

function formatConcurrencyMetric(key: ConcurrencyMetricKey, value: number | null, spread: number | null) {
  if (value === null) return '—'
  const unit = key === 'requests_per_second' ? 'req/s' : 'tok/s'
  return spread === null
    ? `${value.toFixed(2)} ${unit}`
    : `${value.toFixed(2)} ± ${spread.toFixed(2)} ${unit}`
}

function formatKernelWithDeviation(value: number | null, spread: number | null) {
  if (value === null) return '—'
  return spread === null ? formatKernelTime(value) : `${formatKernelTime(value)} ± ${formatKernelTime(spread)}`
}

function formatKernelTime(value: number) {
  if (!Number.isFinite(value)) return '—'
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)} s`
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} ms`
  if (value >= 1_000) return `${(value / 1_000).toFixed(2)} μs`
  return `${value.toFixed(0)} ns`
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
</script>

<style scoped>
.benchmark-comparison {
  --series-0: #2f80ed;
  --series-1: #f2994a;
  --series-2: #56cc9d;
  --series-3: #9b51e0;
  min-width: 0;
}
.comparison-header { display: grid; gap: var(--app-space-lg); margin-bottom: var(--app-space-lg); }
.comparison-header h3,
.comparison-section h4,
.kernel-section h4 { margin: 0; color: var(--app-text-strong); }
.comparison-header p { margin: 5px 0 0; color: var(--app-text-muted); }
.comparison-selectors { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-md); }
.comparison-selectors label { display: grid; gap: 6px; min-width: 0; }
.comparison-selectors label > span { color: var(--app-text-muted); font-size: 12px; }
.series-legend { display: flex; flex-wrap: wrap; gap: var(--app-space-lg); margin-bottom: var(--app-space-lg); }
.series-legend span { display: inline-flex; align-items: center; gap: 7px; }
.legend-swatch { width: 12px; height: 12px; border-radius: 3px; }
.series-0 { background: var(--series-0); }
.series-1 { background: var(--series-1); }
.series-2 { background: var(--series-2); }
.series-3 { background: var(--series-3); }
.comparison-section { display: grid; gap: var(--app-space-md); margin-top: var(--app-space-xl); }
.comparison-chart-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-md); }
.comparison-chart,
.kernel-chart { border: 1px solid var(--app-divider); border-radius: var(--app-radius-lg); padding: var(--app-space-md); background: var(--app-surface-subtle); min-width: 0; }
.chart-heading { display: flex; justify-content: space-between; gap: var(--app-space-sm); margin-bottom: var(--app-space-md); }
.chart-heading span { color: var(--app-text-muted); font-size: 12px; }
.bar-row {
  display: grid;
  grid-template-columns: 150px minmax(80px, 1fr) 190px;
  align-items: center;
  gap: var(--app-space-sm);
  margin: 8px 0;
}
.series-name { color: var(--app-text-muted); font-size: 12px; overflow-wrap: anywhere; }
.bar-track { height: 10px; border-radius: 999px; background: var(--app-fill); overflow: hidden; }
.bar-fill { display: block; height: 100%; border-radius: inherit; }
.kernel-section { display: grid; gap: var(--app-space-md); }
.kernel-chart-list { display: grid; gap: var(--app-space-sm); }
@media (max-width: 760px) {
  .comparison-selectors,
  .comparison-chart-list { grid-template-columns: 1fr; }
  .bar-row { grid-template-columns: 120px minmax(64px, 1fr) 160px; }
}
@media (max-width: 480px) {
  .bar-row { grid-template-columns: 96px minmax(56px, 1fr) 128px; }
  .bar-row > strong { font-size: 11px; overflow-wrap: anywhere; }
}
</style>

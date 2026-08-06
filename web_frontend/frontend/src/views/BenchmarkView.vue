<template>
  <div class="benchmark-view app-scroll-y">
    <header class="context-bar">
      <div class="context-title">
        <div class="title-line">
          <span class="title-icon"><n-icon><BarChartOutline /></n-icon></span>
          <n-text strong class="page-title">{{ t('benchmark.title') }}</n-text>
        </div>
        <n-text depth="3" class="context-subtitle">{{ t('benchmark.subtitle') }}</n-text>
      </div>
      <n-button secondary :loading="loading" @click="refresh()">
        <template #icon><n-icon><Refresh /></n-icon></template>
        {{ t('common.refresh') }}
      </n-button>
    </header>

    <main class="benchmark-content">
      <n-tabs v-model:value="activePageTab" type="line" animated class="benchmark-tabs">
        <n-tab-pane name="configuration" :tab="t('benchmark.configurationTab')">
          <section class="panel run-form-panel">
        <div class="panel-heading">
          <div>
            <h2>{{ t('benchmark.newExperimentGroup') }}</h2>
            <p>{{ t('benchmark.experimentGroupHint') }}</p>
          </div>
          <n-tag v-if="activeGroup" type="info" :bordered="false">{{ statusLabel(activeGroup.status) }}</n-tag>
          <n-tag v-else type="success" :bordered="false">Official + AMD</n-tag>
        </div>

        <n-alert v-if="!readyChatProfiles.length" type="warning" :show-icon="true">
          {{ t('benchmark.modelNotReady') }}
        </n-alert>
        <n-alert v-else-if="!llamaStatus?.available" type="warning" :show-icon="true">
          {{ llamaStatus?.error || t('benchmark.implementationUnavailable') }}
        </n-alert>

        <n-alert type="warning" :show-icon="true">
          {{ t('benchmark.operatorPauseWarning') }}
        </n-alert>
        <n-alert
          v-if="llamaStatus?.builds?.some((build) => !build.benchmark_binary_path)"
          type="error"
          :show-icon="true"
          class="operator-warning"
        >
          {{ t('benchmark.operatorBinaryUnavailable') }}
        </n-alert>

        <div class="form-grid">
          <label class="field field-wide">
            <span>{{ t('benchmark.runName') }}</span>
            <n-input v-model:value="form.name" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field field-wide">
            <span>{{ t('benchmark.profile') }}</span>
            <n-select
              class="profile-select"
              v-model:value="form.profile_id"
              :options="profileOptions"
              :disabled="Boolean(activeGroup)"
            />
          </label>
          <label class="field field-full">
            <span>{{ t('benchmark.prompt') }}</span>
            <n-input
              v-model:value="form.prompt"
              type="textarea"
              :autosize="{ minRows: 4, maxRows: 10 }"
              :placeholder="t('benchmark.promptPlaceholder')"
              :disabled="Boolean(activeGroup)"
            />
          </label>
          <label class="field">
            <span>{{ t('benchmark.experimentRepetitions') }}</span>
            <n-input-number v-model:value="form.repetitions" :min="1" :max="20" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.maxOutputTokens') }}</span>
            <n-input-number v-model:value="form.max_output_tokens" :min="1" :max="32768" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.temperature') }}</span>
            <n-input-number v-model:value="form.temperature" :min="0" :max="2" :step="0.1" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.seed') }}</span>
            <n-input-number v-model:value="form.seed" :min="0" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.warmupIterations') }}</span>
            <n-input-number v-model:value="form.warmup_iterations" :min="0" :max="10" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.measuredIterations') }}</span>
            <n-input-number v-model:value="form.measured_iterations" :min="1" :max="50" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.telemetryInterval') }}</span>
            <n-select
              v-model:value="form.telemetry_interval_ms"
              :options="telemetryIntervalOptions"
              :disabled="Boolean(activeGroup)"
            />
          </label>
          <label class="field">
            <span>{{ t('benchmark.promptCacheMode') }}</span>
            <n-select
              v-model:value="form.prompt_cache_mode"
              :options="promptCacheModeOptions"
              :disabled="Boolean(activeGroup)"
            />
          </label>
          <label class="field">
            <span>{{ t('benchmark.concurrentRequests') }}</span>
            <n-input-number v-model:value="form.concurrency.concurrent_requests" :min="1" :max="128" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.requestsPerWorker') }}</span>
            <n-input-number v-model:value="form.concurrency.requests_per_worker" :min="1" :max="100" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.qpsWarmupRequests') }}</span>
            <n-input-number v-model:value="form.concurrency.warmup_requests_per_worker" :min="0" :max="20" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.prefillTokens') }}</span>
            <n-input-number v-model:value="form.operator_analysis.prefill_tokens" :min="32" :max="32768" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.decodeTokens') }}</span>
            <n-input-number v-model:value="form.operator_analysis.decode_tokens" :min="1" :max="4096" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.operatorRepetitions') }}</span>
            <n-input-number v-model:value="form.operator_analysis.repetitions" :min="1" :max="20" :disabled="Boolean(activeGroup)" />
          </label>
          <label class="field">
            <span>{{ t('benchmark.topKernels') }}</span>
            <n-input-number v-model:value="form.operator_analysis.top_kernels" :min="5" :max="100" :disabled="Boolean(activeGroup)" />
          </label>
        </div>

        <div class="form-actions">
          <n-button
            v-if="!activeGroup"
            type="primary"
            :loading="submitting"
            :disabled="!canStart"
            @click="startGroup"
          >
            <template #icon><n-icon><Play /></n-icon></template>
            {{ t('benchmark.start') }}
          </n-button>
          <n-tag v-else type="warning" :bordered="false">{{ t('benchmark.experimentRunning') }}</n-tag>
        </div>
          </section>
        </n-tab-pane>

        <n-tab-pane name="results" :tab="t('benchmark.resultsTab')">
          <div class="tab-stack">
            <section class="panel history-panel">
              <div class="section-heading history-heading"><h3>{{ t('benchmark.history') }}</h3></div>
              <n-empty v-if="!groups.length" :description="t('benchmark.noHistory')" />
              <div v-else class="history-list">
                <div
                  v-for="group in groups"
                  :key="group.group_id"
                  class="history-item"
                  :class="{ 'is-selected': group.group_id === selectedGroup?.group_id }"
                  role="button"
                  tabindex="0"
                  @click="selectGroup(group.group_id)"
                  @keydown.enter="selectGroup(group.group_id)"
                >
                  <span class="history-main">
                    <strong>{{ group.spec.name }}</strong>
                    <small>{{ t('benchmark.groupRunCount', { completed: group.progress_completed, total: group.progress_total }) }}</small>
                  </span>
                  <span class="history-metrics">
                    <span>Official + AMD</span>
                    <span>{{ group.spec.repetitions }} ×</span>
                  </span>
                  <n-tag size="small" :bordered="false" :type="statusTagType(group.status)">{{ statusLabel(group.status) }}</n-tag>
                  <span class="history-date">{{ formatDate(group.created_at) }}</span>
                  <n-popconfirm
                    v-if="!isActive(group)"
                    :positive-text="t('common.delete')"
                    :negative-text="t('common.cancel')"
                    @positive-click="deleteGroup(group)"
                  >
                    <template #trigger>
                      <n-button quaternary circle size="small" :title="t('benchmark.deleteRun')" @click.stop>
                        <template #icon><n-icon><TrashOutline /></n-icon></template>
                      </n-button>
                    </template>
                    {{ t('benchmark.deleteRun') }}?
                  </n-popconfirm>
                </div>
              </div>
            </section>

            <section v-if="selectedGroup" class="panel group-summary-panel">
              <div class="panel-heading run-heading">
                <div>
                  <div class="run-title-line">
                    <h2>{{ selectedGroup.spec.name }}</h2>
                    <n-tag :type="statusTagType(selectedGroup.status)" :bordered="false">
                      {{ statusLabel(selectedGroup.status) }}
                    </n-tag>
                  </div>
                  <p>{{ t('benchmark.experimentGroupSummary', { repetitions: selectedGroup.spec.repetitions }) }}</p>
                </div>
                <span class="run-time">{{ formatDate(selectedGroup.created_at) }}</span>
              </div>
              <div v-if="isActive(selectedGroup)" class="run-progress">
                <div class="progress-copy">
                  <span>{{ t('benchmark.currentExperimentGroup') }}</span>
                  <strong>{{ t('benchmark.progress', { completed: selectedGroup.progress_completed, total: selectedGroup.progress_total }) }}</strong>
                </div>
                <n-progress type="line" status="info" processing :percentage="groupProgress(selectedGroup)" />
              </div>
              <n-alert v-if="selectedGroup.error" type="error" :show-icon="true" class="run-error">
                {{ selectedGroup.error }}
              </n-alert>
              <n-alert type="info" :show-icon="true" class="measurement-source-alert">
                {{ cacheModeDescription(selectedGroup.spec.prompt_cache_mode) }}
              </n-alert>
              <div class="group-average-grid">
                <article v-for="implementation in implementationIds" :key="implementation" class="group-average-card">
                  <div class="section-heading">
                    <h3>{{ implementationLabel(implementation) }}</h3>
                    <span>{{ t('benchmark.averageOfRuns', { count: completedPerformanceRuns(implementation).length }) }}</span>
                  </div>
                  <div class="metric-grid compact-metric-grid">
                    <article v-for="metric in groupAverageMetrics" :key="metric.key" class="metric-card">
                      <span class="metric-label">{{ metric.label }}</span>
                      <strong class="metric-value">{{ formatMetric(metric.key, groupMetricMean(implementation, metric.key)) }}</strong>
                      <div class="metric-detail">± {{ formatMetric(metric.key, groupMetricStd(implementation, metric.key)) }}</div>
                    </article>
                  </div>
                  <div class="qps-average-row">
                    <span>QPS <strong>{{ formatRate(groupConcurrencyMean(implementation, 'requests_per_second'), 'req/s') }}</strong></span>
                    <span>{{ t('benchmark.aggregateOutputTps') }} <strong>{{ formatRate(groupConcurrencyMean(implementation, 'output_tokens_per_second'), 'tok/s') }}</strong></span>
                  </div>
                </article>
              </div>
              <label class="field group-run-selector">
                <span>{{ t('benchmark.runDetail') }}</span>
                <n-select v-model:value="selectedRunId" :options="selectedGroupRunOptions" />
              </label>
            </section>

            <section v-if="selectedRun" class="panel current-run-panel">
        <div class="panel-heading run-heading">
          <div>
            <div class="run-title-line">
              <h2>{{ selectedRun.spec.name }}</h2>
              <n-tag :type="statusTagType(selectedRun.status)" :bordered="false">
                {{ statusLabel(selectedRun.status) }}
              </n-tag>
            </div>
            <p>{{ selectedRun.spec.implementation.label || selectedRun.spec.profile_id }}</p>
          </div>
          <span class="run-time">{{ formatDate(selectedRun.created_at) }}</span>
        </div>

        <div v-if="isActive(selectedRun)" class="run-progress">
          <div class="progress-copy">
            <span>{{ t('benchmark.currentRun') }}</span>
            <strong>{{ t('benchmark.progress', { completed: selectedRun.progress_completed, total: selectedRun.progress_total }) }}</strong>
          </div>
          <n-progress
            type="line"
            status="info"
            processing
            :percentage="runProgress(selectedRun)"
          />
        </div>

        <n-alert v-if="selectedRun.error" type="error" :show-icon="true" class="run-error">
          {{ selectedRun.error }}
        </n-alert>

        <template v-if="selectedRun.summary">
          <n-alert type="info" :show-icon="true" class="measurement-source-alert">
            {{ t('benchmark.ttftSourceHint') }}
          </n-alert>
          <div class="section-heading">
            <h3>{{ t('benchmark.summary') }}</h3>
            <span>{{ t('benchmark.measuredSamples', { successful: selectedRun.summary.successful_samples, total: selectedRun.summary.measured_samples }) }}</span>
          </div>
          <div class="metric-grid">
            <article v-for="metric in primaryMetrics" :key="metric.key" class="metric-card">
              <span class="metric-label">{{ metric.label }}</span>
              <strong class="metric-value">{{ formatMetric(metric.key, metricStats(selectedRun, metric.key)?.mean) }}</strong>
              <div class="metric-detail">
                <span>{{ t('benchmark.metricP50') }} {{ formatMetric(metric.key, metricStats(selectedRun, metric.key)?.p50) }}</span>
                <span>{{ t('benchmark.metricP95') }} {{ formatMetric(metric.key, metricStats(selectedRun, metric.key)?.p95) }}</span>
              </div>
            </article>
          </div>

          <template v-if="selectedRun.summary.prompt_cache">
            <div class="section-heading cache-heading">
              <h3>{{ t('benchmark.promptCache') }}</h3>
              <span>
                {{ selectedRun.spec.prompt_cache_mode === 'cold'
                  ? t('benchmark.cacheDisabled')
                  : t('benchmark.weightedHitRateHint') }}
              </span>
            </div>
            <n-alert
              v-if="selectedRun.summary.prompt_cache.metric_version === 'legacy'"
              type="warning"
              :show-icon="true"
              class="cache-legacy-warning"
            >
              {{ t('benchmark.legacyCacheMetric') }}
            </n-alert>
            <div class="metric-grid cache-metric-grid">
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.cacheHitRate') }}</span>
                <strong class="metric-value">
                  {{ selectedRun.spec.prompt_cache_mode === 'cold'
                    ? t('benchmark.cacheDisabled')
                    : formatPercent(selectedRun.summary.prompt_cache.hit_rate_percent) }}
                </strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.cachedTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.prompt_cache.cached_tokens) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.processedPromptTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.prompt_cache.processed_tokens) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.promptTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.prompt_cache.prompt_tokens) }}</strong>
              </article>
            </div>
          </template>

          <template v-if="selectedRun.summary.speculative_decoding">
            <div class="section-heading cache-heading">
              <h3>{{ t('benchmark.mtpMetrics') }}</h3>
              <span>{{ t('benchmark.mtpMetricsHint') }}</span>
            </div>
            <div class="metric-grid cache-metric-grid">
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.mtpDraftTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.speculative_decoding.draft_tokens) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.mtpAcceptedTokens') }}</span>
                <strong class="metric-value">{{ formatTokenCount(selectedRun.summary.speculative_decoding.accepted_draft_tokens) }}</strong>
              </article>
              <article class="metric-card">
                <span class="metric-label">{{ t('benchmark.mtpAcceptanceRate') }}</span>
                <strong class="metric-value">{{ formatPercent(selectedRun.summary.speculative_decoding.acceptance_rate_percent) }}</strong>
              </article>
            </div>
          </template>

        </template>

        <section v-if="selectedRun.concurrency" class="operator-results">
          <div class="section-heading">
            <h3>{{ t('benchmark.qpsResults') }}</h3>
            <span>{{ t('benchmark.concurrentRequestCount', { value: selectedRun.concurrency.concurrent_requests }) }}</span>
          </div>
          <div class="metric-grid">
            <article class="metric-card">
              <span class="metric-label">QPS</span>
              <strong class="metric-value">{{ formatRate(selectedRun.concurrency.requests_per_second, 'req/s') }}</strong>
            </article>
            <article class="metric-card">
              <span class="metric-label">{{ t('benchmark.aggregateOutputTps') }}</span>
              <strong class="metric-value">{{ formatRate(selectedRun.concurrency.output_tokens_per_second, 'tok/s') }}</strong>
            </article>
            <article class="metric-card">
              <span class="metric-label">{{ t('benchmark.aggregateInputTps') }}</span>
              <strong class="metric-value">{{ formatRate(selectedRun.concurrency.input_tokens_per_second, 'tok/s') }}</strong>
            </article>
            <article class="metric-card">
              <span class="metric-label">{{ t('benchmark.errorRate') }}</span>
              <strong class="metric-value">{{ formatPercent(selectedRun.concurrency.error_rate_percent) }}</strong>
            </article>
            <article class="metric-card">
              <span class="metric-label">{{ t('benchmark.requestLatencyP95') }}</span>
              <strong class="metric-value">{{ formatMilliseconds(selectedRun.concurrency.request_latency_ms?.p95) }}</strong>
            </article>
            <article class="metric-card">
              <span class="metric-label">{{ t('benchmark.ttftP95') }}</span>
              <strong class="metric-value">{{ formatMilliseconds(selectedRun.concurrency.ttft_ms?.p95) }}</strong>
            </article>
          </div>
        </section>

        <section v-if="selectedRun.operator_analysis" class="operator-results">
          <div class="section-heading">
            <h3>{{ t('benchmark.operatorResults') }}</h3>
            <span>{{ selectedRun.operator_analysis.profiler }}</span>
          </div>
          <n-alert
            :type="selectedRun.operator_analysis.runtime_restored ? 'success' : 'warning'"
            :show-icon="true"
          >
            {{ selectedRun.operator_analysis.runtime_restored
              ? t('benchmark.runtimeRestored')
              : t('benchmark.runtimeRestoreFailed') }}
          </n-alert>
          <n-alert
            v-if="selectedRun.operator_analysis.gpu_graphs_disabled_for_attribution"
            type="info"
            :show-icon="true"
            class="operator-warning"
          >
            {{ t('benchmark.operatorGraphAttributionNotice') }}
          </n-alert>
          <n-alert
            v-for="warning in selectedRun.operator_analysis.warnings"
            :key="warning"
            type="warning"
            :show-icon="true"
            class="operator-warning"
          >
            {{ warning }}
          </n-alert>
          <article
            v-for="phase in selectedRun.operator_analysis.phases"
            :key="phase.phase"
            class="operator-phase"
          >
            <div class="section-heading">
              <h3>{{ phase.phase === 'prefill' ? t('benchmark.prefillPhase') : t('benchmark.decodePhase') }}</h3>
              <span>{{ phase.elapsed_seconds.toFixed(1) }} s · {{ phase.artifact_directory }}</span>
            </div>
            <div class="operator-table-wrap">
              <table class="sample-table">
                <thead><tr>
                  <th>{{ t('benchmark.kernelName') }}</th>
                  <th>{{ t('benchmark.kernelCalls') }}</th>
                  <th>{{ t('benchmark.kernelTotalTime') }}</th>
                  <th>{{ t('benchmark.kernelShare') }}</th>
                </tr></thead>
                <tbody>
                  <tr v-for="kernel in phase.top_kernels" :key="kernel.name">
                    <td class="kernel-name">
                      <n-tooltip trigger="hover">
                        <template #trigger>
                          <strong class="kernel-display-name">
                            {{ kernel.display_name || kernel.name }}
                            <n-icon class="kernel-info-icon" :component="InformationCircleOutline" />
                          </strong>
                        </template>
                        <div class="kernel-description">{{ kernelDescription(kernel.descriptions) }}</div>
                      </n-tooltip>
                      <details v-if="kernel.variants.length" class="kernel-variants">
                        <summary>{{ t('benchmark.kernelVariants', { count: kernel.variant_count || kernel.variants.length }) }}</summary>
                        <code v-for="variant in kernel.variants" :key="variant">{{ variant }}</code>
                      </details>
                    </td>
                    <td>{{ kernel.calls.toLocaleString() }}</td>
                    <td>{{ formatKernelTime(kernel.total_duration_ns) }}</td>
                    <td>{{ formatPercent(kernel.duration_percent) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="phase.dispatch_variants?.length" class="operator-table-wrap dispatch-variant-table-wrap">
              <table class="sample-table dispatch-variant-table">
                <thead><tr>
                  <th>{{ t('benchmark.dispatchPath') }}</th>
                  <th>{{ t('benchmark.weightType') }}</th>
                  <th>{{ t('benchmark.matrixShape') }}</th>
                  <th>{{ t('benchmark.dispatchFeatures') }}</th>
                  <th>{{ t('benchmark.kernelConfiguration') }}</th>
                  <th>{{ t('benchmark.kernelCalls') }}</th>
                  <th>{{ t('benchmark.kernelTotalTime') }}</th>
                  <th>{{ t('benchmark.kernelAverageTime') }}</th>
                  <th>{{ t('benchmark.kernelShare') }}</th>
                </tr></thead>
                <tbody>
                  <tr
                    v-for="item in phase.dispatch_variants"
                    :key="dispatchVariantKey(item)"
                  >
                    <td><strong>{{ item.operation.toUpperCase() }}</strong></td>
                    <td><code>{{ item.weight_type }}</code></td>
                    <td><code>{{ item.m.toLocaleString() }} × {{ item.n.toLocaleString() }} × {{ item.k.toLocaleString() }}</code></td>
                    <td>{{ formatDispatchFeatures(item) }}</td>
                    <td class="dispatch-configuration"><code>{{ formatDispatchConfiguration(item.configuration) }}</code></td>
                    <td>{{ item.calls.toLocaleString() }}</td>
                    <td>{{ formatKernelTime(item.total_duration_ns) }}</td>
                    <td>{{ formatKernelTime(item.average_duration_ns) }}</td>
                    <td>{{ formatPercent(item.duration_percent) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-if="phase.graph_operators.length" class="operator-table-wrap graph-table-wrap">
              <table class="sample-table">
                <thead><tr>
                  <th>{{ t('benchmark.graphOperation') }}</th>
                  <th>{{ t('benchmark.graphBackend') }}</th>
                  <th>{{ t('benchmark.graphCount') }}</th>
                </tr></thead>
                <tbody>
                  <tr v-for="item in phase.graph_operators" :key="`${item.operation}:${item.backend}`">
                    <td>{{ item.operation }}</td>
                    <td>{{ item.backend }}</td>
                    <td>{{ item.count.toLocaleString() }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <n-empty
              v-else
              class="graph-empty"
              :description="t('benchmark.graphUnavailable')"
            />
            <div v-if="phase.custom_kernels.length" class="operator-table-wrap graph-table-wrap">
              <table class="sample-table">
                <thead><tr>
                  <th>{{ t('benchmark.customKernel') }}</th>
                  <th>{{ t('benchmark.kernelSelected') }}</th>
                  <th>{{ t('benchmark.kernelDispatched') }}</th>
                  <th>{{ t('benchmark.kernelFallback') }}</th>
                  <th>{{ t('benchmark.fallbackReason') }}</th>
                </tr></thead>
                <tbody>
                  <tr v-for="item in phase.custom_kernels" :key="item.kernel_id">
                    <td class="kernel-name">
                      <n-tooltip trigger="hover">
                        <template #trigger>
                          <strong class="kernel-display-name">
                            {{ item.display_name || item.kernel_id }}
                            <n-icon class="kernel-info-icon" :component="InformationCircleOutline" />
                          </strong>
                        </template>
                        <div class="kernel-description">{{ kernelDescription(item.descriptions) }}</div>
                      </n-tooltip>
                      <code class="kernel-id">{{ item.kernel_id }}</code>
                    </td>
                    <td>{{ item.selected_count.toLocaleString() }}</td>
                    <td>{{ item.dispatch_count.toLocaleString() }}</td>
                    <td>{{ item.fallback_count.toLocaleString() }}</td>
                    <td>{{ formatFallbackReasons(item.fallback_reasons) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </article>
        </section>

        <div v-if="selectedRun.samples.length" class="samples-section">
          <div class="section-heading"><h3>{{ t('benchmark.samples') }}</h3></div>
          <div class="sample-table-wrap">
            <table class="sample-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{{ t('common.status') }}</th>
                  <th>{{ t('benchmark.ttft') }}</th>
                  <th>{{ t('benchmark.modelComputeTtft') }}</th>
                  <th>{{ t('benchmark.outsideModelCompute') }}</th>
                  <th>{{ t('benchmark.requestToHeaders') }}</th>
                  <th>{{ t('benchmark.firstEvent') }}</th>
                  <th>{{ t('benchmark.promptEval') }}</th>
                  <th>{{ t('benchmark.promptTps') }}</th>
                  <th>{{ t('benchmark.decodeTps') }}</th>
                  <th>{{ t('benchmark.endToEnd') }}</th>
                  <th>{{ t('benchmark.cachedTokens') }}</th>
                  <th>{{ t('benchmark.processedPromptTokens') }}</th>
                  <th>{{ t('benchmark.cacheHitRate') }}</th>
                  <th>{{ t('benchmark.peakVram') }}</th>
                  <th>{{ t('benchmark.peakGpu') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="sample in selectedRun.samples" :key="sample.sample_index">
                  <td>{{ sample.sample_index + 1 }}</td>
                  <td>
                    <n-tag size="small" :bordered="false" :type="sample.status === 'completed' ? 'success' : 'error'">
                      {{ sample.warmup ? t('benchmark.warmup') : t('benchmark.measured') }}
                    </n-tag>
                  </td>
                  <td>{{ formatMetric('ttft_ms', sample.ttft_ms) }}</td>
                  <td>{{ formatMetric('model_compute_ttft_ms', sample.model_compute_ttft_ms) }}</td>
                  <td>{{ formatMetric('outside_model_compute_ms', sample.outside_model_compute_ms) }}</td>
                  <td>{{ formatMetric('request_to_headers_ms', sample.request_to_headers_ms) }}</td>
                  <td>{{ formatMetric('first_event_ms', sample.first_event_ms) }}</td>
                  <td>{{ formatMetric('prompt_ms', sample.prompt_ms) }}</td>
                  <td>{{ formatMetric('prompt_tokens_per_second', sample.prompt_tokens_per_second) }}</td>
                  <td>{{ formatMetric('decode_tokens_per_second', sample.decode_tokens_per_second) }}</td>
                  <td>{{ formatMetric('end_to_end_ms', sample.end_to_end_ms) }}</td>
                  <td>{{ formatTokenCount(sample.cache_tokens) }}</td>
                  <td>{{ formatTokenCount(sampleProcessedPromptTokens(selectedRun, sample)) }}</td>
                  <td>
                    {{ selectedRun.spec.prompt_cache_mode === 'cold'
                      ? t('benchmark.cacheDisabled')
                      : formatPercent(sampleCacheHitRate(selectedRun, sample)) }}
                  </td>
                  <td>{{ formatMetric('peak_vram_bytes', sample.peak_vram_bytes) }}</td>
                  <td>{{ formatMetric('peak_gpu_utilization_percent', sample.peak_gpu_utilization_percent) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <n-collapse v-if="Object.keys(selectedRun.environment).length" class="environment-collapse">
          <n-collapse-item :title="t('benchmark.environment')" name="environment">
            <pre>{{ formatEnvironment(selectedRun.environment) }}</pre>
          </n-collapse-item>
        </n-collapse>
            </section>
          </div>
        </n-tab-pane>

        <n-tab-pane name="comparison" :tab="t('benchmark.comparisonTab')">
          <section class="panel comparison-panel">
            <BenchmarkComparison :groups="groups" :runs-by-group="runsByGroup" />
          </section>
        </n-tab-pane>
      </n-tabs>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCollapse,
  NCollapseItem,
  NEmpty,
  NIcon,
  NInput,
  NInputNumber,
  NPopconfirm,
  NProgress,
  NSelect,
  NTabPane,
  NTag,
  NTabs,
  NText,
  NTooltip,
  useMessage,
} from 'naive-ui'
import {
  BarChartOutline,
  InformationCircleOutline,
  Play,
  Refresh,
  TrashOutline,
} from '@/components/icons'
import { useI18n } from '@/composables/useI18n'
import BenchmarkComparison from '@/components/benchmark/BenchmarkComparison.vue'
import { benchmarkApi } from '@/api/benchmarks'
import type {
  BenchmarkMetricStats,
  BenchmarkExperimentGroup,
  BenchmarkExperimentGroupSpec,
  BenchmarkImplementationId,
  BenchmarkRun,
  BenchmarkRunStatus,
  BenchmarkSample,
} from '@/api/benchmarks'
import { modelPoolApi } from '@/api/modelPool'
import type {
  LlamaImplementationStatus,
  LocalModelProfile,
  LocalModelRuntime,
} from '@/api/modelPool'

type MetricKey =
  | 'ttft_ms'
  | 'model_compute_ttft_ms'
  | 'outside_model_compute_ms'
  | 'request_to_headers_ms'
  | 'first_event_ms'
  | 'first_token_decode_ms'
  | 'prompt_ms'
  | 'decode_ms'
  | 'prompt_tokens_per_second'
  | 'decode_tokens_per_second'
  | 'end_to_end_ms'
  | 'peak_vram_bytes'
  | 'average_gpu_utilization_percent'
  | 'peak_gpu_utilization_percent'
  | 'average_power_watts'
  | 'peak_power_watts'

interface MetricDefinition {
  key: MetricKey
  label: string
  higherIsBetter: boolean
}

const { locale, t } = useI18n()
const message = useMessage()
const loading = ref(false)
const submitting = ref(false)
const groups = ref<BenchmarkExperimentGroup[]>([])
const runsByGroup = ref<Record<string, BenchmarkRun[]>>({})
const profiles = ref<LocalModelProfile[]>([])
const runtimes = ref<LocalModelRuntime[]>([])
const llamaStatus = ref<LlamaImplementationStatus | null>(null)
const selectedGroupId = ref<string | null>(null)
const selectedRunId = ref<string | null>(null)
const activePageTab = ref<'configuration' | 'results' | 'comparison'>('configuration')
let pollTimer: number | undefined
let pollInProgress = false

const form = reactive<BenchmarkExperimentGroupSpec>({
  name: '',
  profile_id: '',
  prompt: '',
  repetitions: 3,
  max_output_tokens: 256,
  temperature: 0,
  seed: 42,
  warmup_iterations: 1,
  measured_iterations: 3,
  telemetry_interval_ms: 250,
  prompt_cache_mode: 'cold',
  concurrency: {
    concurrent_requests: 1,
    requests_per_worker: 2,
    warmup_requests_per_worker: 1,
  },
  operator_analysis: {
    prefill_tokens: 512,
    decode_tokens: 128,
    repetitions: 3,
    top_kernels: 20,
  },
})

const readyProfileIds = computed(() => new Set(
  runtimes.value.filter((runtime) => runtime.phase === 'ready').map((runtime) => runtime.profile_id),
))
const readyChatProfiles = computed(() => profiles.value.filter((profile) =>
  profile.kind === 'chat' && profile.enabled && readyProfileIds.value.has(profile.profile_id),
))
const profileOptions = computed(() => readyChatProfiles.value.map((profile) => ({
  label: profileOptionLabel(profile),
  value: profile.profile_id,
})))

function profileOptionLabel(profile: LocalModelProfile): string {
  const displayName = profile.display_name.trim()
  const servedModelName = profile.served_model_name.trim()
  return displayName || servedModelName || profile.profile_id
}
const telemetryIntervalOptions = [100, 250, 500, 1000].map((value) => ({
  label: t('benchmark.milliseconds', { value }),
  value,
}))
const promptCacheModeOptions = computed(() => [
  { label: t('benchmark.coldCacheMode'), value: 'cold' },
  { label: t('benchmark.warmCacheMode'), value: 'warm' },
])
const activeGroup = computed(() => groups.value.find((group) => isActive(group)) || null)
const selectedGroup = computed(() =>
  groups.value.find((group) => group.group_id === selectedGroupId.value) || groups.value[0] || null,
)
const selectedGroupRuns = computed(() => selectedGroup.value
  ? runsByGroup.value[selectedGroup.value.group_id] || []
  : [])
const selectedRun = computed(() =>
  selectedGroupRuns.value.find((run) => run.run_id === selectedRunId.value)
    || selectedGroupRuns.value[0]
    || null,
)
const implementationIds: BenchmarkImplementationId[] = ['official', 'amd']
const selectedGroupRunOptions = computed(() => {
  if (!selectedGroup.value) return []
  const refs = new Map(selectedGroup.value.runs.map((item) => [item.run_id, item]))
  return selectedGroupRuns.value.map((run) => {
    const ref = refs.get(run.run_id)
    return {
      label: ref
        ? `${t('benchmark.round', { value: ref.repetition_index + 1 })} · ${implementationLabel(ref.implementation)} · ${kindLabel(ref.kind)}`
        : run.spec.name,
      value: run.run_id,
    }
  })
})
const canStart = computed(() => Boolean(
  form.name.trim()
  && form.profile_id
  && form.prompt.trim()
  && readyProfileIds.value.has(form.profile_id)
  && llamaStatus.value?.available
  && llamaStatus.value.builds?.length === 2
  && llamaStatus.value.builds.every((build) => Boolean(build.benchmark_binary_path))
))
const primaryMetrics = computed<MetricDefinition[]>(() => [
  { key: 'ttft_ms', label: t('benchmark.ttft'), higherIsBetter: false },
  { key: 'model_compute_ttft_ms', label: t('benchmark.modelComputeTtft'), higherIsBetter: false },
  { key: 'outside_model_compute_ms', label: t('benchmark.outsideModelCompute'), higherIsBetter: false },
  { key: 'prompt_ms', label: t('benchmark.promptEval'), higherIsBetter: false },
  { key: 'prompt_tokens_per_second', label: t('benchmark.promptTps'), higherIsBetter: true },
  { key: 'decode_tokens_per_second', label: t('benchmark.decodeTps'), higherIsBetter: true },
  { key: 'end_to_end_ms', label: t('benchmark.endToEnd'), higherIsBetter: false },
  { key: 'peak_vram_bytes', label: t('benchmark.peakVram'), higherIsBetter: false },
  { key: 'average_gpu_utilization_percent', label: t('benchmark.averageGpu'), higherIsBetter: true },
])
const groupAverageMetrics = computed<MetricDefinition[]>(() => [
  { key: 'decode_tokens_per_second', label: t('benchmark.decodeTps'), higherIsBetter: true },
  { key: 'prompt_tokens_per_second', label: t('benchmark.promptTps'), higherIsBetter: true },
  { key: 'prompt_ms', label: t('benchmark.promptEval'), higherIsBetter: false },
  { key: 'decode_ms', label: t('benchmark.decodeEval'), higherIsBetter: false },
])

function cacheModeDescription(mode: BenchmarkExperimentGroupSpec['prompt_cache_mode']) {
  if (mode === 'cold') return t('benchmark.coldCacheModeHint')
  if (mode === 'warm') return t('benchmark.warmCacheModeHint')
  return t('benchmark.legacyCacheModeHint')
}

async function refresh(showLoading = true) {
  if (showLoading) loading.value = true
  try {
    const [groupResult, profileResult, runtimeResult, llamaResult] = await Promise.all([
      benchmarkApi.listGroups(),
      modelPoolApi.profiles(),
      modelPoolApi.runtimes(),
      modelPoolApi.llamaRuntime(),
    ])
    groups.value = groupResult.groups
    runsByGroup.value = groupResult.runs
    profiles.value = profileResult.profiles
    runtimes.value = runtimeResult.runtimes
    llamaStatus.value = llamaResult
    if (!selectedGroupId.value && groups.value.length) selectGroup(groups.value[0].group_id)
    if (!form.profile_id && readyChatProfiles.value.length) form.profile_id = readyChatProfiles.value[0].profile_id
  } catch (error) {
    if (showLoading) message.error(errorMessage(error))
  } finally {
    if (showLoading) loading.value = false
  }
}

async function startGroup() {
  if (!canStart.value) return
  submitting.value = true
  try {
    const result = await benchmarkApi.startGroup({
      ...form,
      name: form.name.trim(),
      prompt: form.prompt.trim(),
      operator_analysis: { ...form.operator_analysis },
      concurrency: { ...form.concurrency },
    })
    selectedGroupId.value = result.group.group_id
    selectedRunId.value = null
    activePageTab.value = 'results'
    await refresh(false)
  } catch (error) {
    message.error(errorMessage(error))
  } finally {
    submitting.value = false
  }
}

async function deleteGroup(group: BenchmarkExperimentGroup) {
  try {
    await benchmarkApi.deleteGroup(group.group_id)
    if (selectedGroupId.value === group.group_id) {
      selectedGroupId.value = null
      selectedRunId.value = null
    }
    await refresh(false)
  } catch (error) {
    message.error(errorMessage(error))
  }
}

function isActive(item: BenchmarkRun | BenchmarkExperimentGroup) {
  return item.status === 'queued' || item.status === 'running'
}

function selectGroup(groupId: string) {
  selectedGroupId.value = groupId
  selectedRunId.value = runsByGroup.value[groupId]?.[0]?.run_id || null
}

function groupProgress(group: BenchmarkExperimentGroup) {
  if (!group.progress_total) return 0
  return Math.min(100, Math.round((group.progress_completed / group.progress_total) * 100))
}

function completedPerformanceRuns(implementation: BenchmarkImplementationId) {
  if (!selectedGroup.value) return []
  const runIds = new Set(selectedGroup.value.runs
    .filter((item) => item.implementation === implementation && item.kind === 'performance')
    .map((item) => item.run_id))
  return selectedGroupRuns.value.filter((run) => runIds.has(run.run_id) && run.status === 'completed')
}

function completedConcurrencyRuns(implementation: BenchmarkImplementationId) {
  if (!selectedGroup.value) return []
  const runIds = new Set(selectedGroup.value.runs
    .filter((item) => item.implementation === implementation && item.kind === 'concurrency')
    .map((item) => item.run_id))
  return selectedGroupRuns.value.filter((run) => runIds.has(run.run_id) && run.status === 'completed')
}

function groupConcurrencyMean(
  implementation: BenchmarkImplementationId,
  key: 'requests_per_second' | 'output_tokens_per_second',
) {
  const values = completedConcurrencyRuns(implementation)
    .map((run) => run.concurrency?.[key])
    .filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

function groupMetricMean(implementation: BenchmarkImplementationId, key: MetricKey) {
  const values = groupMetricValues(implementation, key)
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null
}

function groupMetricStd(implementation: BenchmarkImplementationId, key: MetricKey) {
  const values = groupMetricValues(implementation, key)
  if (!values.length) return null
  const average = values.reduce((sum, value) => sum + value, 0) / values.length
  return Math.sqrt(values.reduce((sum, value) => sum + (value - average) ** 2, 0) / values.length)
}

function groupMetricValues(implementation: BenchmarkImplementationId, key: MetricKey) {
  return completedPerformanceRuns(implementation)
    .map((run) => metricMean(run, key))
    .filter((value): value is number => value !== null && Number.isFinite(value))
}

function implementationLabel(value: BenchmarkImplementationId) {
  return value === 'official' ? t('benchmark.officialImplementation') : t('benchmark.amdImplementation')
}

function kindLabel(value: BenchmarkRun['spec']['kind']) {
  if (value === 'performance') return t('benchmark.performanceKind')
  if (value === 'concurrency') return t('benchmark.concurrencyKind')
  return t('benchmark.operatorKind')
}

function runProgress(run: BenchmarkRun) {
  if (!run.progress_total) return 0
  return Math.min(100, Math.round((run.progress_completed / run.progress_total) * 100))
}

function metricStats(run: BenchmarkRun, key: MetricKey): BenchmarkMetricStats | null {
  return run.summary?.[key] || null
}

function metricMean(run: BenchmarkRun, key: MetricKey) {
  return metricStats(run, key)?.mean ?? null
}

function formatMetric(key: MetricKey, value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (key.endsWith('_ms')) return `${value.toFixed(1)} ms`
  if (key === 'peak_vram_bytes') return formatBytes(value)
  if (key.includes('utilization_percent')) return `${value.toFixed(1)}%`
  if (key.includes('power_watts')) return `${value.toFixed(1)} W`
  return `${value.toFixed(2)} tok/s`
}

function formatBytes(value: number) {
  const gib = value / 1024 ** 3
  return `${gib.toFixed(gib >= 10 ? 1 : 2)} GiB`
}

function formatTokenCount(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return Math.round(value).toLocaleString()
}

function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)}%`
}

function formatRate(value: number | null | undefined, unit: string) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(2)} ${unit}`
}

function formatMilliseconds(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)} ms`
}

function formatKernelTime(value: number) {
  if (!Number.isFinite(value)) return '—'
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)} s`
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(2)} ms`
  if (value >= 1_000) return `${(value / 1_000).toFixed(2)} μs`
  return `${value.toFixed(0)} ns`
}

function kernelDescription(descriptions: Record<string, string> | undefined): string {
  if (!descriptions) return t('benchmark.kernelDescriptionUnavailable')
  return descriptions[locale.value]
    || descriptions['zh-CN']
    || descriptions['en-US']
    || t('benchmark.kernelDescriptionUnavailable')
}

function formatFallbackReasons(reasons: Record<string, number>) {
  const entries = Object.entries(reasons)
  return entries.length ? entries.map(([reason, count]) => `${reason}: ${count}`).join(' · ') : '—'
}

function formatDispatchConfiguration(configuration: Record<string, unknown>) {
  const entries = Object.entries(configuration)
  return entries.length
    ? entries.map(([key, value]) => `${key}=${String(value)}`).join(' · ')
    : '—'
}

function formatDispatchFeatures(item: {
  has_ids: boolean
  has_fusion: boolean
  active_experts: number
  experts: number
}) {
  const features: string[] = []
  if (item.has_ids) {
    features.push(t('benchmark.moeExperts', {
      active: item.active_experts.toLocaleString(),
      total: item.experts.toLocaleString(),
    }))
  }
  if (item.has_fusion) features.push(t('benchmark.fusedDispatch'))
  return features.length ? features.join(' · ') : '—'
}

function dispatchVariantKey(item: {
  operation: string
  weight_type: string
  m: number
  n: number
  k: number
  has_ids: boolean
  has_fusion: boolean
  configuration: Record<string, unknown>
}) {
  return [
    item.operation,
    item.weight_type,
    item.m,
    item.n,
    item.k,
    item.has_ids,
    item.has_fusion,
    JSON.stringify(item.configuration),
  ].join(':')
}

function sampleProcessedPromptTokens(run: BenchmarkRun, sample: BenchmarkSample) {
  if (run.summary?.prompt_cache?.metric_version !== 'prompt_prefix_reuse.v1') return null
  if (sample.prompt_tokens === null || sample.prompt_tokens === undefined) return null
  if (sample.cache_tokens === null || sample.cache_tokens === undefined) return null
  return Math.max(0, sample.prompt_tokens - sample.cache_tokens)
}

function sampleCacheHitRate(run: BenchmarkRun, sample: BenchmarkSample) {
  if (run.summary?.prompt_cache?.metric_version !== 'prompt_prefix_reuse.v1') return null
  if (!sample.prompt_tokens || sample.cache_tokens === null || sample.cache_tokens === undefined) return null
  return Math.min(100, Math.max(0, sample.cache_tokens / sample.prompt_tokens * 100))
}

function statusLabel(status: BenchmarkRunStatus) {
  const labels: Record<BenchmarkRunStatus, string> = {
    queued: t('connection.connecting'),
    running: t('run.running'),
    completed: t('run.completed'),
    failed: t('run.failed'),
    cancelled: t('run.cancelled'),
    interrupted: t('run.interrupted'),
  }
  return labels[status]
}

function statusTagType(status: BenchmarkRunStatus): 'default' | 'info' | 'success' | 'warning' | 'error' {
  if (status === 'completed') return 'success'
  if (status === 'running' || status === 'queued') return 'info'
  if (status === 'interrupted' || status === 'cancelled') return 'warning'
  if (status === 'failed') return 'error'
  return 'default'
}

function formatDate(value: string) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatEnvironment(environment: Record<string, unknown>) {
  return JSON.stringify(environment, null, 2)
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

onMounted(async () => {
  await refresh()
  pollTimer = window.setInterval(async () => {
    if (!activeGroup.value || pollInProgress) return
    pollInProgress = true
    try {
      await refresh(false)
    } finally {
      pollInProgress = false
    }
  }, 1000)
})

onUnmounted(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
})
</script>

<style scoped>
.benchmark-view {
  container-name: benchmark;
  container-type: inline-size;
  width: 100%;
  min-width: 0;
  height: 100%;
  background: var(--app-background);
}

.context-bar {
  min-height: 78px;
  padding: var(--app-space-lg) var(--app-space-xl);
  background: var(--app-surface);
  border-bottom: 1px solid var(--app-divider);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-lg);
}

.title-line,
.run-title-line {
  display: flex;
  align-items: center;
  gap: var(--app-space-sm);
}

.title-icon {
  width: 34px;
  height: 34px;
  border-radius: var(--app-radius-md);
  color: var(--app-primary);
  background: var(--app-primary-soft);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
}

.page-title { font-size: 20px; }
.context-title { min-width: 0; }
.context-subtitle { display: block; margin-top: 4px; white-space: normal; line-height: var(--app-leading-normal); }

.benchmark-content {
  width: min(1480px, 100%);
  margin: 0 auto;
  padding: var(--app-space-xl);
  display: grid;
  gap: var(--app-space-lg);
}

.benchmark-tabs,
.benchmark-tabs :deep(.n-tabs-pane-wrapper),
.benchmark-tabs :deep(.n-tab-pane) { min-width: 0; }
.tab-stack {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--app-space-lg);
}

.panel {
  min-width: 0;
  background: var(--app-surface);
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-lg);
  padding: var(--app-space-xl);
}

.panel-heading,
.section-heading,
.progress-copy {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-lg);
}

.panel-heading { margin-bottom: var(--app-space-lg); }
.panel-heading h2,
.section-heading h3 { margin: 0; color: var(--app-text-strong); }
.panel-heading p { margin: 5px 0 0; color: var(--app-text-muted); }
.section-heading { margin: var(--app-space-xl) 0 var(--app-space-md); }
.history-heading { margin-top: 0; }
.section-heading span,
.run-time { color: var(--app-text-muted); font-size: 12px; }

.benchmark-kind-selector {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  margin: var(--app-space-lg) 0;
}
.benchmark-kind-selector > span {
  flex-shrink: 0;
  color: var(--app-text);
  font-size: var(--app-font-md);
  font-weight: 500;
}
.benchmark-kind-control { flex-shrink: 0; }
.implementation-selector {
  padding-bottom: var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}
.selector-label { min-width: 0; display: grid; gap: 3px; }
.selector-label > span { color: var(--app-text); font-size: var(--app-font-md); font-weight: 500; }
.selector-label > small { color: var(--app-text-muted); line-height: var(--app-leading-normal); }

.form-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: var(--app-space-md);
  margin-top: var(--app-space-lg);
}

.field { grid-column: span 1; display: grid; gap: 7px; min-width: 0; }
.field-wide { grid-column: span 3; }
.field-full { grid-column: 1 / -1; }
.field > span { color: var(--app-text); font-size: 12px; font-weight: 600; }
.profile-select { width: 100%; min-width: 0; max-width: 100%; }
.profile-select :deep(.n-base-selection),
.profile-select :deep(.n-base-selection-label),
.profile-select :deep(.n-base-selection-input),
.profile-select :deep(.n-base-selection-input__content) {
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
}
.profile-select :deep(.n-base-selection-input__content) {
  text-overflow: ellipsis;
  white-space: nowrap;
}
.form-actions { margin-top: var(--app-space-lg); display: flex; justify-content: flex-end; }
.qps-average-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-md);
  margin-top: var(--app-space-md);
  color: var(--app-text-muted);
  font-size: 12px;
}
.qps-average-row strong { color: var(--app-text-strong); margin-left: 4px; }
.group-average-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--app-space-md);
  margin-top: var(--app-space-lg);
}
.group-average-card {
  min-width: 0;
  padding: var(--app-space-md);
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-subtle);
}
.compact-metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)) !important; }
.compact-metric-grid .metric-card { padding: var(--app-space-md); }
.compact-metric-grid .metric-value { font-size: 18px; }
.group-run-selector { margin-top: var(--app-space-lg); }

.run-progress {
  padding: var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.progress-copy { margin-bottom: 8px; }
.run-error { margin-top: var(--app-space-md); }
.cache-legacy-warning,
.operator-warning { margin-top: var(--app-space-md); }

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-space-md);
}
.cache-metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }

.metric-card {
  min-width: 0;
  padding: var(--app-space-lg);
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.metric-label { color: var(--app-text-muted); font-size: 12px; }
.metric-value { display: block; margin-top: 8px; font-size: 24px; color: var(--app-text-strong); }
.metric-detail { margin-top: 10px; display: flex; flex-wrap: wrap; gap: var(--app-space-xs) var(--app-space-md); color: var(--app-text-muted); font-size: 11px; }

.sample-table-wrap {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-md);
}
.sample-table { width: 100%; border-collapse: collapse; white-space: nowrap; }
.sample-table th,
.sample-table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--app-divider); }
.sample-table th { background: var(--app-surface-muted); color: var(--app-text-muted); font-size: 12px; }
.sample-table tr:last-child td { border-bottom: 0; }

.operator-phase { margin-top: var(--app-space-xl); }
.operator-table-wrap {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-md);
}
.graph-table-wrap { margin-top: var(--app-space-md); }
.dispatch-variant-table-wrap { margin-top: var(--app-space-md); }
.dispatch-variant-table { min-width: 1180px !important; }
.dispatch-configuration { min-width: 300px; max-width: 520px; white-space: normal; overflow-wrap: anywhere; }
.operator-table-wrap .sample-table { min-width: 680px; }
.kernel-name { min-width: 260px; max-width: 640px; white-space: normal; overflow-wrap: anywhere; }
.kernel-display-name {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--app-text-strong);
  cursor: help;
}
.kernel-info-icon { flex: 0 0 auto; color: var(--app-text-muted); font-size: 15px; }
.kernel-description { max-width: 400px; white-space: normal; line-height: 1.6; }
.kernel-id {
  display: block;
  margin-top: 4px;
  color: var(--app-text-muted);
  font-size: 11px;
  white-space: normal;
  overflow-wrap: anywhere;
}
.kernel-variants { margin-top: 6px; color: var(--app-text-muted); font-size: 11px; }
.kernel-variants summary { cursor: pointer; user-select: none; }
.kernel-variants code {
  display: block;
  margin-top: 6px;
  padding: 6px 8px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  white-space: normal;
  overflow-wrap: anywhere;
}
.graph-empty {
  margin-top: var(--app-space-md);
  padding: var(--app-space-lg);
  border: 1px dashed var(--app-border);
  border-radius: var(--app-radius-md);
}

.environment-collapse { margin-top: var(--app-space-lg); }
.environment-collapse pre {
  max-height: 420px;
  overflow: auto;
  margin: 0;
  padding: var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text);
  font-size: 12px;
}

.history-list { display: grid; gap: 8px; }
.history-item {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(240px, 1fr) minmax(180px, auto) auto auto auto;
  align-items: center;
  gap: var(--app-space-md);
  padding: 12px;
  border: 1px solid var(--app-divider);
  border-radius: var(--app-radius-md);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
}
.history-item:hover,
.history-item.is-selected { background: var(--app-surface-muted); border-color: var(--app-primary); }
.history-main { display: grid; gap: 3px; min-width: 0; }
.history-main strong,
.history-main small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.history-main small,
.history-date { color: var(--app-text-muted); }
.history-metrics { display: flex; gap: var(--app-space-md); font-variant-numeric: tabular-nums; }

@container benchmark (max-width: 1100px) {
  .form-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .field, .field-wide { grid-column: span 1; }
  .field-full { grid-column: 1 / -1; }
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .group-average-grid { grid-template-columns: 1fr; }
  .history-item { grid-template-columns: minmax(0, 1fr) auto auto; }
  .history-main { grid-column: 1; }
  .history-metrics { grid-column: 1 / -1; grid-row: 2; flex-wrap: wrap; }
  .history-date { grid-column: 1 / -1; grid-row: 3; font-size: var(--app-font-xs); }
}

@container benchmark (max-width: 700px) {
  .context-bar { align-items: flex-start; flex-wrap: wrap; padding: var(--app-space-md); }
  .context-bar > .n-button { margin-left: 42px; }
  .benchmark-content { padding: var(--app-space-md); }
  .panel { padding: var(--app-space-md); }
  .panel-heading,
  .section-heading,
  .progress-copy { align-items: flex-start; flex-wrap: wrap; }
  .benchmark-kind-selector { align-items: stretch; flex-direction: column; }
  .form-grid, .metric-grid { grid-template-columns: 1fr; }
  .compact-metric-grid { grid-template-columns: 1fr !important; }
  .field, .field-wide, .field-full { grid-column: 1; }
  .sample-table th,
  .sample-table td { padding: 8px 10px; }
  .history-item { grid-template-columns: minmax(0, 1fr) auto; gap: var(--app-space-sm); }
  .history-main { grid-column: 1 / -1; }
  .history-metrics { grid-column: 1 / -1; }
  .history-date { grid-column: 1 / -1; }
}

@container benchmark (max-width: 420px) {
  .context-bar > .n-button { width: 100%; margin-left: 0; }
  .benchmark-content { padding: var(--app-space-sm); }
  .panel { padding: var(--app-space-sm); }
  .metric-value { font-size: 20px; overflow-wrap: anywhere; }
  .form-actions > .n-button { width: 100%; }
}
</style>

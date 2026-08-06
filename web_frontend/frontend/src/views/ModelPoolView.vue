<template>
  <div class="local-model-view app-scroll-y">
    <div class="context-bar">
      <div class="context-title">
        <div class="title-line">
          <span class="title-icon"><n-icon><HardwareChipOutline /></n-icon></span>
          <n-text strong class="page-title">{{ t('localModel.title') }}</n-text>
        </div>
        <n-text depth="3" class="context-subtitle">{{ t('localModel.subtitle') }}</n-text>
      </div>
      <n-button secondary :loading="loading" @click="refresh">
        <template #icon><n-icon><Refresh /></n-icon></template>
        {{ t('common.refresh') }}
      </n-button>
    </div>

    <section class="overview-grid">
      <article class="overview-card runtime-card" :class="rocm?.available ? 'is-ready' : 'is-warning'">
        <div class="overview-icon"><n-icon><HardwareChipOutline /></n-icon></div>
        <div class="overview-copy">
          <div class="overview-label">{{ t('localModel.rocmRuntime') }}</div>
          <div v-if="rocm?.available" class="overview-value">
            ROCm {{ rocm.rocm_version || '—' }}
          </div>
          <div v-else class="overview-value">{{ t('localModel.rocmUnchecked') }}</div>
          <div v-if="rocm?.available" class="overview-detail">
            PyTorch {{ rocm.torch_version }} · HIP {{ rocm.hip_version }} ·
            {{ t('localModel.deviceCount', { count: rocm.device_count }) }}
          </div>
          <div v-else class="overview-detail">{{ rocm?.error || t('localModel.rocmUnchecked') }}</div>
          <div v-if="rocm?.available && rocm.devices.length" class="runtime-device-list">
            <div v-for="device in rocm.devices" :key="device.index" class="runtime-device">
              <div class="runtime-device-heading">
                <strong>{{ device.name }}</strong>
                <span>{{ device.pci_bus || `GPU ${device.index}` }}</span>
              </div>
              <div class="runtime-metrics">
                <span :title="gpuUtilizationSourceLabel(device.gpu_utilization_source)">
                  {{ t('localModel.gpuBusy') }} {{ formatPercent(device.gpu_utilization_percent) }}
                  <small v-if="device.gpu_utilization_source">· {{ gpuUtilizationSourceLabel(device.gpu_utilization_source) }}</small>
                </span>
                <span v-if="device.memory_activity_percent !== null && device.memory_activity_percent !== undefined">
                  {{ t('localModel.memoryActivity') }} {{ formatPercent(device.memory_activity_percent) }}
                </span>
                <span>{{ t('localModel.vramUsage') }} {{ formatMemoryUsage(device) }}</span>
                <span>{{ t('localModel.gpuTemperature') }} {{ formatTemperature(device.temperature_hotspot_celsius) }}</span>
                <span>{{ t('localModel.gpuPower') }} {{ formatPower(device.power_watts) }}</span>
                <span v-if="device.architecture">{{ device.architecture }}</span>
                <span v-if="device.compute_units">{{ device.compute_units }} CU</span>
                <span v-if="device.vram_type">{{ device.vram_type }}</span>
              </div>
            </div>
          </div>
        </div>
        <span class="status-dot" aria-hidden="true" />
      </article>

      <article class="overview-card">
        <div class="overview-icon"><n-icon><LayersOutline /></n-icon></div>
        <div class="overview-copy">
          <div class="overview-label">{{ t('localModel.profiles') }}</div>
          <div class="overview-value">{{ profiles.length }}</div>
          <div class="overview-detail">{{ t('localModel.profileHint') }}</div>
        </div>
      </article>

      <article class="overview-card">
        <div class="overview-icon"><n-icon><FolderOpenOutline /></n-icon></div>
        <div class="overview-copy">
          <div class="overview-label">{{ t('localModel.artifacts') }}</div>
          <div class="overview-value">{{ artifacts.length }}</div>
          <div class="overview-detail">{{ t('localModel.artifactHint') }}</div>
        </div>
      </article>
    </section>

    <section class="model-panel">
      <n-alert v-if="modelStorage?.remote_error" type="warning" :show-icon="true" class="remote-endpoint-alert">
        {{ modelStorage.remote_error }}
      </n-alert>
      <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="profiles" :tab="t('localModel.profiles')">
        <div class="tab-content">
          <div class="content-header">
            <div>
              <n-text strong class="section-title">{{ t('localModel.profiles') }}</n-text>
              <div class="section-description">{{ t('localModel.profileHint') }}</div>
            </div>
            <n-button type="primary" :disabled="!artifacts.length" @click="openProfile()">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ t('localModel.addProfile') }}
            </n-button>
          </div>
          <div v-if="profiles.length" class="resource-grid">
            <article v-for="profile in profiles" :key="profile.profile_id" class="resource-card">
              <header class="resource-header">
                <div class="resource-identity">
                  <span class="resource-icon"><n-icon><CubeOutline /></n-icon></span>
                  <div class="resource-title-block">
                    <div class="resource-title">{{ profile.display_name }}</div>
                    <div class="resource-id">{{ profile.profile_id }}</div>
                  </div>
                </div>
                <div class="profile-status-tags">
                  <n-tag size="small" :bordered="false" :type="profile.enabled ? 'success' : 'default'">
                    {{ profile.enabled ? t('common.enabled') : t('common.disabled') }}
                  </n-tag>
                  <n-tag size="small" :bordered="false" :type="runtimeTagType(profile)">
                    {{ runtimePhaseLabel(profile) }}
                  </n-tag>
                </div>
              </header>

              <div class="tag-row">
                <n-tag size="small" :bordered="false">{{ kindLabel(profile.kind) }}</n-tag>
                <n-tag size="small" :bordered="false" type="info">{{ engineLabel(profile.engine) }}</n-tag>
                <n-tag v-if="profile.capabilities.input_modalities.includes('image')" size="small" :bordered="false" type="success">
                  {{ t('localModel.imageInput') }}
                </n-tag>
                <n-tag
                  v-for="role in profileDefaultRoles(profile.profile_id)"
                  :key="role"
                  size="small"
                  :bordered="false"
                  type="success"
                >
                  {{ defaultRoleLabel(role) }}
                </n-tag>
              </div>

              <div class="model-name">{{ profile.served_model_name }}</div>
              <div class="path-line" :title="artifactLocation(profile.artifact)">
                <n-icon><FolderOpenOutline /></n-icon>
                <span>{{ artifactLocation(profile.artifact) }}</span>
              </div>

              <div v-if="profileRuntime(profile)" class="profile-runtime-panel">
                <div class="profile-runtime-heading">
                  <span>{{ runtimeStageLabel(profileRuntime(profile)?.stage) }}</span>
                  <strong>{{ rocm?.devices?.[0] ? formatMemoryUsage(rocm.devices[0]) : '—' }}</strong>
                </div>
                <n-progress
                  v-if="isRuntimeTransitioning(profile)"
                  type="line"
                  :percentage="profileRuntime(profile)?.progress_percent ?? 0"
                  :processing="profileRuntime(profile)?.progress_percent == null"
                  :show-indicator="profileRuntime(profile)?.progress_percent != null"
                  status="info"
                />
                <div v-if="profileRuntime(profile)?.error" class="runtime-error">
                  {{ profileRuntime(profile)?.error }}
                </div>
              </div>

              <div class="spec-grid">
                <template v-if="profile.kind === 'chat'">
                  <div class="spec-item"><span>{{ t('localModel.gpuLayers') }}</span><strong>{{ chatRuntimeConfiguration(profile)?.gpu_layers ?? '—' }}</strong></div>
                  <div class="spec-item"><span>{{ t('localModel.parallelSlots') }}</span><strong>{{ chatRuntimeConfiguration(profile)?.parallel_slots ?? '—' }}</strong></div>
                  <div class="spec-item"><span>{{ t('localModel.totalContextBudget') }}</span><strong>{{ formatTokens(profileTotalContextTokens(profile)) }}</strong></div>
                  <div class="spec-item"><span>{{ t('localModel.kvCache') }}</span><strong>{{ chatRuntimeConfiguration(profile)?.cache_type_k || '—' }} / {{ chatRuntimeConfiguration(profile)?.cache_type_v || '—' }}</strong></div>
                  <div class="spec-item"><span>MTP</span><strong>{{ chatRuntimeConfiguration(profile)?.speculative_decoding?.method === 'mtp' ? t('common.enabled') : t('common.disabled') }}</strong></div>
                </template>
                <template v-else-if="profile.kind === 'image_generation'">
                  <div class="spec-item"><span>默认尺寸</span><strong>{{ imageRuntimeConfiguration(profile)?.default_width }} × {{ imageRuntimeConfiguration(profile)?.default_height }}</strong></div>
                  <div class="spec-item"><span>采样步数</span><strong>{{ imageRuntimeConfiguration(profile)?.default_steps ?? '—' }}</strong></div>
                  <div class="spec-item"><span>驻留策略</span><strong>{{ imageRuntimeConfiguration(profile)?.residency_policy || '—' }}</strong></div>
                </template>
                <div v-else class="spec-item"><span>{{ t('localModel.embeddingDimensions') }}</span><strong>{{ profile.embedding_dimensions || '—' }}</strong></div>
                <div class="spec-item"><span>{{ t('modelPool.maxInput') }}</span><strong>{{ formatTokens(profile.limits.max_input_tokens) }}</strong></div>
              </div>

              <div
                v-if="profileMemoryEstimate(profile)"
                class="memory-budget-card"
                :class="memoryBudgetClass(profileMemoryEstimate(profile))"
              >
                <div class="memory-budget-heading">
                  <strong>{{ t('localModel.memoryBudget') }}</strong>
                  <span>{{ memoryFitLabel(profileMemoryEstimate(profile)) }}</span>
                </div>
                <div class="memory-budget-metrics">
                  <span>{{ t('localModel.kvEstimate') }} <strong>{{ formatBytes(profileMemoryEstimate(profile)?.kv_cache_bytes) }}</strong></span>
                  <span>{{ t('localModel.projectedVram') }} <strong>{{ formatBytes(profileMemoryEstimate(profile)?.projected_used_bytes) }}</strong></span>
                  <span>{{ t('localModel.remainingVram') }} <strong>{{ formatBytes(profileMemoryEstimate(profile)?.remaining_memory_bytes) }}</strong></span>
                </div>
              </div>

              <footer class="resource-actions">
                <div class="resource-action-group">
                  <n-button
                    v-if="profileRuntime(profile)?.phase === 'ready'"
                    size="small"
                    secondary
                    @click="restartProfile(profile)"
                  >
                    {{ t('localModel.restart') }}
                  </n-button>
                  <n-button
                    v-if="profileRuntime(profile)?.phase === 'ready'"
                    size="small"
                    secondary
                    @click="unloadProfile(profile)"
                  >
                    {{ t('localModel.unload') }}
                  </n-button>
                  <n-button
                    v-else
                    size="small"
                    secondary
                    :disabled="!profile.enabled"
                    :loading="isRuntimeTransitioning(profile)"
                    @click="loadProfile(profile)"
                  >
                    {{ t('localModel.load') }}
                  </n-button>
                  <n-dropdown
                    trigger="click"
                    :options="defaultRoleOptions(profile)"
                    @select="(role: string | number) => handleDefaultRoleSelect(role, profile)"
                  >
                    <n-button size="small" quaternary :disabled="profileRuntime(profile)?.phase !== 'ready'">
                      {{ t('localModel.setDefault') }}
                    </n-button>
                  </n-dropdown>
                </div>
                <div class="resource-action-group resource-management-actions">
                  <n-button size="small" quaternary @click="openProfile(profile)">{{ t('common.edit') }}</n-button>
                  <n-button size="small" type="error" quaternary @click="removeProfile(profile)">{{ t('common.delete') }}</n-button>
                </div>
              </footer>
            </article>
          </div>
          <div v-else class="empty-panel">
            <span class="empty-icon"><n-icon><LayersOutline /></n-icon></span>
            <n-text strong>{{ t('localModel.noProfiles') }}</n-text>
            <p>{{ t('localModel.profileHint') }}</p>
            <n-button type="primary" @click="openProfileEmptyAction">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ artifacts.length ? t('localModel.addProfile') : t('localModel.addArtifact') }}
            </n-button>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="artifacts" :tab="t('localModel.artifacts')">
        <div class="tab-content">
          <div class="content-header">
            <div>
              <n-text strong class="section-title">{{ t('localModel.artifacts') }}</n-text>
              <div class="section-description">{{ t('localModel.artifactHint') }}</div>
              <div v-if="modelStorage?.inference_mode !== 'external'" class="storage-root">
                <span>{{ t('localModel.storageRoot') }}</span>
                <code>{{ modelStorage?.root_path || '—' }}</code>
              </div>
              <div v-else class="storage-root">
                <span>{{ t('localModel.runtimeMode') }}</span>
                <code>{{ t('localModel.externalEndpoint') }}</code>
              </div>
            </div>
            <n-button type="primary" @click="openArtifact()">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ t('localModel.addArtifact') }}
            </n-button>
          </div>
          <div v-if="artifacts.length" class="resource-grid">
            <article v-for="artifact in artifacts" :key="artifact.artifact_id" class="resource-card artifact-card">
              <header class="resource-header">
                <div class="resource-identity">
                  <span class="resource-icon"><n-icon><FolderOpenOutline /></n-icon></span>
                  <div class="resource-title-block">
                    <div class="resource-title">{{ artifact.display_name }}</div>
                    <div class="resource-id">{{ artifact.artifact_id }}</div>
                  </div>
                </div>
                <n-tag size="small" :bordered="false" :type="artifact.enabled ? 'success' : 'default'">
                  {{ artifact.enabled ? t('common.enabled') : t('common.disabled') }}
                </n-tag>
              </header>

              <div class="tag-row">
                <n-tag size="small" :bordered="false">{{ kindLabel(artifact.kind) }}</n-tag>
                <n-tag size="small" :bordered="false" type="info">{{ artifact.model_format }}</n-tag>
                <n-tag v-if="artifact.revision" size="small" :bordered="false">{{ artifact.revision }}</n-tag>
                <n-tag v-if="artifact.native_context_tokens" size="small" :bordered="false">
                  {{ t('localModel.nativeContext') }} {{ formatTokens(artifact.native_context_tokens) }}
                </n-tag>
                <n-tag v-if="artifact.context_extension" size="small" :bordered="false" type="success">
                  YaRN → {{ formatTokens(artifact.context_extension.max_context_tokens) }}
                </n-tag>
              </div>

              <div class="path-block" :title="artifactLocation(artifact)">
                <span>{{ artifact.source === 'external_endpoint' ? t('localModel.remoteModel') : t('localModel.localPath') }}</span>
                <code>{{ artifactLocation(artifact) }}</code>
              </div>
              <div v-if="artifact.checksum" class="checksum-line">
                <span>{{ t('localModel.checksum') }}</span>
                <code>{{ artifact.checksum }}</code>
              </div>

              <footer class="resource-actions">
                <div class="resource-action-group resource-management-actions">
                  <n-button size="small" quaternary @click="openArtifact(artifact)">{{ t('common.edit') }}</n-button>
                  <n-button size="small" type="error" quaternary @click="removeArtifact(artifact)">{{ t('common.delete') }}</n-button>
                </div>
              </footer>
            </article>
          </div>
          <div v-else class="empty-panel">
            <span class="empty-icon"><n-icon><FolderOpenOutline /></n-icon></span>
            <n-text strong>{{ t('localModel.noArtifacts') }}</n-text>
            <p>{{ t('localModel.artifactHint') }}</p>
            <n-button type="primary" @click="openArtifact()">
              <template #icon><n-icon><Add /></n-icon></template>
              {{ t('localModel.addArtifact') }}
            </n-button>
          </div>
        </div>
      </n-tab-pane>
      <n-tab-pane name="usage" :tab="t('modelPool.usage')">
        <div class="tab-content usage-report">
          <div class="content-header">
            <n-space align="center" wrap>
              <n-radio-group v-model:value="usageGroupBy" class="soft-segmented-control" @update:value="refreshUsage">
                <n-radio-button value="model">{{ t('modelPool.usageByModel') }}</n-radio-button>
                <n-radio-button value="provider">{{ t('modelPool.usageByProvider') }}</n-radio-button>
                <n-radio-button value="agent">{{ t('modelPool.usageByAgent') }}</n-radio-button>
              </n-radio-group>
              <n-radio-group v-model:value="usageChartType" class="soft-segmented-control">
                <n-radio-button value="line">{{ t('modelPool.usageLineChart') }}</n-radio-button>
                <n-radio-button value="bar">{{ t('modelPool.usageBarChart') }}</n-radio-button>
              </n-radio-group>
              <n-select
                v-model:value="usageDays"
                class="usage-range-select"
                :options="usageDayOptions"
                @update:value="refreshUsage"
              />
            </n-space>
            <n-button :loading="usageLoading" @click="refreshUsage">
              <template #icon><n-icon><Refresh /></n-icon></template>
              {{ t('common.refresh') }}
            </n-button>
          </div>

          <div class="usage-overview">
            <div class="usage-metric">
              <span>{{ t('modelPool.usageCalls') }}</span>
              <strong>{{ formatNumber(usageSummary?.totals.call_count || 0) }}</strong>
            </div>
            <div class="usage-metric">
              <span>{{ t('modelPool.usageTotalTokens') }}</span>
              <strong>{{ formatUsageTokens(usageSummary?.totals.total_tokens || 0) }}</strong>
            </div>
            <div class="usage-metric">
              <span>{{ t('modelPool.usageCacheHit') }}</span>
              <strong>{{ formatUsagePercent(usageSummary?.totals.cache_hit_ratio) }}</strong>
            </div>
            <div class="usage-metric">
              <span>{{ t('modelPool.usageCost') }}</span>
              <strong>{{ formatCost(usageSummary?.totals.estimated_cost) }}</strong>
            </div>
          </div>

          <div class="usage-chart-panel">
            <v-chart v-if="usageSummary?.series.length" class="usage-chart" :option="usageChartOptions" autoresize />
            <n-empty v-else class="manager-empty" :description="t('modelPool.noUsage')" />
          </div>

          <n-data-table
            :columns="usageColumns"
            :data="usageSummary?.groups || []"
            :loading="usageLoading"
            :row-key="usageRowKey"
            size="small"
          />
        </div>
      </n-tab-pane>
      </n-tabs>
    </section>

    <n-modal v-model:show="artifactModalOpen" preset="dialog" :title="t('localModel.artifactEditor')">
      <n-form
        ref="artifactFormRef"
        :model="artifactForm"
        :rules="artifactRules"
        label-placement="top"
      >
        <n-form-item :label="t('localModel.displayName')" path="display_name"><n-input v-model:value="artifactForm.display_name" /></n-form-item>
        <n-form-item :label="t('localModel.kind')" path="kind">
          <n-select v-model:value="artifactForm.kind" :options="kindOptions" @update:value="syncArtifactKind" />
        </n-form-item>
        <n-form-item v-if="externalInference" :label="t('localModel.remoteModel')" path="external_model_id">
          <n-select
            v-model:value="artifactForm.external_model_id"
            :options="remoteModelOptions"
            :placeholder="t('localModel.remoteModelPlaceholder')"
            filterable
            @update:value="syncRemoteModel"
          />
        </n-form-item>
        <div v-if="externalInference && selectedRemoteModel" class="model-directory-summary">
          <div class="model-directory-heading">
            <strong>{{ selectedRemoteModel.model_id }}</strong>
            <span>{{ kindLabel(selectedRemoteModel.kind) }}</span>
            <span v-if="selectedRemoteModel.format">{{ selectedRemoteModel.format }}</span>
            <span v-if="selectedRemoteModel.context_length">{{ formatTokens(selectedRemoteModel.context_length) }} context</span>
            <span v-if="selectedRemoteModel.embedding_dimensions">{{ selectedRemoteModel.embedding_dimensions }}D</span>
          </div>
          <code>{{ formatBytes(selectedRemoteModel.size_bytes) }}</code>
        </div>
        <n-form-item v-if="!externalInference" :label="t('localModel.detectedDirectory')" path="local_path">
          <n-select
            v-model:value="artifactForm.local_path"
            :options="modelDirectoryOptions"
            :placeholder="t('localModel.detectedDirectoryPlaceholder')"
            filterable
          />
        </n-form-item>
        <div v-if="selectedModelDirectory" class="model-directory-summary">
          <div class="model-directory-heading">
            <strong>{{ selectedModelDirectory.display_name }}</strong>
            <span v-if="selectedModelDirectory.model_type">{{ selectedModelDirectory.model_type }}</span>
            <span v-if="selectedModelDirectory.dtype">{{ selectedModelDirectory.dtype }}</span>
            <span v-for="architecture in selectedModelDirectory.architectures" :key="architecture">
              {{ architecture }}
            </span>
          </div>
          <code :title="selectedModelDirectory.relative_path">{{ selectedModelDirectory.relative_path }}</code>
        </div>
        <div v-if="!externalInference" class="storage-hint">
          {{ t('localModel.modelscopeCache') }}：<code>{{ modelStorage?.modelscope_cache_path || '—' }}</code>
        </div>
        <template v-if="artifactForm.kind === 'chat'">
          <n-form-item
            :label="t('localModel.nativeContext')"
            :feedback="t('localModel.nativeContextHint')"
          >
            <n-input-number v-model:value="artifactForm.native_context_tokens" :min="1" clearable />
          </n-form-item>
          <n-checkbox v-model:checked="artifactForm.supports_yarn">
            {{ t('localModel.supportsYarn') }}
          </n-checkbox>
          <n-form-item
            v-if="artifactForm.supports_yarn"
            :label="t('localModel.yarnMaxContext')"
            :feedback="t('localModel.yarnMaxContextHint')"
          >
            <n-input-number
              v-model:value="artifactForm.yarn_max_context_tokens"
              :min="(artifactForm.native_context_tokens || 0) + 1"
              clearable
            />
          </n-form-item>
        </template>
        <n-checkbox v-model:checked="artifactForm.enabled">{{ t('common.enabled') }}</n-checkbox>
      </n-form>
      <template #action>
        <n-button @click="artifactModalOpen = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="saving" @click="saveArtifact">{{ t('common.save') }}</n-button>
      </template>
    </n-modal>

    <n-modal v-model:show="profileModalOpen" preset="dialog" :title="t('localModel.profileEditor')" style="width: min(760px, 92vw)">
      <n-form
        ref="profileFormRef"
        :model="profileForm"
        :rules="profileRules"
        label-placement="top"
      >
        <n-form-item :label="t('localModel.displayName')" path="display_name"><n-input v-model:value="profileForm.display_name" /></n-form-item>
        <n-form-item :label="t('common.description')">
          <n-input
            v-model:value="profileForm.description"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="说明模型适合的场景、语言、提示词要求和能力边界，供制造链选择模型时参考"
          />
        </n-form-item>
        <n-form-item :label="t('localModel.artifact')" path="artifact_id">
          <n-select v-model:value="profileForm.artifact_id" :options="artifactOptions" @update:value="syncProfileKind" />
        </n-form-item>
        <n-form-item :label="t('localModel.servedModelName')" path="served_model_name"><n-input v-model:value="profileForm.served_model_name" /></n-form-item>
        <div class="form-grid">
          <n-form-item v-if="profileForm.kind === 'chat'" :label="t('localModel.gpuLayers')">
            <n-input-number v-model:value="profileForm.gpu_layers" :min="0" />
          </n-form-item>
          <n-form-item
            v-if="profileForm.kind === 'chat'"
            :label="t('localModel.parallelSlots')"
            :feedback="t('localModel.parallelSlotsHint')"
          >
            <n-input-number v-model:value="profileForm.parallel_slots" :min="1" />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat'" :label="t('localModel.kCacheType')">
            <n-select v-model:value="profileForm.cache_type_k" :options="cacheTypeOptions" />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat'" :label="t('localModel.vCacheType')">
            <n-select v-model:value="profileForm.cache_type_v" :options="cacheTypeOptions" />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxInput')">
            <n-input-number v-model:value="profileForm.max_input_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item :label="t('modelPool.maxOutput')">
            <n-input-number v-model:value="profileForm.max_output_tokens" :min="1" clearable />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat'" :label="t('localModel.contextCompressionThreshold')">
            <n-input-number v-model:value="profileForm.context_compression_threshold_tokens" :min="1000" clearable />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat'" :label="t('modelPool.temperature')">
            <n-input-number
              v-model:value="profileForm.temperature"
              :min="0"
              :step="0.1"
              clearable
              :placeholder="t('modelPool.providerDefault')"
            />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat' && profileForm.mtp_enabled" :label="t('localModel.mtpMaxDraftTokens')">
            <n-input-number v-model:value="profileForm.mtp_max_draft_tokens" :min="1" :max="32" />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'chat' && profileForm.mtp_enabled" :label="t('localModel.mtpMinAcceptanceProbability')">
            <n-input-number v-model:value="profileForm.mtp_min_acceptance_probability" :min="0" :max="1" :step="0.05" />
          </n-form-item>
          <n-form-item v-if="profileForm.kind === 'embedding'" :label="t('localModel.embeddingDimensions')">
            <n-input-number v-model:value="profileForm.embedding_dimensions" :min="1" />
          </n-form-item>
          <template v-if="profileForm.kind === 'image_generation'">
            <n-form-item label="默认宽度"><n-input-number v-model:value="profileForm.default_width" :min="64" :step="64" /></n-form-item>
            <n-form-item label="默认高度"><n-input-number v-model:value="profileForm.default_height" :min="64" :step="64" /></n-form-item>
            <n-form-item label="采样步数"><n-input-number v-model:value="profileForm.default_steps" :min="1" :max="200" /></n-form-item>
            <n-form-item label="CFG Scale"><n-input-number v-model:value="profileForm.default_cfg_scale" :min="0" :max="30" :step="0.1" /></n-form-item>
            <n-form-item label="显存驻留策略">
              <n-select v-model:value="profileForm.residency_policy" :options="residencyPolicyOptions" />
            </n-form-item>
          </template>
        </div>
        <div v-if="profileForm.kind === 'chat'" class="memory-preview" :class="memoryBudgetClass(memoryEstimate)">
          <div class="memory-budget-heading">
            <strong>{{ t('localModel.memoryBudget') }}</strong>
            <n-spin v-if="memoryEstimateLoading" size="small" />
            <span v-else>{{ memoryFitLabel(memoryEstimate) }}</span>
          </div>
          <div v-if="memoryEstimate?.available" class="memory-preview-grid">
            <div><span>{{ t('localModel.modelAllocation') }}</span><strong>{{ formatBytes(memoryEstimate.model_allocation_bytes) }}</strong></div>
            <div><span>{{ t('localModel.kvEstimate') }}</span><strong>{{ formatBytes(memoryEstimate.kv_cache_bytes) }}</strong></div>
            <div><span>{{ t('localModel.perSlotContext') }}</span><strong>{{ formatTokens(memoryEstimate.context_tokens) }}</strong></div>
            <div><span>{{ t('localModel.estimatedParallelSlots') }}</span><strong>{{ memoryEstimate.parallel_slots }}</strong></div>
            <div><span>{{ t('localModel.totalContextBudget') }}</span><strong>{{ formatTokens(memoryEstimate.total_context_tokens) }}</strong></div>
            <div><span>{{ t('localModel.nativeContext') }}</span><strong>{{ formatTokens(memoryEstimate.native_context_tokens) }}</strong></div>
            <div>
              <span>{{ t('localModel.ropeScaling') }}</span>
              <strong v-if="memoryEstimate.rope_scaling_method">
                {{ memoryEstimate.rope_scaling_method.toUpperCase() }} × {{ formatScalingFactor(memoryEstimate.rope_scaling_factor) }}
              </strong>
              <strong v-else>{{ t('localModel.nativeContextMode') }}</strong>
            </div>
            <div><span>{{ t('localModel.projectedVram') }}</span><strong>{{ formatBytes(memoryEstimate.projected_used_bytes) }} / {{ formatBytes(memoryEstimate.total_memory_bytes) }}</strong></div>
            <div><span>{{ t('localModel.remainingVram') }}</span><strong>{{ formatBytes(memoryEstimate.remaining_memory_bytes) }}</strong></div>
          </div>
          <p v-else-if="memoryEstimate?.error">{{ memoryEstimate.error }}</p>
          <p v-else>{{ t('localModel.memoryEstimatePending') }}</p>
        </div>
        <n-space vertical>
          <n-checkbox v-model:checked="profileForm.enabled">{{ t('localModel.loadWhenEnabled') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat'" v-model:checked="profileForm.flash_attention">{{ t('localModel.flashAttention') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat'" v-model:checked="profileForm.mtp_enabled">{{ t('localModel.mtpEnabled') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat' && profileForm.mtp_enabled" v-model:checked="profileForm.mtp_backend_sampling">{{ t('localModel.mtpBackendSampling') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'embedding'" v-model:checked="profileForm.trust_remote_code">{{ t('localModel.trustRemoteCode') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat'" v-model:checked="profileForm.tool_calling">{{ t('modelPool.toolCalling') }}</n-checkbox>
          <n-checkbox
            v-if="profileForm.kind === 'chat' && profileSupportsImage"
            v-model:checked="profileForm.image_input"
          >
            {{ t('localModel.imageInput') }}
          </n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'chat'" v-model:checked="profileForm.reasoning_supported">{{ t('modelPool.reasoning') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'embedding'" v-model:checked="profileForm.normalize_embeddings">{{ t('localModel.normalizeEmbeddings') }}</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'image_generation'" v-model:checked="profileForm.diffusion_flash_attention">Diffusion Flash Attention</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'image_generation'" v-model:checked="profileForm.eager_load">启动时预加载模型</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'image_generation'" v-model:checked="profileForm.clip_on_cpu">CLIP / T5 使用 CPU</n-checkbox>
          <n-checkbox v-if="profileForm.kind === 'image_generation'" v-model:checked="profileForm.vae_tiling">VAE Tiling</n-checkbox>
        </n-space>
      </n-form>
      <template #action>
        <n-button @click="profileModalOpen = false">{{ t('common.cancel') }}</n-button>
        <n-button type="primary" :loading="saving" @click="saveProfile">{{ t('common.save') }}</n-button>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { use } from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import {
  useDialog,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { storeToRefs } from 'pinia'
import { useI18n } from '@/composables/useI18n'
import { useModelPoolStore } from '@/stores/modelPool'
import {
  Add,
  CubeOutline,
  FolderOpenOutline,
  HardwareChipOutline,
  LayersOutline,
  Refresh,
} from '@/components/icons'
import {
  modelPoolApi,
  type LocalModelArtifact,
  type LocalModelArtifactWritePayload,
  type LocalModelDefaultRole,
  type LocalModelStorage,
  type LocalModelKind,
  type LocalModelProfile,
  type LocalModelRuntime,
  type InferenceMemoryEstimate,
  type LlamaCppRuntimeConfiguration,
  type LlamaCppMtpConfiguration,
  type StableDiffusionCppRuntimeConfiguration,
  type RocmRuntimeInfo,
  type ModelUsageGroup,
  type ModelUsageGroupBy,
  type ModelUsageSummary,
} from '@/api/modelPool'
import {
  requiredTextRule,
  requiredValueRule,
  validateForm,
} from '@/utils/formValidation'

use([BarChart, CanvasRenderer, GridComponent, LegendComponent, LineChart, TooltipComponent])

const { t } = useI18n()
const dialog = useDialog()
const message = useMessage()
const modelPoolStore = useModelPoolStore()
const { defaults, profiles } = storeToRefs(modelPoolStore)
const loading = ref(false)
const saving = ref(false)
const runtimeRefreshing = ref(false)
const activeTab = ref<'profiles' | 'artifacts' | 'usage'>('profiles')
const artifacts = ref<LocalModelArtifact[]>([])
const runtimes = ref<LocalModelRuntime[]>([])
const rocm = ref<RocmRuntimeInfo | null>(null)
const modelStorage = ref<LocalModelStorage | null>(null)
const artifactModalOpen = ref(false)
const profileModalOpen = ref(false)
const artifactFormRef = ref<FormInst | null>(null)
const profileFormRef = ref<FormInst | null>(null)
const artifactEditing = ref<LocalModelArtifact | null>(null)
const profileEditing = ref<LocalModelProfile | null>(null)
const memoryEstimate = ref<InferenceMemoryEstimate | null>(null)
const memoryEstimateLoading = ref(false)
const usageLoading = ref(false)
const usageSummary = ref<ModelUsageSummary | null>(null)
const usageGroupBy = ref<ModelUsageGroupBy>('model')
const usageChartType = ref<'line' | 'bar'>('line')
const usageDays = ref(14)
const DEFAULT_PARALLEL_SLOTS = 3

const artifactForm = reactive({
  display_name: '', kind: 'chat' as LocalModelKind, local_path: '', external_model_id: '',
  revision: '', checksum: '', native_context_tokens: null as number | null,
  supports_yarn: false, yarn_max_context_tokens: null as number | null, enabled: true,
})
const profileForm = reactive({
  display_name: '', description: '', artifact_id: '', kind: 'chat' as LocalModelKind,
  served_model_name: '', gpu_layers: 99, parallel_slots: DEFAULT_PARALLEL_SLOTS,
  cache_type_k: 'f16', cache_type_v: 'f16', flash_attention: true,
  mtp_enabled: false, mtp_max_draft_tokens: 3, mtp_min_draft_tokens: 0,
  mtp_min_acceptance_probability: 0, mtp_backend_sampling: true,
  max_input_tokens: null as number | null,
  max_output_tokens: null as number | null, context_compression_threshold_tokens: null as number | null,
  temperature: null as number | null,
  embedding_dimensions: null as number | null,
  trust_remote_code: false, tool_calling: true, reasoning_supported: false,
  image_input: false,
  normalize_embeddings: true, enabled: true,
  vae_path: '', clip_l_path: '', t5xxl_path: '',
  diffusion_flash_attention: true, eager_load: true, clip_on_cpu: true, vae_tiling: true,
  offload_to_cpu: false, max_vram_gib: null as number | null, stream_layers: null as number | null,
  default_width: 1024, default_height: 1024, default_steps: 20, default_cfg_scale: 1.0,
  default_sampler: 'euler', residency_policy: 'coexist_if_fit' as 'coexist_if_fit' | 'exclusive',
})
const kindOptions = computed(() => [
  { label: t('localModel.chat'), value: 'chat' },
  { label: t('localModel.embedding'), value: 'embedding' },
  { label: '图片生成', value: 'image_generation' },
])
const residencyPolicyOptions = [
  { label: '显存不足时禁止共存', value: 'exclusive' },
  { label: '显存足够时共存', value: 'coexist_if_fit' },
]
const artifactOptions = computed(() => artifacts.value.map((item) => ({
  label: `${item.display_name} · ${item.kind}`,
  value: item.artifact_id,
})))
const cacheTypeOptions = ['f16', 'bf16', 'q8_0', 'q4_0'].map((value) => ({ label: value.toUpperCase(), value }))
const externalInference = computed(() => modelStorage.value?.inference_mode === 'external')
const artifactRules = computed<FormRules>(() => ({
  display_name: [requiredTextRule(t('validation.required'))],
  kind: [requiredValueRule(t('validation.selectionRequired'))],
  external_model_id: externalInference.value
    ? [requiredValueRule(t('validation.selectionRequired'))]
    : [],
  local_path: externalInference.value
    ? []
    : [requiredValueRule(t('validation.selectionRequired'))],
}))
const profileRules = computed<FormRules>(() => ({
  display_name: [requiredTextRule(t('validation.required'))],
  artifact_id: [requiredValueRule(t('validation.selectionRequired'))],
  served_model_name: [requiredTextRule(t('validation.required'))],
}))
const remoteModelOptions = computed(() => (modelStorage.value?.remote_models || [])
  .filter((item) => item.kind === artifactForm.kind)
  .map((item) => ({
    label: [
      item.model_id,
      item.format,
      item.kind === 'embedding' && item.embedding_dimensions
        ? `${item.embedding_dimensions}D`
        : formatTokens(item.context_length),
    ].filter(Boolean).join(' · '),
    value: item.model_id,
  })))
const modelDirectoryOptions = computed(() => {
  const options = (modelStorage.value?.directories || [])
    .filter((item) => item.supported_kinds.includes(artifactForm.kind))
    .map((item) => ({
      label: [item.display_name, item.model_type, item.dtype].filter(Boolean).join(' · '),
      value: item.absolute_path,
    }))
  const currentPath = artifactForm.local_path
  if (currentPath && !options.some((item) => item.value === currentPath)) {
    options.unshift({ label: currentPath, value: currentPath })
  }
  return options
})
const selectedModelDirectory = computed(() => (
  modelStorage.value?.directories.find((item) => item.absolute_path === artifactForm.local_path) || null
))
const selectedRemoteModel = computed(() => (
  modelStorage.value?.remote_models.find((item) => (
    item.model_id === artifactForm.external_model_id && item.kind === artifactForm.kind
  )) || null
))
const profileRemoteModel = computed(() => {
  const artifact = artifacts.value.find((item) => item.artifact_id === profileForm.artifact_id)
  return artifact ? remoteModelForArtifact(artifact) : null
})
const profileSupportsImage = computed(() => (
  profileRemoteModel.value?.capabilities.includes('multimodal') || false
))
const usageDayOptions = computed(() => [
  { label: t('modelPool.usageLast7Days'), value: 7 },
  { label: t('modelPool.usageLast14Days'), value: 14 },
  { label: t('modelPool.usageLast30Days'), value: 30 },
  { label: t('modelPool.usageLast90Days'), value: 90 },
])
const usageColumns = computed<DataTableColumns<ModelUsageGroup>>(() => [
  { title: t('modelPool.usageName'), key: 'label', minWidth: 180, ellipsis: { tooltip: true } },
  { title: t('modelPool.usageCalls'), key: 'call_count', width: 96, render: row => formatNumber(row.totals.call_count) },
  { title: t('modelPool.usageInput'), key: 'input_tokens', width: 120, render: row => formatUsageTokens(row.totals.input_tokens) },
  { title: t('modelPool.usageOutput'), key: 'output_tokens', width: 120, render: row => formatUsageTokens(row.totals.output_tokens) },
  { title: t('modelPool.usageTotalTokens'), key: 'total_tokens', width: 120, render: row => formatUsageTokens(row.totals.total_tokens) },
  { title: t('modelPool.usageReasoning'), key: 'reasoning_tokens', width: 120, render: row => formatUsageTokens(row.totals.reasoning_tokens) },
  { title: t('modelPool.usageCacheHit'), key: 'cache_hit_ratio', width: 110, render: row => formatUsagePercent(row.totals.cache_hit_ratio) },
  { title: t('modelPool.usageCost'), key: 'estimated_cost', width: 110, render: row => formatCost(row.totals.estimated_cost) },
])
const usageChartOptions = computed(() => {
  const summary = usageSummary.value
  const chartType = usageChartType.value
  const buckets = Array.from(
    new Set((summary?.series || []).flatMap(item => item.points.map(point => point.bucket))),
  ).sort()
  return {
    tooltip: { trigger: 'axis', valueFormatter: (value: number) => formatUsageTokens(value) },
    legend: { top: 0, type: 'scroll' },
    grid: { left: 18, right: 42, top: 48, bottom: 32, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: chartType === 'bar',
      data: buckets,
      axisLabel: { hideOverlap: true, margin: 12 },
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (value: number) => formatUsageTokens(value) },
      splitLine: { lineStyle: { color: 'rgba(0, 0, 0, 0.08)' } },
    },
    series: (summary?.series || []).map(item => {
      const pointsByBucket = new Map(item.points.map(point => [point.bucket, point]))
      return {
        name: item.label,
        type: chartType,
        smooth: chartType === 'line',
        symbol: chartType === 'line' ? 'circle' : undefined,
        symbolSize: chartType === 'line' ? 6 : undefined,
        barMaxWidth: chartType === 'bar' ? 28 : undefined,
        barCategoryGap: chartType === 'bar' ? '32%' : undefined,
        data: buckets.map(bucket => pointsByBucket.get(bucket)?.total_tokens || 0),
      }
    }),
  }
})

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [artifactData, runtimeData, storageData] = await Promise.all([
      modelPoolApi.artifacts(),
      modelPoolApi.runtimes(),
      modelPoolApi.storage(),
      modelPoolStore.refresh(),
    ])
    artifacts.value = artifactData.artifacts
    runtimes.value = runtimeData.runtimes
    rocm.value = runtimeData.rocm
    modelStorage.value = storageData
    void refreshUsage()
  } catch (error) {
    message.error(errorText(error))
  } finally {
    loading.value = false
  }
}

async function refreshUsage(): Promise<void> {
  usageLoading.value = true
  try {
    usageSummary.value = await modelPoolApi.usage({
      groupBy: usageGroupBy.value,
      days: usageDays.value,
    })
  } catch (error) {
    message.error(errorText(error))
  } finally {
    usageLoading.value = false
  }
}

function openArtifact(item?: LocalModelArtifact): void {
  artifactEditing.value = item || null
  artifactForm.display_name = item?.display_name || ''
  artifactForm.kind = item?.kind || 'chat'
  artifactForm.local_path = item?.local_path || ''
  artifactForm.external_model_id = item?.external_model_id || ''
  artifactForm.revision = item?.revision || ''
  artifactForm.checksum = item?.checksum || ''
  artifactForm.native_context_tokens = item?.native_context_tokens ?? null
  artifactForm.supports_yarn = item?.context_extension?.method === 'yarn'
  artifactForm.yarn_max_context_tokens = item?.context_extension?.max_context_tokens ?? null
  artifactForm.enabled = item?.enabled ?? true
  artifactModalOpen.value = true
  void nextTick(() => artifactFormRef.value?.restoreValidation())
}

async function saveArtifact(): Promise<void> {
  if (!await validateForm(artifactFormRef.value)) return
  saving.value = true
  try {
    const payload: LocalModelArtifactWritePayload = {
      display_name: artifactForm.display_name,
      kind: artifactForm.kind,
      source: externalInference.value ? 'external_endpoint' : 'local_storage',
      local_path: externalInference.value ? null : artifactForm.local_path,
      external_model_id: externalInference.value ? artifactForm.external_model_id : null,
      model_format: externalInference.value
        ? selectedRemoteModel.value?.format || 'external'
        : artifactForm.kind === 'chat' ? 'llama_cpp' : artifactForm.kind === 'embedding' ? 'transformers' : 'stable_diffusion_cpp',
      revision: artifactForm.revision,
      checksum: artifactForm.checksum,
      native_context_tokens: artifactForm.kind === 'chat' ? artifactForm.native_context_tokens : null,
      context_extension: artifactForm.kind === 'chat'
        && artifactForm.supports_yarn
        && artifactForm.yarn_max_context_tokens !== null
        ? { method: 'yarn', max_context_tokens: artifactForm.yarn_max_context_tokens }
        : null,
      enabled: artifactForm.enabled,
    }
    if (artifactEditing.value) payload.artifact_id = artifactEditing.value.artifact_id
    if (artifactEditing.value) await modelPoolApi.patchArtifact(artifactEditing.value.artifact_id, payload)
    else await modelPoolApi.saveArtifact(payload)
    artifactModalOpen.value = false
    await refresh()
  } catch (error) { message.error(errorText(error)) } finally { saving.value = false }
}

function openProfile(item?: LocalModelProfile): void {
  const artifact = item?.artifact || artifacts.value[0]
  const kind = item?.kind || artifact?.kind || 'chat'
  const directory = artifact ? directoryForArtifact(artifact) : null
  const remoteModel = artifact ? remoteModelForArtifact(artifact) : null
  profileEditing.value = item || null
  profileForm.display_name = item?.display_name || artifact?.display_name || ''
  profileForm.description = item?.description || ''
  profileForm.artifact_id = item?.artifact_id || artifact?.artifact_id || ''
  profileForm.kind = kind
  profileForm.served_model_name = item?.served_model_name || artifact?.external_model_id || artifact?.display_name || ''
  const chatInference = item?.kind === 'chat' ? chatRuntimeConfiguration(item, remoteModel) : null
  const mtpInference = mtpRuntimeConfiguration(chatInference)
  const embeddingInference = item?.kind === 'embedding' ? item.inference : null
  const imageInference = kind === 'image_generation'
    ? item ? imageRuntimeConfiguration(item, remoteModel) : remoteImageRuntimeConfiguration(remoteModel)
    : null
  profileForm.gpu_layers = chatInference?.gpu_layers ?? 99
  profileForm.parallel_slots = chatInference?.parallel_slots ?? DEFAULT_PARALLEL_SLOTS
  profileForm.cache_type_k = chatInference?.cache_type_k ?? 'f16'
  profileForm.cache_type_v = chatInference?.cache_type_v ?? 'f16'
  profileForm.flash_attention = chatInference?.flash_attention ?? true
  profileForm.mtp_enabled = Boolean(mtpInference)
  profileForm.mtp_max_draft_tokens = mtpInference?.max_draft_tokens ?? 3
  profileForm.mtp_min_draft_tokens = mtpInference?.min_draft_tokens ?? 0
  profileForm.mtp_min_acceptance_probability = mtpInference?.min_acceptance_probability ?? 0
  profileForm.mtp_backend_sampling = mtpInference?.backend_sampling ?? true
  profileForm.max_input_tokens = item?.limits.max_input_tokens
    ?? artifact?.native_context_tokens
    ?? remoteModel?.native_context_tokens
    ?? remoteModel?.context_length
    ?? null
  profileForm.max_output_tokens = item?.limits.max_output_tokens ?? null
  profileForm.context_compression_threshold_tokens = item?.limits.context_compression_threshold_tokens ?? null
  profileForm.temperature = item?.settings.temperature ?? null
  profileForm.embedding_dimensions = item?.embedding_dimensions
    ?? remoteModel?.embedding_dimensions
    ?? directory?.embedding_dimensions
    ?? null
  profileForm.trust_remote_code = embeddingInference && 'trust_remote_code' in embeddingInference
    ? embeddingInference.trust_remote_code
    : false
  profileForm.tool_calling = item?.capabilities.tool_calling ?? true
  profileForm.image_input = item?.capabilities.input_modalities.includes('image')
    ?? remoteModel?.capabilities.includes('multimodal')
    ?? false
  profileForm.reasoning_supported = item?.capabilities.reasoning_supported ?? false
  profileForm.normalize_embeddings = item?.normalize_embeddings ?? true
  applyImageRuntimeConfiguration(imageInference)
  profileForm.enabled = item?.enabled ?? true
  memoryEstimate.value = remoteModel?.memory_estimate || null
  profileModalOpen.value = true
  void nextTick(() => profileFormRef.value?.restoreValidation())
}

function syncProfileKind(artifactId: string): void {
  const artifact = artifacts.value.find((item) => item.artifact_id === artifactId)
  if (!artifact) return
  const directory = directoryForArtifact(artifact)
  const remoteModel = remoteModelForArtifact(artifact)
  const runtimeConfiguration = remoteChatRuntimeConfiguration(remoteModel)
  const mtpInference = mtpRuntimeConfiguration(runtimeConfiguration)
  profileForm.kind = artifact.kind
  profileForm.display_name = artifact.display_name
  profileForm.description = ''
  profileForm.served_model_name = artifact.external_model_id || artifact.display_name
  profileForm.gpu_layers = runtimeConfiguration?.gpu_layers ?? 99
  profileForm.parallel_slots = runtimeConfiguration?.parallel_slots ?? DEFAULT_PARALLEL_SLOTS
  profileForm.cache_type_k = runtimeConfiguration?.cache_type_k ?? 'f16'
  profileForm.cache_type_v = runtimeConfiguration?.cache_type_v ?? 'f16'
  profileForm.flash_attention = runtimeConfiguration?.flash_attention ?? true
  profileForm.mtp_enabled = Boolean(mtpInference)
  profileForm.mtp_max_draft_tokens = mtpInference?.max_draft_tokens ?? 3
  profileForm.mtp_min_draft_tokens = mtpInference?.min_draft_tokens ?? 0
  profileForm.mtp_min_acceptance_probability = mtpInference?.min_acceptance_probability ?? 0
  profileForm.mtp_backend_sampling = mtpInference?.backend_sampling ?? true
  profileForm.max_input_tokens = artifact.native_context_tokens
    ?? remoteModel?.native_context_tokens
    ?? remoteModel?.context_length
    ?? profileForm.max_input_tokens
  profileForm.image_input = remoteModel?.capabilities.includes('multimodal') || false
  profileForm.embedding_dimensions = remoteModel?.embedding_dimensions ?? directory?.embedding_dimensions ?? null
  applyImageRuntimeConfiguration(
    artifact.kind === 'image_generation' ? remoteImageRuntimeConfiguration(remoteModel) : null,
  )
}

function syncRemoteModel(modelId: string): void {
  const model = modelStorage.value?.remote_models.find((item) => (
    item.model_id === modelId && item.kind === artifactForm.kind
  ))
  if (!model) return
  artifactForm.display_name = model.model_id
  artifactForm.kind = model.kind
  artifactForm.native_context_tokens = model.native_context_tokens ?? model.context_length ?? null
  artifactForm.supports_yarn = model.context_extension?.method === 'yarn'
  artifactForm.yarn_max_context_tokens = model.context_extension?.max_context_tokens ?? null
}

function syncArtifactKind(): void {
  artifactForm.external_model_id = ''
  artifactForm.local_path = ''
  artifactForm.native_context_tokens = null
  artifactForm.supports_yarn = false
  artifactForm.yarn_max_context_tokens = null
}

function directoryForArtifact(artifact: LocalModelArtifact) {
  return modelStorage.value?.directories.find((directory) => directory.absolute_path === artifact.local_path)
}

function remoteModelForArtifact(artifact: LocalModelArtifact) {
  return modelStorage.value?.remote_models.find((model) => (
    model.model_id === artifact.external_model_id && model.kind === artifact.kind
  ))
}

function openProfileEmptyAction(): void {
  if (artifacts.value.length) {
    openProfile()
    return
  }
  activeTab.value = 'artifacts'
  openArtifact()
}

async function saveProfile(): Promise<void> {
  if (!await validateForm(profileFormRef.value)) return
  saving.value = true
  try {
    const isChat = profileForm.kind === 'chat'
    const isEmbedding = profileForm.kind === 'embedding'
    const chatSpeculativeDecoding = profileForm.mtp_enabled
      ? {
          method: 'mtp' as const,
          max_draft_tokens: profileForm.mtp_max_draft_tokens,
          min_draft_tokens: profileForm.mtp_min_draft_tokens,
          min_acceptance_probability: profileForm.mtp_min_acceptance_probability,
          backend_sampling: profileForm.mtp_backend_sampling,
        }
      : { method: 'disabled' as const }
    const imageInference = {
      vae_path: profileForm.vae_path,
      clip_l_path: profileForm.clip_l_path,
      t5xxl_path: profileForm.t5xxl_path,
      diffusion_flash_attention: profileForm.diffusion_flash_attention,
      eager_load: profileForm.eager_load,
      clip_on_cpu: profileForm.clip_on_cpu,
      vae_tiling: profileForm.vae_tiling,
      offload_to_cpu: profileForm.offload_to_cpu,
      max_vram_gib: profileForm.max_vram_gib,
      stream_layers: profileForm.stream_layers,
      default_width: profileForm.default_width,
      default_height: profileForm.default_height,
      default_steps: profileForm.default_steps,
      default_cfg_scale: profileForm.default_cfg_scale,
      default_sampler: profileForm.default_sampler,
      residency_policy: profileForm.residency_policy,
    }
    const payload = {
      profile_id: profileEditing.value?.profile_id,
      display_name: profileForm.display_name,
      description: profileForm.description,
      kind: profileForm.kind,
      artifact_id: profileForm.artifact_id,
      engine: externalInference.value ? 'external' : isChat ? 'llama_cpp_rocm' : isEmbedding ? 'transformers_rocm' : 'stable_diffusion_cpp_rocm',
      served_model_name: profileForm.served_model_name,
      enabled: profileForm.enabled,
      capabilities: {
        input_modalities: isChat && profileForm.image_input ? ['text', 'image'] : ['text'],
        output_modalities: isChat || isEmbedding ? ['text'] : ['image'],
        tool_calling: isChat && profileForm.tool_calling,
        streaming_tool_calls: false, strict_tool_schema: false,
        structured_output_methods: isChat ? ['function_calling', 'json_mode'] : [],
        reasoning_supported: isChat && profileForm.reasoning_supported,
        reasoning_efforts: [], reasoning_content: isChat && profileForm.reasoning_supported,
        cache_usage: false,
        text_to_image: !isChat && !isEmbedding,
        image_to_image: false,
        image_edit: false,
        batch_generation: false,
        async_job: !isChat && !isEmbedding,
      },
      limits: {
        max_input_tokens: profileForm.max_input_tokens,
        max_output_tokens: profileForm.max_output_tokens,
        timeout_seconds: null,
        context_compression_threshold_tokens: isChat ? profileForm.context_compression_threshold_tokens : null,
      },
      settings: {
        temperature: isChat ? profileForm.temperature : null,
      },
      inference: externalInference.value
        ? {
            external: true,
            remote_inference: isChat
              ? {
                  gpu_layers: profileForm.gpu_layers,
                  parallel_slots: profileForm.parallel_slots,
                  cache_type_k: profileForm.cache_type_k,
                  cache_type_v: profileForm.cache_type_v,
                  flash_attention: profileForm.flash_attention,
                  speculative_decoding: chatSpeculativeDecoding,
                }
              : isEmbedding ? { trust_remote_code: profileForm.trust_remote_code } : imageInference,
          }
        : isChat
        ? {
            gpu_layers: profileForm.gpu_layers,
            parallel_slots: profileForm.parallel_slots,
            cache_type_k: profileForm.cache_type_k,
            cache_type_v: profileForm.cache_type_v,
            flash_attention: profileForm.flash_attention,
            speculative_decoding: chatSpeculativeDecoding,
          }
        : isEmbedding ? { trust_remote_code: profileForm.trust_remote_code } : imageInference,
      embedding_dimensions: isEmbedding ? profileForm.embedding_dimensions : null,
      normalize_embeddings: profileForm.normalize_embeddings,
      notes: '',
    }
    const result = profileEditing.value
      ? await modelPoolApi.patchProfile(profileEditing.value.profile_id, payload)
      : await modelPoolApi.saveProfile(payload)
    modelPoolStore.upsertProfile(result.profile)
    upsertRuntime(result.runtime)
    if (result.runtime.phase === 'failed') message.error(result.runtime.error)
    else if (profileForm.enabled) message.info(t('localModel.runtimeLoading'))
    profileModalOpen.value = false
    await refresh()
  } catch (error) { message.error(errorText(error)) } finally { saving.value = false }
}

async function loadProfile(profile: LocalModelProfile): Promise<void> {
  try {
    const result = await modelPoolApi.loadProfile(profile.profile_id)
    upsertRuntime(result.runtime)
    if (result.runtime.phase === 'failed') message.error(result.runtime.error)
  } catch (error) { message.error(errorText(error)) }
}

async function unloadProfile(profile: LocalModelProfile): Promise<void> {
  try {
    const result = await modelPoolApi.unloadProfile(profile.profile_id)
    upsertRuntime(result.runtime)
    await refreshRuntimeState()
  } catch (error) { message.error(errorText(error)) }
}

async function restartProfile(profile: LocalModelProfile): Promise<void> {
  try {
    const result = await modelPoolApi.restartProfile(profile.profile_id)
    upsertRuntime(result.runtime)
    if (result.runtime.phase === 'failed') message.error(result.runtime.error)
  } catch (error) { message.error(errorText(error)) }
}

function profileRuntime(profile: LocalModelProfile): LocalModelRuntime | undefined {
  return runtimes.value.find((runtime) => runtime.profile_id === profile.profile_id)
}

function isRuntimeTransitioning(profile: LocalModelProfile): boolean {
  return ['starting', 'loading', 'stopping'].includes(profileRuntime(profile)?.phase || '')
}

function runtimeTagType(profile: LocalModelProfile): 'default' | 'info' | 'success' | 'error' | 'warning' {
  const phase = profileRuntime(profile)?.phase
  if (phase === 'ready') return 'success'
  if (phase === 'failed') return 'error'
  if (phase === 'starting' || phase === 'loading' || phase === 'stopping') return 'info'
  return profile.enabled ? 'warning' : 'default'
}

function runtimePhaseLabel(profile: LocalModelProfile): string {
  const phase = profileRuntime(profile)?.phase
  if (phase === 'ready') return t('localModel.runtimeReady')
  if (phase === 'failed') return t('localModel.runtimeFailed')
  if (phase === 'starting' || phase === 'loading') return t('localModel.runtimeLoading')
  if (phase === 'stopping') return t('localModel.runtimeStopping')
  return t('localModel.runtimeNotLoaded')
}

function runtimeStageLabel(stage?: string): string {
  const labels: Record<string, string> = {
    validating_runtime: t('localModel.runtimeStageValidating'),
    process_started: t('localModel.runtimeStageStarting'),
    loading_weights: t('localModel.runtimeStageWeights'),
    initializing_engine: t('localModel.runtimeStageEngine'),
    initializing_service: t('localModel.runtimeStageService'),
    ready: t('localModel.runtimeReady'),
    failed: t('localModel.runtimeFailed'),
  }
  return labels[stage || ''] || t('localModel.runtimeLoading')
}

function upsertRuntime(runtime: LocalModelRuntime): void {
  if (runtime.phase === 'idle') {
    runtimes.value = runtimes.value.filter((item) => item.profile_id !== runtime.profile_id)
    return
  }
  const next = runtimes.value.filter((item) => item.kind !== runtime.kind)
  next.push(runtime)
  runtimes.value = next
}

async function refreshRuntimeState(): Promise<void> {
  if (runtimeRefreshing.value) return
  runtimeRefreshing.value = true
  try {
    const summary = await modelPoolApi.runtimes()
    runtimes.value = summary.runtimes
    rocm.value = summary.rocm
  } catch {
    // The full page refresh already owns user-visible transport errors.
  } finally {
    runtimeRefreshing.value = false
  }
}

function profileDefaultRoles(profileId: string): LocalModelDefaultRole[] {
  return (Object.entries(defaults.value) as Array<[LocalModelDefaultRole, string | null]>)
    .filter(([, defaultProfileId]) => defaultProfileId === profileId)
    .map(([role]) => role)
}

function defaultRoleOptions(profile: LocalModelProfile) {
  const roles: LocalModelDefaultRole[] = profile.kind === 'embedding'
    ? ['embedding']
    : profile.kind === 'image_generation'
      ? ['image_generation']
      : ['main', 'task', 'compression']
  return roles.map((role) => ({
    key: role,
    label: defaultRoleLabel(role),
    disabled: defaults.value[role] === profile.profile_id,
  }))
}

function defaultRoleLabel(role: LocalModelDefaultRole): string {
  return t(`localModel.defaultRole.${role}`)
}

async function handleDefaultRoleSelect(
  role: string | number,
  profile: LocalModelProfile,
): Promise<void> {
  const normalizedRole = String(role) as LocalModelDefaultRole
  try {
    const result = await modelPoolApi.setDefault(normalizedRole, profile.profile_id)
    modelPoolStore.setDefault(normalizedRole, result.profile_id)
    message.success(t('localModel.defaultUpdated'))
  } catch (error) {
    message.error(errorText(error))
  }
}

function removeArtifact(item: LocalModelArtifact): void {
  dialog.warning({
    title: t('common.delete'), content: item.display_name,
    positiveText: t('common.delete'), negativeText: t('common.cancel'),
    onPositiveClick: async () => { await modelPoolApi.deleteArtifact(item.artifact_id); await refresh() },
  })
}

function removeProfile(item: LocalModelProfile): void {
  dialog.warning({
    title: t('common.delete'), content: item.display_name,
    positiveText: t('common.delete'), negativeText: t('common.cancel'),
    onPositiveClick: async () => {
      await modelPoolApi.deleteProfile(item.profile_id)
      modelPoolStore.removeProfile(item.profile_id)
      await refresh()
    },
  })
}

function kindLabel(kind: LocalModelKind): string {
  if (kind === 'chat') return t('localModel.chat')
  if (kind === 'embedding') return t('localModel.embedding')
  return '图片生成'
}

function engineLabel(engine: LocalModelProfile['engine']): string {
  if (engine === 'external') return t('localModel.externalEndpoint')
  if (engine === 'llama_cpp_rocm') return 'llama.cpp · ROCm'
  if (engine === 'stable_diffusion_cpp_rocm') return 'stable-diffusion.cpp · ROCm'
  return 'Transformers · ROCm'
}

function imageRuntimeConfiguration(
  profile: LocalModelProfile,
  remoteModel = remoteModelForProfile(profile),
): StableDiffusionCppRuntimeConfiguration | null {
  if (profile.kind !== 'image_generation') return null
  if ('vae_path' in profile.inference) return profile.inference
  if ('remote_inference' in profile.inference && profile.inference.remote_inference && 'vae_path' in profile.inference.remote_inference) {
    return profile.inference.remote_inference
  }
  return remoteImageRuntimeConfiguration(remoteModel)
}

function remoteImageRuntimeConfiguration(
  remoteModel?: LocalModelStorage['remote_models'][number] | null,
): StableDiffusionCppRuntimeConfiguration | null {
  const value = remoteModel?.runtime_configuration
  if (
    !value
    || typeof value.vae_path !== 'string'
    || typeof value.clip_l_path !== 'string'
    || typeof value.t5xxl_path !== 'string'
  ) return null
  return value as unknown as StableDiffusionCppRuntimeConfiguration
}

function applyImageRuntimeConfiguration(
  inference: StableDiffusionCppRuntimeConfiguration | null,
): void {
  profileForm.vae_path = inference?.vae_path ?? ''
  profileForm.clip_l_path = inference?.clip_l_path ?? ''
  profileForm.t5xxl_path = inference?.t5xxl_path ?? ''
  profileForm.diffusion_flash_attention = inference?.diffusion_flash_attention ?? true
  profileForm.eager_load = inference?.eager_load ?? true
  profileForm.clip_on_cpu = inference?.clip_on_cpu ?? true
  profileForm.vae_tiling = inference?.vae_tiling ?? true
  profileForm.offload_to_cpu = inference?.offload_to_cpu ?? false
  profileForm.max_vram_gib = inference?.max_vram_gib ?? null
  profileForm.stream_layers = inference?.stream_layers ?? null
  profileForm.default_width = inference?.default_width ?? 1024
  profileForm.default_height = inference?.default_height ?? 1024
  profileForm.default_steps = inference?.default_steps ?? 20
  profileForm.default_cfg_scale = inference?.default_cfg_scale ?? 1.0
  profileForm.default_sampler = inference?.default_sampler ?? 'euler'
  profileForm.residency_policy = inference?.residency_policy ?? 'coexist_if_fit'
}

function artifactLocation(artifact?: LocalModelArtifact | null): string {
  return artifact?.external_model_id || artifact?.local_path || '—'
}

function chatRuntimeConfiguration(
  profile: LocalModelProfile,
  remoteModel = remoteModelForProfile(profile),
): LlamaCppRuntimeConfiguration | null {
  if (profile.kind !== 'chat') return null
  if ('gpu_layers' in profile.inference) return profile.inference
  if ('remote_inference' in profile.inference && profile.inference.remote_inference && 'gpu_layers' in profile.inference.remote_inference) {
    return profile.inference.remote_inference
  }
  return remoteChatRuntimeConfiguration(remoteModel)
}

function remoteChatRuntimeConfiguration(remoteModel?: LocalModelStorage['remote_models'][number] | null): LlamaCppRuntimeConfiguration | null {
  const configuration = remoteModel?.runtime_configuration
  if (!configuration || typeof configuration.gpu_layers !== 'number') return null
  return {
    gpu_layers: configuration.gpu_layers,
    parallel_slots: typeof configuration.parallel_slots === 'number'
      ? configuration.parallel_slots
      : DEFAULT_PARALLEL_SLOTS,
    per_slot_context_tokens: typeof configuration.per_slot_context_tokens === 'number' ? configuration.per_slot_context_tokens : null,
    server_context_tokens: typeof configuration.server_context_tokens === 'number' ? configuration.server_context_tokens : null,
    cache_type_k: typeof configuration.cache_type_k === 'string' ? configuration.cache_type_k : 'f16',
    cache_type_v: typeof configuration.cache_type_v === 'string' ? configuration.cache_type_v : 'f16',
    flash_attention: configuration.flash_attention !== false,
    speculative_decoding: configuration.speculative_decoding && typeof configuration.speculative_decoding === 'object'
      ? configuration.speculative_decoding as unknown as LlamaCppRuntimeConfiguration['speculative_decoding']
      : { method: 'disabled' },
  }
}

function mtpRuntimeConfiguration(
  configuration?: LlamaCppRuntimeConfiguration | null,
): LlamaCppMtpConfiguration | null {
  const speculative = configuration?.speculative_decoding
  return speculative?.method === 'mtp' ? speculative : null
}

function profileTotalContextTokens(profile: LocalModelProfile): number | null {
  if (profile.kind !== 'chat') return null
  const inference = chatRuntimeConfiguration(profile)
  if (typeof inference?.server_context_tokens === 'number') return inference.server_context_tokens
  const perSlotTokens = profile.limits.max_input_tokens
  return perSlotTokens
    ? perSlotTokens * (inference?.parallel_slots ?? DEFAULT_PARALLEL_SLOTS)
    : null
}

function profileMemoryEstimate(profile: LocalModelProfile): InferenceMemoryEstimate | null {
  if (profile.kind !== 'chat') return null
  return remoteModelForProfile(profile)?.memory_estimate || null
}

function remoteModelForProfile(profile: LocalModelProfile) {
  const artifact = profile.artifact || artifacts.value.find((item) => item.artifact_id === profile.artifact_id)
  return artifact ? remoteModelForArtifact(artifact) : null
}

function memoryBudgetClass(estimate?: InferenceMemoryEstimate | null): string {
  if (!estimate?.available || estimate.fits === null || estimate.fits === undefined) return 'is-unknown'
  return estimate.fits ? 'is-safe' : 'is-overflow'
}

function memoryFitLabel(estimate?: InferenceMemoryEstimate | null): string {
  if (!estimate?.available) return t('localModel.memoryEstimateUnavailable')
  return estimate.fits ? t('localModel.memoryFits') : t('localModel.memoryOverflow')
}

function formatPercent(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)}%` : '—'
}

function formatUsageTokens(value?: number | null): string {
  const numeric = Number(value || 0)
  if (numeric >= 1_000_000_000) return `${Math.round(numeric / 100_000_000) / 10}B`
  if (numeric >= 1_000_000) return `${Math.round(numeric / 100_000) / 10}M`
  if (numeric >= 1_000) return `${Math.round(numeric / 1_000)}K`
  return String(numeric)
}

function usageRowKey(row: ModelUsageGroup): string {
  return row.key
}

function formatNumber(value?: number | null): string {
  return new Intl.NumberFormat('zh-CN').format(Number(value || 0))
}

function formatUsagePercent(value?: number | null): string {
  if (value === null || value === undefined) return '—'
  return `${Math.round(Number(value) * 1_000) / 10}%`
}

function formatCost(value?: number | null): string {
  if (value === null || value === undefined) return '—'
  return `¥${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 4 }).format(Number(value || 0))}`
}

function formatScalingFactor(value?: number | null): string {
  return typeof value === 'number' ? value.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : '—'
}

function gpuUtilizationSourceLabel(source?: string): string {
  if (!source) return t('localModel.telemetryUnavailable')
  const labels: Record<string, string> = {
    'linux-sysfs': 'Linux sysfs',
    'rocm-smi': 'rocm-smi',
    'amd-smi': 'amd-smi',
  }
  return labels[source] || source
}

function formatBytes(value?: number | null): string {
  if (typeof value !== 'number' || value < 0) return '—'
  return `${(value / 1024 ** 3).toFixed(1)} GiB`
}

function formatMemoryUsage(device: RocmRuntimeInfo['devices'][number]): string {
  const used = formatBytes(device.used_memory_bytes)
  const total = formatBytes(device.total_memory_bytes)
  if (used === '—') return total
  const ratio = device.total_memory_bytes > 0 && typeof device.used_memory_bytes === 'number'
    ? ` (${Math.round(device.used_memory_bytes / device.total_memory_bytes * 100)}%)`
    : ''
  return `${used} / ${total}${ratio}`
}

function formatTemperature(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)} °C` : '—'
}

function formatPower(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value)} W` : '—'
}

function formatTokens(value?: number | null): string {
  if (!value) return '—'
  return value >= 1000 ? `${Math.round(value / 1024)}K` : String(value)
}

function errorText(error: unknown): string { return error instanceof Error ? error.message : String(error) }

let runtimePollTimer: ReturnType<typeof setInterval> | null = null
let memoryEstimateTimer: ReturnType<typeof setTimeout> | null = null
let memoryEstimateSerial = 0

function scheduleMemoryEstimate(): void {
  if (memoryEstimateTimer) clearTimeout(memoryEstimateTimer)
  if (!profileModalOpen.value || profileForm.kind !== 'chat') return
  memoryEstimateTimer = setTimeout(refreshMemoryEstimate, 250)
}

async function refreshMemoryEstimate(): Promise<void> {
  const modelId = profileForm.served_model_name.trim()
  if (!modelId || !profileForm.max_input_tokens) {
    memoryEstimate.value = null
    return
  }
  const serial = ++memoryEstimateSerial
  memoryEstimateLoading.value = true
  try {
    const result = await modelPoolApi.estimateMemory({
      kind: 'chat',
      model_id: modelId,
      profile: {
        limits: {
          max_input_tokens: profileForm.max_input_tokens,
          max_output_tokens: profileForm.max_output_tokens,
          timeout_seconds: null,
          context_compression_threshold_tokens: profileForm.context_compression_threshold_tokens,
        },
        capabilities: {
          input_modalities: profileForm.image_input ? ['text', 'image'] : ['text'],
          output_modalities: ['text'],
          tool_calling: profileForm.tool_calling,
          streaming_tool_calls: false,
          strict_tool_schema: false,
          structured_output_methods: ['function_calling', 'json_mode'],
          reasoning_supported: profileForm.reasoning_supported,
          reasoning_efforts: [],
          reasoning_content: profileForm.reasoning_supported,
          cache_usage: false,
        },
        inference: {
          gpu_layers: profileForm.gpu_layers,
          parallel_slots: profileForm.parallel_slots,
          cache_type_k: profileForm.cache_type_k,
          cache_type_v: profileForm.cache_type_v,
          flash_attention: profileForm.flash_attention,
          speculative_decoding: profileForm.mtp_enabled
            ? {
                method: 'mtp',
                max_draft_tokens: profileForm.mtp_max_draft_tokens,
                min_draft_tokens: profileForm.mtp_min_draft_tokens,
                min_acceptance_probability: profileForm.mtp_min_acceptance_probability,
                backend_sampling: profileForm.mtp_backend_sampling,
              }
            : { method: 'disabled' },
        },
        embedding_dimensions: null,
        normalize_embeddings: true,
      },
    })
    if (serial === memoryEstimateSerial) memoryEstimate.value = result.estimate
  } catch (error) {
    if (serial === memoryEstimateSerial) {
      memoryEstimate.value = {
        available: false,
        model_id: modelId,
        context_tokens: profileForm.max_input_tokens,
        total_context_tokens: profileForm.max_input_tokens * profileForm.parallel_slots,
        parallel_slots: profileForm.parallel_slots,
        cache_type_k: profileForm.cache_type_k,
        cache_type_v: profileForm.cache_type_v,
        basis: 'unavailable',
        error: errorText(error),
      }
    }
  } finally {
    if (serial === memoryEstimateSerial) memoryEstimateLoading.value = false
  }
}

watch(
  () => [
    profileModalOpen.value,
    profileForm.served_model_name,
    profileForm.max_input_tokens,
    profileForm.parallel_slots,
    profileForm.cache_type_k,
    profileForm.cache_type_v,
    profileForm.gpu_layers,
    profileForm.flash_attention,
    profileForm.mtp_enabled,
    profileForm.mtp_max_draft_tokens,
    profileForm.mtp_min_draft_tokens,
    profileForm.mtp_min_acceptance_probability,
    profileForm.mtp_backend_sampling,
  ],
  scheduleMemoryEstimate,
)

onMounted(async () => {
  await refresh()
  runtimePollTimer = setInterval(refreshRuntimeState, 2000)
})

onBeforeUnmount(() => {
  if (runtimePollTimer) clearInterval(runtimePollTimer)
  if (memoryEstimateTimer) clearTimeout(memoryEstimateTimer)
})
</script>

<style scoped>
.local-model-view {
  container-name: local-model;
  container-type: inline-size;
  width: 100%;
  min-width: 0;
  height: 100%;
  padding: var(--app-space-xl);
  background: var(--app-surface);
}

.context-bar,
.content-header,
.resource-header,
.resource-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-lg);
}

.context-bar { margin-bottom: var(--app-space-xl); }
.context-title { display: flex; flex-direction: column; gap: var(--app-space-xs); min-width: 0; }
.title-line { display: flex; align-items: center; gap: var(--app-space-sm); }
.title-icon,
.resource-icon,
.empty-icon,
.overview-icon {
  display: inline-grid;
  place-items: center;
  flex: 0 0 auto;
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text);
}
.title-icon { width: 34px; height: 34px; font-size: 19px; }
.page-title { font-size: var(--app-font-xl); }
.context-subtitle { padding-left: 42px; font-size: var(--app-font-sm); }

.overview-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) repeat(2, minmax(150px, 1fr));
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-xl);
}

.overview-card {
  display: flex;
  align-items: center;
  gap: var(--app-space-md);
  min-width: 0;
  padding: var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-sm);
}
.overview-icon { width: 42px; height: 42px; font-size: 22px; }
.overview-copy { min-width: 0; flex: 1; }
.overview-label,
.spec-item span,
.path-block span,
.checksum-line span { color: var(--app-text-muted); font-size: var(--app-font-sm); }
.overview-value { margin-top: 2px; color: var(--app-text-strong); font-size: var(--app-font-lg); font-weight: 650; }
.overview-detail { margin-top: 2px; overflow: hidden; color: var(--app-text-secondary); font-size: var(--app-font-sm); text-overflow: ellipsis; white-space: nowrap; }
.runtime-device-list { display: grid; gap: var(--app-space-sm); margin-top: var(--app-space-md); }
.runtime-device { padding: var(--app-space-sm); border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: var(--app-surface-muted); }
.runtime-device-heading { display: flex; align-items: baseline; justify-content: space-between; gap: var(--app-space-md); color: var(--app-text-strong); }
.runtime-device-heading span { color: var(--app-text-secondary); font-size: var(--app-font-xs); }
.runtime-metrics { display: flex; flex-wrap: wrap; gap: var(--app-space-xs) var(--app-space-md); margin-top: var(--app-space-xs); color: var(--app-text-secondary); font-size: var(--app-font-xs); }
.status-dot { width: 9px; height: 9px; flex: 0 0 auto; border-radius: 50%; background: var(--app-warning); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-warning) 14%, transparent); }
.runtime-card.is-ready .status-dot { background: var(--app-success); box-shadow: 0 0 0 4px color-mix(in srgb, var(--app-success) 14%, transparent); }
.runtime-card.is-ready .overview-icon { color: var(--app-success); background: color-mix(in srgb, var(--app-success) 10%, var(--app-surface)); }
.runtime-card.is-warning .overview-icon { color: var(--app-warning); background: color-mix(in srgb, var(--app-warning) 10%, var(--app-surface)); }

.model-panel {
  min-height: 420px;
  padding: 0 var(--app-space-lg) var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  box-shadow: var(--app-shadow-sm);
}
.tab-content { padding: var(--app-space-lg) 0 0; }
.content-header { margin-bottom: var(--app-space-lg); flex-wrap: wrap; }
.section-title { display: block; font-size: var(--app-font-lg); }
.section-description { margin-top: var(--app-space-xs); color: var(--app-text-secondary); font-size: var(--app-font-sm); }

.resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-md); }
.resource-card {
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: var(--app-space-lg);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface);
  transition: border-color var(--app-transition-base), box-shadow var(--app-transition-base), transform var(--app-transition-base);
}
.resource-card:hover { transform: translateY(-1px); border-color: var(--app-border-hover); box-shadow: var(--app-shadow-md); }
.resource-identity { display: flex; align-items: center; gap: var(--app-space-sm); min-width: 0; }
.profile-status-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--app-space-xs); }
.resource-icon { width: 38px; height: 38px; font-size: 20px; }
.resource-title-block { min-width: 0; }
.resource-title { overflow: hidden; color: var(--app-text-strong); font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.resource-id { margin-top: 2px; overflow: hidden; color: var(--app-text-muted); font-family: 'SF Mono', Monaco, monospace; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.tag-row { display: flex; flex-wrap: wrap; gap: var(--app-space-xs); margin-top: var(--app-space-md); }
.model-name { margin-top: var(--app-space-md); color: var(--app-text); font-family: 'SF Mono', Monaco, monospace; font-size: var(--app-font-sm); font-weight: 600; }
.path-line { display: flex; align-items: center; gap: var(--app-space-xs); min-width: 0; margin-top: var(--app-space-xs); color: var(--app-text-muted); font-size: var(--app-font-sm); }
.path-line span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.profile-runtime-panel {
  display: grid;
  gap: var(--app-space-xs);
  margin-top: var(--app-space-md);
  padding: var(--app-space-sm) var(--app-space-md);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.profile-runtime-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); color: var(--app-text-secondary); font-size: var(--app-font-xs); }
.profile-runtime-heading strong { color: var(--app-text); font-weight: 600; }
.runtime-error { color: var(--app-error); font-size: var(--app-font-xs); line-height: var(--app-leading-normal); overflow-wrap: anywhere; }
.spec-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-xs); margin-top: var(--app-space-lg); }
.spec-item { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-sm); padding: var(--app-space-sm); border-radius: var(--app-radius-sm); background: var(--app-surface-muted); }
.spec-item strong { color: var(--app-text); font-size: var(--app-font-sm); }
.memory-budget-card,
.memory-preview {
  display: grid;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.memory-budget-card.is-safe,
.memory-preview.is-safe { border-color: color-mix(in srgb, var(--app-success) 42%, var(--app-border)); }
.memory-budget-card.is-overflow,
.memory-preview.is-overflow { border-color: color-mix(in srgb, var(--app-error) 55%, var(--app-border)); }
.memory-budget-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); }
.memory-budget-heading span { color: var(--app-text-secondary); font-size: var(--app-font-xs); }
.memory-budget-metrics { display: flex; flex-wrap: wrap; gap: var(--app-space-xs) var(--app-space-lg); color: var(--app-text-muted); font-size: var(--app-font-xs); }
.memory-budget-metrics strong { margin-left: 3px; color: var(--app-text); }
.memory-preview { margin: 0 0 var(--app-space-lg); }
.memory-preview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--app-space-sm); }
.memory-preview-grid > div { display: grid; gap: 3px; min-width: 0; }
.memory-preview-grid span { color: var(--app-text-muted); font-size: var(--app-font-xs); }
.memory-preview-grid strong { color: var(--app-text); overflow-wrap: anywhere; }
.memory-preview p { margin: 0; color: var(--app-text-muted); font-size: var(--app-font-xs); line-height: var(--app-leading-normal); overflow-wrap: anywhere; }
.resource-actions { flex-wrap: wrap; margin-top: auto; padding-top: var(--app-space-lg); }
.resource-action-group { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-xs); min-width: 0; }
.resource-management-actions { margin-inline-start: auto; }

.path-block { margin-top: var(--app-space-lg); padding: var(--app-space-md); border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: var(--app-surface-muted); }
.path-block span { display: block; margin-bottom: var(--app-space-xs); }
.path-block code,
.checksum-line code { display: block; overflow: hidden; color: var(--app-text); font-size: var(--app-font-sm); text-overflow: ellipsis; white-space: nowrap; }
.checksum-line { display: flex; align-items: center; justify-content: space-between; gap: var(--app-space-md); margin-top: var(--app-space-sm); }
.checksum-line code { min-width: 0; }
.storage-root { display: flex; flex-wrap: wrap; gap: var(--app-space-xs); margin-top: var(--app-space-xs); color: var(--app-text-muted); font-size: var(--app-font-sm); }
.storage-root code,
.storage-hint code { color: var(--app-text); }
.storage-hint { margin-bottom: var(--app-space-md); color: var(--app-text-secondary); font-size: var(--app-font-sm); }
.model-directory-summary {
  display: grid;
  gap: var(--app-space-xs);
  margin: calc(var(--app-space-sm) * -1) 0 var(--app-space-md);
  padding: var(--app-space-sm) var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}
.model-directory-heading { display: flex; flex-wrap: wrap; align-items: center; gap: var(--app-space-xs); }
.model-directory-heading strong { margin-right: var(--app-space-xs); color: var(--app-text-strong); }
.model-directory-heading span {
  padding: 2px var(--app-space-xs);
  border-radius: var(--app-radius-pill);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font-size: var(--app-font-xs);
}
.model-directory-summary code {
  overflow: hidden;
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.usage-report {
  display: grid;
  gap: var(--app-space-md);
}

.usage-range-select {
  width: 132px;
}

.usage-overview {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.usage-metric {
  display: flex;
  min-height: 72px;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  padding: 12px 14px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel);
}

.usage-metric span {
  color: var(--app-text-muted);
  font-size: 12px;
}

.usage-metric strong {
  color: var(--app-text);
  font-size: 22px;
  font-weight: 650;
  line-height: 1.1;
}

.usage-chart-panel {
  min-height: 320px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-panel);
}

.usage-chart {
  width: 100%;
  height: 320px;
}

.empty-panel {
  min-height: 300px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-sm);
  padding: var(--app-space-xl);
  border: 1px dashed var(--app-border-hover);
  border-radius: var(--app-radius-lg);
  background: var(--app-surface-muted);
  text-align: center;
  animation: app-fade-in-up 0.3s cubic-bezier(0.16, 1, 0.3, 1) both;
}
.empty-icon { width: 56px; height: 56px; margin-bottom: var(--app-space-xs); color: var(--app-text-muted); font-size: 29px; background: var(--app-surface); box-shadow: var(--app-shadow-sm); }
.empty-panel p { max-width: 460px; margin: 0 0 var(--app-space-sm); color: var(--app-text-muted); font-size: var(--app-font-sm); line-height: var(--app-leading-normal); }

.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 var(--app-space-lg); }
.memory-form-item { grid-column: 1 / -1; }
.memory-limit-control { display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: var(--app-space-sm) var(--app-space-md); width: 100%; align-items: center; }
.memory-limit-control p { grid-column: 1 / -1; margin: 0; color: var(--app-text-muted); font-size: var(--app-font-xs); line-height: var(--app-leading-normal); }

@container local-model (max-width: 900px) {
  .overview-grid { grid-template-columns: 1fr 1fr; }
  .runtime-card { grid-column: 1 / -1; }
  .resource-grid { grid-template-columns: 1fr; }
  .usage-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@container local-model (max-width: 620px) {
  .local-model-view { padding: var(--app-space-md); }
  .context-bar { align-items: flex-start; flex-wrap: wrap; }
  .context-bar > .n-button { margin-left: 42px; }
  .context-subtitle { padding-left: 0; }
  .overview-grid { grid-template-columns: 1fr; }
  .runtime-card { grid-column: auto; }
  .overview-detail { overflow: visible; text-overflow: clip; white-space: normal; line-height: var(--app-leading-normal); }
  .runtime-device-heading { align-items: flex-start; flex-direction: column; gap: 2px; }
  .model-panel { padding: 0 var(--app-space-md) var(--app-space-md); }
  .form-grid { grid-template-columns: 1fr; }
  .resource-header { align-items: flex-start; flex-direction: column; }
  .profile-status-tags { justify-content: flex-start; }
  .resource-title { overflow: visible; text-overflow: clip; white-space: normal; overflow-wrap: anywhere; }
  .model-name,
  .path-line span { white-space: normal; overflow-wrap: anywhere; }
  .spec-grid,
  .memory-preview-grid { grid-template-columns: 1fr; }
  .spec-item { align-items: flex-start; }
  .resource-actions { align-items: stretch; justify-content: flex-start; gap: var(--app-space-xs); }
  .resource-management-actions { margin-inline-start: 0; }
  .memory-form-item { grid-column: auto; }
  .memory-limit-control { grid-template-columns: 1fr; }
  .memory-limit-control p { grid-column: auto; }
  .content-header { align-items: flex-start; }
  .usage-report .content-header { align-items: stretch; flex-direction: column; }
}

@container local-model (max-width: 420px) {
  .local-model-view { padding: var(--app-space-sm); }
  .context-bar > .n-button { width: 100%; margin-left: 0; }
  .overview-card,
  .resource-card { padding: var(--app-space-md); }
  .overview-card { position: relative; align-items: stretch; flex-direction: column; }
  .overview-icon { width: 36px; height: 36px; }
  .overview-card .status-dot { position: absolute; top: var(--app-space-md); right: var(--app-space-md); }
  .runtime-device { padding: var(--app-space-xs); }
  .runtime-metrics { display: grid; grid-template-columns: 1fr; }
  .model-panel { padding-inline: var(--app-space-sm); }
  .usage-overview { grid-template-columns: 1fr; }
  .resource-action-group > .n-button,
  .resource-action-group > .n-dropdown { flex: 1 1 calc(50% - var(--app-space-xs)); }
}

@media (max-width: 620px) {
  .form-grid,
  .memory-preview-grid { grid-template-columns: 1fr; }
}
</style>

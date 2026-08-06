<template>
  <component
    :is="embedded ? 'div' : NDrawer"
    v-bind="drawerContainerProps"
    @update:show="emit('update:show', $event)"
  >
    <component :is="embedded ? 'div' : NDrawerContent" v-bind="detailContentProps">
      <div v-if="agentPackage" class="detail-panel">
        <section class="detail-section">
          <div class="detail-title">{{ packageDisplayName(agentPackage, t) }}</div>
          <div class="detail-description">
            {{ agentPackage.agent_description || t('common.noDescription') }}
          </div>
        </section>

        <section class="detail-section detail-grid">
          <div class="detail-row">
            <span>{{ t('common.status') }}</span>
            <n-tag size="small" :type="statusType(agentPackage.status || '')">
              {{ packageStatusLabel(agentPackage.status) }}
            </n-tag>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.tools') }}</span>
            <strong>{{ agentPackage.tool_count || 0 }}</strong>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.sessions') }}</span>
            <strong>{{ agentPackage.session_count || 0 }}</strong>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.updatedAt') }}</span>
            <strong>{{ formatPackageDateTime(agentPackage.updated_at, locale, t) }}</strong>
          </div>
          <div class="detail-row">
            <span>MCP</span>
            <strong>{{ mcpServers.length }}</strong>
          </div>
          <div class="detail-row">
            <span>Skill</span>
            <strong>{{ skills.length }}</strong>
          </div>
          <div class="detail-row">
            <span>{{ t('agentDetail.knowledgeSources') }}</span>
            <strong>{{ knowledgeSources.length }}</strong>
          </div>
        </section>

        <agent-tool-settings-panel :package-id="agentPackage.package_id" class="detail-section" />

        <section v-if="resourceItems.length > 0 || resourceLoadError" class="detail-section resource-section">
          <div class="section-header">
            <div class="section-label">Resource 配置</div>
            <n-tag size="small" :type="resourceStatusType">{{ resourceStatusLabel }}</n-tag>
          </div>
          <div class="resource-section-hint">
            这些配置只保存在本机加密资源库中，不会写入 AgentPackage。已配置值会完整回填；密码字段默认遮挡，可点击眼睛查看。
          </div>
          <div v-if="resourceLoadError" class="resource-error">{{ resourceLoadError }}</div>
          <div v-else class="detail-list">
            <div v-for="resource in resourceItems" :key="resource.resource_id" class="detail-list-item resource-item">
              <div class="item-main">
                <div class="item-title">{{ resource.resource_id }}</div>
                <div v-if="resource.description" class="item-description">{{ resource.description }}</div>
                <div class="item-meta">
                  {{ resource.required ? '必填' : '按需配置' }} · {{ resource.used_by.join(', ') || '运行时' }}
                </div>
                <resource-schema-form
                  :model-value="resourceDrafts[resource.resource_id]"
                  :schema="resource.value_schema"
                  :secret-fields="resource.secret_fields"
                  :show-validation="Boolean(resourceValidationVisible[resource.resource_id])"
                  class="resource-input"
                  @update:model-value="resourceDrafts[resource.resource_id] = $event"
                />
                <div v-if="resourceErrors[resource.resource_id]" class="resource-error">
                  {{ resourceErrors[resource.resource_id] }}
                </div>
              </div>
              <div class="resource-actions">
                <n-tag size="small" :type="resource.configured ? 'success' : resource.required ? 'warning' : 'default'">
                  {{ resource.configured ? '已配置' : '待配置' }}
                </n-tag>
                <n-button
                  size="tiny"
                  type="primary"
                  :loading="resourceSavingId === resource.resource_id"
                  :disabled="!resourceStoreReady"
                  @click="saveResource(resource)"
                >
                  {{ resource.configured ? '覆盖' : '保存' }}
                </n-button>
                <n-button
                  v-if="resource.configured"
                  size="tiny"
                  quaternary
                  :disabled="resourceSavingId === resource.resource_id"
                  @click="removeResource(resource.resource_id)"
                >
                  移除
                </n-button>
              </div>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">定时任务策略</div>
            <n-tag size="small" :bordered="false">
              {{ agentPackage.scheduler_contract?.version || t('common.unknown') }}
            </n-tag>
          </div>
          <div v-if="schedulerDraft" class="context-policy-panel">
            <div class="context-config-row">
              <div class="context-config-main">
                <setting-help-label
                  label="默认时区"
                  help="新建定时任务未单独指定时区时使用。已有任务保留创建时记录的时区。"
                />
              </div>
              <div class="scheduler-value-control">
                <n-select
                  v-model:value="schedulerDraft.timezone"
                  :options="timezoneOptions"
                  filterable
                />
              </div>
            </div>
            <div class="context-config-row">
              <div class="context-config-main">
                <setting-help-label
                  label="默认并发策略"
                  help="同一任务上一次运行尚未结束时再次触发的默认处理方式。任务自身配置可以覆盖此值。"
                />
              </div>
              <div class="scheduler-value-control">
                <n-select
                  v-model:value="schedulerDraft.default_concurrency_policy"
                  :options="schedulerConcurrencyOptions"
                />
              </div>
            </div>
            <context-number-setting
              v-model="schedulerDraft.default_timeout_seconds"
              label="默认超时时间（秒）"
              help="新建任务未单独设置超时时间时使用。"
              :min="1"
              :max="86400"
            />
            <div class="context-config-row">
              <div class="context-config-main">
                <setting-help-label
                  label="无人值守审批策略"
                  help="定时任务在没有用户驻留时遇到需要审批的操作所采用的默认策略。"
                />
              </div>
              <div class="scheduler-value-control">
                <n-select
                  v-model:value="schedulerDraft.unattended_policy"
                  :options="schedulerUnattendedOptions"
                />
              </div>
            </div>
            <div class="context-setting-line">
              <setting-help-label
                label="连续失败后自动暂停"
                help="开启后，任务连续失败达到设定次数时自动暂停，避免持续消耗资源。"
              />
              <n-switch v-model:value="schedulerDraft.default_failure_policy.enabled" />
            </div>
            <context-number-setting
              v-model="schedulerDraft.default_failure_policy.max_consecutive_failures"
              label="连续失败次数"
              help="达到该次数后自动暂停新建任务；任务自身配置可以覆盖此值。"
              :min="1"
              :max="100"
              :disabled="!schedulerDraft.default_failure_policy.enabled"
            />
            <div class="resource-section-hint">
              这些设置是新建定时任务的默认值。正在运行的 Agent 实例需重新初始化后读取新配置，已有任务不会被批量改写。
            </div>
            <div v-if="schedulerConfigError" class="resource-error">{{ schedulerConfigError }}</div>
            <n-button
              size="small"
              type="primary"
              class="context-save-button"
              :loading="schedulerConfigSaving"
              :disabled="!schedulerConfigDirty"
              @click="saveSchedulerConfig"
            >
              {{ t('common.save') }}
            </n-button>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.contextPolicy') }}</div>
            <n-tag size="small" :bordered="false">
              {{ agentPackage.context_contract?.version || t('common.unknown') }}
            </n-tag>
          </div>
          <div v-if="contextDraft" class="context-policy-panel">
            <div class="context-setting-line">
              <span>启用上下文系统</span>
              <n-switch v-model:value="contextDraft.enabled" />
            </div>
            <div class="context-config-row">
              <div class="context-config-main">
                <div class="context-config-heading">
                  <div class="item-title">{{ t('agentDetail.contextWindowLimit') }}</div>
                  <div class="context-window-meta">
                    <span>{{ t('agentDetail.contextEffective', { tokens: formatTokens(agentPackage.context_contract?.context_window_tokens) }) }}</span>
                    <span>{{ t('agentDetail.contextModelProfile', { profile: agentPackage.context_contract?.model_profile_id || t('common.auto') }) }}</span>
                    <span>{{ contextSourceLabel(agentPackage.context_contract?.context_window_tokens_source) }}</span>
                  </div>
                </div>
              </div>
              <div class="context-value-control">
                <n-input-number
                  v-model:value="contextDraft.context_window_tokens"
                  clearable
                  :min="1000"
                  :precision="0"
                  placeholder="跟随模型"
                />
              </div>
            </div>

            <div class="context-setting-line">
              <span>启用上下文压缩</span>
              <n-switch v-model:value="contextDraft.default_policy.compression.enabled" />
            </div>
            <div class="context-config-row">
              <div class="context-config-main">
                <div class="context-config-heading">
                  <div class="item-title">{{ t('agentDetail.compressionThreshold') }}</div>
                  <div class="context-window-meta">
                    <span>{{ t('agentDetail.contextEffective', { tokens: formatTokens(agentPackage.context_contract?.compression_threshold_tokens) }) }}</span>
                    <span>{{ t('agentDetail.contextModelProfile', { profile: agentPackage.context_contract?.model_profile_id || t('common.auto') }) }}</span>
                    <span>{{ contextSourceLabel(agentPackage.context_contract?.compression_threshold_tokens_source) }}</span>
                  </div>
                </div>
              </div>
              <div class="context-value-control">
                <n-input-number
                  v-model:value="contextDraft.default_policy.compression.trigger_token_threshold"
                  clearable
                  :min="1000"
                  :precision="0"
                  placeholder="跟随模型"
                />
              </div>
            </div>
            <context-number-setting
              v-model="contextDraft.default_policy.compression.keep_recent_messages"
              label="压缩后保留最近消息"
              :min="2"
              :max="128"
            />

            <div class="context-subsection-title">跨会话记忆</div>
            <div class="context-setting-line">
              <setting-help-label
                label="启用跨会话记忆"
                help="总开关。关闭后不再从其他会话读取或写入记忆。例如临时咨询不希望影响后续会话时可关闭。"
              />
              <n-switch v-model:value="contextDraft.default_policy.cross_session_memory.enabled" />
            </div>
            <div class="context-setting-line">
              <setting-help-label
                label="写入记忆"
                help="允许从当前对话提取可复用信息。例如记住“回答使用中文”这类长期偏好。"
              />
              <n-switch v-model:value="contextDraft.default_policy.cross_session_memory.write_enabled" />
            </div>
            <div class="context-setting-line">
              <setting-help-label
                label="注入记忆"
                help="允许把相关的历史记忆加入新请求。例如讨论同一项目时带入此前确认的技术决策。"
              />
              <n-switch v-model:value="contextDraft.default_policy.cross_session_memory.injection_enabled" />
            </div>
            <context-number-setting
              v-model="contextDraft.default_policy.cross_session_memory.write_interval_turns"
              label="写入间隔（轮）"
              help="每隔多少轮对话整理一次记忆。例如设为 3，约每完成 3 轮用户与 Agent 对话后提取一次。"
              :min="1"
              :max="1000"
            />
            <context-number-setting
              v-model="contextDraft.default_policy.cross_session_memory.max_candidates"
              label="最大候选数"
              help="检索阶段最多比较多少条候选记忆。例如设为 24，会从相关候选中继续筛选最终注入项。"
              :min="1"
              :max="128"
            />
            <context-number-setting
              v-model="contextDraft.default_policy.cross_session_memory.min_score"
              label="最低相关分数"
              help="候选记忆进入上下文所需的最低相关度，范围 0–1。例如 0.55 会过滤关联较弱的历史信息。"
              :min="0"
              :max="1"
              :step="0.05"
            />
            <context-number-setting
              v-model="contextDraft.default_policy.cross_session_memory.max_items"
              label="最大注入条数"
              help="单次请求最多注入多少条记忆。例如设为 8，即使检索到更多相关内容也只选最多 8 条。"
              :min="1"
              :max="64"
            />
            <context-number-setting
              v-model="contextDraft.default_policy.cross_session_memory.max_tokens"
              label="最大注入 Token"
              help="所有跨会话记忆占用的总上下文预算。例如 1200 表示记忆内容合计最多约 1200 Token。"
              :min="100"
              :max="32000"
            />

            <div class="context-subsection-title">分类上限</div>
            <context-number-setting
              v-for="kind in memoryKinds"
              :key="kind"
              v-model="contextDraft.default_policy.cross_session_memory.per_kind_limits[kind]"
              :label="memoryKindLabel(kind)"
              :help="memoryKindHelp(kind)"
              :min="0"
              :max="32"
            />

            <div v-if="contextConfigError" class="resource-error">{{ contextConfigError }}</div>
            <n-button
              size="small"
              type="primary"
              class="context-save-button"
              :loading="contextConfigSaving"
              :disabled="!contextConfigDirty"
              @click="saveContextConfig"
            >
              {{ t('common.save') }}
            </n-button>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.models') }}</div>
            <n-tag size="small" :bordered="false">{{ modelBindings.length }}</n-tag>
          </div>
          <n-empty v-if="modelBindings.length === 0" :description="t('agentDetail.noModels')" size="small" />
          <div v-else class="detail-list">
            <div v-for="binding in modelBindings" :key="binding.role" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ binding.role }} · {{ binding.profile_id }}</div>
                <div v-if="binding.reason" class="item-description">{{ binding.reason }}</div>
                <div class="item-meta">
                  {{ binding.selection_source || t('common.auto') }}
                </div>
                <div class="model-override-grid">
                  <div class="model-override-field">
                    <setting-help-label
                      label="Temperature"
                      help="覆盖当前 Agent 使用该模型时的随机性。留空跟随模型池配置；模型池也未设置时使用供应商默认值。数值越低，输出通常越稳定。"
                    />
                    <n-input-number
                      v-model:value="modelOverrideDrafts[binding.role].temperature"
                      clearable
                      :min="0"
                      :step="0.1"
                      placeholder="跟随模型池"
                    />
                  </div>
                  <div class="model-override-field">
                    <setting-help-label
                      label="最大输出 Token"
                      help="限制单次模型回复的最大 Token 数。留空跟随模型池配置；不影响上下文大小。"
                    />
                    <n-input-number
                      v-model:value="modelOverrideDrafts[binding.role].max_output_tokens"
                      clearable
                      :min="1"
                      :precision="0"
                      placeholder="跟随模型池"
                    />
                  </div>
                </div>
              </div>
              <n-tag size="small" :bordered="false">
                {{ agentPackage.model_contract?.version || t('common.unknown') }}
              </n-tag>
            </div>
          </div>
          <div v-if="modelConfigError" class="resource-error">{{ modelConfigError }}</div>
          <n-button
            v-if="modelBindings.length > 0"
            size="small"
            type="primary"
            class="context-save-button"
            :loading="modelConfigSaving"
            :disabled="!modelConfigDirty"
            @click="saveModelOverrides"
          >
            {{ t('common.save') }}
          </n-button>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.modelTools') }}</div>
            <n-tag size="small" :bordered="false">{{ modelToolBindings.length }}</n-tag>
          </div>
          <n-empty v-if="modelToolBindings.length === 0" :description="t('agentDetail.noModelTools')" size="small" />
          <div v-else class="detail-list">
            <div v-for="binding in modelToolBindings" :key="binding.tool_id" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ binding.tool_id }} · {{ binding.profile_id }}</div>
                <div v-if="binding.description || binding.reason" class="item-description">
                  {{ binding.description || binding.reason }}
                </div>
                <div class="item-meta">
                  {{ binding.capability || t('common.unknown') }} · {{ binding.selection_source || t('common.auto') }}
                </div>
              </div>
              <n-tag size="small" :bordered="false">
                {{ agentPackage.model_contract?.version || t('common.unknown') }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.packageTools') }}</div>
            <n-tag size="small" :bordered="false">{{ packageTools.length }}</n-tag>
          </div>
          <n-empty v-if="packageTools.length === 0" :description="t('agentDetail.noPackageTools')" size="small" />
          <div v-else class="detail-list">
            <div v-for="tool in packageTools" :key="tool.id || tool.name" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ tool.name }}</div>
                <div v-if="tool.description" class="item-description">{{ tool.description }}</div>
                <div class="item-meta">{{ toolMeta(tool, t) }}</div>
              </div>
              <n-tag size="small" :bordered="false">{{ tool.risk_level || 'low' }}</n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">运行环境</div>
            <n-tag size="small" :type="agentPackage.environment?.status === 'ready' ? 'success' : 'warning'">{{ agentPackage.environment?.status || 'missing' }}</n-tag>
          </div>
          <div class="item-meta">{{ environmentMeta }}</div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">MCP</div>
            <n-tag size="small" :bordered="false">{{ mcpServers.length }}</n-tag>
          </div>
          <n-empty v-if="mcpServers.length === 0" :description="t('agentDetail.noMcp')" size="small" />
          <div v-else class="detail-list">
            <div v-for="server in mcpServers" :key="extensionKey(server)" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ server.name }}</div>
                <div v-if="extensionDescription(server)" class="item-description">
                  {{ extensionDescription(server) }}
                </div>
                <div class="item-meta">{{ mcpMeta(server, t) }}</div>
              </div>
              <n-tag size="small" :bordered="false" :type="server.enabled === false ? 'default' : 'success'">
                {{ server.enabled === false ? t('agentDetail.disabled') : t('agentDetail.enabled') }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">Skill</div>
            <n-tag size="small" :bordered="false">{{ skills.length }}</n-tag>
          </div>
          <n-empty v-if="skills.length === 0" :description="t('agentDetail.noSkill')" size="small" />
          <div v-else class="detail-list">
            <div v-for="skill in skills" :key="extensionKey(skill)" class="detail-list-item">
              <div class="item-main">
                <div class="item-title">{{ skill.name }}</div>
                <div v-if="extensionDescription(skill)" class="item-description">
                  {{ extensionDescription(skill) }}
                </div>
                <div class="item-meta">{{ skillMeta(skill, t) }}</div>
              </div>
              <n-tag size="small" :bordered="false" :type="skill.enabled === false ? 'default' : 'success'">
                {{ skill.enabled === false ? t('agentDetail.disabled') : t('agentDetail.enabled') }}
              </n-tag>
            </div>
          </div>
        </section>

        <section class="detail-section">
          <div class="section-header">
            <div class="section-label">{{ t('agentDetail.knowledgeBase') }}</div>
            <n-tag size="small" :bordered="false">{{ knowledgeSources.length }}</n-tag>
          </div>
          <n-empty v-if="knowledgeSources.length === 0" :description="t('agentDetail.noKnowledge')" size="small" />
          <div v-else class="detail-list">
            <div
              v-for="source in knowledgeSources"
              :key="source.source_id || source.name"
              class="detail-list-item knowledge-item"
            >
              <div class="item-main">
                <div class="item-title">{{ source.name }}</div>
                <div class="item-description">
                  {{ knowledgeMeta(source, locale, t) }}
                </div>
                <div v-if="source.uri" class="item-uri">{{ source.uri }}</div>
                <div v-if="knowledgeSamples(source, t)" class="item-meta">
                  {{ knowledgeSamples(source, t) }}
                </div>
              </div>
              <n-tag size="small" :bordered="false" :type="source.status === 'ready' ? 'success' : 'default'">
                {{ packageStatusLabel(source.status) }}
              </n-tag>
            </div>
          </div>
        </section>

        <section v-if="agentPackage.extensions_error || agentPackage.knowledge_error" class="detail-section">
          <div class="section-label">{{ t('agentDetail.readHint') }}</div>
          <div v-if="agentPackage.extensions_error" class="detail-note">
            {{ t('agentDetail.extensionsReadFailed', { error: agentPackage.extensions_error }) }}
          </div>
          <div v-if="agentPackage.knowledge_error" class="detail-note">
            {{ t('agentDetail.knowledgeReadFailed', { error: agentPackage.knowledge_error }) }}
          </div>
        </section>

        <section v-if="agentPackage.error" class="detail-section">
          <div class="section-label">{{ t('agentDetail.statusNote') }}</div>
          <div class="detail-note">
            {{ agentPackage.error }}
          </div>
        </section>

        <div v-if="!embedded" class="detail-actions">
          <n-button
            v-if="ready"
            :loading="instanceBusy"
            @click="emit('shutdown', agentPackage)"
          >
            {{ t('agentDetail.shutdown') }}
          </n-button>
          <n-button
            v-else
            :loading="instanceBusy"
            @click="emit('initialize', agentPackage)"
          >
            {{ t('agentDetail.initialize') }}
          </n-button>
          <n-button type="primary" :disabled="!ready" @click="emit('run', agentPackage)">{{ t('agents.run') }}</n-button>
          <n-button @click="emit('evolve', agentPackage)">{{ t('agents.evolve') }}</n-button>
          <n-button :loading="exportBusy" @click="emit('export', agentPackage)">
            {{ t('common.export') }}
          </n-button>
        </div>
      </div>
    </component>
  </component>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInputNumber,
  NSelect,
  NSwitch,
  NTag,
} from 'naive-ui'
import { agentPackagesApi, type AgentPackageResourceDescriptorView } from '@/api/agentPackages'
import { useI18n } from '@/composables/useI18n'
import type {
  AgentPackageExtensionView,
  AgentPackageInstanceView,
  AgentPackageKnowledgeSourceView,
  AgentPackageToolView,
  AgentPackageView,
} from '@/stores/agent'
import {
  extensionDescription,
  extensionKey,
  formatPackageDateTime,
  isPackageReady,
  knowledgeMeta,
  knowledgeSamples,
  mcpMeta,
  packageDisplayName,
  skillMeta,
  statusType,
  toolMeta,
} from './agentPackagePresentation'
import ResourceSchemaForm from './ResourceSchemaForm.vue'
import ContextNumberSetting from './ContextNumberSetting.vue'
import SettingHelpLabel from './SettingHelpLabel.vue'
import AgentToolSettingsPanel from './AgentToolSettingsPanel.vue'
import {
  createResourceDraft,
  resourceDraftComplete,
  resourceDraftValue,
} from './resourceSchema'

const props = withDefaults(defineProps<{
  show?: boolean
  embedded?: boolean
  agentPackage: AgentPackageView | null
  instance?: AgentPackageInstanceView | null
  instanceBusy?: boolean
  exportBusy?: boolean
}>(), {
  show: true,
  embedded: false,
  instance: null,
  instanceBusy: false,
  exportBusy: false,
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  initialize: [agentPackage: AgentPackageView]
  shutdown: [agentPackage: AgentPackageView]
  run: [agentPackage: AgentPackageView]
  evolve: [agentPackage: AgentPackageView]
  export: [agentPackage: AgentPackageView]
  packageUpdated: [agentPackage: AgentPackageView]
}>()

const ready = computed(() => isPackageReady(props.instance))
const { locale, t } = useI18n()
const drawerContainerProps = computed(() => props.embedded
  ? { class: 'embedded-detail-shell' }
  : { show: props.show, width: 460, placement: 'right' as const })
const detailContentProps = computed(() => props.embedded
  ? { class: 'embedded-detail-content' }
  : { title: t('agentDetail.title'), closable: true })
const detailVisible = computed(() => props.embedded || props.show)
const packageTools = computed<AgentPackageToolView[]>(() => props.agentPackage?.tools || [])
const mcpServers = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.mcp_servers || [])
const skills = computed<AgentPackageExtensionView[]>(() => props.agentPackage?.skills || [])
const knowledgeSources = computed<AgentPackageKnowledgeSourceView[]>(() => props.agentPackage?.knowledge_sources || [])
const resourceItems = ref<AgentPackageResourceDescriptorView[]>([])
const resourceStoreReady = ref(false)
const resourceDrafts = ref<Record<string, unknown>>({})
const resourceErrors = ref<Record<string, string>>({})
const resourceValidationVisible = ref<Record<string, boolean>>({})
const resourceLoadError = ref('')
const resourceSavingId = ref('')
let resourceRequestId = 0
const resourceStatusType = computed(() => resourceItems.value.every(item => !item.required || item.configured) ? 'success' : 'warning')
const resourceStatusLabel = computed(() => resourceStoreReady.value ? '运行时配置' : '需要主密钥')
const environmentMeta = computed(() => {
  const environment = props.agentPackage?.environment
  if (!environment) return '尚未生成环境锁定信息'
  const platform = environment.platform?.architecture || ''
  return [environment.image, platform, environment.verified_at].filter(Boolean).join(' · ') || environment.error || '尚未生成环境锁定信息'
})
const modelBindings = computed(() => {
  const bindings = props.agentPackage?.model_contract?.bindings || {}
  return Object.entries(bindings).map(([role, binding]) => ({ role, ...binding }))
})
const modelToolBindings = computed(() => {
  const bindings = props.agentPackage?.model_contract?.tool_bindings || {}
  return Object.entries(bindings).map(([tool_id, binding]) => ({ tool_id, ...binding }))
})
type MemoryKind = 'constraint' | 'preference' | 'decision' | 'fact' | 'artifact'
interface ContextConfigDraft {
  version: 'context_system.v1'
  enabled: boolean
  context_window_tokens: number | null
  default_policy: {
    version: 'context_policy.v1'
    compression: {
      enabled: boolean
      trigger_token_threshold: number | null
      keep_recent_messages: number
    }
    cross_session_memory: {
      enabled: boolean
      write_enabled: boolean
      injection_enabled: boolean
      write_interval_turns: number
      max_candidates: number
      min_score: number
      max_items: number
      max_tokens: number
      per_kind_limits: Record<MemoryKind, number>
    }
  }
}
interface ModelOverrideDraft {
  temperature: number | null
  max_output_tokens: number | null
}
interface SchedulerConfigDraft {
  store_backend: 'sqlite'
  store_path: string
  timezone: string
  default_concurrency_policy: 'skip' | 'queue' | 'replace'
  default_timeout_seconds: number
  unattended_policy: 'deny_if_approval_required' | 'pause_and_wait_for_user' | 'allow_preapproved_only'
  default_failure_policy: {
    enabled: boolean
    max_consecutive_failures: number
    action: 'pause'
  }
}
const memoryKinds: MemoryKind[] = ['constraint', 'preference', 'decision', 'fact', 'artifact']
const contextDraft = ref<ContextConfigDraft | null>(null)
const contextConfigSaving = ref(false)
const contextConfigError = ref('')
const schedulerDraft = ref<SchedulerConfigDraft | null>(null)
const schedulerConfigSaving = ref(false)
const schedulerConfigError = ref('')
const modelOverrideDrafts = ref<Record<string, ModelOverrideDraft>>({})
const modelToolOverrideDrafts = ref<Record<string, ModelOverrideDraft>>({})
const modelConfigSaving = ref(false)
const modelConfigError = ref('')
const contextConfigDirty = computed(() => {
  const persisted = props.agentPackage?.context_contract?.config
  if (!contextDraft.value || !persisted) return false
  return JSON.stringify(contextDraft.value) !== JSON.stringify(persisted)
})
const schedulerConfigDirty = computed(() => {
  const persisted = props.agentPackage?.scheduler_contract?.config
  if (!schedulerDraft.value || !persisted) return false
  return JSON.stringify(schedulerDraft.value) !== JSON.stringify(persisted)
})
const schedulerConcurrencyOptions = [
  { label: '跳过本次触发', value: 'skip' },
  { label: '排队等待', value: 'queue' },
  { label: '替换当前运行', value: 'replace' },
]
const schedulerUnattendedOptions = [
  { label: '需要审批时拒绝执行', value: 'deny_if_approval_required' },
  { label: '暂停并等待用户', value: 'pause_and_wait_for_user' },
  { label: '仅允许预先批准的操作', value: 'allow_preapproved_only' },
]
const timezoneOptions = computed(() => {
  const intl = Intl as typeof Intl & { supportedValuesOf?: (key: 'timeZone') => string[] }
  const current = schedulerDraft.value?.timezone || ''
  const values = intl.supportedValuesOf?.('timeZone') || []
  if (current && !values.includes(current)) values.unshift(current)
  return values.map(value => ({ label: value, value }))
})
const modelConfigDirty = computed(() => {
  const bindings = props.agentPackage?.model_contract?.bindings || {}
  const toolBindings = props.agentPackage?.model_contract?.tool_bindings || {}
  const persistedBindings = Object.fromEntries(
    Object.entries(bindings).map(([role, binding]) => [role, modelOverrideDraft(binding.overrides)]),
  )
  const persistedToolBindings = Object.fromEntries(
    Object.entries(toolBindings).map(([toolId, binding]) => [toolId, modelOverrideDraft(binding.overrides)]),
  )
  return JSON.stringify(modelOverrideDrafts.value) !== JSON.stringify(persistedBindings)
    || JSON.stringify(modelToolOverrideDrafts.value) !== JSON.stringify(persistedToolBindings)
})

watch(
  () => props.agentPackage?.context_contract?.config,
  (contract) => {
    contextDraft.value = contract
      ? JSON.parse(JSON.stringify(contract)) as ContextConfigDraft
      : null
    contextConfigError.value = ''
  },
  { immediate: true },
)

watch(
  () => props.agentPackage?.scheduler_contract?.config,
  (config) => {
    schedulerDraft.value = config
      ? JSON.parse(JSON.stringify(config)) as SchedulerConfigDraft
      : null
    schedulerConfigError.value = ''
  },
  { immediate: true },
)

watch(
  () => props.agentPackage?.model_contract,
  (contract) => {
    modelOverrideDrafts.value = Object.fromEntries(
      Object.entries(contract?.bindings || {}).map(
        ([role, binding]) => [role, modelOverrideDraft(binding.overrides)],
      ),
    )
    modelToolOverrideDrafts.value = Object.fromEntries(
      Object.entries(contract?.tool_bindings || {}).map(
        ([toolId, binding]) => [toolId, modelOverrideDraft(binding.overrides)],
      ),
    )
    modelConfigError.value = ''
  },
  { immediate: true },
)


watch(
  () => [detailVisible.value, props.agentPackage?.package_id] as const,
  async ([visible, packageId]) => {
    if (!visible || !packageId) {
      resourceRequestId += 1
      resourceItems.value = []
      resourceStoreReady.value = false
      resourceDrafts.value = {}
      resourceErrors.value = {}
      resourceValidationVisible.value = {}
      resourceLoadError.value = ''
      return
    }
    await loadResources(packageId)
  },
  { immediate: true },
)

async function loadResources(packageId: string): Promise<void> {
  const requestId = ++resourceRequestId
  resourceLoadError.value = ''
  let payload
  try {
    payload = await agentPackagesApi.resources(packageId)
  } catch (error) {
    if (requestId === resourceRequestId) resourceLoadError.value = errorMessage(error)
    return
  }
  if (
    requestId !== resourceRequestId ||
    !detailVisible.value ||
    props.agentPackage?.package_id !== packageId
  ) return
  resourceItems.value = payload.resources
  resourceStoreReady.value = payload.key_available
  resourceDrafts.value = Object.fromEntries(
    payload.resources.map(item => [item.resource_id, createResourceDraft(item.value_schema, item.value)]),
  )
  resourceErrors.value = {}
  resourceValidationVisible.value = {}
}

async function saveResource(resource: AgentPackageResourceDescriptorView) {
  const packageId = props.agentPackage?.package_id
  if (!packageId) return
  resourceValidationVisible.value = {
    ...resourceValidationVisible.value,
    [resource.resource_id]: true,
  }
  if (!resourceDraftComplete(resource.value_schema, resourceDrafts.value[resource.resource_id])) return
  resourceSavingId.value = resource.resource_id
  resourceErrors.value = { ...resourceErrors.value, [resource.resource_id]: '' }
  try {
    const value = resourceDraftValue(resource.value_schema, resourceDrafts.value[resource.resource_id])
    await agentPackagesApi.putResource(packageId, resource.resource_id, value)
    await loadResources(packageId)
  } catch (error) {
    resourceErrors.value = { ...resourceErrors.value, [resource.resource_id]: errorMessage(error) }
  } finally {
    resourceSavingId.value = ''
  }
}

async function removeResource(resourceId: string) {
  const packageId = props.agentPackage?.package_id
  if (!packageId) return
  resourceSavingId.value = resourceId
  resourceErrors.value = { ...resourceErrors.value, [resourceId]: '' }
  try {
    await agentPackagesApi.deleteResource(packageId, resourceId)
    await loadResources(packageId)
  } catch (error) {
    resourceErrors.value = { ...resourceErrors.value, [resourceId]: errorMessage(error) }
  } finally {
    resourceSavingId.value = ''
  }
}

async function saveContextConfig(): Promise<void> {
  const packageId = props.agentPackage?.package_id
  if (!packageId || !contextDraft.value || !contextConfigDirty.value) return
  contextConfigSaving.value = true
  contextConfigError.value = ''
  try {
    const response = await agentPackagesApi.updateContextConfig(packageId, contextDraft.value)
    emit('packageUpdated', response.package as AgentPackageView)
  } catch (error) {
    contextConfigError.value = errorMessage(error)
  } finally {
    contextConfigSaving.value = false
  }
}

async function saveSchedulerConfig(): Promise<void> {
  const packageId = props.agentPackage?.package_id
  if (!packageId || !schedulerDraft.value || !schedulerConfigDirty.value) return
  schedulerConfigSaving.value = true
  schedulerConfigError.value = ''
  try {
    const response = await agentPackagesApi.updateSchedulerConfig(packageId, schedulerDraft.value)
    emit('packageUpdated', response.package as AgentPackageView)
  } catch (error) {
    schedulerConfigError.value = errorMessage(error)
  } finally {
    schedulerConfigSaving.value = false
  }
}

async function saveModelOverrides(): Promise<void> {
  const packageId = props.agentPackage?.package_id
  if (!packageId || !modelConfigDirty.value) return
  modelConfigSaving.value = true
  modelConfigError.value = ''
  try {
    const response = await agentPackagesApi.updateModelOverrides(
      packageId,
      modelOverrideDrafts.value,
      modelToolOverrideDrafts.value,
    )
    emit('packageUpdated', response.package as AgentPackageView)
  } catch (error) {
    modelConfigError.value = errorMessage(error)
  } finally {
    modelConfigSaving.value = false
  }
}

function modelOverrideDraft(overrides: Record<string, any> | undefined): ModelOverrideDraft {
  return {
    temperature: typeof overrides?.temperature === 'number' ? overrides.temperature : null,
    max_output_tokens: typeof overrides?.max_output_tokens === 'number'
      ? overrides.max_output_tokens
      : null,
  }
}

function memoryKindLabel(kind: MemoryKind): string {
  return {
    constraint: '约束',
    preference: '偏好',
    decision: '决策',
    fact: '事实',
    artifact: '产物',
  }[kind]
}

function memoryKindHelp(kind: MemoryKind): string {
  return {
    constraint: '单次最多注入的约束记忆。例如“必须使用中文”“不要修改原文件”。',
    preference: '单次最多注入的偏好记忆。例如“偏好简洁回复”“界面使用黑白风格”。',
    decision: '单次最多注入的已确认决策。例如“主运行模式采用 ReAct”。',
    fact: '单次最多注入的稳定事实。例如“服务器位于阿里云北京区域”。',
    artifact: '单次最多注入的产物线索。例如此前生成的报告名称或工作区文件。',
  }[kind]
}

function contextSourceLabel(source: string | null | undefined): string {
  return {
    agent_override: 'Agent 覆盖',
    agent_window_limit: '受 Agent 窗口限制',
    model_profile: '跟随模型',
    system_default: '系统默认',
  }[source || ''] || '系统默认'
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function formatTokens(value: number | null | undefined): string {
  if (!value) return t('common.unset')
  return `${formatTokenK(value)}k`
}

function formatTokenK(value: number): string {
  const kValue = value / 1000
  return Number.isInteger(kValue) ? String(kValue) : String(Math.round(kValue * 10) / 10)
}

function packageStatusLabel(status: string | null | undefined): string {
  const value = status || ''
  const labels: Record<string, string> = {
    ready: t('agents.statusReady'),
    running: t('agents.statusRunning'),
    failed: t('run.failed'),
    initializing: t('agentDetail.initializing'),
  }
  return labels[value] || value || t('common.unknown')
}
</script>

<style scoped>
.detail-panel {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.embedded-detail-shell,
.embedded-detail-content {
  height: 100%;
  min-height: 0;
}

.embedded-detail-content {
  overflow-y: auto;
  padding: var(--app-space-lg);
}

.embedded-detail-content .detail-list-item {
  flex-direction: column;
}

.embedded-detail-content .item-title {
  white-space: normal;
  overflow-wrap: anywhere;
}

.embedded-detail-content .resource-actions {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
}

.detail-section {
  padding-bottom: var(--app-space-lg);
  border-bottom: 1px solid var(--app-divider);
}

.resource-section {
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.resource-section-hint {
  margin-bottom: var(--app-space-md);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.45;
}

.resource-item { align-items: flex-start; background: var(--app-surface); }
.resource-input { margin-top: var(--app-space-md); }
.resource-actions { display: grid; justify-items: end; gap: var(--app-space-xs); }

.resource-error {
  margin-top: var(--app-space-sm);
  color: var(--n-color-error, #d03050);
  font-size: var(--app-font-xs);
  line-height: 1.45;
}

.detail-section:last-child {
  border-bottom: 0;
}

.detail-title {
  font-size: var(--app-font-xl);
  font-weight: 600;
  color: var(--app-text-strong);
  letter-spacing: -0.01em;
}

.detail-description {
  margin-top: var(--app-space-xs);
  color: var(--app-text-secondary);
  line-height: var(--app-leading-normal);
}

.detail-grid {
  display: grid;
  gap: var(--app-space-sm);
}

.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  font-size: var(--app-font-md);
}

.detail-row span,
.section-label {
  color: var(--app-text-secondary);
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
  margin-bottom: var(--app-space-sm);
}

.detail-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
}

.detail-list-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-md);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  transition: border-color var(--app-transition-fast), background-color var(--app-transition-fast);
}

.detail-list-item:hover {
  border-color: var(--app-border-hover);
  background: var(--app-surface-hover);
}

.item-main {
  min-width: 0;
  flex: 1;
}

.item-title {
  color: var(--app-text);
  font-size: var(--app-font-md);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-description {
  margin-top: var(--app-space-xs);
  color: var(--app-text-secondary);
  font-size: var(--app-font-sm);
  line-height: var(--app-leading-normal);
}

.item-meta {
  margin-top: var(--app-space-xs);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.4;
}

.model-override-grid {
  display: grid;
  gap: var(--app-space-sm);
  margin-top: var(--app-space-md);
}

.model-override-field {
  display: grid;
  gap: var(--app-space-xs);
}

.model-override-field :deep(.n-input-number) {
  width: 100%;
}

.context-policy-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-md);
}

.context-setting-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-md);
}

.context-subsection-title {
  padding-top: var(--app-space-xs);
  color: var(--app-text);
  font-size: var(--app-font-sm);
  font-weight: 600;
}

.context-value-control {
  width: 100%;
}

.context-value-control :deep(.n-input-number) {
  width: 100%;
}

.scheduler-value-control {
  width: 220px;
  flex: 0 0 220px;
}

.context-config-row {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-sm);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
}

.context-config-main {
  min-width: 0;
}

.context-config-heading {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-xs);
}

.context-window-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-xs) var(--app-space-sm);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.4;
}

.context-window-help {
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.45;
}

.context-save-button {
  align-self: flex-end;
}

.item-uri {
  margin-top: var(--app-space-xs);
  color: var(--app-text-muted);
  font-size: var(--app-font-xs);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.knowledge-item {
  align-items: flex-start;
}

.detail-actions {
  display: flex;
  gap: var(--app-space-sm);
}

.detail-note {
  margin-top: var(--app-space-sm);
  padding: var(--app-space-md);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-muted);
  color: var(--app-text-secondary);
  font-size: var(--app-font-md);
  line-height: var(--app-leading-normal);
}

.detail-note + .detail-note {
  margin-top: var(--app-space-sm);
}
</style>

import { nextTick } from 'vue'
import { knowledgeSourceView, schedulerJobView } from '@/stores/runtime/viewMappers'
import { useAgentStore } from '@/stores/agent'
import { useKnowledgeStore } from '@/stores/knowledge'
import { useRuntimeStore } from '@/stores/runtime'
import { useRuntimePreferencesStore } from '@/stores/runtimePreferences'
import { useSchedulerStore } from '@/stores/scheduler'
import { useUiStore } from '@/stores/ui'
import type { ChatMessagePart, TranscriptItem } from '@/types/protocol'
import { showcaseRouter } from './router'
import {
  SHOWCASE_PACKAGE_ID,
  SHOWCASE_SESSION_ID,
  agentPackage,
} from './fakeServer'

interface ShowcaseDirectorOptions {
  onResetTransition: (active: boolean) => void
}

type ExtensionKind = 'mcp' | 'skill'

const BASE_TIME = '2026-07-29T02:20:00.000Z'
const CHAT_PACKAGE_ID = 'factory_chat'
const SCENE_GAP_MS = 950
const READING_PAUSE_MS = 2200

export function useShowcaseDirector(options: ShowcaseDirectorOptions) {
  const runtimeStore = useRuntimeStore()
  const agentStore = useAgentStore()
  const knowledgeStore = useKnowledgeStore()
  const schedulerStore = useSchedulerStore()
  const uiStore = useUiStore()
  const preferences = useRuntimePreferencesStore()
  let stopped = false
  let cycle = 0

  function start(): void {
    stopped = false
    preferences.setMainModelProfileId('showcase-main-model')
    preferences.setReasoningIntensity(2)
    seedAgents()
    void play()
  }

  function stop(): void {
    stopped = true
  }

  async function play(): Promise<void> {
    while (!stopped) {
      cycle += 1
      await conversationScene()
      await transition()
      await manufacturingScene()
      await transition()
      await evolutionScene()
      await transition()
      await collaborationScene()
      await transition()
      await knowledgeScene()
      await transition()
      await schedulerScene()
      await transition()
      await extensionScene('mcp')
      await transition()
      await extensionScene('skill')
      if (stopped) return
      await wait(READING_PAUSE_MS)
      options.onResetTransition(true)
      await wait(620)
      options.onResetTransition(false)
      await wait(420)
    }
  }

  async function conversationScene(): Promise<void> {
    await showcaseRouter.replace({
      name: 'Factory',
      query: { package_id: CHAT_PACKAGE_ID, new: '1' },
    })
    await waitForView('.factory-view')
    agentStore.enterAgentChat(CHAT_PACKAGE_ID, null)
    runtimeStore.showEmptyAgentPackageSession(CHAT_PACKAGE_ID)
    resetConversation()
    uiStore.setConversationDockPanel('workspace')
    await wait(850)

    const input = await waitForElement<HTMLTextAreaElement>('.message-input-container textarea')
    if (!input) return
    await typeText(input, '帮我把下周东京出差和周末亲子行程安排在一起')
    appendMessage(message('user', [
      textPart('帮我把下周东京出差和周末亲子行程安排在一起'),
    ]))
    input.value = ''
    await wait(1050)

    appendMessage(message('assistant', [
      textPart('可以。我会把工作日会议、通勤距离和周末亲子活动一起考虑，先整理成一个不会赶路的五日安排。'),
    ], { display_name: '闲聊' }))
    await wait(1500)
    appendMessage(message('assistant', [
      toolPart('workspace_write', 'completed', {
        path: 'output/东京五日安排.md',
      }, {
        path: 'output/东京五日安排.md',
        status: 'created',
      }),
      textPart('初版已经放进工作区：周四、周五以会议为主，周末安排上野、浅草和台场，并预留了雨天替代方案。'),
    ], { display_name: '闲聊' }))
    await wait(READING_PAUSE_MS)
  }

  async function manufacturingScene(): Promise<void> {
    await showcaseRouter.replace({
      name: 'Factory',
      query: { package_id: CHAT_PACKAGE_ID, new: '1' },
    })
    await waitForView('.message-input-container')
    agentStore.enterAgentChat(CHAT_PACKAGE_ID, null)
    runtimeStore.showEmptyAgentPackageSession(CHAT_PACKAGE_ID)
    resetConversation()
    uiStore.setConversationDockPanel('workspace')
    await wait(900)

    const input = await waitForElement<HTMLTextAreaElement>('.message-input-container textarea')
    if (!input) return
    await typeText(input, '制造一个能持续调研信息并交付 PDF 的旅行规划 Agent')
    appendMessage(message('user', [
      textPart('制造一个能持续调研信息并交付 PDF 的旅行规划 Agent'),
    ]))
    input.value = ''
    await wait(1100)

    appendMessage(message('assistant', [
      textPart('我会把需求转成可运行的 Agent 包：先定义交付标准，再配置工具、上下文与运行模式。'),
      toolPart('create_agent_authoring', 'running', {
        action: 'configure_package',
        agent_name: '旅行规划师',
      }, null),
    ], { display_name: '制造 Agent' }))
    await wait(1900)
    completeLastTool({
      status: 'committed',
      operations_count: 6,
      affected_files: [
        changedFile('package.json', 'created', 38),
        changedFile('context.json', 'created', 24),
        changedFile('tools/travel_plan.py', 'created', 112),
      ],
      duration_ms: 1240,
    })
    appendMessage(message('assistant', [
      textPart('基础包已经生成并通过结构检查。旅行规划师现在具备明确的输入、执行步骤与 PDF 交付标准。'),
    ], { display_name: '制造 Agent' }))
    await wait(READING_PAUSE_MS)
  }

  async function evolutionScene(): Promise<void> {
    agentStore.selectPackage(SHOWCASE_PACKAGE_ID)
    await showcaseRouter.replace({
      name: 'Factory',
      query: { package_id: CHAT_PACKAGE_ID, new: '1' },
    })
    await waitForView('.message-input-container')
    agentStore.enterAgentChat(CHAT_PACKAGE_ID, null)
    runtimeStore.showEmptyAgentPackageSession(CHAT_PACKAGE_ID)
    resetConversation()
    await wait(1000)

    appendMessage(message('user', [
      textPart('让它能根据同行人的年龄、预算和天气自动给出替代路线。'),
    ]))
    await wait(1100)
    appendMessage(message('assistant', [
      textPart('正在分析现有旅行规划师的边界。我会保留原有交付格式，并增强约束建模与备选方案生成。'),
      toolPart('evolve_agent_authoring', 'running', {
        package_id: SHOWCASE_PACKAGE_ID,
        focus: ['同行人约束', '预算控制', '天气备选'],
      }, null),
    ], { display_name: '进化 Agent' }))
    await wait(1900)
    completeLastTool({
      status: 'committed',
      version: '2.0',
      improved_capabilities: ['家庭成员适配', '预算分级', '天气降级路线'],
      duration_ms: 1680,
    })
    appendMessage(message('assistant', [
      textPart('进化完成。新版会在每天的计划中同时给出主路线、预算区间和雨天替代方案。'),
    ], { display_name: '进化 Agent' }))
    await wait(READING_PAUSE_MS)
  }

  async function collaborationScene(): Promise<void> {
    await showcaseRouter.replace({
      name: 'Factory',
      query: { package_id: CHAT_PACKAGE_ID, new: '1' },
    })
    await waitForView('.factory-view')
    agentStore.enterAgentChat(CHAT_PACKAGE_ID, null)
    runtimeStore.showEmptyAgentPackageSession(CHAT_PACKAGE_ID)
    resetConversation()
    uiStore.setConversationDockPanel('workspace')
    appendMessage(message('user', [
      textPart('请分工完成东京五日亲子旅行手册，并给出可直接执行的最终版本。'),
    ]))
    await wait(1000)
    appendMessage(message('assistant', [
      textPart('我已拆分任务：调研员核对实时资料，行程编排师处理路线与节奏，文档交付员负责最终手册。'),
      toolPart('agent_team', 'running', {
        tasks: [
          { assignee_package_id: 'destination_researcher', task_text: '核对实时资料' },
          { assignee_package_id: 'itinerary_designer', task_text: '编排行程路线' },
          { assignee_package_id: 'document_assistant', task_text: '生成最终手册' },
        ],
      }, null),
    ], { display_name: '主 Agent' }))
    runtimeStore.runStatus = 'waiting_for_workers'
    await wait(1800)

    completeLastTool({
      status: 'submitted',
      submitted_count: 3,
    })
    appendMessage(message('assistant', [
      textPart('实时资料与路线编排已经汇总，文档交付员正在生成最终 PDF。'),
    ], { display_name: '主 Agent' }))
    await wait(1700)
    runtimeStore.runStatus = 'completed'
    appendMessage(message('assistant', [
      textPart('协作完成。最终版本包含每日路线、交通换乘、预算、预约清单与雨天备选。'),
      artifactPart('东京五日亲子旅行手册.pdf', 'output/东京五日亲子旅行手册.pdf'),
    ], { display_name: '主 Agent' }))
    await wait(READING_PAUSE_MS)
  }

  async function knowledgeScene(): Promise<void> {
    await showcaseRouter.replace({ name: 'Knowledge' })
    await waitForView('.knowledge-manager')
    await nextTick()
    seedKnowledge()
    await wait(1200)
    const cards = [...document.querySelectorAll<HTMLElement>('.source-card')]
    scrollWithinContainer(
      cards[1],
      document.querySelector<HTMLElement>('.source-list .n-scrollbar-container'),
    )
    await wait(2800)
  }

  async function schedulerScene(): Promise<void> {
    await showcaseRouter.replace({ name: 'Scheduler' })
    await waitForView('.scheduler-manager')
    await nextTick()
    seedScheduler()
    await wait(3800)
  }

  async function extensionScene(kind: ExtensionKind): Promise<void> {
    await showcaseRouter.replace({ name: 'Extensions' })
    await waitForView('.extension-workbench')
    await wait(1150)
    window.dispatchEvent(new CustomEvent('fastagentfactory:showcase-extension-bind', {
      detail: {
        kind,
        identifier: kind === 'mcp' ? 'tavily_search' : 'travel_itinerary',
        targetId: `package:${SHOWCASE_PACKAGE_ID}`,
      },
    }))
    await wait(4100)
  }

  async function transition(): Promise<void> {
    if (stopped) return
    options.onResetTransition(true)
    await wait(360)
    options.onResetTransition(false)
    await wait(SCENE_GAP_MS)
  }

  function seedAgents(): void {
    agentStore.setPackages([
      {
        ...agentPackage,
        package_id: CHAT_PACKAGE_ID,
        agent_id: CHAT_PACKAGE_ID,
        agent_name: '闲聊',
        name: '闲聊',
        agent_description: '系统内置通用 Agent。',
      } as any,
      agentPackage as any,
      {
        ...agentPackage,
        package_id: 'destination_researcher',
        agent_id: 'destination_researcher',
        agent_name: '目的地调研员',
        name: '目的地调研员',
      },
      {
        ...agentPackage,
        package_id: 'itinerary_designer',
        agent_id: 'itinerary_designer',
        agent_name: '行程编排师',
        name: '行程编排师',
      },
      {
        ...agentPackage,
        package_id: 'document_assistant',
        agent_id: 'document_assistant',
        agent_name: '文档交付员',
        name: '文档交付员',
      },
    ])
    agentStore.setRecentSessions([{
      session_id: SHOWCASE_SESSION_ID,
      package_id: SHOWCASE_PACKAGE_ID,
      display_title: '东京五日亲子行程',
      first_user_input: '规划一份东京五日亲子旅行方案',
      turn_count: 4,
      created_at: '2026-07-29T02:00:00.000Z',
      updated_at: '2026-07-29T02:26:00.000Z',
      agent_name: '旅行规划师',
      visible_in_agent_session_list: true,
    }])
    runtimeStore.connectionStatus = 'connected'
  }

  function seedKnowledge(): void {
    const rawSources = [
      knowledgeSource('tokyo-travel', '东京旅行资料', 42, 'ready'),
      knowledgeSource('family-preferences', '家庭偏好与预算', 8, 'ready'),
      knowledgeSource('transport-booking', '交通与预约指南', 19, 'ready'),
    ]
    knowledgeStore.setSources(rawSources.map((source) => knowledgeSourceView(source, BASE_TIME)))
  }

  function seedScheduler(): void {
    schedulerStore.setJobs([
      schedulerJobView({
        job_id: 'weekly-travel-update',
        task_content: '每周更新目的地开放时间',
        schedule_expr: '每周一 09:00 · Asia/Shanghai',
        enabled: true,
        target: {
          target_type: 'graph_run',
          payload: { package_id: SHOWCASE_PACKAGE_ID },
        },
      }),
      schedulerJobView({
        job_id: 'departure-reminder',
        task_content: '出发前 24 小时生成行前提醒',
        schedule_expr: '2026-08-07 08:30 · Asia/Shanghai',
        enabled: true,
        target: {
          target_type: 'tool_call',
          payload: { tool_id: 'travel_reminder' },
        },
      }),
      schedulerJobView({
        job_id: 'budget-summary',
        task_content: '每晚汇总当日预算与次日安排',
        schedule_expr: '每天 21:30 · Asia/Tokyo',
        enabled: false,
        target: {
          target_type: 'graph_run',
          payload: { package_id: SHOWCASE_PACKAGE_ID },
        },
      }),
    ])
  }

  function resetConversation(): void {
    runtimeStore.transcript = []
    runtimeStore.conversationTurns = []
    runtimeStore.tools = []
    runtimeStore.modelStreams = {}
    runtimeStore.activeRequestId = null
    runtimeStore.activeRequests = {}
    runtimeStore.runStatus = 'idle'
    runtimeStore.pendingInterrupt = null
    runtimeStore.createAgentPublishReady = null
  }

  function appendMessage(item: TranscriptItem): void {
    runtimeStore.transcript.push(item)
  }

  function completeLastTool(output: unknown): void {
    const item = [...runtimeStore.transcript].reverse()
      .find((candidate) => candidate.parts.some(
        (part) => part.type === 'tool_execution' && part.status === 'running',
      ))
    const part = item
      ? [...item.parts].reverse().find(
        (candidate) => candidate.type === 'tool_execution' && candidate.status === 'running',
      )
      : undefined
    if (!part || part.type !== 'tool_execution') return
    part.status = 'completed'
    part.output = output
    part.updatedAt = new Date().toISOString()
  }

  return { start, stop }

  async function wait(milliseconds: number): Promise<void> {
    if (stopped) return
    await new Promise<void>((resolve) => window.setTimeout(resolve, milliseconds))
  }

  async function waitForView(selector: string): Promise<void> {
    await nextTick()
    await waitForElement(selector)
  }

  async function waitForElement<T extends Element = Element>(selector: string): Promise<T | null> {
    for (let attempt = 0; attempt < 100 && !stopped; attempt += 1) {
      const element = document.querySelector<T>(selector)
      if (element) return element
      await wait(60)
    }
    return null
  }

  async function typeText(input: HTMLTextAreaElement, text: string): Promise<void> {
    input.value = ''
    for (const character of text) {
      if (stopped) return
      input.value += character
      await wait(78)
    }
  }

  function scrollWithinContainer(
    target: HTMLElement | undefined,
    container: HTMLElement | null,
  ): void {
    if (!target || !container) return
    const targetRect = target.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    const centeredTop = (
      container.scrollTop
      + targetRect.top
      - containerRect.top
      - (container.clientHeight - targetRect.height) / 2
    )
    container.scrollTo({
      top: Math.max(0, centeredTop),
      behavior: 'smooth',
    })
  }

  function id(prefix: string): string {
    return `${prefix}-${cycle}-${crypto.randomUUID()}`
  }

  function message(
    role: 'user' | 'assistant' | 'system',
    parts: ChatMessagePart[],
    metadata: Record<string, any> = {},
  ): TranscriptItem {
    return {
      id: id(`message-${role}`),
      role,
      parts,
      content: parts
        .filter((part) => part.type === 'text')
        .map((part) => part.type === 'text' ? part.text : '')
        .join('\n'),
      timestamp: new Date().toISOString(),
      status: 'completed',
      metadata,
    }
  }

  function textPart(text: string): ChatMessagePart {
    return {
      id: id('text'),
      type: 'text',
      format: 'markdown',
      text,
      status: 'completed',
      createdAt: BASE_TIME,
      updatedAt: BASE_TIME,
    }
  }

  function toolPart(
    toolName: string,
    status: 'running' | 'completed',
    args: unknown,
    output: unknown,
  ): ChatMessagePart {
    return {
      id: id('tool'),
      type: 'tool_execution',
      toolName,
      callId: id('call'),
      arguments: args,
      output,
      error: null,
      approvalState: null,
      artifacts: [],
      status,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    }
  }

  function artifactPart(name: string, path: string): ChatMessagePart {
    return {
      id: id('artifact'),
      type: 'artifact',
      name,
      path,
      mimeType: 'application/pdf',
      sizeBytes: 2841032,
      status: 'completed',
      createdAt: BASE_TIME,
      updatedAt: BASE_TIME,
    }
  }

  function changedFile(path: string, changeType: string, addedLines: number) {
    return {
      path,
      change_type: changeType,
      change_summary: { added_lines: addedLines, removed_lines: 0 },
    }
  }
}

function knowledgeSource(
  sourceId: string,
  displayName: string,
  documentCount: number,
  status: string,
) {
  return {
    source_id: sourceId,
    display_name: displayName,
    mount_mode: 'local',
    status,
    document_count: documentCount,
    updated_at: BASE_TIME,
  }
}

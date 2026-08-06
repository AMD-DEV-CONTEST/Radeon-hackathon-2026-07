const SHOWCASE_PACKAGE_ID = 'travel_planner'
const SHOWCASE_SESSION_ID = 'showcase-travel-session'

interface ShowcaseBindings {
  mcp_server_ids: string[]
  skill_ids: string[]
}

const bindingsByTarget = new Map<string, ShowcaseBindings>([
  ['resource:create_agent', { mcp_server_ids: [], skill_ids: [] }],
  ['resource:evolve_agent', { mcp_server_ids: [], skill_ids: [] }],
  [`package:${SHOWCASE_PACKAGE_ID}`, { mcp_server_ids: [], skill_ids: [] }],
])

const agentPackage = {
  package_id: SHOWCASE_PACKAGE_ID,
  agent_id: SHOWCASE_PACKAGE_ID,
  agent_name: '旅行规划师',
  name: '旅行规划师',
  agent_description: '检索目的地信息，规划行程并生成可交付的旅行手册。',
  runtime_pattern_id: 'plan_and_execute',
  status: 'published',
  tool_count: 8,
  session_count: 3,
  created_at: '2026-07-29T02:00:00.000Z',
  updated_at: '2026-07-29T02:26:00.000Z',
}

const extensionRegistry = [
  {
    kind: 'mcp',
    name: 'Tavily Search',
    summary: '面向实时网页资料调研的搜索服务',
    payload: {
      server_id: 'tavily_search',
      description: '搜索目的地、交通、开放时间与实时旅行信息',
      command: 'npx',
      args: ['-y', 'tavily-mcp@latest'],
    },
  },
  {
    kind: 'mcp',
    name: '地图与路线',
    summary: '地点解析与行程路线规划',
    payload: {
      server_id: 'map_routes',
      description: '计算地点距离并生成每天的路线顺序',
      url: 'https://mcp.example.local/maps',
    },
  },
  {
    kind: 'skill',
    name: '旅行计划编排',
    summary: '把调研结果整理为可执行的逐日行程',
    payload: {
      skill_id: 'travel_itinerary',
      description: '覆盖节奏、预算、同行人约束与备选方案',
      path: 'extensions/skills/travel-itinerary',
    },
  },
  {
    kind: 'skill',
    name: '专业文档交付',
    summary: '生成结构清晰、可直接分享的 PDF 手册',
    payload: {
      skill_id: 'document_delivery',
      description: '负责封面、目录、表格、地图引用和最终 PDF',
      path: 'extensions/skills/document-delivery',
    },
  },
]

const modelProfile = {
  profile_id: 'showcase-main-model',
  display_name: '主对话模型',
  description: 'Showcase',
  kind: 'chat',
  provider: 'openai_compatible',
  credential_id: 'showcase',
  model_name: 'fastagent-main',
  enabled: true,
  capabilities: {
    input_modalities: ['text', 'image'],
    output_modalities: ['text'],
    tool_calling: true,
    streaming_tool_calls: true,
    strict_tool_schema: true,
    structured_output_methods: ['json_mode', 'function_calling'],
    reasoning_supported: true,
    reasoning_efforts: ['low', 'medium', 'high'],
    reasoning_content: true,
    cache_usage: true,
  },
  settings: { temperature: 0.4 },
  limits: {
    max_input_tokens: 262144,
    compression_trigger_tokens: 204800,
    max_output_tokens: 16384,
    timeout_seconds: 300,
  },
  pricing: { currency: 'USD' },
  notes: '',
  credential: {
    credential_id: 'showcase',
    display_name: 'Showcase',
    provider: 'openai_compatible',
    base_url: 'https://example.local/v1',
    api_key_masked: '••••••••',
    api_key_fingerprint: 'showcase',
    has_api_key: true,
    enabled: true,
    created_at: '2026-07-29T00:00:00.000Z',
    updated_at: '2026-07-29T00:00:00.000Z',
  },
}

export function installShowcaseServer(): void {
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const request = input instanceof Request ? input : null
    const url = new URL(request?.url || String(input), window.location.origin)
    const method = String(init?.method || request?.method || 'GET').toUpperCase()
    const body = await requestBody(request, init)

    if (url.pathname === '/api/model-pool/profiles') {
      return jsonResponse({ profiles: [modelProfile] })
    }
    if (url.pathname === '/api/model-pool/infrastructure-bindings') {
      if (method === 'PUT') {
        return jsonResponse({ bindings: body.bindings || { task: null, embedding: null } })
      }
      return jsonResponse({
        bindings: { task: null, embedding: null },
        defaults: { context_window_tokens: 262144, compression_trigger_tokens: 204800 },
      })
    }
    if (url.pathname === '/api/file-capabilities') {
      return jsonResponse({
        attachment_accept: '.pdf,.docx,.xlsx,.png,.jpg,.jpeg,.txt,.md',
        attachment_extensions: ['.pdf', '.docx', '.xlsx', '.png', '.jpg', '.jpeg', '.txt', '.md'],
      })
    }
    if (url.pathname === '/api/agent-packages/recent-sessions') {
      return jsonResponse({
        sessions: [{
          session_id: SHOWCASE_SESSION_ID,
          package_id: SHOWCASE_PACKAGE_ID,
          display_title: '东京五日亲子行程',
          first_user_input: '规划一份东京五日亲子旅行方案',
          turn_count: 4,
          created_at: '2026-07-29T02:00:00.000Z',
          updated_at: '2026-07-29T02:26:00.000Z',
          agent_name: '旅行规划师',
          visible_in_agent_session_list: true,
        }],
      })
    }
    if (url.pathname === '/api/agent-packages') {
      return eventResponse('agent_packages_listed', { packages: [agentPackage] })
    }
    if (url.pathname === '/api/agent-packages/select') {
      return eventResponse('agent_package_selected', {
        package_id: SHOWCASE_PACKAGE_ID,
        purpose: 'run',
        package: agentPackage,
      })
    }
    if (url.pathname.endsWith('/sessions') && url.pathname.includes('/api/agent-packages/')) {
      return eventResponse('agent_package_sessions_listed', {
        package_id: SHOWCASE_PACKAGE_ID,
        sessions: [{
          session_id: SHOWCASE_SESSION_ID,
          package_id: SHOWCASE_PACKAGE_ID,
          display_title: '东京五日亲子行程',
          first_user_input: '规划一份东京五日亲子旅行方案',
          turn_count: 4,
          created_at: '2026-07-29T02:00:00.000Z',
          updated_at: '2026-07-29T02:26:00.000Z',
          visible_in_agent_session_list: true,
        }],
      })
    }
    if (url.pathname.includes(`/api/agent-packages/${SHOWCASE_PACKAGE_ID}/sessions/${SHOWCASE_SESSION_ID}`)) {
      return eventResponse('agent_package_session_loaded', {
        package_id: SHOWCASE_PACKAGE_ID,
        session: {
          session_id: SHOWCASE_SESSION_ID,
          package_id: SHOWCASE_PACKAGE_ID,
          messages: [],
          process_events: [],
        },
      })
    }
    if (url.pathname === '/api/extensions/bindings' && method === 'POST') {
      const targetKey = targetKeyFromPayload(body)
      const current = bindingsFor(targetKey)
      const kind = body.kind === 'skill' ? 'skill' : 'mcp'
      const identifier = String(body.identifier || '')
      const enabled = body.enabled !== false
      const key = kind === 'skill' ? 'skill_ids' : 'mcp_server_ids'
      const values = new Set(current[key])
      if (enabled) values.add(identifier)
      else values.delete(identifier)
      bindingsByTarget.set(targetKey, { ...current, [key]: [...values] })
      return eventResponse('extension_binding_updated', {
        bindings: bindingsByTarget.get(targetKey),
      })
    }
    if (url.pathname === '/api/extensions') {
      const targetKey = targetKeyFromUrl(url)
      return eventResponse('extensions_listed', {
        mcp_servers: extensionRegistry.filter((item) => item.kind === 'mcp'),
        skills: extensionRegistry.filter((item) => item.kind === 'skill'),
        bindings: bindingsFor(targetKey),
      })
    }
    if (url.pathname === '/api/extensions/skills/skillhub/status') {
      return eventResponse('skillhub_status', {
        cli_available: true,
        message: 'SkillHUB 已就绪',
        items: [],
      })
    }
    if (url.pathname === '/api/workspace/entries') {
      return eventResponse('workspace_entries', {
        scope: url.searchParams.get('scope') || 'workdir',
        path: url.searchParams.get('path') || '',
        entries: workspaceEntries(url.searchParams.get('path') || ''),
      })
    }
    if (url.pathname === '/api/workspace/file') {
      return eventResponse('workspace_file', {
        file: {
          scope: url.searchParams.get('scope') || 'workdir',
          path: url.searchParams.get('path') || 'output/东京五日旅行手册.md',
          name: '东京五日旅行手册.md',
          mime_type: 'text/markdown',
          content: '# 东京五日亲子旅行手册\n\n浅草、上野、台场与迪士尼的逐日行程已经整理完成。',
          truncated: false,
        },
      })
    }
    if (url.pathname === '/api/commands' && method === 'POST') {
      return jsonResponse({ accepted: true, command: body.command || {} })
    }
    return eventResponse('showcase_noop', {})
  }
}

function bindingsFor(key: string): ShowcaseBindings {
  return bindingsByTarget.get(key) || { mcp_server_ids: [], skill_ids: [] }
}

function targetKeyFromUrl(url: URL): string {
  const packageId = String(url.searchParams.get('package_id') || '')
  if (packageId) return `package:${packageId}`
  const resourceMode = String(url.searchParams.get('resource_mode') || 'create_agent')
  return `resource:${resourceMode}`
}

function targetKeyFromPayload(payload: Record<string, any>): string {
  const context = payload.context || {}
  const packageId = String(context.package_id || context.packageId || payload.package_id || '')
  if (packageId) return `package:${packageId}`
  const resourceMode = String(context.resource_mode || context.resourceMode || payload.resource_mode || 'create_agent')
  return `resource:${resourceMode}`
}

function workspaceEntries(path: string): Array<Record<string, any>> {
  if (path === 'output') {
    return [
      entry('output/东京五日旅行手册.md', '东京五日旅行手册.md', 'file', 18240),
      entry('output/东京五日旅行手册.pdf', '东京五日旅行手册.pdf', 'file', 2841032),
      entry('output/每日路线.xlsx', '每日路线.xlsx', 'file', 32640),
    ]
  }
  if (path === 'research') {
    return [
      entry('research/景点开放时间.md', '景点开放时间.md', 'file', 7420),
      entry('research/交通与票价.md', '交通与票价.md', 'file', 6118),
    ]
  }
  return [
    entry('input_files', 'input_files', 'directory', null),
    entry('research', 'research', 'directory', null),
    entry('output', 'output', 'directory', null),
    entry('旅行需求.md', '旅行需求.md', 'file', 1240),
  ]
}

function entry(path: string, name: string, kind: 'file' | 'directory', sizeBytes: number | null) {
  return {
    scope: 'workdir',
    path,
    name,
    kind,
    size_bytes: sizeBytes,
    updated_at: '2026-07-29T02:26:00.000Z',
    mount: false,
    mount_id: null,
    mount_source: null,
    connected: true,
  }
}

async function requestBody(request: Request | null, init?: RequestInit): Promise<Record<string, any>> {
  const source = init?.body ?? (request ? await request.clone().text() : '')
  if (typeof source !== 'string' || !source.trim()) return {}
  try {
    return JSON.parse(source)
  } catch {
    return {}
  }
}

function eventResponse(eventType: string, payload: Record<string, any>): Response {
  return jsonResponse({
    event: {
      event_id: crypto.randomUUID(),
      protocol_version: 'factory_frontend.v1',
      event_type: eventType,
      producer_type: 'showcase',
      request_id: null,
      run_id: null,
      session_id: null,
      thread_id: null,
      mode: null,
      graph_id: null,
      node_id: null,
      node_label: null,
      node_kind: null,
      stage_id: null,
      span_id: null,
      parent_span_id: null,
      sequence: 1,
      timestamp: new Date().toISOString(),
      severity: null,
      message: null,
      payload,
    },
  })
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

export {
  SHOWCASE_PACKAGE_ID,
  SHOWCASE_SESSION_ID,
  agentPackage,
}

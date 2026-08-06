export type WorkspaceScope = 'package' | 'runtime' | 'workdir' | 'artifacts' | 'extensions'
export type WorkspaceResourceMode = 'package' | 'create_agent' | 'evolve_agent' | 'agent_group'

export interface WorkspaceRequestContext {
  resourceMode?: WorkspaceResourceMode
  packageId?: string | null
  packageSessionId?: string | null
  workspaceId?: string | null
  factorySessionId?: string | null
  createAgentSessionId?: string | null
  groupId?: string | null
}

export type WorkspaceContextInput = WorkspaceRequestContext | string | null | undefined

export interface KnowledgeSourceInput {
  kind: 'folder' | 'file' | 'url' | 'note'
  display_name: string
  uri: string
  content?: string
  mount_mode: 'index_only' | 'rag'
  files?: KnowledgeUploadFile[]
  ingestion_plan?: {
    planner: 'system_default'
    default_splitter: 'recursive' | 'markdown' | 'code' | 'json'
    default_chunk_size: number
    default_chunk_overlap: number
    rules: Array<{
      match: string
      splitter: 'recursive' | 'markdown' | 'code' | 'json'
      chunk_size: number
      chunk_overlap: number
      reason?: string
    }>
  }
}

export interface KnowledgeUploadFile {
  file: File
  relativePath: string
}

export interface McpServerConfig {
  server_id?: string
  display_name: string
  description?: string
  transport: 'stdio' | 'streamable_http' | 'sse'
  command?: string
  args?: string | string[]
  cwd?: string
  env?: string | Record<string, string>
  url?: string
  headers?: string | Record<string, string>
  timeout_seconds: number
  enabled: boolean
  risk_level_default?: 'low' | 'medium' | 'high'
  source?: {
    type: 'local' | 'remote' | 'imported'
    name: string
    description?: string
  }
}

export interface SkillConfig {
  path: string
  source: 'local' | string
  enabled: boolean
  required?: boolean
  replace_skill_id?: string
}

export type ScheduleType = 'cron' | 'interval' | 'date'
export type SchedulerTargetType = 'graph_run' | 'script_run' | 'tool_call'
export interface SchedulerJobInput {
  task_content: string
  schedule_type: ScheduleType
  schedule_expr: string
  enabled?: boolean
  runtime_config?: {
    user_config?: Record<string, any>
    runtime_request?: Record<string, any>
  }
  target:
    | {
        target_type: 'graph_run'
        payload: {
          message: string
        }
      }
    | {
        target_type: 'script_run'
        payload: {
          command: string
        }
      }
    | {
        target_type: 'tool_call'
        payload: {
          tool_id: string
          arguments?: Record<string, any>
        }
      }
}

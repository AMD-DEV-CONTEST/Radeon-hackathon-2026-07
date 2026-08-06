import axios from 'axios'

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
})

export async function uploadImage(file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const res = await api.post('/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return res.data as { job_id: string; path: string; filename: string }
}

export async function createJob(input: {
  input_image_path: string
  style: string
  prompt: string
  output_mode?: string
}) {
  const res = await api.post('/jobs', { ...input, output_mode: input.output_mode || 'fullcolor_3d' })
  return res.data as JobResponse
}

export async function getJob(jobId: string) {
  const res = await api.get(`/jobs/${jobId}`)
  return res.data as JobResponse
}

export async function fetchStyles() {
  const res = await api.get('/styles')
  return res.data as StyleTemplate[]
}

export async function agentPlan(userInput: string, imagePath?: string | null) {
  const res = await api.post('/agent/plan', { user_input: userInput, image_path: imagePath || null })
  return res.data as PlanResponse
}

export async function agentChat(message: string, plan?: PlanResponse | null) {
  const res = await api.post('/agent/chat', { message, plan: plan || null })
  return res.data as AgentChatResponse
}

export async function agentExecute(plan: PlanResponse, inputImagePath: string) {
  const res = await api.post('/agent/execute', { plan, input_image_path: inputImagePath })
  return res.data as { job_id: string; status: string }
}

export interface JobResponse {
  id: string
  status: string
  input_image_path: string
  style: string
  prompt: string
  output_mode: string
  result_model_path: string | null
  result_preview_path: string | null
  multiview_image_paths: string[] | null
  print_report: Record<string, unknown> | null
  error_message: string | null
  created_at: string
  updated_at: string
}

export interface StyleTemplate {
  id: string
  name: string
  description: string
  category: '3d' | 'relief_2d5' | 'stylized_3d'
  output_mode: 'fullcolor_3d' | 'relief_2d5'
  style_prompt: string
  negative_prompt: string
  postprocess_params: Record<string, unknown>
  sample_image_url: string
}

export interface SkillStep {
  id: string
  skill: string
  description: string
  params: Record<string, unknown>
  depends_on: string[]
  status: string
  output: Record<string, unknown> | null
  error: string | null
}

export interface PlanResponse {
  goal: string
  style_id: string
  output_mode: 'fullcolor_3d' | 'relief_2d5'
  user_prompt: string
  postprocess_params: Record<string, unknown>
  steps: SkillStep[]
  reasoning: string
}

export interface GpuStatus {
  rocm_available: boolean
  hip_version: string | null
  gpu_name: string | null
  gpu_count: number
  gpu_memory_mb: number | null
  torch_cuda_available: boolean
  use_rocm_forced: boolean
}

export async function getGpuStatus() {
  const res = await api.get('/health/gpu')
  return res.data as GpuStatus
}

export interface AgentChatResponse {
  action: 'update_style' | 'update_params' | 'regenerate' | 'regenerate_step' | 'general'
  params: Record<string, unknown>
  response: string
}

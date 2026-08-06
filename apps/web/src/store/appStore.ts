import { create } from 'zustand'
import type { JobResponse, PlanResponse, StyleTemplate } from '../api/client'

export type Page = 'landing' | 'director' | 'result'

export type ViewMode3D = 'solid' | 'wireframe' | 'texture' | 'printbed'

export interface ChatMessage {
  role: 'user' | 'agent'
  content: string
  actions?: string[]
}

export interface Project {
  id: string
  name: string
  thumbnailUrl?: string
  jobId?: string
  updatedAt: string
}

interface AppState {
  page: Page
  currentJob: JobResponse | null
  plan: PlanResponse | null
  styles: StyleTemplate[]
  selectedStyleId: string
  chatMessages: ChatMessage[]
  projects: Project[]
  activeStepId: string | null
  previewMode: ViewMode3D
  rotation: number
  brightness: number
  shadowDensity: number

  setPage: (page: Page) => void
  setJob: (job: JobResponse) => void
  updateJob: (job: Partial<JobResponse>) => void
  setPlan: (plan: PlanResponse | null) => void
  setStyles: (styles: StyleTemplate[]) => void
  setSelectedStyleId: (id: string) => void
  addChatMessage: (msg: ChatMessage) => void
  setProjects: (projects: Project[]) => void
  addProject: (project: Project) => void
  setActiveStepId: (id: string | null) => void
  setPreviewMode: (mode: ViewMode3D) => void
  setRotation: (value: number) => void
  setBrightness: (value: number) => void
  setShadowDensity: (value: number) => void
  reset: () => void
}

const WELCOME_MESSAGE: ChatMessage = {
  role: 'agent',
  content:
    'What would you like to do next? Upload a photo and I will plan the full 3D pipeline for you.',
  actions: ['Realistic 3D', 'Cartoon 3D', 'Relief Coin', 'Low Poly'],
}

const initialState = {
  page: 'landing' as Page,
  currentJob: null as JobResponse | null,
  plan: null as PlanResponse | null,
  styles: [] as StyleTemplate[],
  selectedStyleId: 'realistic_3d',
  chatMessages: [WELCOME_MESSAGE] as ChatMessage[],
  projects: [] as Project[],
  activeStepId: null as string | null,
  previewMode: 'solid' as ViewMode3D,
  rotation: 35,
  brightness: 50,
  shadowDensity: 50,
}

export const useAppStore = create<AppState>((set) => ({
  ...initialState,

  setPage: (page) => set({ page }),
  setJob: (job) => set({ currentJob: job }),
  updateJob: (patch) =>
    set((state) => ({
      currentJob: state.currentJob ? { ...state.currentJob, ...patch } : null,
    })),
  setPlan: (plan) => set({ plan }),
  setStyles: (styles) => set({ styles }),
  setSelectedStyleId: (id) => set({ selectedStyleId: id }),
  addChatMessage: (msg) =>
    set((state) => ({ chatMessages: [...state.chatMessages, msg] })),
  setProjects: (projects) => set({ projects }),
  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects].slice(0, 20) })),  setActiveStepId: (id) => set({ activeStepId: id }),
  setPreviewMode: (mode) => set({ previewMode: mode }),
  setRotation: (value) => set({ rotation: value }),
  setBrightness: (value) => set({ brightness: value }),
  setShadowDensity: (value) => set({ shadowDensity: value }),
  reset: () => set(initialState),
}))

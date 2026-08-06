/**
 * Vue Router 配置
 */

import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import {
  defaultLocale,
  localeStorageKey,
  normalizeLocale,
  routeTitleKey,
  translate,
} from '@/i18n'

export const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/factory',
  },
  {
    path: '/factory',
    name: 'Factory',
    component: () => import('@/views/FactoryView.vue'),
  },
  {
    path: '/agents',
    name: 'Agents',
    component: () => import('@/views/PublishedView.vue'),
  },
  {
    path: '/agents/:packageId',
    name: 'AgentDetail',
    component: () => import('@/views/AgentPackageDetailView.vue'),
  },
  {
    path: '/agent-group',
    name: 'AgentGroup',
    component: () => import('@/views/AgentGroupView.vue'),
  },
  {
    path: '/knowledge',
    name: 'Knowledge',
    component: () => import('@/views/KnowledgeView.vue'),
  },
  {
    path: '/scheduler',
    name: 'Scheduler',
    component: () => import('@/views/SchedulerView.vue'),
  },
  {
    path: '/extensions',
    name: 'Extensions',
    component: () => import('@/views/ExtensionsView.vue'),
  },
  {
    path: '/model-pool',
    name: 'ModelPool',
    component: () => import('@/views/ModelPoolView.vue'),
  },
  {
    path: '/benchmarks',
    name: 'Benchmarks',
    component: () => import('@/views/BenchmarkView.vue'),
    meta: { rightSidebarAvailable: false },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  if (typeof document !== 'undefined') {
    const storedLocale = typeof window === 'undefined' ? null : window.localStorage.getItem(localeStorageKey)
    const locale = storedLocale ? normalizeLocale(storedLocale) : defaultLocale
    document.title = `${translate(locale, routeTitleKey(to.name))} - FastAgentFactory`
  }
  next()
})

export default router

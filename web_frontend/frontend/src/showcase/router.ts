import { createMemoryHistory, createRouter } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'
import { routes } from '@/router'

const showcaseRoutes: RouteRecordRaw[] = routes.map((route) => ({
  ...route,
  meta: {
    ...route.meta,
    showcaseMode: true,
  },
}))

export const showcaseRouter = createRouter({
  history: createMemoryHistory(),
  routes: showcaseRoutes,
})

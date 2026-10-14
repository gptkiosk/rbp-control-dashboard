import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'
import type { IconName } from '@/icons/icons'
import { navItems } from './routes'
import LoginGate from '@/components/LoginGate.vue'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    icon?: IconName
  }
}

export const APP_TITLE = 'Raspberry Pi Control Dashboard'

/** "Tasks · RCD" in the browser tab; the bare product name on unknown pages. */
export function pageTitle(title: string | undefined): string {
  return title ? `${title} · RCD` : APP_TITLE
}

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({
    history,
    routes: [
      ...navItems.map((item) => ({
        path: item.path,
        name: item.name,
        component: item.component,
        meta: { title: item.label, icon: item.icon },
      })),
      // Old MCD bookmarks and help links.
      { path: '/mac', redirect: (to) => ({ path: '/pi', hash: to.hash }) },
      { path: '/login', name: 'login', component: LoginGate, meta: { title: 'Sign in' } },
      { path: '/setup', name: 'setup', component: () => import('@/views/SetupView.vue'), meta: { title: 'Setup wizard' } },
      {
        path: '/:pathMatch(.*)*',
        name: 'not-found',
        component: () => import('@/views/NotFoundView.vue'),
        meta: { title: 'Not found' },
      },
    ],
  })
  router.afterEach((to) => {
    if (typeof document !== 'undefined') document.title = pageTitle(to.meta.title)
  })
  return router
}

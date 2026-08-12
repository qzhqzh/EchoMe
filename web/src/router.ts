import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
  },
  {
    path: '/memories',
    name: 'Memories',
    component: () => import('@/views/Memories.vue'),
  },
  {
    path: '/memories/new',
    name: 'MemoryNew',
    component: () => import('@/views/MemoryNew.vue'),
  },
  {
    path: '/memories/:id',
    name: 'MemoryDetail',
    component: () => import('@/views/MemoryDetail.vue'),
  },
  {
    path: '/review',
    name: 'Review',
    component: () => import('@/views/Review.vue'),
  },
  {
    path: '/projects',
    name: 'Projects',
    component: () => import('@/views/Projects.vue'),
  },
  {
    path: '/project-workspace',
    name: 'ProjectWorkspace',
    component: () => import('@/views/ProjectWorkspace.vue'),
  },
  {
    path: '/market',
    name: 'Market',
    component: () => import('@/views/Market.vue'),
  },
  {
    path: '/observability',
    name: 'Observability',
    component: () => import('@/views/Observability.vue'),
  },
  {
    path: '/eval',
    name: 'MemoryEval',
    component: () => import('@/views/MemoryEval.vue'),
  },
  {
    path: '/logs',
    name: 'RetrievalLogs',
    component: () => import('@/views/RetrievalLogs.vue'),
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/Settings.vue'),
  },
  {
    path: '/help',
    name: 'Help',
    component: () => import('@/views/Help.vue'),
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('@/views/Admin.vue'),
    meta: { requiresAdmin: true },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const { isAuthenticated, getUser } = useAuth()
  if (!to.meta.public && !isAuthenticated()) {
    return { name: 'Login' }
  }
  if (to.meta.requiresAdmin) {
    const user = getUser()
    if (!user || user.role !== 'admin') {
      return { name: 'Dashboard' }
    }
  }
})

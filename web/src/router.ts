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
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const { isAuthenticated } = useAuth()
  if (!to.meta.public && !isAuthenticated()) {
    return { name: 'Login' }
  }
})

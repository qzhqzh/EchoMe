import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '@/stores/auth'

const routes = [
  { path: '/knowledge', name: 'KnowledgeLibrary', component: () => import('@/views/KnowledgeLibrary.vue') },
  { path: '/knowledge/review', name: 'KnowledgeReview', component: () => import('@/views/KnowledgeReview.vue') },
  { path: '/knowledge/:id', name: 'KnowledgeDetail', component: () => import('@/views/KnowledgeDetail.vue') },
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
    path: '/cards',
    name: 'CardLibrary',
    component: () => import('@/views/CardLibrary.vue'),
  },
  {
    path: '/cards/memories',
    name: 'MemoryCards',
    component: () => import('@/views/MemoryDeck.vue'),
  },
  {
    path: '/cards/habits/review',
    name: 'HabitCardReview',
    component: () => import('@/views/MemoryDeck.vue'),
    props: { kind: 'habits' },
  },
  {
    path: '/cards/skills/review',
    name: 'SkillCardReview',
    component: () => import('@/views/MemoryDeck.vue'),
    props: { kind: 'skills' },
  },
  {
    path: '/cards/knowledge/review',
    name: 'KnowledgeCardReview',
    component: () => import('@/views/MemoryDeck.vue'),
    props: { kind: 'knowledge' },
  },
  {
    path: '/cards/habits/:id?',
    name: 'HabitCards',
    component: () => import('@/views/CardCollection.vue'),
    props: { kind: 'habits' },
  },
  {
    path: '/cards/skills/:id?',
    name: 'SkillCards',
    component: () => import('@/views/CardCollection.vue'),
    props: { kind: 'skills' },
  },
  {
    path: '/cards/knowledge/:id?',
    name: 'KnowledgeCards',
    component: () => import('@/views/CardCollection.vue'),
    props: { kind: 'knowledge' },
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
    path: '/scenarios',
    name: 'Scenarios',
    component: () => import('@/views/Scenarios.vue'),
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

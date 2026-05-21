<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const route = useRoute()
const router = useRouter()
const { clearToken } = useAuth()

interface NavItem {
  name: string
  path: string
  icon: string
}

const navItems: NavItem[] = [
  { name: 'Dashboard', path: '/', icon: 'dashboard' },
  { name: 'Memories', path: '/memories', icon: 'memories' },
  { name: 'Review', path: '/review', icon: 'review' },
  { name: 'Projects', path: '/projects', icon: 'projects' },
]

const currentPath = computed(() => route.path)

function navigate(path: string): void {
  router.push(path)
  emit('close')
}

function logout(): void {
  clearToken()
  router.push('/login')
}
</script>

<template>
  <aside
    :class="[
      'fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-slate-700 bg-slate-800',
      'transition-transform duration-200 lg:static lg:translate-x-0',
      open ? 'translate-x-0' : '-translate-x-full'
    ]"
  >
    <!-- Logo -->
    <div class="flex h-16 items-center gap-3 border-b border-slate-700 px-5">
      <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600">
        <span class="text-sm font-bold text-white">E</span>
      </div>
      <div>
        <h1 class="text-base font-semibold text-slate-100">EchoMe</h1>
        <p class="text-xs text-slate-400">Memory Console</p>
      </div>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 space-y-1 px-3 py-4">
      <button
        v-for="item in navItems"
        :key="item.path"
        :class="[
          'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
          currentPath === item.path || (item.path !== '/' && currentPath.startsWith(item.path))
            ? 'bg-blue-600/20 text-blue-300'
            : 'text-slate-300 hover:bg-slate-700 hover:text-slate-100'
        ]"
        @click="navigate(item.path)"
      >
        <!-- Dashboard icon -->
        <svg v-if="item.icon === 'dashboard'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
        <!-- Memories icon -->
        <svg v-else-if="item.icon === 'memories'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
        <!-- Review icon -->
        <svg v-else-if="item.icon === 'review'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <!-- Projects icon -->
        <svg v-else-if="item.icon === 'projects'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        {{ item.name }}
      </button>
    </nav>

    <!-- Add Memory button -->
    <div class="border-t border-slate-700 px-3 py-3">
      <button
        class="btn-primary w-full gap-2"
        @click="navigate('/memories/new')"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        New Memory
      </button>
    </div>

    <!-- User/Logout -->
    <div class="border-t border-slate-700 px-3 py-3">
      <button
        class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
        @click="logout"
      >
        <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
        </svg>
        Sign Out
      </button>
    </div>
  </aside>
</template>

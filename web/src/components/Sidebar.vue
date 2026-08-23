<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useI18n } from '@/i18n'

defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const route = useRoute()
const router = useRouter()
const { clearToken, getUser } = useAuth()
const { t, locale, setLocale } = useI18n()

const user = computed(() => getUser())

interface NavItem {
  name: string
  path: string
  icon: string
}

const navItems = computed<NavItem[]>(() => {
  const items = [
    { name: t('nav_dashboard'), path: '/', icon: 'dashboard' },
    { name: t('nav_memories'), path: '/memories', icon: 'memories' },
    { name: t('nav_review'), path: '/review', icon: 'review' },
    { name: t('nav_projects'), path: '/projects', icon: 'projects' },
  ]
  if (import.meta.env.VITE_ECHOME_MARKET_ENABLED === 'true') {
    items.push({ name: t('nav_market'), path: '/market', icon: 'market' })
  }
  items.push(
    { name: t('nav_diagnostics'), path: '/observability', icon: 'observability' },
    { name: t('nav_help'), path: '/help', icon: 'help' },
  )
  return items
})

const visibleNavItems = computed(() => {
  const items = [...navItems.value]
  if (user.value?.role === 'admin') {
    items.push({ name: t('nav_admin'), path: '/admin', icon: 'admin' })
  }
  return items
})

const currentPath = computed(() => route.path)

function navigate(path: string): void {
  router.push(path)
  emit('close')
}

function isNavActive(item: NavItem): boolean {
  if (item.path === '/observability') {
    return ['/observability', '/eval', '/logs'].includes(currentPath.value)
  }
  return currentPath.value === item.path
    || (item.path !== '/' && currentPath.value.startsWith(item.path))
}

function logout(): void {
  clearToken()
  router.push('/login')
}

function toggleLocale(): void {
  setLocale(locale.value === 'zh' ? 'en' : 'zh')
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
        <p class="text-xs text-slate-400">{{ t('nav_console') }}</p>
      </div>
    </div>

    <!-- Navigation -->
    <nav class="flex-1 space-y-1 px-3 py-4">
      <button
        v-for="item in visibleNavItems"
        :key="item.path"
        :class="[
          'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors',
          isNavActive(item)
            ? 'bg-blue-600/20 text-blue-300'
            : 'text-slate-300 hover:bg-slate-700 hover:text-slate-100'
        ]"
        @click="navigate(item.path)"
      >
        <svg v-if="item.icon === 'dashboard'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
        </svg>
        <svg v-else-if="item.icon === 'memories'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
        <svg v-else-if="item.icon === 'review'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <svg v-else-if="item.icon === 'projects'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        <svg v-else-if="item.icon === 'market'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9m-9 9a9 9 0 019-9" />
        </svg>
        <svg v-else-if="item.icon === 'observability'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 3v18h18M7 15l3-3 3 2 5-7" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 7h.01M11 7h.01M15 7h.01" />
        </svg>
        <svg v-else-if="item.icon === 'eval'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 11l2 2 4-5" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M5 4h14v16H5z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 17h8" />
        </svg>
        <svg v-else-if="item.icon === 'logs'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 7h10M7 12h10M7 17h6" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M5 3h14a1 1 0 011 1v16a1 1 0 01-1 1H5a1 1 0 01-1-1V4a1 1 0 011-1z" />
        </svg>
        <svg v-else-if="item.icon === 'help'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <svg v-else-if="item.icon === 'admin'" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
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
        {{ t('nav_new_memory') }}
      </button>
    </div>

    <!-- User/Logout -->
    <div class="border-t border-slate-700 px-3 py-3">
      <div v-if="user" class="flex items-center gap-3 px-3 py-2 mb-2">
        <img
          v-if="user.avatar_url"
          :src="user.avatar_url"
          :alt="user.username"
          class="h-7 w-7 rounded-full"
        />
        <div v-else class="flex h-7 w-7 items-center justify-center rounded-full bg-blue-600 text-xs font-bold text-white">
          {{ user.username.charAt(0).toUpperCase() }}
        </div>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-slate-200">{{ user.username }}</p>
          <p class="truncate text-xs text-slate-400">{{ user.role }}</p>
        </div>
      </div>
      <!-- Language switch -->
      <button
        class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
        @click="toggleLocale"
      >
        <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129" />
        </svg>
        {{ locale === 'zh' ? 'English' : '中文' }}
      </button>
      <button
        class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
        @click="navigate('/settings')"
      >
        <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        {{ t('nav_settings') }}
      </button>
      <button
        class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
        @click="logout"
      >
        <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
        </svg>
        {{ t('nav_sign_out') }}
      </button>
    </div>
  </aside>
</template>

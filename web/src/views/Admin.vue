<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useI18n } from '@/i18n'
import { api } from '@/api/client'
import { useAuth } from '@/stores/auth'
import { useToast } from '@/stores/toast'

const { t } = useI18n()
const { getUser } = useAuth()
const { success, error } = useToast()

const currentUser = computed(() => getUser())

interface SystemStats {
  total_users: number
  total_memories: number
  total_projects: number
  total_syncs: number
  memories_active: number
  memories_pending: number
  memories_public: number
  memories_last_7d: number
  users_last_7d: number
}

interface AdminUser {
  id: string
  github_id: number
  username: string
  email: string | null
  avatar_url: string | null
  role: string
  created_at: string
  last_login_at: string | null
  memory_count: number
}

const stats = ref<SystemStats | null>(null)
const users = ref<AdminUser[]>([])
const totalUsers = ref(0)
const loading = ref(true)
const activeTab = ref<'stats' | 'users'>('stats')

onMounted(async () => {
  await Promise.all([loadStats(), loadUsers()])
  loading.value = false
})

async function loadStats() {
  try {
    stats.value = await api.getAdminStats()
  } catch (e) {
    error('Failed to load stats')
  }
}

async function loadUsers() {
  try {
    const data = await api.getAdminUsers()
    users.value = data.items
    totalUsers.value = data.total
  } catch (e) {
    error('Failed to load users')
  }
}

async function changeRole(userId: string, newRole: string) {
  if (!confirm(`Change this user's role to "${newRole}"?`)) return
  try {
    await api.updateUserRole(userId, newRole)
    success(`Role updated to ${newRole}`)
    await loadUsers()
  } catch {}
}

async function deleteUser(userId: string, username: string) {
  if (!confirm(`DELETE user "${username}" and ALL their data? This cannot be undone.`)) return
  try {
    await api.deleteAdminUser(userId)
    success(`User ${username} deleted`)
    await loadUsers()
    await loadStats()
  } catch {}
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Never'
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div>
      <h1 class="text-2xl font-bold text-slate-100">{{ t('admin_title') }}</h1>
      <p class="mt-1 text-sm text-slate-400">{{ t('admin_subtitle') }}</p>
    </div>

    <!-- Tabs -->
    <div class="flex gap-1 border-b border-slate-700">
      <button
        :class="[
          'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
          activeTab === 'stats'
            ? 'border-blue-500 text-blue-400'
            : 'border-transparent text-slate-400 hover:text-slate-200'
        ]"
        @click="activeTab = 'stats'"
      >
        {{ t('admin_system_stats') }}
      </button>
      <button
        :class="[
          'px-4 py-2.5 text-sm font-medium border-b-2 transition-colors',
          activeTab === 'users'
            ? 'border-blue-500 text-blue-400'
            : 'border-transparent text-slate-400 hover:text-slate-200'
        ]"
        @click="activeTab = 'users'"
      >
        {{ t('admin_users') }} ({{ totalUsers }})
      </button>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="text-center py-12">
      <svg class="mx-auto h-8 w-8 animate-spin text-blue-400" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    </div>

    <!-- Stats Tab -->
    <div v-else-if="activeTab === 'stats' && stats" class="space-y-6">
      <!-- Overview Cards -->
      <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <div class="card">
          <div class="text-2xl font-bold text-blue-400">{{ stats.total_users }}</div>
          <div class="text-xs text-slate-400 mt-1">{{ t('admin_total_users') }}</div>
        </div>
        <div class="card">
          <div class="text-2xl font-bold text-green-400">{{ stats.total_memories }}</div>
          <div class="text-xs text-slate-400 mt-1">{{ t('admin_total_memories') }}</div>
        </div>
        <div class="card">
          <div class="text-2xl font-bold text-purple-400">{{ stats.total_projects }}</div>
          <div class="text-xs text-slate-400 mt-1">{{ t('admin_projects') }}</div>
        </div>
        <div class="card">
          <div class="text-2xl font-bold text-orange-400">{{ stats.total_syncs }}</div>
          <div class="text-xs text-slate-400 mt-1">{{ t('admin_sync_operations') }}</div>
        </div>
      </div>

      <!-- Memory Breakdown -->
      <div class="card">
        <h3 class="text-sm font-semibold text-slate-200 mb-4">{{ t('admin_memory_breakdown') }}</h3>
        <div class="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <div class="text-lg font-bold text-green-400">{{ stats.memories_active }}</div>
            <div class="text-xs text-slate-400">{{ t('admin_active') }}</div>
          </div>
          <div>
            <div class="text-lg font-bold text-yellow-400">{{ stats.memories_pending }}</div>
            <div class="text-xs text-slate-400">{{ t('admin_pending_review') }}</div>
          </div>
          <div>
            <div class="text-lg font-bold text-cyan-400">{{ stats.memories_public }}</div>
            <div class="text-xs text-slate-400">{{ t('admin_public_market') }}</div>
          </div>
          <div>
            <div class="text-lg font-bold text-slate-300">{{ stats.memories_last_7d }}</div>
            <div class="text-xs text-slate-400">{{ t('admin_new_7d') }}</div>
          </div>
        </div>
      </div>

      <!-- Activity -->
      <div class="card">
        <h3 class="text-sm font-semibold text-slate-200 mb-4">{{ t('admin_recent_activity') }}</h3>
        <div class="grid grid-cols-2 gap-4">
          <div>
            <div class="text-lg font-bold text-blue-400">{{ stats.users_last_7d }}</div>
            <div class="text-xs text-slate-400">{{ t('admin_new_users') }}</div>
          </div>
          <div>
            <div class="text-lg font-bold text-green-400">{{ stats.memories_last_7d }}</div>
            <div class="text-xs text-slate-400">{{ t('admin_new_memories') }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Users Tab -->
    <div v-else-if="activeTab === 'users'" class="space-y-3">
      <div
        v-for="u in users"
        :key="u.id"
        class="card flex items-center gap-4"
      >
        <!-- Avatar -->
        <img
          v-if="u.avatar_url"
          :src="u.avatar_url"
          :alt="u.username"
          class="h-10 w-10 rounded-full shrink-0"
        />
        <div v-else class="flex h-10 w-10 items-center justify-center rounded-full bg-slate-600 text-sm font-bold text-white shrink-0">
          {{ u.username.charAt(0).toUpperCase() }}
        </div>

        <!-- Info -->
        <div class="flex-1 min-w-0">
          <div class="flex items-center gap-2">
            <span class="text-sm font-semibold text-slate-100 truncate">{{ u.username }}</span>
            <span
              :class="[
                'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                u.role === 'admin' ? 'bg-red-900/50 text-red-300' : 'bg-slate-700 text-slate-300'
              ]"
            >
              {{ u.role }}
            </span>
          </div>
          <div class="text-xs text-slate-400 mt-0.5">
            {{ u.email || t('admin_no_email') }} · {{ u.memory_count }} {{ t('admin_memories') }} · {{ t('admin_last_login') }} {{ formatDate(u.last_login_at) }}
          </div>
          <div class="text-xs text-slate-500">
            {{ t('admin_joined') }} {{ formatDate(u.created_at) }}
          </div>
        </div>

        <!-- Actions -->
        <div v-if="u.id !== currentUser?.id" class="flex items-center gap-2 shrink-0">
          <button
            v-if="u.role === 'user'"
            class="rounded px-2 py-1 text-xs text-blue-400 border border-blue-500/30 hover:bg-blue-500/10 transition-colors"
            @click="changeRole(u.id, 'admin')"
          >
            {{ t('admin_promote') }}
          </button>
          <button
            v-else
            class="rounded px-2 py-1 text-xs text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500/10 transition-colors"
            @click="changeRole(u.id, 'user')"
          >
            {{ t('admin_demote') }}
          </button>
          <button
            class="rounded px-2 py-1 text-xs text-red-400 border border-red-500/30 hover:bg-red-500/10 transition-colors"
            @click="deleteUser(u.id, u.username)"
          >
            {{ t('delete') }}
          </button>
        </div>
        <div v-else class="shrink-0">
          <span class="text-xs text-slate-500">{{ t('admin_you') }}</span>
        </div>
      </div>

      <div v-if="users.length === 0" class="text-center py-8 text-slate-400">
        {{ t('admin_no_users') }}
      </div>
    </div>
  </div>
</template>

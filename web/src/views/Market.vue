<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { api } from '@/api/client'
import { useAuth } from '@/stores/auth'
import { useToast } from '@/stores/toast'

const { isAuthenticated } = useAuth()
const { success, error } = useToast()

interface MarketMemory {
  id: string
  title: string
  content: string
  type: string
  layer: string
  priority: number
  tags: string[]
  source: string
  token_count: number
  user_id: string
  created_at: string
  updated_at: string
}

interface MarketStats {
  total_public: number
  by_type: Record<string, number>
  recent_count_7d: number
}

const memories = ref<MarketMemory[]>([])
const stats = ref<MarketStats | null>(null)
const total = ref(0)
const loading = ref(false)
const searchQuery = ref('')
const filterType = ref('')
const filterLayer = ref('')
const offset = ref(0)
const limit = 20

const memoryTypes = ['persona', 'workflow', 'tech', 'constraint', 'snippet', 'decision', 'knowledge', 'interaction', 'project']
const layers = ['L0', 'L1', 'L2']

async function loadStats() {
  try {
    stats.value = await api.getMarketStats()
  } catch {}
}

async function loadMemories() {
  loading.value = true
  try {
    const params: Record<string, string | number> = {
      offset: offset.value,
      limit,
    }
    if (searchQuery.value) params.q = searchQuery.value
    if (filterType.value) params.type = filterType.value
    if (filterLayer.value) params.layer = filterLayer.value

    const data = await api.listMarketMemories(params)
    memories.value = data.items
    total.value = data.total
  } catch (e) {
    error('Failed to load market memories')
  } finally {
    loading.value = false
  }
}

async function forkMemory(id: string) {
  if (!isAuthenticated()) {
    error('Please login to fork memories')
    return
  }
  try {
    const result = await api.forkMarketMemory(id)
    success(`Forked: ${result.title}`)
  } catch {}
}

function handleSearch() {
  offset.value = 0
  loadMemories()
}

function nextPage() {
  offset.value += limit
  loadMemories()
}

function prevPage() {
  offset.value = Math.max(0, offset.value - limit)
  loadMemories()
}

const hasNextPage = computed(() => offset.value + limit < total.value)
const hasPrevPage = computed(() => offset.value > 0)

onMounted(() => {
  loadStats()
  loadMemories()
})
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div>
      <h1 class="text-2xl font-bold text-slate-100">Memory Market</h1>
      <p class="mt-1 text-sm text-slate-400">Browse and fork public memories shared by the community</p>
    </div>

    <!-- Stats -->
    <div v-if="stats" class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div class="card">
        <div class="text-2xl font-bold text-blue-400">{{ stats.total_public }}</div>
        <div class="text-sm text-slate-400">Public Memories</div>
      </div>
      <div class="card">
        <div class="text-2xl font-bold text-green-400">{{ stats.recent_count_7d }}</div>
        <div class="text-sm text-slate-400">New This Week</div>
      </div>
      <div class="card">
        <div class="text-2xl font-bold text-purple-400">{{ Object.keys(stats.by_type).length }}</div>
        <div class="text-sm text-slate-400">Memory Types</div>
      </div>
    </div>

    <!-- Search & Filters -->
    <div class="card">
      <form class="flex flex-col gap-3 sm:flex-row" @submit.prevent="handleSearch">
        <input
          v-model="searchQuery"
          type="text"
          class="input-field flex-1"
          placeholder="Search public memories..."
        />
        <select v-model="filterType" class="input-field sm:w-40" @change="handleSearch">
          <option value="">All Types</option>
          <option v-for="t in memoryTypes" :key="t" :value="t">{{ t }}</option>
        </select>
        <select v-model="filterLayer" class="input-field sm:w-32" @change="handleSearch">
          <option value="">All Layers</option>
          <option v-for="l in layers" :key="l" :value="l">{{ l }}</option>
        </select>
        <button type="submit" class="btn-primary whitespace-nowrap">Search</button>
      </form>
    </div>

    <!-- Results -->
    <div v-if="loading" class="text-center py-8">
      <svg class="mx-auto h-8 w-8 animate-spin text-blue-400" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    </div>

    <div v-else-if="memories.length === 0" class="text-center py-12">
      <p class="text-slate-400">No public memories found.</p>
    </div>

    <div v-else class="space-y-3">
      <div
        v-for="mem in memories"
        :key="mem.id"
        class="card hover:border-blue-500/50 transition-colors"
      >
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1 min-w-0">
            <h3 class="text-base font-semibold text-slate-100 truncate">{{ mem.title }}</h3>
            <p class="mt-1 text-sm text-slate-400 line-clamp-2">{{ mem.content }}</p>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <span class="inline-flex items-center rounded-full bg-blue-900/50 px-2 py-0.5 text-xs font-medium text-blue-300">
                {{ mem.type }}
              </span>
              <span class="inline-flex items-center rounded-full bg-slate-700 px-2 py-0.5 text-xs font-medium text-slate-300">
                {{ mem.layer }}
              </span>
              <span
                v-for="tag in mem.tags.slice(0, 3)"
                :key="tag"
                class="inline-flex items-center rounded-full bg-slate-700/50 px-2 py-0.5 text-xs text-slate-400"
              >
                {{ tag }}
              </span>
              <span class="text-xs text-slate-500">{{ mem.token_count }} tokens</span>
            </div>
          </div>
          <button
            v-if="isAuthenticated()"
            class="shrink-0 rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700 hover:text-slate-100 transition-colors"
            @click="forkMemory(mem.id)"
          >
            Fork
          </button>
        </div>
      </div>
    </div>

    <!-- Pagination -->
    <div v-if="total > limit" class="flex items-center justify-between">
      <button
        :disabled="!hasPrevPage"
        class="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
        @click="prevPage"
      >
        Previous
      </button>
      <span class="text-sm text-slate-400">
        {{ offset + 1 }}-{{ Math.min(offset + limit, total) }} of {{ total }}
      </span>
      <button
        :disabled="!hasNextPage"
        class="rounded-lg border border-slate-600 px-4 py-2 text-sm text-slate-300 hover:bg-slate-700 disabled:opacity-40 disabled:cursor-not-allowed"
        @click="nextPage"
      >
        Next
      </button>
    </div>
  </div>
</template>

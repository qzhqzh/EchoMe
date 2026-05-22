<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { api } from '@/api/client'
import SearchBar from '@/components/SearchBar.vue'
import MemoryCard from '@/components/MemoryCard.vue'
import { MEMORY_LAYERS, MEMORY_STATUSES } from '@/types'
import type { MemoryListItem, MemoryType } from '@/types'

const router = useRouter()
const route = useRoute()

const memories = ref<MemoryListItem[]>([])
const total = ref(0)
const loading = ref(false)
const limit = 20

// Restore filters from URL query params (preserves state on back navigation)
const activeType = ref<MemoryType | ''>((route.query.type as MemoryType) || '')
const filterLayer = ref((route.query.layer as string) || '')
const filterStatus = ref((route.query.status as string) || 'active')
const filterTags = ref((route.query.tags as string) || '')
const offset = ref(Number(route.query.offset) || 0)
const searchQuery = ref('')

// Type tab config with priority order and display info
const typeTabs: { key: MemoryType | ''; label: string; icon: string; color: string }[] = [
  { key: '', label: 'All', icon: '📋', color: 'text-slate-300' },
  { key: 'identity', label: 'Identity', icon: '🧠', color: 'text-purple-300' },
  { key: 'guardrail', label: 'Guardrails', icon: '🚫', color: 'text-red-300' },
  { key: 'reasoning', label: 'Reasoning', icon: '💡', color: 'text-violet-300' },
  { key: 'method', label: 'Methods', icon: '⚡', color: 'text-blue-300' },
  { key: 'stack', label: 'Stack', icon: '🔧', color: 'text-emerald-300' },
  { key: 'style', label: 'Style', icon: '💬', color: 'text-pink-300' },
  { key: 'decision', label: 'Decisions', icon: '📋', color: 'text-indigo-300' },
  { key: 'context', label: 'Context', icon: '📚', color: 'text-cyan-300' },
  { key: 'template', label: 'Templates', icon: '📝', color: 'text-amber-300' },
  { key: 'project', label: 'Project', icon: '📁', color: 'text-teal-300' },
]

onMounted(() => {
  loadMemories()
})

// Sync filters to URL query params so back navigation restores state
function updateUrlQuery(): void {
  const query: Record<string, string> = {}
  if (activeType.value) query.type = activeType.value
  if (filterLayer.value) query.layer = filterLayer.value
  if (filterStatus.value && filterStatus.value !== 'active') query.status = filterStatus.value
  if (filterTags.value) query.tags = filterTags.value
  if (offset.value > 0) query.offset = String(offset.value)
  router.replace({ query })
}

watch([activeType, filterLayer, filterStatus, filterTags], () => {
  offset.value = 0
  updateUrlQuery()
  loadMemories()
})

async function loadMemories(): Promise<void> {
  loading.value = true
  try {
    const res = await api.listMemories({
      type: activeType.value || undefined,
      layer: filterLayer.value || undefined,
      status: filterStatus.value || undefined,
      tags: filterTags.value || undefined,
      offset: offset.value,
      limit,
    })
    memories.value = res.items
    total.value = res.total
  } catch {
    // handled
  } finally {
    loading.value = false
  }
}

async function handleSearch(query: string): Promise<void> {
  if (!query.trim()) {
    loadMemories()
    return
  }
  loading.value = true
  try {
    const res = await api.searchMemories({
      query,
      type: activeType.value as never || undefined,
      layer: filterLayer.value as never || undefined,
      top_k: 20,
      min_score: 0.2,
    })
    memories.value = res.results.map(r => ({
      id: r.id,
      title: r.title,
      type: r.type,
      layer: r.layer,
      priority: 5,
      tags: r.tags,
      status: 'active' as const,
      scope: { global: true, projects: [], exclude_projects: [] },
      source: 'manual' as const,
      token_count: 0,
      created_at: '',
      updated_at: '',
    }))
    total.value = res.results.length
  } catch {
    // handled
  } finally {
    loading.value = false
  }
}

function nextPage(): void {
  if (offset.value + limit < total.value) {
    offset.value += limit
    updateUrlQuery()
    loadMemories()
  }
}

function prevPage(): void {
  if (offset.value > 0) {
    offset.value = Math.max(0, offset.value - limit)
    updateUrlQuery()
    loadMemories()
  }
}

const currentPage = () => Math.floor(offset.value / limit) + 1
const totalPages = () => Math.ceil(total.value / limit)
</script>

<template>
  <div class="space-y-5">
    <!-- Header -->
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">Memories</h1>
        <p class="text-sm text-slate-400">{{ total }} memories{{ activeType ? ` in ${activeType}` : '' }}</p>
      </div>
      <button class="btn-primary" @click="router.push('/memories/new')">
        <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        New Memory
      </button>
    </div>

    <!-- Type Tabs -->
    <div class="flex gap-1 overflow-x-auto pb-1 scrollbar-thin">
      <button
        v-for="tab in typeTabs"
        :key="tab.key"
        :class="[
          'flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-all',
          activeType === tab.key
            ? 'bg-blue-600/20 text-blue-300 ring-1 ring-blue-500/40'
            : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
        ]"
        @click="activeType = tab.key"
      >
        <span class="text-base">{{ tab.icon }}</span>
        <span>{{ tab.label }}</span>
      </button>
    </div>

    <!-- Search -->
    <SearchBar
      v-model="searchQuery"
      placeholder="Search memories..."
      @search="handleSearch"
    />

    <!-- Secondary Filters -->
    <div class="flex flex-wrap gap-3">
      <select v-model="filterLayer" class="input-field w-auto min-w-[100px]">
        <option value="">All Layers</option>
        <option v-for="l in MEMORY_LAYERS" :key="l" :value="l">{{ l }}</option>
      </select>
      <select v-model="filterStatus" class="input-field w-auto min-w-[120px]">
        <option v-for="s in MEMORY_STATUSES" :key="s" :value="s">{{ s }}</option>
      </select>
      <input
        v-model="filterTags"
        type="text"
        class="input-field w-auto min-w-[160px]"
        placeholder="Filter by tags..."
        @change="loadMemories()"
      />
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="grid gap-3">
      <div v-for="i in 5" :key="i" class="card animate-pulse">
        <div class="h-4 w-2/3 rounded bg-slate-700" />
        <div class="mt-2 flex gap-2">
          <div class="h-5 w-16 rounded bg-slate-700" />
          <div class="h-5 w-10 rounded bg-slate-700" />
        </div>
      </div>
    </div>

    <!-- Memory list -->
    <div v-else-if="memories.length === 0" class="card text-center py-12">
      <svg class="mx-auto h-12 w-12 text-slate-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
      </svg>
      <p class="mt-3 text-slate-400">
        {{ activeType ? `No ${activeType} memories found` : 'No memories found' }}
      </p>
      <button class="btn-primary mt-4" @click="router.push('/memories/new')">Create your first memory</button>
    </div>

    <div v-else class="grid gap-3">
      <MemoryCard
        v-for="memory in memories"
        :key="memory.id"
        :memory="memory"
      />
    </div>

    <!-- Pagination -->
    <div v-if="total > limit" class="flex items-center justify-between pt-2">
      <p class="text-sm text-slate-400">
        Showing {{ offset + 1 }}-{{ Math.min(offset + limit, total) }} of {{ total }}
      </p>
      <div class="flex gap-2">
        <button
          class="btn-secondary text-xs"
          :disabled="offset === 0"
          @click="prevPage"
        >
          Previous
        </button>
        <span class="flex items-center px-3 text-sm text-slate-400">
          {{ currentPage() }} / {{ totalPages() }}
        </span>
        <button
          class="btn-secondary text-xs"
          :disabled="offset + limit >= total"
          @click="nextPage"
        >
          Next
        </button>
      </div>
    </div>
  </div>
</template>

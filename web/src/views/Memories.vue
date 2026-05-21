<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import SearchBar from '@/components/SearchBar.vue'
import MemoryCard from '@/components/MemoryCard.vue'
import { MEMORY_TYPES, MEMORY_LAYERS, MEMORY_STATUSES } from '@/types'
import type { MemoryListItem } from '@/types'

const router = useRouter()

const memories = ref<MemoryListItem[]>([])
const total = ref(0)
const loading = ref(false)
const offset = ref(0)
const limit = 20

const filterType = ref('')
const filterLayer = ref('')
const filterStatus = ref('active')
const filterTags = ref('')
const searchQuery = ref('')

onMounted(() => {
  loadMemories()
})

watch([filterType, filterLayer, filterStatus, filterTags], () => {
  offset.value = 0
  loadMemories()
})

async function loadMemories(): Promise<void> {
  loading.value = true
  try {
    const res = await api.listMemories({
      type: filterType.value || undefined,
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
      type: filterType.value as never || undefined,
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
    loadMemories()
  }
}

function prevPage(): void {
  if (offset.value > 0) {
    offset.value = Math.max(0, offset.value - limit)
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
        <p class="text-sm text-slate-400">{{ total }} total memories</p>
      </div>
      <button class="btn-primary" @click="router.push('/memories/new')">
        <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        New Memory
      </button>
    </div>

    <!-- Search -->
    <SearchBar
      v-model="searchQuery"
      placeholder="Search memories..."
      @search="handleSearch"
    />

    <!-- Filters -->
    <div class="flex flex-wrap gap-3">
      <select v-model="filterType" class="input-field w-auto min-w-[120px]">
        <option value="">All Types</option>
        <option v-for="t in MEMORY_TYPES" :key="t" :value="t">{{ t }}</option>
      </select>
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
      <p class="mt-3 text-slate-400">No memories found</p>
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

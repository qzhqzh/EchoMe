<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/i18n'
import { api } from '@/api/client'
import SearchBar from '@/components/SearchBar.vue'
import MemoryCard from '@/components/MemoryCard.vue'
import Badge from '@/components/Badge.vue'
import { MEMORY_TYPE_COLORS } from '@/types'
import type { MemoryListItem, SearchResultItem } from '@/types'

const { t } = useI18n()
const router = useRouter()

const recentMemories = ref<MemoryListItem[]>([])
const searchResults = ref<SearchResultItem[]>([])
const typeCounts = ref<Record<string, number>>({})
const totalCount = ref(0)
const pendingCount = ref(0)
const loading = ref(true)
const searching = ref(false)
const searchQuery = ref('')

onMounted(async () => {
  await loadDashboard()
})

async function loadDashboard(): Promise<void> {
  loading.value = true
  try {
    const [memoriesRes, pendingRes] = await Promise.all([
      api.listMemories({ limit: 10 }),
      api.listPending({ limit: 1 }),
    ])

    recentMemories.value = memoriesRes.items
    totalCount.value = memoriesRes.total
    pendingCount.value = pendingRes.total

    const counts: Record<string, number> = {}
    for (const item of memoriesRes.items) {
      counts[item.type] = (counts[item.type] || 0) + 1
    }
    typeCounts.value = counts
  } catch {
    // handled by api client
  } finally {
    loading.value = false
  }
}

async function handleSearch(query: string): Promise<void> {
  searchQuery.value = query
  if (!query.trim()) {
    searchResults.value = []
    return
  }
  searching.value = true
  try {
    const res = await api.searchMemories({ query, top_k: 10, min_score: 0.3 })
    searchResults.value = res.results
  } catch {
    // handled
  } finally {
    searching.value = false
  }
}
</script>

<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">{{ t('dashboard_title') }}</h1>
        <p class="text-sm text-slate-400">{{ t('dashboard_subtitle') }}</p>
      </div>
      <button class="btn-primary" @click="router.push('/memories/new')">
        <svg class="mr-2 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        {{ t('memories_new') }}
      </button>
    </div>

    <!-- Search -->
    <SearchBar
      v-model="searchQuery"
      :placeholder="t('dashboard_search_placeholder')"
      @search="handleSearch"
    />

    <!-- Search Results -->
    <div v-if="searchResults.length > 0" class="space-y-3">
      <h2 class="text-sm font-medium text-slate-400">{{ t('dashboard_search_results') }}</h2>
      <div class="grid gap-3">
        <div
          v-for="result in searchResults"
          :key="result.id"
          class="card-hover"
          @click="router.push(`/memories/${result.id}`)"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0 flex-1">
              <h3 class="text-sm font-medium text-slate-100">{{ result.title }}</h3>
              <p class="mt-1 line-clamp-2 text-xs text-slate-400">{{ result.content }}</p>
            </div>
            <div class="flex items-center gap-2">
              <Badge :color="MEMORY_TYPE_COLORS[result.type]" size="sm">{{ result.type }}</Badge>
              <span class="text-xs text-slate-500">{{ (result.score * 100).toFixed(0) }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Stats Grid -->
    <div v-if="!searchQuery" class="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <div class="card">
        <p class="text-sm text-slate-400">{{ t('dashboard_total_memories') }}</p>
        <p class="mt-1 text-3xl font-bold text-slate-100">{{ totalCount }}</p>
      </div>
      <div class="card">
        <p class="text-sm text-slate-400">{{ t('dashboard_pending_review') }}</p>
        <p class="mt-1 text-3xl font-bold text-amber-400">{{ pendingCount }}</p>
        <button
          v-if="pendingCount > 0"
          class="mt-2 text-xs text-blue-400 hover:text-blue-300"
          @click="router.push('/review')"
        >
          {{ t('dashboard_review_now') }} &rarr;
        </button>
      </div>
      <div class="card">
        <p class="text-sm text-slate-400">{{ t('dashboard_types') }}</p>
        <div class="mt-2 flex flex-wrap gap-1">
          <Badge
            v-for="(count, typeName) in typeCounts"
            :key="typeName"
            :color="MEMORY_TYPE_COLORS[typeName as keyof typeof MEMORY_TYPE_COLORS]"
            size="sm"
          >
            {{ typeName }}: {{ count }}
          </Badge>
        </div>
      </div>
    </div>

    <!-- Recent Memories -->
    <div v-if="!searchQuery">
      <div class="mb-3 flex items-center justify-between">
        <h2 class="text-sm font-medium text-slate-400">{{ t('dashboard_recent') }}</h2>
        <button
          class="text-xs text-blue-400 hover:text-blue-300"
          @click="router.push('/memories')"
        >
          {{ t('dashboard_view_all') }} &rarr;
        </button>
      </div>

      <div v-if="loading" class="grid gap-3">
        <div v-for="i in 5" :key="i" class="card animate-pulse">
          <div class="h-4 w-2/3 rounded bg-slate-700" />
          <div class="mt-2 flex gap-2">
            <div class="h-5 w-16 rounded bg-slate-700" />
            <div class="h-5 w-10 rounded bg-slate-700" />
          </div>
        </div>
      </div>

      <div v-else-if="recentMemories.length === 0" class="card text-center">
        <p class="text-slate-400">{{ t('dashboard_no_memories') }}</p>
      </div>

      <div v-else class="grid gap-3">
        <MemoryCard
          v-for="memory in recentMemories"
          :key="memory.id"
          :memory="memory"
        />
      </div>
    </div>
  </div>
</template>

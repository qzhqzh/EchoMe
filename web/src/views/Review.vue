<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/i18n'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import { LAYER_COLORS, MEMORY_TYPE_COLORS, STATUS_COLORS } from '@/types'
import type { MemoryListItem, MemoryStatus } from '@/types'

const { t } = useI18n()
const router = useRouter()
const { success } = useToast()

const pending = ref<MemoryListItem[]>([])
const total = ref(0)
const loading = ref(true)
const processingId = ref<string | null>(null)
const reviewStatus = ref<MemoryStatus>('ai_review')

onMounted(async () => {
  await loadPending()
})

async function loadPending(): Promise<void> {
  loading.value = true
  try {
    const res = await api.listPending({ limit: 50, status: reviewStatus.value })
    pending.value = res.items
    total.value = res.total
  } catch {
    // handled
  } finally {
    loading.value = false
  }
}

async function approve(id: string): Promise<void> {
  processingId.value = id
  try {
    await api.approveMemory(id)
    pending.value = pending.value.filter(m => m.id !== id)
    total.value--
    success('Memory approved and activated')
  } catch {
    // handled
  } finally {
    processingId.value = null
  }
}

async function reject(id: string): Promise<void> {
  processingId.value = id
  try {
    await api.rejectMemory(id)
    pending.value = pending.value.filter(m => m.id !== id)
    total.value--
    success('Memory rejected')
  } catch {
    // handled
  } finally {
    processingId.value = null
  }
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h1 class="text-2xl font-bold text-slate-100">{{ t('review_title') }}</h1>
      <p class="text-sm text-slate-400">
        {{ total }} {{ t('review_subtitle').replace('{count}', '') }}
      </p>
    </div>

    <div class="flex flex-wrap gap-3">
      <select v-model="reviewStatus" class="input-field w-auto min-w-[180px]" @change="loadPending">
        <option value="ai_review">ai_review</option>
        <option value="pending">pending</option>
      </select>
    </div>

    <div v-if="loading" class="grid gap-4">
      <div v-for="i in 3" :key="i" class="card animate-pulse">
        <div class="h-5 w-2/3 rounded bg-slate-700" />
        <div class="mt-3 h-16 rounded bg-slate-700" />
      </div>
    </div>

    <div v-else-if="pending.length === 0" class="card py-16 text-center">
      <svg class="mx-auto h-16 w-16 text-emerald-500/40" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <h3 class="mt-4 text-lg font-medium text-slate-200">{{ t('review_all_caught_up') }}</h3>
      <p class="mt-1 text-sm text-slate-400">{{ t('review_no_pending') }}</p>
    </div>

    <div v-else class="grid gap-4">
      <div
        v-for="item in pending"
        :key="item.id"
        class="card"
      >
        <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h3 class="text-sm font-medium text-slate-100">{{ item.title }}</h3>
            </div>
            <div class="mt-2 flex flex-wrap gap-1.5">
              <Badge :color="MEMORY_TYPE_COLORS[item.type]" size="sm">{{ item.type }}</Badge>
              <Badge :color="LAYER_COLORS[item.layer]" size="sm">{{ item.layer }}</Badge>
              <Badge :color="STATUS_COLORS[item.status]" size="sm">{{ item.status }}</Badge>
              <span
                v-for="tag in item.tags.slice(0, 4)"
                :key="tag"
                class="inline-flex items-center rounded px-1.5 py-0.5 text-xs text-slate-400 bg-slate-700/50"
              >
                #{{ tag }}
              </span>
            </div>
            <p class="mt-2 text-xs text-slate-500">
              Source: {{ item.source }} | Priority: {{ item.priority }}/10
            </p>
          </div>

          <div class="flex items-center gap-2 shrink-0">
            <button
              class="text-xs text-slate-400 hover:text-slate-200 transition-colors"
              @click="router.push(`/memories/${item.id}`)"
            >
              {{ t('view') }}
            </button>
            <button
              class="btn-danger text-xs px-3 py-1.5"
              :disabled="processingId === item.id"
              @click="reject(item.id)"
            >
              {{ t('reject') }}
            </button>
            <button
              class="btn-success text-xs px-3 py-1.5"
              :disabled="processingId === item.id"
              @click="approve(item.id)"
            >
              {{ t('approve') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import Badge from './Badge.vue'
import { MEMORY_TYPE_COLORS, LAYER_COLORS } from '@/types'
import type { MemoryListItem } from '@/types'

defineProps<{
  memory: MemoryListItem
}>()

const router = useRouter()

function navigateToDetail(id: string): void {
  router.push(`/memories/${id}`)
}

function formatDate(dateStr: string): string {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString()
}
</script>

<template>
  <div
    class="card-hover group"
    @click="navigateToDetail(memory.id)"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0 flex-1">
        <h3 class="truncate text-sm font-medium text-slate-100 group-hover:text-blue-300 transition-colors">
          {{ memory.title }}
        </h3>
        <div class="mt-2 flex flex-wrap items-center gap-1.5">
          <Badge :color="MEMORY_TYPE_COLORS[memory.type]" size="sm">
            {{ memory.type }}
          </Badge>
          <Badge :color="LAYER_COLORS[memory.layer]" size="sm">
            {{ memory.layer }}
          </Badge>
          <span
            v-for="tag in memory.tags.slice(0, 3)"
            :key="tag"
            class="inline-flex items-center rounded px-1.5 py-0.5 text-xs text-slate-400 bg-slate-700/50"
          >
            #{{ tag }}
          </span>
          <span v-if="memory.tags.length > 3" class="text-xs text-slate-500">
            +{{ memory.tags.length - 3 }}
          </span>
        </div>
      </div>
      <div class="flex flex-col items-end gap-1 shrink-0">
        <span class="text-xs text-slate-500">{{ formatDate(memory.updated_at) }}</span>
        <span class="text-xs text-slate-500">P{{ memory.priority }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/i18n'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import Badge from '@/components/Badge.vue'
import MemoryForm from '@/components/MemoryForm.vue'
import Modal from '@/components/Modal.vue'
import { MEMORY_TYPE_COLORS, LAYER_COLORS, STATUS_COLORS } from '@/types'
import type { Memory, MemoryCreateRequest, Project } from '@/types'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const { success } = useToast()

const memory = ref<Memory | null>(null)
const loading = ref(true)
const saving = ref(false)
const editing = ref(false)
const showDeleteModal = ref(false)
const showHardDeleteModal = ref(false)
const projects = ref<Project[]>([])

const memoryId = route.params.id as string

// 获取关联项目的详情
const linkedProject = ref<Project | null>(null)

onMounted(async () => {
  await loadMemory()
  await loadProjects()
})

async function loadMemory(): Promise<void> {
  loading.value = true
  try {
    memory.value = await api.getMemory(memoryId)
  } catch {
    router.push('/memories')
  } finally {
    loading.value = false
  }
}

async function loadProjects(): Promise<void> {
  try {
    projects.value = await api.listProjects()
    // 如果记忆有关联项目，找到对应的项目详情
    if (memory.value && memory.value.scope.projects.length > 0) {
      const projectId = memory.value.scope.projects[0]
      linkedProject.value = projects.value.find(p => p.id === projectId) || null
    }
  } catch {
    // handled
  }
}

async function handleUpdate(data: MemoryCreateRequest): Promise<void> {
  saving.value = true
  try {
    memory.value = await api.updateMemory(memoryId, data)
    editing.value = false
    success('Memory updated')
  } catch {
    // handled
  } finally {
    saving.value = false
  }
}

async function handleArchive(): Promise<void> {
  try {
    const memoryType = memory.value?.type
    await api.deleteMemory(memoryId)
    success(t('memory_detail_archived_success'))
    router.push(`/memories?type=${memoryType}`)
  } catch {
    // handled
  }
}

async function handleHardDelete(): Promise<void> {
  try {
    const memoryType = memory.value?.type
    await api.deleteMemory(memoryId, true)
    success(t('memory_detail_deleted_success'))
    router.push(`/memories?type=${memoryType}`)
  } catch {
    // handled
  }
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString()
}
</script>

<template>
  <div class="mx-auto max-w-4xl space-y-6">
    <!-- Loading -->
    <div v-if="loading" class="card animate-pulse space-y-4">
      <div class="h-6 w-1/2 rounded bg-slate-700" />
      <div class="h-4 w-full rounded bg-slate-700" />
      <div class="h-4 w-3/4 rounded bg-slate-700" />
    </div>

    <!-- Editing mode -->
    <div v-else-if="editing && memory" class="space-y-4">
      <div class="flex items-center justify-between">
        <h1 class="text-2xl font-bold text-slate-100">{{ t('memory_detail_edit') }}</h1>
      </div>
      <div class="card">
        <MemoryForm
          :initial="memory"
          :loading="saving"
          @submit="handleUpdate"
          @cancel="editing = false"
        />
      </div>
    </div>

    <!-- View mode -->
    <div v-else-if="memory" class="space-y-6">
      <!-- Back button -->
      <button
        class="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-slate-400 hover:bg-slate-700/50 hover:text-slate-200 transition-all"
        @click="router.back()"
      >
        <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
        </svg>
        {{ t('back') }}
      </button>

      <!-- Header -->
      <div class="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div class="min-w-0 flex-1">
          <h1 class="text-2xl font-bold text-slate-100">{{ memory.title }}</h1>
          <div class="mt-2 flex flex-wrap items-center gap-2">
            <Badge :color="MEMORY_TYPE_COLORS[memory.type]">{{ memory.type }}</Badge>
            <Badge :color="LAYER_COLORS[memory.layer]">{{ memory.layer }}</Badge>
            <Badge :color="STATUS_COLORS[memory.status]">{{ memory.status }}</Badge>
            <span class="text-xs text-slate-500">Priority: {{ memory.priority }}/10</span>
          </div>
        </div>
        <div class="flex gap-2 shrink-0">
          <button class="btn-secondary" @click="editing = true">
            <svg class="mr-1.5 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
            {{ t('edit') }}
          </button>
          <button class="btn-danger" @click="showDeleteModal = true">
            <svg class="mr-1.5 h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
            {{ t('delete') }}
          </button>
        </div>
      </div>

      <!-- Content -->
      <div class="card">
        <h3 class="mb-2 text-sm font-medium text-slate-400">{{ t('memory_detail_content') }}</h3>
        <div class="whitespace-pre-wrap text-sm text-slate-200 leading-relaxed">{{ memory.content }}</div>
      </div>

      <!-- Metadata -->
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div class="card">
          <h3 class="mb-3 text-sm font-medium text-slate-400">{{ t('memory_detail_details') }}</h3>
          <dl class="space-y-2 text-sm">
            <div class="flex justify-between">
              <dt class="text-slate-400">{{ t('memory_detail_source') }}</dt>
              <dd class="text-slate-200">{{ memory.source }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-400">{{ t('memory_detail_token_count') }}</dt>
              <dd class="text-slate-200">{{ memory.token_count }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-400">{{ t('memory_detail_created') }}</dt>
              <dd class="text-slate-200">{{ formatDate(memory.created_at) }}</dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-400">{{ t('memory_detail_updated') }}</dt>
              <dd class="text-slate-200">{{ formatDate(memory.updated_at) }}</dd>
            </div>
          </dl>
        </div>

        <div class="card">
          <h3 class="mb-3 text-sm font-medium text-slate-400">{{ t('memory_detail_scope_tags') }}</h3>
          <div class="space-y-3">
            <div>
              <span class="text-xs text-slate-500">{{ t('memory_detail_scope') }}</span>
              <div v-if="memory.scope.global" class="text-sm text-slate-200">
                {{ t('memory_detail_global') }}
              </div>
              <div v-else-if="linkedProject" class="space-y-2">
                <p class="text-sm text-slate-200">
                  <span class="font-medium">{{ linkedProject.name }}</span>
                  <span class="text-slate-500 ml-2">({{ linkedProject.id }})</span>
                </p>
                <p v-if="linkedProject.description" class="text-xs text-slate-400">
                  {{ linkedProject.description }}
                </p>
                <a v-if="linkedProject.git_remote" :href="linkedProject.git_remote" target="_blank" class="text-xs text-blue-400 hover:text-blue-300">
                  {{ linkedProject.git_remote }}
                </a>
              </div>
              <div v-else class="text-sm text-slate-200">
                {{ memory.scope.projects.join(', ') }}
              </div>
            </div>
            <div v-if="memory.tags.length > 0">
              <span class="text-xs text-slate-500">{{ t('memory_detail_tags') }}</span>
              <div class="mt-1 flex flex-wrap gap-1.5">
                <span
                  v-for="tag in memory.tags"
                  :key="tag"
                  class="inline-flex items-center rounded-md bg-slate-700 px-2 py-0.5 text-xs text-slate-300"
                >
                  #{{ tag }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete confirmation modal -->
    <Modal :open="showDeleteModal" :title="t('memory_detail_delete_title')" @close="showDeleteModal = false">
      <p class="text-sm text-slate-300">
        {{ t('memory_detail_delete_confirm') }}
      </p>
      <template #footer>
        <button class="btn-secondary" @click="showDeleteModal = false">{{ t('cancel') }}</button>
        <button class="btn-danger" @click="handleArchive">{{ t('memory_detail_archive') }}</button>
        <button
          class="rounded-lg border border-red-700 bg-red-900/50 px-4 py-2 text-sm font-medium text-red-300 hover:bg-red-900 transition-colors"
          @click="showDeleteModal = false; showHardDeleteModal = true"
        >
          {{ t('memory_detail_hard_delete') }}
        </button>
      </template>
    </Modal>

    <!-- Hard delete confirmation modal -->
    <Modal :open="showHardDeleteModal" :title="t('memory_detail_hard_delete_title')" @close="showHardDeleteModal = false">
      <p class="text-sm text-red-300">
        {{ t('memory_detail_hard_delete_confirm') }}
      </p>
      <template #footer>
        <button class="btn-secondary" @click="showHardDeleteModal = false">{{ t('cancel') }}</button>
        <button class="btn-danger" @click="handleHardDelete">{{ t('memory_detail_hard_delete') }}</button>
      </template>
    </Modal>
  </div>
</template>

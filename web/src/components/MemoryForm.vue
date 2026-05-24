<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '@/i18n'
import { api } from '@/api/client'
import { MEMORY_TYPES, MEMORY_LAYERS } from '@/types'
import type { MemoryCreateRequest, Memory, MemoryType, MemoryLayer, MemorySource, Project } from '@/types'

const { t } = useI18n()

const props = defineProps<{
  initial?: Memory | null
  loading?: boolean
  defaultType?: MemoryType
}>()

const emit = defineEmits<{
  submit: [data: MemoryCreateRequest]
  cancel: []
}>()

const title = ref(props.initial?.title || '')
const content = ref(props.initial?.content || '')
const type = ref<MemoryType>(props.initial?.type || props.defaultType || 'context')
const layer = ref<MemoryLayer>(props.initial?.layer || 'L2')
const priority = ref(props.initial?.priority || 5)
const tagsInput = ref(props.initial?.tags.join(', ') || '')
const scopeGlobal = ref(props.initial?.scope.global ?? true)
const selectedProject = ref(props.initial?.scope.projects[0] || '')
const source = ref<MemorySource>(props.initial?.source || 'manual')
const projects = ref<Project[]>([])

// 需要 project/decision 强制关联项目
const requiresProject = computed(() => type.value === 'project' || type.value === 'decision')

const isValid = computed(() => {
  if (!title.value.trim() || !content.value.trim()) return false
  if (requiresProject.value && !selectedProject.value) return false
  return true
})

onMounted(async () => {
  try {
    projects.value = await api.listProjects()
  } catch {
    // handled
  }
})

function handleSubmit(): void {
  if (!isValid.value) return

  const tags = tagsInput.value
    .split(',')
    .map(t => t.trim())
    .filter(Boolean)

  const projectsList = requiresProject.value || !scopeGlobal.value
    ? selectedProject.value ? [selectedProject.value] : []
    : []

  const data: MemoryCreateRequest = {
    title: title.value.trim(),
    content: content.value.trim(),
    type: type.value,
    layer: layer.value,
    priority: priority.value,
    tags,
    status: 'active',
    scope: {
      global: !requiresProject.value && scopeGlobal.value,
      projects: projectsList,
      exclude_projects: [],
    },
    source: source.value,
  }

  emit('submit', data)
}
</script>

<template>
  <form class="space-y-5" @submit.prevent="handleSubmit">
    <!-- Title -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">{{ t('form_title') }}</label>
      <input
        v-model="title"
        type="text"
        class="input-field"
        :placeholder="t('form_title_placeholder')"
        maxlength="256"
      />
    </div>

    <!-- Content -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">{{ t('form_content') }}</label>
      <textarea
        v-model="content"
        class="input-field min-h-[150px] resize-y"
        :placeholder="t('form_content_placeholder')"
        rows="6"
      />
    </div>

    <!-- Type + Layer row -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <label class="mb-1.5 block text-sm font-medium text-slate-300">{{ t('form_type') }}</label>
        <select v-model="type" class="input-field">
          <option v-for="t in MEMORY_TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
      </div>
      <div>
        <label class="mb-1.5 block text-sm font-medium text-slate-300">{{ t('form_layer') }}</label>
        <select v-model="layer" class="input-field">
          <option v-for="l in MEMORY_LAYERS" :key="l" :value="l">
            {{ l }} {{ l === 'L0' ? t('form_layer_critical') : l === 'L1' ? t('form_layer_important') : t('form_layer_general') }}
          </option>
        </select>
      </div>
    </div>

    <!-- Priority -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">
        {{ t('form_priority') }}: {{ priority }}
      </label>
      <input
        v-model.number="priority"
        type="range"
        min="1"
        max="10"
        class="w-full accent-blue-500"
      />
      <div class="flex justify-between text-xs text-slate-500">
        <span>{{ t('form_priority_low') }}</span>
        <span>{{ t('form_priority_high') }}</span>
      </div>
    </div>

    <!-- Tags -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">{{ t('form_tags') }}</label>
      <input
        v-model="tagsInput"
        type="text"
        class="input-field"
        :placeholder="t('form_tags_placeholder')"
      />
    </div>

    <!-- Project association -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">
        {{ t('form_project') }}
        <span v-if="requiresProject" class="text-red-400">*</span>
      </label>
      <select v-model="selectedProject" class="input-field">
        <option value="">-- {{ requiresProject ? t('form_project_required') : t('form_project_optional') }} --</option>
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
      <p v-if="requiresProject && !selectedProject" class="mt-1 text-xs text-red-400">
        {{ t('form_project_required_hint') }}
      </p>
      <label v-if="!requiresProject" class="mt-2 flex items-center gap-2 text-sm text-slate-300">
        <input
          v-model="scopeGlobal"
          type="checkbox"
          class="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
        />
        {{ t('form_scope_global') }}
      </label>
    </div>

    <!-- Actions -->
    <div class="flex items-center justify-end gap-3 pt-2">
      <button type="button" class="btn-secondary" @click="emit('cancel')">
        {{ t('cancel') }}
      </button>
      <button
        type="submit"
        class="btn-primary"
        :disabled="!isValid || loading"
      >
        <svg v-if="loading" class="mr-2 h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        {{ initial ? t('form_update_memory') : t('form_create_memory') }}
      </button>
    </div>
  </form>
</template>

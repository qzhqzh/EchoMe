<script setup lang="ts">
import { ref, computed } from 'vue'
import { MEMORY_TYPES, MEMORY_LAYERS } from '@/types'
import type { MemoryCreateRequest, Memory, MemoryType, MemoryLayer, MemorySource } from '@/types'

const props = defineProps<{
  initial?: Memory | null
  loading?: boolean
}>()

const emit = defineEmits<{
  submit: [data: MemoryCreateRequest]
  cancel: []
}>()

const title = ref(props.initial?.title || '')
const content = ref(props.initial?.content || '')
const type = ref<MemoryType>(props.initial?.type || 'knowledge')
const layer = ref<MemoryLayer>(props.initial?.layer || 'L2')
const priority = ref(props.initial?.priority || 5)
const tagsInput = ref(props.initial?.tags.join(', ') || '')
const scopeGlobal = ref(props.initial?.scope.global ?? true)
const scopeProjects = ref(props.initial?.scope.projects.join(', ') || '')
const source = ref<MemorySource>(props.initial?.source || 'manual')

const isValid = computed(() => title.value.trim() && content.value.trim())

function handleSubmit(): void {
  if (!isValid.value) return

  const tags = tagsInput.value
    .split(',')
    .map(t => t.trim())
    .filter(Boolean)

  const projects = scopeProjects.value
    .split(',')
    .map(p => p.trim())
    .filter(Boolean)

  const data: MemoryCreateRequest = {
    title: title.value.trim(),
    content: content.value.trim(),
    type: type.value,
    layer: layer.value,
    priority: priority.value,
    tags,
    status: 'active',
    scope: {
      global: scopeGlobal.value,
      projects,
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
      <label class="mb-1.5 block text-sm font-medium text-slate-300">Title</label>
      <input
        v-model="title"
        type="text"
        class="input-field"
        placeholder="Enter memory title..."
        maxlength="256"
      />
    </div>

    <!-- Content -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">Content</label>
      <textarea
        v-model="content"
        class="input-field min-h-[150px] resize-y"
        placeholder="Enter memory content (supports markdown)..."
        rows="6"
      />
    </div>

    <!-- Type + Layer row -->
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <div>
        <label class="mb-1.5 block text-sm font-medium text-slate-300">Type</label>
        <select v-model="type" class="input-field">
          <option v-for="t in MEMORY_TYPES" :key="t" :value="t">{{ t }}</option>
        </select>
      </div>
      <div>
        <label class="mb-1.5 block text-sm font-medium text-slate-300">Layer</label>
        <select v-model="layer" class="input-field">
          <option v-for="l in MEMORY_LAYERS" :key="l" :value="l">
            {{ l }} {{ l === 'L0' ? '(Critical)' : l === 'L1' ? '(Important)' : '(General)' }}
          </option>
        </select>
      </div>
    </div>

    <!-- Priority -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">
        Priority: {{ priority }}
      </label>
      <input
        v-model.number="priority"
        type="range"
        min="1"
        max="10"
        class="w-full accent-blue-500"
      />
      <div class="flex justify-between text-xs text-slate-500">
        <span>1 (Low)</span>
        <span>10 (High)</span>
      </div>
    </div>

    <!-- Tags -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">Tags</label>
      <input
        v-model="tagsInput"
        type="text"
        class="input-field"
        placeholder="comma, separated, tags"
      />
    </div>

    <!-- Scope -->
    <div>
      <label class="mb-1.5 block text-sm font-medium text-slate-300">Scope</label>
      <div class="space-y-3">
        <label class="flex items-center gap-2 text-sm text-slate-300">
          <input
            v-model="scopeGlobal"
            type="checkbox"
            class="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500"
          />
          Global (applies to all projects)
        </label>
        <input
          v-if="!scopeGlobal"
          v-model="scopeProjects"
          type="text"
          class="input-field"
          placeholder="Project IDs (comma separated)"
        />
      </div>
    </div>

    <!-- Actions -->
    <div class="flex items-center justify-end gap-3 pt-2">
      <button type="button" class="btn-secondary" @click="emit('cancel')">
        Cancel
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
        {{ initial ? 'Update Memory' : 'Create Memory' }}
      </button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  modelValue?: string
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  search: [query: string]
}>()

const query = ref(props.modelValue || '')

function handleInput(event: Event): void {
  const value = (event.target as HTMLInputElement).value
  query.value = value
  emit('update:modelValue', value)
}

function handleSubmit(): void {
  emit('search', query.value)
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter') {
    handleSubmit()
  }
}
</script>

<template>
  <div class="relative">
    <div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3">
      <svg class="h-5 w-5 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
    </div>
    <input
      type="text"
      :value="query"
      :placeholder="placeholder || 'Search memories...'"
      class="w-full rounded-lg border border-slate-600 bg-slate-800 py-2.5 pl-10 pr-4 text-sm text-slate-100 placeholder-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/20 transition-all"
      @input="handleInput"
      @keydown="handleKeydown"
    />
    <button
      v-if="query"
      class="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-200"
      @click="query = ''; emit('update:modelValue', ''); emit('search', '')"
    >
      <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
      </svg>
    </button>
  </div>
</template>

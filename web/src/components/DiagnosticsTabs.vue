<script setup lang="ts">
import { useRoute } from 'vue-router'

const route = useRoute()
const tabs = [
  { label: 'Memory Graph', path: '/observability' },
  { label: 'Quality Eval', path: '/eval' },
  { label: 'Retrieval Logs', path: '/logs' },
]
</script>

<template>
  <nav class="inline-flex max-w-full overflow-x-auto rounded border border-slate-700 bg-slate-800 p-1" aria-label="Diagnostics">
    <RouterLink
      v-for="tab in tabs"
      :key="tab.path"
      :to="tab.path"
      :class="[
        'whitespace-nowrap rounded px-3 py-1.5 text-sm font-medium transition-colors',
        route.path === tab.path
          ? 'bg-blue-600 text-white'
          : 'text-slate-400 hover:bg-slate-700 hover:text-slate-100',
      ]"
    >
      {{ tab.label }}
    </RouterLink>
  </nav>
</template>

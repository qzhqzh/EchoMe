<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
const route = useRoute(), router = useRouter(), text = ref('')
watch(() => route.query.q, value => { text.value = typeof value === 'string' ? value : '' }, { immediate: true })
function search() {
  if (text.value.trim()) router.push({ path: '/knowledge', query: { view: 'search', q: text.value.trim() } })
}
</script>

<template>
  <form role="search" aria-label="知识库全局搜索" class="flex min-w-0 items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/70 px-3 focus-within:border-blue-400" @submit.prevent="search">
    <svg class="h-4 w-4 shrink-0 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></svg>
    <input v-model="text" type="search" maxlength="500" aria-label="搜索整个知识库" placeholder="搜索整个知识库" class="min-w-0 flex-1 bg-transparent py-3 text-sm text-slate-200 outline-none placeholder:text-slate-500" />
    <button :disabled="!text.trim()" class="shrink-0 py-3 text-xs text-blue-300 disabled:text-slate-600">搜索</button>
  </form>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { kb, titleOf, type KRecord } from '@/knowledge'
import { recentIds, clearVisits } from '@/knowledge-state'
const items = ref<KRecord[]>([])
onMounted(async () => { const results = await Promise.allSettled(recentIds().slice(0, 4).map(id => kb.get(id))); items.value = results.flatMap(r => r.status === 'fulfilled' ? [r.value] : []) })
</script>
<template>
  <section v-if="items.length" aria-label="最近查看" class="rounded-xl border border-slate-700/60 bg-slate-800/15 px-4 py-3">
    <div class="mb-2 flex justify-between text-xs"><h2 class="text-slate-500">最近查看</h2><button aria-label="清空最近查看" class="text-slate-500 hover:text-slate-300" @click="clearVisits(); items = []">清空</button></div>
    <div class="flex flex-wrap gap-x-5 gap-y-2"><router-link v-for="item in items" :key="item.id" :to="`/knowledge/${item.id}`" class="max-w-full truncate text-xs text-slate-300 hover:text-blue-300">{{ titleOf(item) }}</router-link></div>
  </section>
</template>

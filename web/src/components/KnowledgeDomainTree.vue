<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { kb, type DirectoryEntry } from '@/knowledge'
import KnowledgeTreeNode from './KnowledgeTreeNode.vue'
import { collapseFamily } from '@/knowledge-state'

const props = defineProps<{ search: string }>()
const emit = defineEmits<{ create: []; clear: [] }>()
const entries = ref<DirectoryEntry[]>([]), total = ref(0), next = ref<number | null>(null), busy = ref(false), error = ref('')
const unplacedCount = ref(0), unplaced = ref<DirectoryEntry[]>([]), unplacedNext = ref<number | null>(null), unplacedOpen = ref(false), unplacedBusy = ref(false), unplacedError = ref('')
const collapseToken = ref(0)
let generation = 0
onBeforeUnmount(() => { generation++ })

async function load(more = false) {
  const current = more ? generation : ++generation; busy.value = true; error.value = ''
  try {
    const page = await kb.directory({ search: props.search || undefined, offset: more ? next.value || 0 : 0, limit: 30 })
    if (current !== generation) return
    entries.value = more ? [...entries.value, ...page.items] : page.items
    total.value = page.total; next.value = page.next_offset; unplacedCount.value = page.unplaced_total
  } catch (e) { if (current === generation) error.value = String(e) } finally { if (current === generation) busy.value = false }
}
async function loadUnplaced(more = false) {
  const current = generation; unplacedBusy.value = true; unplacedError.value = ''
  try {
    const page = await kb.directory({ unplaced: true, offset: more ? unplacedNext.value || 0 : 0, limit: 30 })
    if (current !== generation) return
    unplaced.value = more ? [...unplaced.value, ...page.items] : page.items
    unplacedNext.value = page.next_offset
  } catch (e) { if (current === generation) unplacedError.value = String(e) } finally { if (current === generation) unplacedBusy.value = false }
}
function toggleUnplaced() { unplacedOpen.value = !unplacedOpen.value; if (unplacedOpen.value && !unplaced.value.length) loadUnplaced() }
watch(() => props.search, () => {
  entries.value = []; unplaced.value = []; unplacedOpen.value = false; unplacedBusy.value = false; unplacedError.value = ''
  load()
}, { immediate: true })
</script>

<template>
  <section aria-label="领域目录" class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3 text-xs text-slate-500">
      <span aria-live="polite">{{ busy && !entries.length ? '加载中…' : search ? `${total} 个匹配领域` : `${total} 项顶层目录` }}</span>
      <button v-if="search" class="text-blue-300" @click="emit('clear')">清除搜索</button>
      <button v-else-if="entries.some(node => node.child_count)" class="text-slate-400 hover:text-slate-200" @click="collapseFamily('domains'); collapseToken++">收起全部</button>
    </div>
    <p v-if="error" role="alert" class="break-words rounded-lg border border-rose-400/20 p-4 text-sm text-rose-300">{{ error }} <button class="underline" @click="load(!!entries.length)">重试</button></p>
    <div v-if="busy && !entries.length" class="py-12 text-center text-sm text-slate-500">加载中…</div>
    <template v-else-if="entries.length">
      <div v-if="search" class="divide-y divide-slate-700 rounded-xl border border-slate-700/80 px-5">
        <article v-for="entry in entries" :key="entry.entity_id" class="py-4">
          <p v-for="(path, index) in entry.paths" :key="index" class="mb-2 break-words text-xs leading-6 text-slate-500">{{ path.incomplete ? '上级未显示 / ' : '' }}{{ path.names.join(' / ') }}</p>
          <p v-if="!entry.paths?.length" class="mb-2 text-xs text-slate-500">未归类</p>
          <router-link :to="{ path: `/knowledge/${entry.entity_id}`, query: { from: 'domains' } }" class="break-words text-sm font-medium text-slate-200 hover:text-blue-300">{{ entry.name }}</router-link>
          <p v-if="entry.summary" class="mt-2 line-clamp-2 text-sm leading-6 text-slate-400">{{ entry.summary }}</p>
        </article>
      </div>
      <ul v-else aria-label="领域层级" class="rounded-xl border border-slate-700/80 bg-slate-800/20 p-2 sm:p-3">
        <KnowledgeTreeNode v-for="entry in entries" :key="entry.placement_id || entry.entity_id" :node="entry" :auto-expand="total <= 10" :collapse-token="collapseToken" />
      </ul>
      <button v-if="next !== null" :disabled="busy" class="text-sm text-blue-300 disabled:opacity-50" @click="load(true)">{{ busy ? '加载中…' : '加载更多' }}</button>
    </template>
    <div v-else-if="!error && !unplacedCount" class="rounded-xl border border-dashed border-slate-700 px-5 py-12 text-center">
      <h2 class="text-base text-slate-200">{{ search ? '没有找到匹配领域' : '暂无领域' }}</h2>
      <button class="mt-4 text-sm text-blue-300" @click="search ? emit('clear') : emit('create')">{{ search ? '清除搜索' : '新建领域' }}</button>
    </div>
    <section v-if="unplacedCount && !search" class="rounded-xl border border-slate-700/70 p-4">
      <button :aria-expanded="unplacedOpen" class="flex w-full items-center justify-between text-sm text-slate-400" @click="toggleUnplaced"><span>未归类领域</span><span>{{ unplacedCount }} {{ unplacedOpen ? '−' : '＋' }}</span></button>
      <div v-if="unplacedOpen" class="mt-3">
        <p v-if="unplacedError" role="alert" class="text-xs text-rose-300">{{ unplacedError }} <button class="underline" @click="loadUnplaced(!!unplaced.length)">重试</button></p>
        <ul><KnowledgeTreeNode v-for="entry in unplaced" :key="entry.entity_id" :node="entry" /></ul>
        <p v-if="unplacedBusy" class="py-2 text-xs text-slate-500">加载中…</p>
        <button v-else-if="unplacedNext !== null" class="py-2 text-xs text-blue-300" @click="loadUnplaced(true)">加载更多</button>
      </div>
    </section>
  </section>
</template>

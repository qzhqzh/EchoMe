<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { kb, kindNames, type KnowledgeChoice, type KnowledgeKind, type KRecord } from '@/knowledge'
import { knowledgeError } from '@/knowledge-state'
const props = defineProps<{ modelValue?: string | null; kinds: KnowledgeKind[]; label: string; emptyLabel?: string; required?: boolean; excludeId?: string; excludeTopics?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [id: string | null]; selected: [record: KRecord] }>()
const open = ref(false), query = ref(''), items = ref<KnowledgeChoice[]>([]), selected = ref<KRecord | null>(null), selectedName = ref(''), busy = ref(false), error = ref(''), next = ref<number | null>(null)
const pathLabels = new Map<string, string>()
let generation = 0, selection = 0, timer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => { generation++; selection++; clearTimeout(timer) })
watch(() => props.modelValue, async id => {
  const current = ++selection
  if (!id) { selected.value = null; selectedName.value = ''; return }
  try {
    const row = await kb.get(id)
    if (current !== selection) return
    selected.value = row
    if (row.kind === 'placement') {
      const entity = await kb.get(row.data.entity_id)
      if (current !== selection) return
      selectedName.value = pathLabels.get(id) || entity.data.name
    } else selectedName.value = row.data.name || row.data.title || row.data.label || row.data.statement_md || kindNames[row.kind]
    emit('selected', row)
  } catch (e) { if (current === selection) error.value = knowledgeError(e) }
}, { immediate: true })
async function load(more = false) {
  const current = ++generation; busy.value = true; error.value = ''
  try {
    const result = await kb.choices({ kinds: props.kinds.join(','), search: query.value.trim() || undefined, exclude_id: props.excludeId, exclude_topics: props.excludeTopics, offset: more ? next.value || 0 : 0, limit: 20 })
    if (current !== generation) return
    items.value = more ? [...items.value, ...result.items] : result.items; next.value = result.next_offset
  } catch (e) { if (current === generation) error.value = knowledgeError(e) } finally { if (current === generation) busy.value = false }
}
watch(query, () => { generation++; clearTimeout(timer); timer = setTimeout(() => load(), 220) })
function toggle() { open.value = !open.value; if (open.value) { query.value = ''; load() } }
function choose(item: KnowledgeChoice | null) {
  if (item?.path) pathLabels.set(item.id, item.path.nodes.map(n => n.name).join(' / '))
  emit('update:modelValue', item?.id || null)
  if (item) selectedName.value = item.path?.nodes.map(n => n.name).join(' / ') || item.name
  open.value = false
}
function escape(event: KeyboardEvent) { if (open.value) { event.preventDefault(); event.stopPropagation(); open.value = false } }
</script>
<template>
  <div class="mt-2 min-w-0" @keydown.esc="escape">
    <button type="button" :aria-label="label" :aria-expanded="open" :disabled="disabled" class="flex w-full items-center justify-between gap-3 rounded-lg border border-slate-600 bg-slate-950 px-3 py-2.5 text-left text-sm disabled:opacity-40" @click="toggle"><span class="min-w-0 break-words" :class="modelValue ? 'text-slate-200' : 'text-slate-500'">{{ modelValue ? selectedName || '读取中…' : emptyLabel || '搜索并选择' }}</span><span aria-hidden="true" class="shrink-0 text-slate-500">⌄</span></button>
    <div v-if="open" class="mt-2 rounded-xl border border-slate-600 bg-slate-950 p-3">
      <input v-model="query" :aria-label="'搜索' + label" placeholder="输入名称查找…" class="w-full rounded-lg border border-slate-700 bg-slate-900 p-2.5 text-sm outline-none focus:border-blue-400" @keydown.enter.prevent="load()" />
      <div :aria-label="label + '选项'" class="mt-2 max-h-60 space-y-1 overflow-y-auto overscroll-contain">
        <button v-if="!required" type="button" class="block w-full rounded-lg p-2.5 text-left text-xs text-slate-500 hover:bg-slate-800" @click="choose(null)">{{ emptyLabel || '不关联' }}</button>
        <button v-for="item in items" :key="item.id" type="button" :aria-label="item.path?.nodes.map(n => n.name).join(' / ') || item.name" class="block w-full rounded-lg p-2.5 text-left hover:bg-slate-800" @click="choose(item)"><span class="block break-words text-sm text-slate-200">{{ item.name }}</span><span class="mt-1 block break-words text-xs text-slate-500">{{ item.path ? (item.path.incomplete ? '上级未显示 / ' : '') + item.path.nodes.map(n => n.name).join(' / ') : kindNames[item.kind] }}</span></button>
        <p v-if="busy" class="p-3 text-xs text-slate-500">加载中…</p><p v-else-if="!items.length && !error" class="p-3 text-xs text-slate-500">没有匹配内容，可调整关键词。</p>
        <button v-if="next !== null" type="button" :disabled="busy" class="p-2.5 text-xs text-blue-300 disabled:opacity-40" @click="load(true)">加载更多选项</button>
      </div>
    </div>
    <p v-if="error" role="alert" class="mt-2 text-xs text-rose-300">{{ error }} <button v-if="open" type="button" class="underline" @click="load()">重试</button></p>
  </div>
</template>

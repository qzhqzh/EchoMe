<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { kb, type DirectoryEntry } from '@/knowledge'
import { expansion, rememberExpansion } from '@/knowledge-state'

const props = withDefaults(defineProps<{ node: DirectoryEntry; depth?: number; autoExpand?: boolean; collapseToken?: number }>(), { depth: 0, autoExpand: false, collapseToken: 0 })
const expanded = ref(false), loaded = ref(false), busy = ref(false), error = ref('')
const children = ref<DirectoryEntry[]>([]), next = ref<number | null>(null)
const labels: Record<string, string> = { topic: '领域', concept: '概念', method: '方法', tool: '工具', object: '对象' }
const groupId = `directory-${props.node.placement_id}`

async function load(more = false) {
  if (!props.node.placement_id || busy.value) return
  busy.value = true; error.value = ''
  try {
    const page = await kb.directory({ parent_id: props.node.placement_id, offset: more ? next.value || 0 : 0, limit: 30 })
    children.value = more ? [...children.value, ...page.items] : page.items
    next.value = page.next_offset; loaded.value = true
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
function toggle() {
  expanded.value = !expanded.value
  rememberExpansion('domains:' + props.node.placement_id, expanded.value)
  if (expanded.value && !loaded.value) load()
}
onMounted(() => { expanded.value = expansion('domains:' + props.node.placement_id) ?? (props.autoExpand && props.depth < 2 && props.node.child_count > 0 && props.node.child_count <= 10); if (expanded.value && props.node.child_count) load() })
watch(() => props.collapseToken, () => { expanded.value = false; rememberExpansion('domains:' + props.node.placement_id, false) })
</script>

<template>
  <li class="min-w-0">
    <div class="group flex min-h-12 items-center gap-1 rounded-lg pr-2 hover:bg-slate-800/60">
      <button v-if="node.child_count" :aria-label="(expanded ? '收起' : '展开') + node.name" :aria-expanded="expanded" :aria-controls="groupId" class="flex h-10 w-10 shrink-0 items-center justify-center rounded text-slate-400 hover:text-slate-100 focus-visible:outline-blue-400" @click="toggle">
        <svg :class="['h-4 w-4 transition-transform', expanded ? 'rotate-90' : '']" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
      </button>
      <span v-else class="flex h-10 w-10 shrink-0 items-center justify-center text-slate-600" aria-hidden="true">·</span>
      <svg v-if="node.entity_kind === 'topic'" class="h-4 w-4 shrink-0 text-indigo-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3 7V5h6l2 2h10v12H3Z" /></svg>
      <router-link :to="{ path: `/knowledge/${node.entity_id}`, query: { from: 'domains' } }" class="min-w-0 flex-1 break-words px-2 py-3 text-sm leading-6 text-slate-200 hover:text-blue-300">{{ node.name }}</router-link>
      <span class="shrink-0 text-[11px] text-slate-500">{{ node.entity_kind === 'topic' && node.child_count ? `${node.child_count} 项` : labels[node.entity_kind] }}</span>
    </div>
    <div v-if="expanded" :id="groupId" class="ml-5 border-l border-slate-700 pl-2 sm:pl-4">
      <p v-if="error" role="alert" class="break-words p-3 text-xs text-rose-300">{{ error }} <button class="underline" @click="load(loaded)">重试</button></p>
      <ul v-if="children.length" :aria-label="node.name + '的下级内容'" class="min-w-0">
        <KnowledgeTreeNode v-for="child in children" :key="child.placement_id || child.entity_id" :node="child" :depth="depth + 1" :auto-expand="autoExpand" :collapse-token="collapseToken" />
      </ul>
      <p v-if="busy" class="p-3 text-xs text-slate-500">加载中…</p>
      <p v-else-if="loaded && !children.length" class="p-3 text-xs text-slate-500">暂无下级内容。</p>
      <button v-if="next !== null && !busy" class="px-3 py-2 text-xs text-blue-300" @click="load(true)">加载更多</button>
    </div>
  </li>
</template>

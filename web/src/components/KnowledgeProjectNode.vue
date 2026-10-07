<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { kb, entityNames, kindNames, stateNames, usageNames, type KnowledgeNode } from '@/knowledge'
import { expansion, rememberExpansion } from '@/knowledge-state'
const props = withDefaults(defineProps<{ node: KnowledgeNode; card?: boolean; autoExpand?: boolean }>(), { card: false, autoExpand: false })
const expanded = ref(false), loaded = ref(false), busy = ref(false), error = ref('')
const items = ref<KnowledgeNode[]>([]), next = ref<number | null>(null)
async function load(more = false) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const page = await kb.projectTree({ parent_id: props.node.id, offset: more ? next.value || 0 : 0, limit: 20 })
    items.value = more ? [...items.value, ...page.items] : page.items
    next.value = page.next_offset; loaded.value = true
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
function toggle() { expanded.value = !expanded.value; rememberExpansion('projects:' + props.node.id, expanded.value); if (expanded.value && !loaded.value) load() }
onMounted(() => { expanded.value = expansion('projects:' + props.node.id) ?? (props.autoExpand && props.node.child_count > 0 && props.node.child_count <= 8); if (expanded.value) load() })
</script>

<template>
  <li :class="['min-w-0', card ? 'rounded-2xl border border-slate-700/80 bg-slate-800/25 p-4 sm:p-5' : 'py-1']">
    <div class="flex min-w-0 items-start gap-2">
      <button v-if="node.child_count" :aria-label="(expanded ? '收起' : '展开') + node.name" :aria-expanded="expanded" :aria-controls="`project-branch-${node.id}`" class="flex h-10 w-8 shrink-0 items-center justify-center rounded text-slate-400 hover:bg-slate-800 hover:text-white" @click="toggle">
        <svg :class="['h-4 w-4 transition-transform', expanded ? 'rotate-90' : '']" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="m7 4 6 6-6 6" /></svg>
      </button>
      <span v-else class="flex h-10 w-8 shrink-0 items-center justify-center text-slate-600" aria-hidden="true">·</span>
      <div class="min-w-0 flex-1 py-1.5">
        <div v-if="card" class="mb-2 flex items-center justify-between text-xs"><span class="text-blue-300">项目</span><span class="text-slate-500">{{ node.status === 'active' ? '进行中' : stateNames[node.status] }}</span></div>
        <component :is="card ? 'h2' : 'div'"><router-link :to="{ path: `/knowledge/${node.id}`, query: { from: 'projects' } }" :class="['block break-words leading-6 hover:text-blue-300', card ? 'text-base font-semibold text-slate-100' : node.kind === 'question' ? 'text-sm font-medium text-slate-200' : 'text-sm text-indigo-200']">{{ node.name }}</router-link></component>
        <p v-if="card && node.summary" class="mt-2 line-clamp-2 text-xs leading-6 text-slate-400">{{ node.summary }}</p>
        <div v-if="!card" class="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-slate-500">
          <span>{{ node.entity_kind ? entityNames[node.entity_kind] : kindNames[node.kind] }}</span>
          <span v-if="node.kind === 'question'">{{ stateNames[node.status] }}</span>
          <span v-if="node.role">{{ usageNames[node.role] }} · v{{ node.knowledge_revision }}</span>
          <span v-if="['archived','merged'].includes(node.status)" class="text-amber-300">{{ stateNames[node.status] }}</span>
          <router-link v-if="node.via_id" :to="`/knowledge/${node.via_id}?from=projects`" class="text-slate-400 hover:text-blue-300">使用记录 ↗</router-link>
        </div>
      </div>
    </div>
    <div v-if="expanded" :id="`project-branch-${node.id}`" :class="['ml-4 border-l border-slate-700 pl-2 sm:pl-3', card ? 'mt-3' : 'mt-1']">
      <ul :aria-label="node.name + '的下级内容'"><KnowledgeProjectNode v-for="item in items" :key="item.via_id || item.id" :node="item" :auto-expand="autoExpand" /></ul>
      <p v-if="error" role="alert" class="break-words py-3 text-xs text-rose-300">{{ error }} <button class="underline" @click="load(loaded)">重试</button></p>
      <p v-if="busy" class="py-3 text-xs text-slate-500">加载中…</p>
      <p v-else-if="loaded && !items.length" class="py-3 text-xs text-slate-500">暂无问题或知识引用。</p>
      <button v-if="next !== null && !busy" class="py-3 text-xs text-blue-300" @click="load(true)">加载更多</button>
    </div>
    <p v-else-if="card && !node.child_count" class="ml-10 mt-3 text-xs text-slate-500">进入项目，提出第一个问题。</p>
  </li>
</template>

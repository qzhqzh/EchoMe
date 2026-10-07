<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { kb, type KnowledgeNode } from '@/knowledge'
import KnowledgeProjectNode from './KnowledgeProjectNode.vue'
const props = defineProps<{ parentId?: string; independent?: boolean }>()
const emit = defineEmits<{ question: []; project: [] }>()
const items = ref<KnowledgeNode[]>([]), busy = ref(false), error = ref(''), total = ref(0), next = ref<number | null>(null)
const independentTotal = ref(0), independentOpen = ref(false)
let generation = 0
onBeforeUnmount(() => { generation++ })
async function load(more = false) {
  const current = ++generation; busy.value = true; error.value = ''
  try {
    const page = await kb.projectTree({ parent_id: props.parentId, independent: props.independent, offset: more ? next.value || 0 : 0, limit: 12 })
    if (current !== generation) return
    items.value = more ? [...items.value, ...page.items] : page.items
    total.value = page.total; next.value = page.next_offset; independentTotal.value = page.independent_total
  } catch (e) { if (current === generation) error.value = String(e) } finally { if (current === generation) busy.value = false }
}
watch(() => [props.parentId, props.independent], () => { items.value = []; load() }, { immediate: true })
</script>

<template>
  <section :aria-label="parentId ? '问题与知识' : independent ? '独立问题' : '项目层级'" class="space-y-4">
    <p v-if="!parentId && !independent" aria-live="polite" class="text-xs text-slate-500">{{ busy && !items.length ? '加载中…' : `${total} 个项目` }}</p>
    <p v-if="error" role="alert" class="break-words rounded-lg border border-rose-400/20 p-4 text-sm text-rose-300">{{ error }} <button class="underline" @click="load(!!items.length)">重试</button></p>
    <ul :class="!parentId && !independent ? 'grid items-start gap-5 lg:grid-cols-2' : 'space-y-2'">
      <KnowledgeProjectNode v-for="item in items" :key="item.via_id || item.id" :node="item" :card="!parentId && !independent" :auto-expand="total <= 6" />
    </ul>
    <p v-if="busy" class="py-4 text-sm text-slate-500">加载中…</p>
    <section v-else-if="!error && !items.length && !parentId && !independent && !independentTotal" class="rounded-2xl border border-dashed border-slate-600 bg-slate-800/20 px-5 py-12 text-center"><h2 class="text-lg font-semibold text-slate-100">从一个想解决的问题开始</h2><p class="mx-auto mt-3 max-w-md text-sm leading-7 text-slate-400">先记下问题，知识和领域可以在研究过程中逐步补充。有明确交付目标时，也可以创建项目。</p><div class="mt-6 flex flex-wrap justify-center gap-3"><button class="rounded-lg bg-blue-600 px-4 py-2.5 text-sm text-white" @click="emit('question')">提出第一个问题</button><button class="rounded-lg border border-slate-600 px-4 py-2.5 text-sm text-slate-300" @click="emit('project')">创建项目</button></div></section>
    <p v-else-if="!error && !items.length && (parentId || independent)" class="py-8 text-center text-sm text-slate-500">{{ parentId ? '暂无问题或知识引用。' : '暂无独立问题。' }}</p>
    <button v-if="next !== null" :disabled="busy" class="text-sm text-blue-300 disabled:opacity-40" @click="load(true)">加载更多</button>
    <section v-if="!parentId && !independent && independentTotal" class="rounded-xl border border-slate-700/70 p-4 sm:p-5">
      <button :aria-expanded="independentOpen" class="flex w-full items-center justify-between text-sm text-slate-300" @click="independentOpen = !independentOpen"><span>独立问题 <span class="ml-2 text-xs text-slate-500">{{ independentTotal }}</span></span><span class="text-slate-500">{{ independentOpen ? '收起 −' : '展开 ＋' }}</span></button>
      <KnowledgeProjectTree v-if="independentOpen" independent class="mt-4" />
    </section>
  </section>
</template>

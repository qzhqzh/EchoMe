<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { kb, searchCategories, entityNames, type KnowledgeSearchItem } from '@/knowledge'
const route = useRoute(), router = useRouter()
const query = computed(() => typeof route.query.q === 'string' ? route.query.q : '')
const category = computed(() => typeof route.query.category === 'string' && route.query.category in searchCategories ? route.query.category : 'all')
const offset = computed(() => { const n = Number(route.query.offset || 0); return Number.isSafeInteger(n) && n > 0 ? n : 0 })
const items = ref<KnowledgeSearchItem[]>([]), counts = ref<Record<string, number>>({}), total = ref(0), next = ref<number | null>(null), busy = ref(false), error = ref('')
const allCount = computed(() => Object.values(counts.value).reduce((a, b) => a + b, 0))
let generation = 0
onBeforeUnmount(() => { generation++ })
async function load() {
  const current = ++generation; busy.value = true; error.value = ''
  if (!query.value.trim()) { items.value = []; counts.value = {}; total.value = 0; busy.value = false; return }
  try {
    const result = await kb.search({ q: query.value, category: category.value, offset: offset.value, limit: 15 })
    if (current !== generation) return
    items.value = result.items; counts.value = result.counts; total.value = result.total; next.value = result.next_offset
  } catch (e) { if (current === generation) error.value = String(e) } finally { if (current === generation) busy.value = false }
}
function show(group = category.value, start = 0) { router.push({ path: '/knowledge', query: { view: 'search', q: query.value, category: group === 'all' ? undefined : group, offset: start || undefined } }) }
function parts(text: string) {
  const q = query.value.trim().toLocaleLowerCase()
  if (!q) return [{ text, match: false }]
  const result = []; let start = 0, index = text.toLocaleLowerCase().indexOf(q)
  while (index >= 0) {
    if (index > start) result.push({ text: text.slice(start, index), match: false })
    result.push({ text: text.slice(index, index + q.length), match: true })
    start = index + q.length; index = text.toLocaleLowerCase().indexOf(q, start)
  }
  result.push({ text: text.slice(start), match: false }); return result
}
watch(() => [query.value, category.value, offset.value], load, { immediate: true })
</script>

<template>
  <section aria-label="全局搜索结果" class="space-y-5">
    <div class="flex flex-wrap items-baseline gap-3"><h2 class="break-words text-base font-medium text-slate-200">{{ query ? `“${query}” 的搜索结果` : '搜索知识库' }}</h2><span aria-live="polite" class="text-xs text-slate-500">{{ busy ? '搜索中…' : `${total} 条结果` }}</span></div>
    <nav aria-label="搜索结果类型" class="flex flex-wrap gap-2">
      <template v-for="(label, key) in searchCategories" :key="key">
        <button v-if="key === 'all' || counts[key] || category === key" :aria-pressed="category === key" :class="['rounded-full border px-3 py-2 text-xs', category === key ? 'border-blue-400/40 bg-blue-400/10 text-blue-200' : 'border-slate-700 text-slate-400 hover:border-slate-500']" @click="show(key)">{{ label }} <span class="ml-1 opacity-70">{{ key === 'all' ? allCount : counts[key] || 0 }}</span></button>
      </template>
    </nav>
    <p v-if="error" role="alert" class="break-words rounded-lg border border-rose-400/20 p-4 text-sm text-rose-300">{{ error }} <button class="underline" @click="load">重试</button></p>
    <div v-else-if="busy" class="py-12 text-center text-sm text-slate-500">搜索中…</div>
    <div v-else-if="!items.length" class="rounded-xl border border-dashed border-slate-700 p-10 text-center"><h3 class="text-sm text-slate-300">{{ query ? '没有找到匹配内容' : '输入名称、关键词或正文片段' }}</h3><p class="mt-3 text-xs leading-6 text-slate-500">搜索项目、问题、领域、知识、文档、资料和成果。</p></div>
    <div v-else class="divide-y divide-slate-700/70 rounded-xl border border-slate-700/80 bg-slate-800/20 px-4 sm:px-6">
      <article v-for="item in items" :key="item.id" class="min-w-0 py-5">
        <div class="mb-2 flex flex-wrap items-center gap-2 text-xs"><span :class="['rounded px-2 py-1', item.category === 'knowledge' ? 'bg-indigo-400/10 text-indigo-300' : item.category === 'projects' ? 'bg-blue-400/10 text-blue-300' : 'bg-slate-700/40 text-slate-400']">{{ item.entity_kind ? entityNames[item.entity_kind] : searchCategories[item.category] }}</span>
          <span v-for="(location, index) in item.locations" :key="index" class="min-w-0 break-words text-slate-500">{{ location.incomplete ? '上级未显示 / ' : '' }}{{ location.nodes.map(n => n.name).join(' / ') || '目录顶层' }}<span v-if="item.location_count > 1"> · {{ item.location_count }} 处收纳</span></span>
        </div>
        <router-link :to="{ path: `/knowledge/${item.id}`, query: { from: 'search', q: query, category: category === 'all' ? undefined : category, offset: offset || undefined } }" class="break-words text-base font-medium leading-7 text-slate-100 hover:text-blue-300"><template v-for="(part, i) in parts(item.name)" :key="i"><mark v-if="part.match" class="rounded-sm bg-blue-400/15 text-blue-200">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></router-link>
        <p v-if="item.snippet" class="mt-2 line-clamp-3 break-words text-sm leading-7 text-slate-400"><template v-for="(part, i) in parts(item.snippet)" :key="i"><mark v-if="part.match" class="rounded-sm bg-blue-400/15 text-blue-200">{{ part.text }}</mark><template v-else>{{ part.text }}</template></template></p>
      </article>
    </div>
    <div v-if="offset || next !== null" class="flex justify-center gap-6 text-sm"><button :disabled="!offset || busy" class="text-blue-300 disabled:opacity-30" @click="show(category, Math.max(0, offset - 15))">上一页</button><span class="text-slate-500">{{ Math.floor(offset / 15) + 1 }}</span><button :disabled="next === null || busy" class="text-blue-300 disabled:opacity-30" @click="show(category, next || 0)">下一页</button></div>
  </section>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { kb, kindNames, stateNames, titleOf, type KnowledgeKind, type KRecord } from '@/knowledge'
import KnowledgeForm from '@/components/KnowledgeForm.vue'
import KnowledgeDomainTree from '@/components/KnowledgeDomainTree.vue'
import KnowledgeProjectTree from '@/components/KnowledgeProjectTree.vue'
import KnowledgeSearch from '@/components/KnowledgeSearch.vue'
import KnowledgeSearchResults from '@/components/KnowledgeSearchResults.vue'
import KnowledgeRecent from '@/components/KnowledgeRecent.vue'

const route = useRoute(), router = useRouter()
const views = [
  { key: 'projects', section: 'projects', label: '所有项目', kind: 'project', title: '项目', create: '新建项目', unit: '个项目' },
  { key: 'questions', section: 'projects', label: '所有问题', kind: 'question', title: '问题', create: '提出问题', unit: '个问题' },
  { key: 'domains', section: 'domains', label: '领域目录', kind: 'entity', title: '领域', create: '新建领域', unit: '个领域' },
  { key: 'knowledge', section: 'domains', label: '全部知识', kind: 'entity', title: '知识', create: '新建知识', unit: '条知识' },
  { key: 'pages', section: 'resources', label: '文档', kind: 'page', title: '文档', create: '新建文档', unit: '篇文档' },
  { key: 'sources', section: 'resources', label: '资料', kind: 'source', title: '资料', create: '登记资料', unit: '份资料' },
  { key: 'search', section: 'search', label: '搜索结果', kind: 'entity', title: '搜索结果', create: '', unit: '条结果' },
] as const
const entityTypes: Record<string, string> = { concept: '概念', method: '方法', tool: '工具', object: '对象' }
const active = computed(() => views.find(view => view.key === route.query.view) || views[0])
const search = ref(''), typeFilter = ref(''), busy = ref(false), error = ref(''), records = ref<KRecord[]>([])
const total = ref(0), next = ref<number | null>(null), createKind = ref<KnowledgeKind | null>(null), reviewCount = ref<number | null>(null)
const offset = computed(() => {
  const value = Number(route.query.offset || 0)
  return Number.isSafeInteger(value) && value >= 0 ? value : 0
})
const queryText = computed(() => typeof route.query.q === 'string' ? route.query.q : '')
const queriedType = computed(() => active.value.key === 'knowledge' && typeof route.query.type === 'string' && Object.keys(entityTypes).includes(route.query.type) ? route.query.type : '')
const hasFilter = computed(() => !!queryText.value || !!queriedType.value)
let request = 0
onBeforeUnmount(() => { request++ })

async function load() {
  const seq = ++request
  const view = active.value
  busy.value = true; error.value = ''
  if (view.key === 'domains' || view.key === 'projects' || view.key === 'search') { busy.value = false; return }
  try {
    const result = await kb.list(view.kind, {
      search: queryText.value || undefined,
      entity_kind: queriedType.value || undefined,
      exclude_entity_kind: view.key === 'knowledge' ? 'topic' : undefined,
      offset: offset.value, limit: 24,
    })
    if (seq !== request) return
    records.value = result.items; total.value = result.total; next.value = result.next_offset
  } catch (e) {
    if (seq === request) error.value = String(e)
  } finally {
    if (seq === request) busy.value = false
  }
}
watch(() => [active.value.key, route.query.q, route.query.type, route.query.offset], () => {
  if (route.path !== '/knowledge') return
  search.value = queryText.value; typeFilter.value = queriedType.value
  load()
}, { immediate: true })
kb.query('review', { status: 'open' }, { limit: 1 }).then(result => { reviewCount.value = result.total }).catch(() => {})
function show(view: string) { router.push({ path: '/knowledge', query: { view } }) }
function find(pageOffset = 0) {
  const query = { view: active.value.key, q: search.value.trim() || undefined, type: typeFilter.value || undefined, offset: pageOffset || undefined }
  if (router.resolve({ path: '/knowledge', query }).fullPath === route.fullPath) load()
  else router.push({ path: '/knowledge', query })
}
function clearFilters() { search.value = ''; typeFilter.value = ''; find() }
async function saved(record: KRecord) {
  createKind.value = null
  await router.push({ path: `/knowledge/${record.id}`, query: { from: active.value.key } })
}
function labelOf(record: KRecord) {
  if (record.kind === 'entity') return record.data.entity_kind === 'topic' ? '领域' : entityTypes[record.data.entity_kind] || '知识'
  if (record.kind === 'question' && !record.data.project_id) return '独立问题'
  return kindNames[record.kind]
}
function statusOf(record: KRecord) {
  if (record.kind === 'entity') return record.data.entity_kind === 'topic' ? '' : stateNames[record.review_state] || ''
  if (record.kind === 'project' && record.status === 'active') return '进行中'
  return record.status === 'active' ? '' : stateNames[record.status] || record.status
}
function summaryOf(record: KRecord): string {
  if (record.data.summary || record.data.resolution_note) return record.data.summary || record.data.resolution_note
  if (record.kind === 'source') return record.data.origin_ref || ''
  if (record.kind === 'page') return (record.data.body_md || '').replace(/^#+ .*$/gm, '').replace(/[*_`#]/g, '').trim().slice(0, 140)
  return ''
}
const dateOf = (value: string) => new Date(value).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
</script>

<template>
  <div class="mx-auto max-w-6xl space-y-5">
    <header class="flex flex-wrap items-center gap-4">
      <h1 class="shrink-0 text-2xl font-semibold tracking-tight text-slate-100">知识库</h1>
      <KnowledgeSearch class="order-last w-full sm:order-none sm:ml-4 sm:w-auto sm:max-w-lg sm:flex-1" />
      <div class="ml-auto flex items-center gap-4 text-sm">
        <button :aria-pressed="active.section === 'resources'" :class="active.section === 'resources' ? 'text-blue-300' : 'text-slate-400 hover:text-slate-200'" @click="show('pages')">文档与资料</button>
        <router-link to="/knowledge/review" class="flex items-center gap-2 text-slate-400 hover:text-slate-200">待核对<span v-if="reviewCount" class="rounded bg-amber-400/10 px-1.5 py-0.5 text-xs text-amber-200">{{ reviewCount }}</span></router-link>
      </div>
    </header>
    <nav aria-label="知识库主导航" class="flex gap-7 border-b border-slate-700/70">
      <button v-for="item in [{ key: 'projects', label: '项目' }, { key: 'domains', label: '领域' }]" :key="item.key" :aria-pressed="active.section === item.key" :class="['border-b-2 px-1 pb-3 pt-1 text-sm font-medium transition', active.section === item.key ? 'border-blue-400 text-blue-300' : 'border-transparent text-slate-400 hover:text-slate-200']" @click="show(item.key)">{{ item.label }}</button>
    </nav>

    <KnowledgeSearchResults v-if="active.key === 'search'" />
    <section v-else aria-label="内容列表" class="space-y-4">
      <div class="flex flex-wrap items-center gap-3">
        <button v-if="active.key === 'domains'" class="text-sm text-slate-400 hover:text-blue-300" @click="show('knowledge')">知识索引 ↗</button>
        <button v-if="active.key === 'knowledge'" class="text-sm text-slate-400 hover:text-blue-300" @click="show('domains')">← 领域目录</button>
        <button v-if="active.key === 'questions'" class="text-sm text-slate-400 hover:text-blue-300" @click="show('projects')">← 项目</button>
        <nav v-if="active.section === 'resources'" aria-label="文档与资料" class="flex gap-2"><button v-for="view in views.filter(v => v.section === 'resources')" :key="view.key" :aria-pressed="active.key === view.key" :class="['rounded-lg px-3 py-2 text-sm', active.key === view.key ? 'bg-slate-700/60 text-slate-100' : 'text-slate-400']" @click="show(view.key)">{{ view.label }}</button></nav>
        <select v-if="active.key === 'knowledge'" v-model="typeFilter" aria-label="知识类型" class="kb-select" @change="find()">
          <option value="">全部类型</option><option v-for="(label, value) in entityTypes" :key="value" :value="value">{{ label }}</option>
        </select>
        <button v-if="active.key === 'projects'" class="text-sm text-slate-400 hover:text-blue-300" @click="createKind = 'question'">＋ 独立问题</button>
        <button class="ml-auto shrink-0 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-500" @click="createKind = active.kind">＋ {{ active.create }}</button>
      </div>
      <KnowledgeDomainTree v-if="active.key === 'domains'" :search="queryText" @create="createKind = 'entity'" @clear="clearFilters" />
      <template v-else-if="active.key === 'projects'"><KnowledgeRecent /><KnowledgeProjectTree @question="createKind = 'question'" @project="createKind = 'project'" /></template>
      <template v-else>
      <div class="flex items-center gap-3 text-xs text-slate-500">
        <span aria-live="polite">{{ busy ? '加载中…' : `${total} ${active.unit}` }}</span>
        <button v-if="hasFilter" class="text-blue-300" @click="clearFilters">清除筛选</button>
      </div>
      <p v-if="error" role="alert" class="rounded-lg border border-rose-400/20 bg-rose-950/20 p-4 text-sm text-rose-300">{{ error }} <button class="ml-2 underline" @click="load">重试</button></p>
      <div v-else-if="busy" class="py-16 text-center text-sm text-slate-500">加载中…</div>
      <div v-else-if="!records.length" class="rounded-xl border border-dashed border-slate-700 px-5 py-14 text-center">
        <h2 class="text-base font-medium text-slate-200">{{ hasFilter ? '没有找到匹配内容' : '暂无' + active.title }}</h2>
        <p class="mt-2 text-sm text-slate-500">{{ hasFilter ? '调整关键词或筛选条件后重试。' : '创建后会显示在这里。' }}</p>
        <button class="mt-5 text-sm text-blue-300" @click="hasFilter ? clearFilters() : createKind = active.kind">{{ hasFilter ? '清除筛选' : active.create }}</button>
      </div>
      <div v-else class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <router-link v-for="record in records" :key="record.id" :to="{ path: `/knowledge/${record.id}`, query: { from: active.key } }" class="group flex min-h-40 flex-col rounded-xl border border-slate-700/80 bg-slate-800/30 p-5 transition hover:border-slate-500 hover:bg-slate-800/60">
          <div class="flex items-center justify-between gap-3 text-xs">
            <span class="text-slate-400">{{ labelOf(record) }}</span>
            <span v-if="statusOf(record)" :class="record.review_state === 'disputed' ? 'text-amber-300' : 'text-slate-500'">{{ statusOf(record) }}</span>
          </div>
          <h2 class="mt-3 break-words text-base font-semibold leading-7 text-slate-100 group-hover:text-blue-200">{{ titleOf(record) }}</h2>
          <p v-if="summaryOf(record)" class="mt-2 line-clamp-3 break-words text-sm leading-6 text-slate-400">{{ summaryOf(record) }}</p>
          <time :datetime="record.updated_at" :title="new Date(record.updated_at).toLocaleString('zh-CN')" class="mt-auto pt-4 text-xs text-slate-500">{{ dateOf(record.updated_at) }} 更新</time>
        </router-link>
      </div>
      <div v-if="offset || next !== null" class="flex items-center justify-center gap-5 text-sm">
        <button :disabled="!offset || busy" class="disabled:opacity-30" @click="find(Math.max(0, offset - 24))">上一页</button>
        <span class="text-slate-500">{{ Math.floor(offset / 24) + 1 }}</span>
        <button :disabled="next === null || busy" class="disabled:opacity-30" @click="find(next || 0)">下一页</button>
      </div>
      </template>
    </section>
    <KnowledgeForm v-if="createKind" :kind="createKind" :preset="createKind === 'entity' ? { entity_kind: active.key === 'domains' ? 'topic' : 'concept' } : undefined" @close="createKind = null" @saved="saved" />
  </div>
</template>

<style scoped>
.kb-select { max-width: 100%; border: 1px solid #334155; border-radius: .5rem; background: #0f172a; padding: .65rem .75rem; color: #cbd5e1; font-size: .875rem; }
.kb-select:focus-visible { outline: 2px solid #60a5fa; outline-offset: 2px; }
</style>

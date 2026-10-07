<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { kb, kindNames, stateNames, titleOf, type KRecord, type KnowledgeKind } from '@/knowledge'
import KnowledgePageEditor from '@/components/KnowledgePageEditor.vue'
import KnowledgeMarkdown from '@/components/KnowledgeMarkdown.vue'
import KnowledgeResource from '@/components/KnowledgeResource.vue'
import KnowledgeForm from '@/components/KnowledgeForm.vue'
import KnowledgeProjectTree from '@/components/KnowledgeProjectTree.vue'
import KnowledgeConnections from '@/components/KnowledgeConnections.vue'
import KnowledgeSearch from '@/components/KnowledgeSearch.vue'
import KnowledgeClassification from '@/components/KnowledgeClassification.vue'
import { rememberVisit } from '@/knowledge-state'
import { useKnowledgeDraft } from '@/knowledge-draft'
const route = useRoute(), router = useRouter()
const record = ref<KRecord | null>(null), overview = ref<KRecord | null>(null), related = ref<KRecord[]>([]), lookup = ref<Record<string, KRecord>>({}), children = ref<KRecord[]>([]), busy = ref(true), error = ref('')
const form = ref<KnowledgeKind | null>(null), editing = ref(false), history = ref<Awaited<ReturnType<typeof kb.history>> | null>(null), historyOpen = ref(false)
const classificationOpen = ref(false), childDomain = ref(false)
const locations = computed(() => byKind('placement').filter(p => p.data.entity_id === record.value?.id))
const byKind = (kind: KnowledgeKind) => related.value.filter(r => r.kind === kind && r.status !== 'archived' && r.status !== 'merged')
const historical = computed(() => !!record.value && record.value.revision !== record.value.current_revision)
const contextRecord = computed(() => record.value && ['project', 'question'].includes(record.value.kind))
const pageRecord = computed(() => record.value?.kind === 'page' ? record.value : overview.value)
const libraryViews: Record<string, string> = { projects: '项目', questions: '问题总览', domains: '领域目录', knowledge: '知识索引', pages: '文档', sources: '资料', search: '搜索结果' }
const browsingView = computed(() => {
  const from = typeof route.query.from === 'string' ? route.query.from : ''
  if (Object.keys(libraryViews).includes(from)) return from
  const kind = record.value?.kind
  return kind === 'project' ? 'projects' : kind === 'question' ? 'questions' : kind === 'page' ? 'pages' : kind === 'source' ? 'sources' : 'domains'
})
const childGroups = computed(() => [
  { label: '子领域', items: children.value.filter(child => lookup.value[child.data.entity_id]?.data.entity_kind === 'topic') },
  { label: '本领域的知识', items: children.value.filter(child => lookup.value[child.data.entity_id]?.data.entity_kind !== 'topic') },
].filter(group => group.items.length))
const linkedContexts = computed<string[]>(() => record.value?.kind === 'page'
  ? (record.value.data.bindings || []).map((binding: { target_id: string }) => binding.target_id)
  : record.value?.kind === 'source' ? record.value.data.context_ids || [] : [])
function detailLink(id: string) {
  return { path: `/knowledge/${id}`, query: { from: browsingView.value, ...(browsingView.value === 'search' ? { q: route.query.q, category: route.query.category, offset: route.query.offset } : {}) } }
}
const returnQuery = computed(() => ({ view: browsingView.value, ...(browsingView.value === 'search' ? { q: route.query.q, category: route.query.category, offset: route.query.offset } : {}) }))
const note = ref(''), savingNote = ref(false)
useKnowledgeDraft(() => !!record.value && note.value !== (record.value.data.personal_note || ''))
let generation = 0
async function load() {
  const current = ++generation; busy.value = true; error.value = ''; history.value = null; historyOpen.value = false
  try {
    const id = String(route.params.id)
    const [root, links] = await Promise.all([kb.get(id, route.query.revision ? Number(route.query.revision) : undefined), kb.backlinks(id)])
    if (current !== generation) return
    record.value = root; related.value = links.items; note.value = root.data.personal_note || ''
    overview.value = root.overview_page_id ? await kb.get(root.overview_page_id) : null
    const ids = new Set<string>()
    linkedContexts.value.forEach(id => ids.add(id))
    for (const item of [root, ...links.items]) for (const key of ['project_id', 'context_id', 'knowledge_id', 'subject_id', 'predicate_id', 'object_entity_id', 'entity_id', 'merged_into_id', 'deliverable_id', 'criteria_page_id', 'reproduction_page_id']) if (item.data[key]) ids.add(item.data[key])
    const locations = root.kind === 'entity' ? byKind('placement').filter(p => p.data.entity_id === root.id) : []
    const childLists = await Promise.all(locations.map(p => kb.query('placement', { parent_id: p.id })))
    children.value = childLists.flatMap(r => r.items)
    children.value.forEach(p => ids.add(p.data.entity_id))
    const values = await Promise.all([...ids].map(id => kb.get(id)))
    if (current !== generation) return
    lookup.value = Object.fromEntries(values.map(value => [value.id, value]))
    if (!route.query.revision && ['project', 'question', 'entity', 'page'].includes(root.kind)) rememberVisit(root.id)
  } catch (e) { if (current === generation) error.value = String(e) } finally { if (current === generation) busy.value = false }
}
watch(() => [route.params.id, route.query.revision], load, { immediate: true })
function open(kind: KnowledgeKind, edit = false) { editing.value = edit; childDomain.value = false; form.value = kind }
function newChild() { open('entity'); childDomain.value = true }
async function saved(value: KRecord) {
  form.value = null
  if (value.kind === 'question' || (value.kind === 'entity' && !contextRecord.value)) await router.push(detailLink(value.id))
  else await load()
}
async function showHistory() { historyOpen.value = !historyOpen.value; if (historyOpen.value && record.value) history.value = await kb.history(record.value.id) }
async function saveNote() {
  if (!record.value) return
  savingNote.value = true; error.value = ''
  try { record.value = await kb.update(record.value, { ...record.value.data, personal_note: note.value }, '更新个人认知'); }
  catch (e) { error.value = String(e) } finally { savingNote.value = false }
}
const name = (id: string) => lookup.value[id] ? titleOf(lookup.value[id]) : '查看关联记录'
function formPreset(): Record<string, any> | undefined {
  if (form.value === 'placement' && record.value?.kind === 'entity') return { entity_id: record.value.id }
  if (form.value === 'entity' && !editing.value) return { entity_kind: childDomain.value ? 'topic' : 'concept' }
  return undefined
}
</script>
<template>
  <div class="mx-auto max-w-6xl space-y-6">
    <div class="flex flex-wrap items-center gap-4">
    <nav aria-label="浏览位置" class="flex min-w-0 flex-1 flex-wrap items-center gap-2 text-sm text-slate-400">
      <router-link to="/knowledge" class="hover:text-white">知识库</router-link><span aria-hidden="true">/</span>
      <router-link :to="{ path: '/knowledge', query: returnQuery }" class="hover:text-white">{{ libraryViews[browsingView] }}</router-link>
    </nav>
    <KnowledgeSearch class="w-full sm:w-72" />
    </div>
    <p v-if="error" role="alert" class="rounded-xl border border-rose-500/20 bg-rose-950/30 p-4 text-sm text-rose-300">{{ error }} <button class="underline" @click="load">重新读取</button></p>
    <div v-if="busy" class="py-20 text-center text-slate-500">读取正文与关联记录…</div>
    <template v-else-if="record">
      <header class="border-b border-slate-700/70 pb-5">
        <div class="flex flex-wrap items-center gap-3 text-xs"><span class="rounded-md bg-indigo-400/10 px-2 py-1 text-indigo-300">{{ record.data.entity_kind === 'topic' ? '领域' : kindNames[record.kind] }}</span><span class="text-slate-400">{{ stateNames[record.status] || record.status }}</span><span v-if="['entity','relation'].includes(record.kind)" class="text-amber-300/80">{{ stateNames[record.review_state] }}</span></div>
        <h1 class="mt-3 break-words text-2xl font-semibold leading-snug text-slate-100">{{ titleOf(record) }}</h1>
        <p v-if="record.data.summary" class="mt-3 max-w-3xl text-sm leading-7 text-slate-300">{{ record.data.summary }}</p>
        <router-link v-if="record.data.project_id" :to="detailLink(record.data.project_id)" class="mt-4 inline-block text-sm text-blue-300">所属项目：{{ name(record.data.project_id) }}</router-link>
        <div class="mt-4 flex flex-wrap items-center gap-3 text-sm"><button v-if="!historical && record.kind !== 'review' && record.kind !== 'acceptance'" class="rounded-lg border border-slate-600 px-3 py-2 text-slate-300" @click="open(record.kind, true)">编辑{{ record.data.entity_kind === 'topic' ? '领域' : kindNames[record.kind] }}</button><button v-if="record.kind === 'entity'" class="rounded-lg border border-slate-700 px-3 py-2 text-slate-400" @click="classificationOpen = true">调整分类</button><button v-if="record.kind === 'project'" class="rounded-lg border border-slate-700 px-3 py-2 text-slate-400" @click="open('usage')">引用知识</button><details class="relative"><summary class="cursor-pointer list-none rounded-lg px-3 py-2 text-slate-500 hover:bg-slate-800">更多 ···</summary><div class="absolute left-0 z-20 mt-2 w-44 space-y-1 rounded-xl border border-slate-600 bg-slate-800 p-2 shadow-xl"><button class="block w-full rounded px-3 py-2 text-left text-slate-300 hover:bg-slate-700" @click="showHistory">版本记录 · v{{ record.revision }}</button><button v-if="!['review','acceptance','placement','usage'].includes(record.kind)" class="block w-full rounded px-3 py-2 text-left text-amber-200 hover:bg-slate-700" @click="open('review')">提出核对问题</button></div></details></div>
      </header>
      <router-link v-if="historical" :to="detailLink(record.id)" class="block rounded-lg bg-indigo-950/40 p-4 text-sm text-indigo-200">正在查看历史 v{{ record.revision }}，当前是 v{{ record.current_revision }}。打开当前版本 →</router-link>
      <div v-for="warning in record.warnings" :key="warning" class="rounded-lg border border-amber-500/25 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">{{ warning }}</div>
      <router-link v-if="record.data.merged_into_id" :to="`/knowledge/${record.data.merged_into_id}`" class="block rounded-lg bg-indigo-950/40 p-4 text-indigo-200">此记录已合并。打开：{{ name(record.data.merged_into_id) }} →</router-link>
      <KnowledgeConnections v-if="record.kind === 'entity' || record.kind === 'relation'" :key="record.id + ':' + record.revision" :record-id="record.id" :historical="historical" />
      <section v-if="historyOpen && history" class="rounded-xl border border-slate-700 p-5"><h2 class="mb-4 font-semibold text-slate-200">版本记录 · 共 {{ history.total }} 版</h2><details v-for="version in history.items" :key="version.revision" class="border-t border-slate-700 py-4"><summary class="cursor-pointer text-sm text-slate-400">v{{ version.revision }} · {{ new Date(version.created_at).toLocaleString() }} · {{ version.reason || '保存内容' }}</summary><KnowledgeMarkdown v-if="version.data.body_md" class="mt-4" :body="version.data.body_md" /><pre v-else class="mt-4 overflow-auto whitespace-pre-wrap break-all text-xs text-slate-400">{{ JSON.stringify(version.data, null, 2) }}</pre></details><button v-if="history.next_offset !== null" class="text-sm text-blue-300" @click="kb.history(record.id, history.next_offset).then(page => { history!.items.push(...page.items); history!.next_offset = page.next_offset })">读取更早版本</button></section>
      <div class="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_19rem]">
        <main class="min-w-0 space-y-6">
          <section v-if="record.kind === 'project'" class="rounded-xl border border-slate-700 p-5"><div class="mb-4 flex items-center justify-between"><h2 class="font-semibold text-slate-200">问题与知识</h2><button class="text-sm text-blue-300" @click="open('question')">＋ 提出问题</button></div><KnowledgeProjectTree :key="record.id + ':' + related.length" :parent-id="record.id" /></section>
          <section v-if="record.kind === 'question'" class="rounded-xl border border-slate-700 p-5">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <h2 class="font-semibold text-slate-200">相关知识</h2>
              <div class="flex gap-4 text-sm text-blue-300"><button @click="open('usage')">引用已有知识</button><button @click="open('entity')">＋ 新知识</button></div>
            </div>

            <article v-for="use in byKind('usage')" :key="use.id" class="mt-4 border-t border-slate-700 pt-4">
              <div class="flex flex-wrap items-start justify-between gap-3 text-sm">
                <router-link :to="detailLink(use.data.knowledge_id)" class="text-indigo-200 hover:underline">{{ name(use.data.knowledge_id) }} →</router-link>
                <span class="text-xs text-slate-500">使用 v{{ use.data.knowledge_revision }} · {{ ({ used: '实际使用', to_research: '准备研究', derived: '研究中形成' } as Record<string,string>)[use.data.role] }}</span>
              </div>
              <p class="mt-2 line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-slate-400">{{ use.data.application_note || '' }}</p>
              <p v-if="use.warnings.length" class="mt-2 text-xs text-amber-300">所引用知识已有变更，请核对当前状态。</p>
              <router-link :to="detailLink(use.id)" class="mt-3 inline-block text-xs text-blue-300">查看本次使用记录 →</router-link>
            </article>
            <p v-if="!byKind('usage').length" class="mt-4 text-sm text-slate-500">暂无关联知识。</p>
          </section>
          <section v-if="record.kind === 'entity' && record.data.entity_kind === 'topic'" class="flex flex-wrap gap-3 text-sm"><template v-if="locations.length"><button class="rounded-lg border border-slate-600 px-3 py-2 text-blue-300" @click="newChild">＋ 子领域</button><button class="rounded-lg border border-slate-600 px-3 py-2 text-blue-300" @click="open('entity')">＋ 本领域知识</button></template><button v-else class="text-blue-300" @click="classificationOpen = true">先设置目录位置，再添加下级内容</button></section>
          <section v-for="group in childGroups" :key="group.label" class="rounded-xl border border-slate-700 p-5">
            <h2 class="mb-4 font-semibold text-slate-200">{{ group.label }}</h2>
            <div class="grid gap-3 sm:grid-cols-2">
              <router-link v-for="child in group.items" :key="child.id" :to="detailLink(child.data.entity_id)" class="rounded-lg bg-slate-900 p-4 text-sm text-indigo-200 hover:bg-slate-800">{{ name(child.data.entity_id) }} →</router-link>
            </div>
          </section>
          <KnowledgePageEditor v-if="['project','question','entity','page'].includes(record.kind)" :owner="record" :page="pageRecord" :readonly="historical" @saved="load" />
          <section v-if="record.kind === 'source'" class="rounded-xl border border-slate-700 p-6"><h2 class="mb-4 font-semibold text-slate-200">出处与保留内容</h2><a v-if="/^https?:\/\//.test(record.data.origin_ref)" :href="record.data.origin_ref" target="_blank" rel="noopener noreferrer" class="break-all text-sm text-blue-300 underline">{{ record.data.origin_ref }}</a><p v-else class="break-all text-sm text-slate-400">{{ record.data.origin_ref || '暂未登记出处' }}</p><p class="my-4 text-xs text-slate-500">保留方式：{{ ({ reference: '仅出处', excerpt: '必要摘录', snapshot: '已保存文本', internal_version: '内部文档固定版本' } as Record<string,string>)[record.data.retention] }}</p><KnowledgeMarkdown v-if="record.data.content_text" :body="record.data.content_text" /><router-link v-if="record.data.page_id" :to="`/knowledge/${record.data.page_id}?revision=${record.data.page_revision}`" class="text-blue-300">引用文档 · v{{ record.data.page_revision }}</router-link></section>
          <section v-if="record.kind === 'relation'" class="rounded-xl border border-slate-700 p-6"><h2 class="mb-4 font-semibold text-slate-200">结构化陈述</h2><div class="flex flex-wrap gap-3 text-sm"><router-link :to="`/knowledge/${record.data.subject_id}`" class="text-blue-300">{{ name(record.data.subject_id) }}</router-link><span class="text-slate-500">→ {{ name(record.data.predicate_id) }} →</span><router-link v-if="record.data.object_entity_id" :to="`/knowledge/${record.data.object_entity_id}`" class="text-blue-300">{{ name(record.data.object_entity_id) }}</router-link><span v-else class="text-slate-200">{{ record.data.object_value?.value }}</span></div><KnowledgeMarkdown class="mt-5" :body="record.data.statement_md" /><p class="mt-4 text-sm text-amber-200">{{ record.data.perspective === 'personal' ? '个人实践结论' : record.data.perspective === 'general' ? '通用结论（仍需依据）' : '适用范围尚未判断' }}</p><div v-for="e in record.data.evidence" :key="e.source_id + e.locator" class="mt-5 rounded-lg bg-slate-900 p-4"><router-link :to="`/knowledge/${e.source_id}?revision=${e.source_revision}`" class="text-xs text-blue-300">证据来源 · v{{ e.source_revision }} · {{ e.locator }}</router-link><blockquote class="mt-2 text-sm text-slate-400">{{ e.quote }}</blockquote><p class="mt-2 text-xs text-slate-500">{{ e.role === 'supports' ? '支持' : e.role === 'refutes' ? '反驳' : '背景参考' }}</p></div></section>
          <section v-if="record.kind === 'usage'" class="rounded-xl border border-slate-700 p-6"><h2 class="font-semibold text-slate-200">这次如何使用知识</h2><router-link :to="`/knowledge/${record.data.knowledge_id}?revision=${record.data.knowledge_revision}`" class="mt-4 block text-blue-300">{{ name(record.data.knowledge_id) }} · 使用 v{{ record.data.knowledge_revision }}</router-link><KnowledgeMarkdown class="mt-4" :body="record.data.application_note" /><router-link v-if="record.data.page_id" :to="`/knowledge/${record.data.page_id}?revision=${record.data.page_revision}`" class="mt-4 block text-sm text-blue-300">使用时的说明正文 · v{{ record.data.page_revision }}</router-link><router-link :to="`/knowledge/${record.data.context_id}`" class="mt-5 block text-sm text-slate-400">返回使用场景：{{ name(record.data.context_id) }}</router-link></section>
          <section v-if="record.kind === 'deliverable'" class="space-y-5 rounded-xl border border-slate-700 p-6"><div class="flex items-center justify-between"><h2 class="font-semibold text-slate-200">真实成果</h2><span class="text-xs text-slate-500">{{ record.data.format }}</span></div><KnowledgeResource :resource="record.data.resource_ref" :label="titleOf(record) + (record.data.format ? '.' + record.data.format : '')" /><div class="grid gap-3 sm:grid-cols-2"><KnowledgeResource v-for="(preview, index) in record.data.preview_refs" :key="preview" :resource="preview" preview :label="'预览 ' + (index + 1)" /></div><router-link v-if="record.data.reproduction_page_id" :to="`/knowledge/${record.data.reproduction_page_id}?revision=${record.data.reproduction_page_revision}`" class="block text-sm text-blue-300">复现说明 · v{{ record.data.reproduction_page_revision }}</router-link><button class="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white" @click="open('acceptance')">记录检查与验收</button><div v-for="item in byKind('acceptance')" :key="item.id" class="rounded-lg bg-slate-900 p-4"><div class="flex flex-wrap gap-2 text-sm"><span :class="item.data.state === 'accepted' ? 'text-emerald-300' : 'text-amber-200'">{{ stateNames[item.data.state] }}</span><span class="text-slate-500">成果 v{{ item.data.deliverable_revision }}{{ item.data.deliverable_revision !== record.revision ? '（历史版本）' : '' }}</span></div><p class="mt-2 whitespace-pre-wrap text-sm text-slate-400">{{ item.data.checks }}</p><p class="mt-2 text-sm text-slate-500">{{ item.data.note }}</p></div></section>
          <section v-if="record.kind === 'entity' && (record.data.entity_kind !== 'topic' || byKind('relation').length)" class="rounded-xl border border-slate-700 p-5"><div class="flex justify-between gap-3"><h2 class="font-semibold text-slate-200">知识关系</h2><div class="flex gap-4 text-sm text-blue-300"><button @click="open('predicate')">定义关系类型</button><button @click="open('relation')">＋ 建立关系</button></div></div><router-link v-for="relation in byKind('relation')" :key="relation.id" :to="`/knowledge/${relation.id}`" class="mt-4 block rounded-lg bg-slate-900 p-4 text-sm text-slate-300">{{ relation.data.statement_md || name(relation.data.subject_id) + ' → ' + name(relation.data.predicate_id) }}<span class="mt-2 block text-xs text-amber-200/70">{{ stateNames[relation.review_state] }}</span></router-link><p v-if="!byKind('relation').length" class="mt-5 text-sm text-slate-500">暂无关联。</p></section>
          <section v-if="contextRecord" class="rounded-xl border border-slate-700 p-5"><div class="flex items-center justify-between"><h2 class="font-semibold text-slate-200">成果与交付</h2><button class="text-sm text-blue-300" @click="open('deliverable')">＋ 登记成果</button></div><router-link v-for="output in byKind('deliverable')" :key="output.id" :to="`/knowledge/${output.id}`" class="mt-4 flex items-center justify-between rounded-lg bg-slate-900 p-4 text-sm"><span class="text-slate-200">{{ titleOf(output) }}</span><span class="text-xs text-slate-500">v{{ output.revision }} →</span></router-link><p v-if="!byKind('deliverable').length" class="mt-5 text-sm text-slate-500">暂无成果。</p></section>
        </main>
        <aside class="min-w-0 space-y-5">
          <section v-if="record.kind === 'entity'" class="rounded-xl border border-slate-700 bg-slate-800/30 p-5"><h2 class="mb-3 text-sm font-semibold text-slate-200">我的理解与疑问</h2><textarea v-model="note" aria-label="我的理解与疑问" rows="5" placeholder="已经理解什么？哪些仍不确定？" class="w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm text-slate-300" /><button class="mt-3 text-sm text-blue-300 disabled:opacity-50" :disabled="savingNote" @click="saveNote">保存认知</button></section>
          <section v-if="['project','question','entity'].includes(record.kind)" class="rounded-xl border border-slate-700 bg-slate-800/20 p-5">
            <h2 class="text-sm font-semibold text-slate-200">文档与资料</h2>
            <div class="mt-4">
              <div class="flex items-center justify-between"><h3 class="text-xs font-medium text-slate-400">补充文档</h3><button aria-label="添加补充文档" class="text-sm text-blue-300" @click="open('page')">＋</button></div>
              <router-link v-for="page in byKind('page').filter(p => p.id !== overview?.id)" :key="page.id" :to="detailLink(page.id)" class="mt-3 block text-sm text-slate-400 hover:text-blue-300">{{ titleOf(page) }}</router-link>
              <p v-if="!byKind('page').some(p => p.id !== overview?.id)" class="mt-3 text-xs leading-6 text-slate-500">暂无补充文档。</p>
            </div>
            <div class="mt-5 border-t border-slate-700 pt-4">
              <div class="flex items-center justify-between"><h3 class="text-xs font-medium text-slate-400">参考资料</h3><button aria-label="添加参考资料" class="text-sm text-blue-300" @click="open('source')">＋</button></div>
              <router-link v-for="source in byKind('source')" :key="source.id" :to="detailLink(source.id)" class="mt-3 block text-sm text-slate-400 hover:text-blue-300">{{ titleOf(source) }}</router-link>
              <p v-if="!byKind('source').length" class="mt-3 text-xs leading-6 text-slate-500">暂无参考资料。</p>
            </div>
          </section>
          <section v-if="linkedContexts.length" class="rounded-xl border border-slate-700 p-5">
            <h2 class="text-sm font-semibold text-slate-200">关联的项目、问题与知识</h2>
            <router-link v-for="id in linkedContexts" :key="id" :to="detailLink(id)" class="mt-4 block text-sm text-indigo-300">{{ name(id) }} →</router-link>
          </section>
          <section v-if="byKind('review').length" class="rounded-xl border border-amber-400/20 bg-amber-950/10 p-5"><h2 class="text-sm font-semibold text-amber-200">相关核对记录</h2><router-link v-for="issue in byKind('review')" :key="issue.id" :to="`/knowledge/review?issue=${issue.id}`" class="mt-4 block text-sm text-slate-400">{{ titleOf(issue) }}<span class="mt-1 block text-xs text-slate-500">{{ stateNames[issue.status] }}</span></router-link></section>
          <details class="px-1 text-xs text-slate-500"><summary class="cursor-pointer">记录信息</summary><p class="mt-2 break-all text-[11px] leading-5">ID · {{ record.id }}</p></details>
        </aside>
      </div>
      <KnowledgeClassification v-if="classificationOpen && record.kind === 'entity'" :owner="record" @close="classificationOpen = false" @saved="classificationOpen = false; load()" />
      <KnowledgeForm v-if="form" :kind="form" :context="editing ? undefined : record" :record="editing ? record : undefined" :preset="formPreset()" :placement-parent-id="!editing && form === 'entity' && record.data.entity_kind === 'topic' && locations.length === 1 ? locations[0].id : undefined" :require-parent="!editing && form === 'entity' && record.data.entity_kind === 'topic'" @saved="saved" @close="form = null" />
    </template>
  </div>
</template>

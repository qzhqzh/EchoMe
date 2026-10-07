<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { kb, titleOf, stateNames, issueNames, type KRecord } from '@/knowledge'
import KnowledgeMarkdown from '@/components/KnowledgeMarkdown.vue'
const route = useRoute()
const router = useRouter()
const items = ref<KRecord[]>([]), index = ref(0), targets = ref<KRecord[]>([]), impacts = ref<Record<string, KRecord[]>>({}), loading = ref(true), busy = ref(false), error = ref(''), note = ref(''), reviewKey = ref(''), confirmAction = ref(''), allStatuses = ref(false)
const current = computed(() => items.value[index.value])
const stale = computed(() => !['resolved', 'dismissed'].includes(current.value?.status || '') && targets.value.some(t => t.current_revision !== t.revision))
const actions: Record<string, string> = { apply: '采纳建议', keep_distinct: '保留各自含义', request_evidence: '需要补充依据', dispute: '保留争议', snooze: '稍后处理', dismiss: '忽略此问题', reopen: '重新打开' }
let generation = 0
async function load() {
  loading.value = true; error.value = ''
  try {
    const all: KRecord[] = []; let offset: number | null = 0
    while (offset !== null) { const page = await kb.list('review', { limit: 100, offset }); all.push(...page.items); offset = page.next_offset }
    items.value = all.filter(i => allStatuses.value || ['open', 'disputed'].includes(i.status))
    if (route.query.issue) { const requested = all.find(i => i.id === route.query.issue); if (requested && !items.value.includes(requested)) items.value.unshift(requested) }
    index.value = Math.max(0, items.value.findIndex(i => i.id === route.query.issue))
  } catch (e) { error.value = String(e) } finally { loading.value = false }
}
watch(allStatuses, load, { immediate: true })
watch(current, async value => {
  const seq = ++generation; targets.value = []; impacts.value = {}; note.value = ''; confirmAction.value = ''; error.value = ''
  if (!value) return
  try {
    const records = await Promise.all(value.data.targets.map((t: { id: string; revision: number }) => kb.get(t.id, t.revision)))
    const linked = await Promise.all(records.map((r: KRecord) => kb.backlinks(r.id)))
    if (seq !== generation) return
    targets.value = records; impacts.value = Object.fromEntries(records.map((r: KRecord, i: number) => [r.id, linked[i].items.filter(item => item.kind !== 'review')]))
  } catch (e) { if (seq === generation) error.value = String(e) }
})
async function decide() {
  if (!current.value) return
  busy.value = true; error.value = ''
  try {
    const id = current.value.id
    await api.knowledge('POST', `/reviews/${id}/decisions`, { expected_revision: current.value.revision, action: confirmAction.value, note: note.value }, undefined, reviewKey.value)
    confirmAction.value = ''
    if (!allStatuses.value) await router.replace('/knowledge/review')
    await load()
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
let touchX = 0, touchY = 0
function touchEnd(event: TouchEvent) {
  const dx = event.changedTouches[0].clientX - touchX, dy = event.changedTouches[0].clientY - touchY
  if (Math.abs(dx) > 90 && Math.abs(dx) > Math.abs(dy) * 1.8) index.value = Math.max(0, Math.min(items.value.length - 1, index.value + (dx < 0 ? 1 : -1)))
}
</script>
<template>
  <div class="mx-auto max-w-5xl space-y-6">
    <router-link to="/knowledge" class="text-sm text-slate-400">← 知识库</router-link>
    <header class="flex flex-wrap items-end justify-between gap-4"><div><p class="mb-3 text-xs uppercase tracking-[.2em] text-amber-300">Knowledge review</p><h1 class="text-3xl font-bold text-white">一起核对知识</h1><p class="mt-3 text-sm leading-7 text-slate-400">AI 提出具体疑点，你结合依据作决定。左右滑动只切换卡片。</p></div><label class="flex items-center gap-2 text-xs text-slate-400"><input v-model="allStatuses" type="checkbox" />包括稍后与已处理</label></header>
    <p v-if="error" role="alert" class="rounded-lg bg-rose-950/30 p-4 text-sm text-rose-300">{{ error }}</p>
    <div v-if="loading" class="py-20 text-center text-slate-500">读取审核卡片…</div>
    <div v-else-if="!current" class="rounded-2xl border border-dashed border-slate-700 py-24 text-center"><h2 class="text-xl text-slate-200">当前没有待核对的问题</h2><p class="mt-3 text-sm text-slate-500">同名候选或 AI 提出的风险会出现在这里。</p></div>
    <template v-else>
      <div class="flex items-center justify-between text-sm"><button :disabled="index === 0" class="px-3 py-2 text-slate-400 disabled:opacity-25" @click="index--">← 上一张</button><span class="text-slate-500">{{ index + 1 }} / {{ items.length }}</span><button :disabled="index >= items.length - 1" class="px-3 py-2 text-slate-400 disabled:opacity-25" @click="index++">下一张 →</button></div>
      <article class="overflow-hidden rounded-2xl border border-amber-400/25 bg-slate-800/50" style="touch-action: pan-y" @touchstart.passive="touchX = $event.touches[0].clientX; touchY = $event.touches[0].clientY" @touchend.passive="touchEnd">
        <header class="border-b border-slate-700 p-5 sm:p-7"><div class="flex justify-between gap-3 text-xs"><span class="rounded-md bg-amber-400/10 px-2 py-1 text-amber-200">{{ issueNames[current.data.issue_kind] }}</span><span class="text-slate-500">{{ stateNames[current.status] }} · v{{ current.revision }}</span></div><h2 class="mt-4 text-xl font-semibold text-white">{{ titleOf(current) }}</h2><p class="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-300">{{ current.data.explanation }}</p></header>
        <div class="grid gap-4 p-5 sm:p-7" :class="targets.length > 1 ? 'md:grid-cols-2' : ''"><section v-for="target in targets" :key="target.id" class="min-w-0 rounded-xl border border-slate-700 bg-slate-900 p-5"><router-link :to="`/knowledge/${target.id}`" class="font-medium text-indigo-200">{{ titleOf(target) }} ↗</router-link><p class="mt-2 text-xs text-slate-500">提案基于 v{{ target.revision }} · 当前 v{{ target.current_revision }}</p><KnowledgeMarkdown class="mt-4 text-sm" :body="target.data.body_md || target.data.statement_md || target.data.summary || target.data.personal_note || '暂无详细说明，需补充依据后判断。'" /><div v-for="evidence in target.data.evidence || []" :key="evidence.source_id + evidence.locator" class="mt-4 rounded-lg border border-slate-700 p-3"><router-link :to="`/knowledge/${evidence.source_id}?revision=${evidence.source_revision}`" class="text-xs text-blue-300">证据 · v{{ evidence.source_revision }} · {{ evidence.locator }} ↗</router-link><p class="mt-2 text-sm text-slate-300">{{ evidence.quote || '仅登记定位，尚无留存引文' }}</p></div><div v-if="target.data.qualifiers && Object.keys(target.data.qualifiers).length" class="mt-4 text-xs text-slate-400">适用条件：{{ target.data.qualifiers }}</div><div class="mt-5 border-t border-slate-700 pt-4"><p class="text-xs text-slate-500">影响 {{ impacts[target.id]?.length || 0 }} 条当前关联记录</p><router-link v-for="impact in (impacts[target.id] || []).slice(0, 6)" :key="impact.id" :to="`/knowledge/${impact.id}`" class="mt-2 block text-xs text-blue-300">{{ titleOf(impact) }}</router-link></div></section></div>
        <section class="border-t border-slate-700 px-5 py-5 sm:px-7"><h3 class="text-sm font-semibold text-slate-200">建议处理</h3><p class="mt-3 text-sm leading-7 text-slate-400">{{ ({ none: '保留记录，先讨论或补充证据。', merge: '合并重复实体。原 ID 和历史引用继续保留，并指向保留的知识。', archive: '确认此内容有误后归档，立即停止默认检索与新复用；历史使用保留警示。', verify: '核对所指的内容版本。以后修改正文或结论需要重新核对。', update: '按下面的具体差异修订，并保留旧版本。' } as Record<string,string>)[current.data.proposal.operation] }}</p><div v-if="current.data.proposal.patch && Object.keys(current.data.proposal.patch).length" class="mt-3 space-y-3"><div v-for="(value, field) in current.data.proposal.patch" :key="field" class="rounded-lg bg-slate-900 p-3"><p class="text-xs text-slate-500">{{ field }}</p><p class="mt-2 whitespace-pre-wrap text-sm text-rose-300 line-through">{{ targets.find(t => t.id === current.data.proposal.target_id)?.data[field] }}</p><p class="mt-2 whitespace-pre-wrap text-sm text-emerald-200">{{ value }}</p></div></div><p v-if="stale" class="mt-4 rounded-lg bg-amber-950/30 p-3 text-sm text-amber-300">内容已有新版本，当前提案不能直接采纳。请重新核对并针对新版本提出处理方案。</p></section>
      </article>
      <div class="rounded-xl border border-slate-700 bg-slate-900 p-5"><label class="block text-sm text-slate-300">判断依据或下一步<textarea v-model="note" rows="3" class="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 p-3 text-sm" placeholder="例如：适用版本不同，应保留为两条知识。" /></label><div class="mt-5 flex flex-wrap gap-3"><button v-if="current.data.proposal.operation !== 'none' && !['resolved','dismissed'].includes(current.status)" :disabled="stale || !targets.length" class="rounded-lg bg-indigo-600 px-4 py-2.5 text-sm text-white disabled:opacity-30" @click="confirmAction = 'apply'">采纳建议</button><button v-for="action in (['resolved','dismissed'].includes(current.status) ? ['reopen'] : ['keep_distinct','request_evidence','dispute','snooze','dismiss'])" :key="action" class="rounded-lg border border-slate-600 px-3 py-2.5 text-sm text-slate-300" @click="confirmAction = action">{{ actions[action] }}</button></div></div>
      <section v-if="confirmAction" role="dialog" aria-label="确认审核决定" class="rounded-xl border border-amber-400/40 bg-amber-950/10 p-5"><h3 class="font-medium text-amber-200">确认：{{ actions[confirmAction] }}</h3><p class="mt-2 text-sm leading-6 text-slate-400">此操作会留下版本和判断记录。独立审核凭据仅保存在当前页面内存中，刷新后清除。</p><label class="mt-4 block text-sm text-slate-300">审核凭据<input v-model="reviewKey" type="password" autocomplete="off" class="mt-2 w-full rounded-lg border border-slate-600 bg-slate-950 p-3" /></label><div class="mt-4 flex gap-3"><button :disabled="busy || !reviewKey" class="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-50" @click="decide">{{ busy ? '保存决定…' : '确认并保存' }}</button><button class="px-3 text-sm text-slate-400" @click="confirmAction = ''">取消</button></div></section>
    </template>
  </div>
</template>

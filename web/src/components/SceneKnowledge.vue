<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useI18n } from '@/i18n'
import { useToast } from '@/stores/toast'
import type { SceneCategory, SceneKnowledge, SceneKnowledgeDetail, SceneKnowledgeEntry, SceneSopValidation } from '@/types'

const { locale } = useI18n()
const { success, error } = useToast()
const tr = (cn: string, en: string) => locale.value === 'zh' ? cn : en
const labels: Record<SceneCategory, [string, string]> = {
  fact: ['事实', 'Facts'], observation: ['历史观测', 'Observations'],
  sop: ['已验证 SOP', 'Validated SOPs'], caution: ['注意事项', 'Cautions'],
  work: ['进行中', 'Current work'],
}
const order: SceneCategory[] = ['fact', 'observation', 'sop', 'caution', 'work']

const scenes = ref<SceneKnowledge[]>([])
const selected = ref<SceneKnowledgeDetail | null>(null)
const search = ref('')
const loading = ref(false)
const saving = ref(false)
const includeArchived = ref(false)
const documentOpen = ref(false)
const createOpen = ref(false)
const addOpen = ref(false)
const sopOpen = ref(false)
const editing = ref<SceneKnowledgeEntry | null>(null)
const history = ref<Array<{ revision: number; reason: string; snapshot: SceneKnowledgeEntry; created_at: string }>>([])
const historyEntry = ref<string | null>(null)

const sceneForm = ref({ slug: '', title: '', summary: '', aliases: '', project_id: '' })
const entryForm = ref({ category: 'fact' as Exclude<SceneCategory, 'sop'>,
  content: '', source_ref: '', evidence_at: '', status: 'active' as 'active' | 'needs_review' })
const editForm = ref({ content: '', source_ref: '', evidence_at: '', reason: '',
  status: 'active' as 'active' | 'needs_review' | 'archived' })
const sopForm = ref({ content: '', source_ref: '', candidate_entry_id: '' })
const validationRows = ref<Array<{ executed_at: string; session_id: string; conditions: string; observed_result: string; evidence_ref: string }>>([
  { executed_at: '', session_id: '', conditions: '', observed_result: '', evidence_ref: '' },
  { executed_at: '', session_id: '', conditions: '', observed_result: '', evidence_ref: '' },
  { executed_at: '', session_id: '', conditions: '', observed_result: '', evidence_ref: '' },
])

const grouped = computed(() => Object.fromEntries(order.map(category => [category,
  selected.value?.entries.filter(entry => entry.category === category) || [],
])) as Record<SceneCategory, SceneKnowledgeEntry[]>)

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try {
    const result = await api.listSceneKnowledge(search.value.trim() || undefined)
    scenes.value = result.items
    const slug = selected.value?.scene.slug
    if (slug && scenes.value.some(scene => scene.slug === slug)) await open(slug)
    else if (scenes.value.length) await open(scenes.value[0].slug)
    else selected.value = null
  } catch {
    // The API client reports request failures.
  } finally {
    loading.value = false
  }
}

async function open(selector: string): Promise<void> {
  selected.value = await api.getSceneKnowledge(selector, includeArchived.value)
  editing.value = null
  historyEntry.value = null
}

async function saveScene(): Promise<void> {
  saving.value = true
  try {
    const result = await api.createSceneKnowledge({
      slug: sceneForm.value.slug.trim(), title: sceneForm.value.title.trim(),
      summary: sceneForm.value.summary.trim(),
      aliases: sceneForm.value.aliases.split(',').map(value => value.trim()).filter(Boolean),
      project_id: sceneForm.value.project_id.trim() || null,
    })
    createOpen.value = false
    sceneForm.value = { slug: '', title: '', summary: '', aliases: '', project_id: '' }
    success(tr('场景资料已创建', 'Scene knowledge created'))
    await load()
    await open(result.scene.slug)
  } catch {
    // The API client reports request failures.
  } finally {
    saving.value = false
  }
}

function iso(value: string): string | null {
  return value ? new Date(value).toISOString() : null
}

async function addEntry(): Promise<void> {
  if (!selected.value) return
  saving.value = true
  try {
    await api.addSceneEntry(selected.value.scene.slug, {
      category: entryForm.value.category, content: entryForm.value.content.trim(),
      source_ref: entryForm.value.source_ref.trim(), evidence_at: iso(entryForm.value.evidence_at),
      status: entryForm.value.status,
    })
    addOpen.value = false
    entryForm.value = { category: 'fact', content: '', source_ref: '', evidence_at: '', status: 'active' }
    await open(selected.value.scene.slug)
    success(tr('条目已保存', 'Entry saved'))
  } catch {
    // The API client reports request failures.
  } finally {
    saving.value = false
  }
}

function beginEdit(entry: SceneKnowledgeEntry): void {
  editing.value = entry
  editForm.value = { content: entry.content, source_ref: entry.source_ref,
    evidence_at: '', reason: '', status: entry.status }
}

async function correctEntry(): Promise<void> {
  if (!selected.value || !editing.value) return
  saving.value = true
  try {
    const original = editing.value
    const changedContent = editForm.value.content.trim() !== original.content
    const changedStatus = editForm.value.status !== original.status
    const evidenceAt = iso(editForm.value.evidence_at)
    if (!changedContent && !changedStatus && !evidenceAt) {
      error(tr('请先修改内容、状态或证据时间', 'Change content, status, or evidence time first'))
      return
    }
    await api.correctSceneEntry(selected.value.scene.slug, original.id, {
      expected_revision: original.revision, reason: editForm.value.reason.trim(),
      source_ref: editForm.value.source_ref.trim(),
      ...(changedContent ? { content: editForm.value.content.trim() } : {}),
      ...(changedStatus ? { status: editForm.value.status } : {}),
      ...(evidenceAt ? { evidence_at: evidenceAt } : {}),
    })
    const slug = selected.value.scene.slug
    await open(slug)
    success(tr('校正已保存，历史版本可查看', 'Correction saved with history'))
  } catch {
    if (selected.value) await open(selected.value.scene.slug).catch(() => undefined)
  } finally {
    saving.value = false
  }
}

async function showHistory(entry: SceneKnowledgeEntry): Promise<void> {
  if (!selected.value) return
  const result = await api.sceneEntryHistory(selected.value.scene.slug, entry.id)
  history.value = result.items
  historyEntry.value = entry.id
}

async function publishSop(): Promise<void> {
  if (!selected.value) return
  saving.value = true
  try {
    const validations: SceneSopValidation[] = validationRows.value.map(row => ({
      executed_at: new Date(row.executed_at).toISOString(),
      session_id: row.session_id.trim(), conditions: row.conditions.trim(),
      observed_result: row.observed_result.trim(), evidence_ref: row.evidence_ref.trim(),
      result: 'effective',
    }))
    await api.publishSceneSop(selected.value.scene.slug, {
      content: sopForm.value.content.trim(), source_ref: sopForm.value.source_ref.trim(),
      validations, candidate_entry_id: sopForm.value.candidate_entry_id || null,
    })
    sopOpen.value = false
    await open(selected.value.scene.slug)
    success(tr('已保存正式 SOP', 'Validated SOP saved'))
  } catch (err) {
    if (err instanceof RangeError) error(tr('请填写每次实测的时间', 'Enter every validation time'))
  } finally {
    saving.value = false
  }
}

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US',
    { timeZoneName: 'short' }) : '—'
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center justify-between gap-3">
      <p class="text-sm text-slate-400">{{ tr('每条知识独立保存；仅反复验证有效的方法进入 SOP。',
        'Knowledge is stored one item at a time; only repeatedly validated methods enter SOPs.') }}</p>
      <button class="btn-primary" @click="createOpen = !createOpen">{{ tr('新建场景资料', 'New scene document') }}</button>
    </div>

    <section v-if="createOpen" class="card grid gap-3 md:grid-cols-2">
      <label class="text-sm text-slate-300">ID<input v-model="sceneForm.slug" class="input-field mt-1" placeholder="home-network" /></label>
      <label class="text-sm text-slate-300">{{ tr('名称', 'Title') }}<input v-model="sceneForm.title" class="input-field mt-1" /></label>
      <label class="text-sm text-slate-300 md:col-span-2">{{ tr('简介', 'Summary') }}<textarea v-model="sceneForm.summary" class="input-field mt-1" rows="2" /></label>
      <label class="text-sm text-slate-300">{{ tr('别名，逗号分隔', 'Aliases, comma separated') }}<input v-model="sceneForm.aliases" class="input-field mt-1" /></label>
      <label class="text-sm text-slate-300">{{ tr('项目 ID，可留空', 'Project ID, optional') }}<input v-model="sceneForm.project_id" class="input-field mt-1" /></label>
      <div class="md:col-span-2"><button class="btn-primary" :disabled="saving" @click="saveScene">{{ tr('保存资料', 'Save document') }}</button></div>
    </section>

    <div class="grid gap-5 xl:grid-cols-[minmax(0,0.7fr)_minmax(0,1.6fr)]">
      <aside class="space-y-3">
        <div class="card flex gap-2"><input v-model="search" class="input-field" :placeholder="tr('按名称或别名查找', 'Find by name or alias')" @keyup.enter="load" /><button class="btn-secondary" @click="load">{{ tr('查找', 'Find') }}</button></div>
        <div v-if="loading" class="card text-sm text-slate-400">{{ tr('正在加载…', 'Loading…') }}</div>
        <div v-if="!scenes.length && !loading" class="card text-sm text-slate-400">{{ tr('暂无场景资料。', 'No scene documents yet.') }}</div>
        <button v-for="scene in scenes" :key="scene.id" class="card w-full text-left hover:border-blue-500" @click="open(scene.slug)">
          <h3 class="font-semibold text-slate-100">{{ scene.title }}</h3>
          <p class="mt-1 text-xs text-slate-400">{{ scene.slug }}</p>
          <p v-if="scene.summary" class="mt-2 text-sm text-slate-300">{{ scene.summary }}</p>
        </button>
      </aside>

      <section v-if="selected" class="card space-y-5">
        <header class="space-y-2">
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div><h2 class="text-xl font-semibold text-slate-100">{{ selected.scene.title }}</h2><p class="text-xs text-slate-400">{{ selected.scene.slug }} · {{ when(selected.scene.updated_at) }}</p></div>
            <div class="flex flex-wrap gap-2"><button class="btn-secondary" @click="addOpen = !addOpen; sopOpen = false">{{ tr('补充条目', 'Add item') }}</button><button class="btn-secondary" @click="sopOpen = !sopOpen; addOpen = false">{{ tr('验证后录入 SOP', 'Add validated SOP') }}</button></div>
          </div>
          <p class="text-sm text-slate-300">{{ selected.scene.summary }}</p>
          <button class="text-xs text-blue-300 hover:text-blue-200" @click="documentOpen = !documentOpen">{{ documentOpen ? tr('收起纯文档', 'Hide Markdown document') : tr('查看纯文档', 'View Markdown document') }}</button>
          <label class="flex items-center gap-2 text-xs text-slate-400"><input v-model="includeArchived" type="checkbox" @change="open(selected.scene.slug)" />{{ tr('查看归档条目', 'Show archived items') }}</label>
        </header>

        <pre v-if="documentOpen" class="overflow-x-auto whitespace-pre-wrap break-words rounded-lg border border-slate-700 bg-slate-950/70 p-4 text-sm leading-relaxed text-slate-200">{{ selected.markdown }}</pre>

        <section v-if="addOpen" class="rounded-lg border border-slate-700 bg-slate-900/50 p-4 space-y-3">
          <h3 class="font-medium text-slate-100">{{ tr('补充一条知识', 'Add one knowledge item') }}</h3>
          <div class="grid gap-3 md:grid-cols-2">
            <label class="text-xs text-slate-300">{{ tr('分类', 'Category') }}<select v-model="entryForm.category" class="input-field mt-1"><option v-for="category in order.filter(value => value !== 'sop')" :key="category" :value="category">{{ labels[category][locale === 'zh' ? 0 : 1] }}</option></select></label>
            <label class="text-xs text-slate-300">{{ tr('状态', 'Status') }}<select v-model="entryForm.status" class="input-field mt-1"><option value="active">{{ tr('已核实', 'Active') }}</option><option value="needs_review">{{ tr('待核实', 'Needs review') }}</option></select></label>
            <label class="text-xs text-slate-300 md:col-span-2">{{ tr('正文，一条一事', 'Text, one claim per item') }}<textarea v-model="entryForm.content" class="input-field mt-1" rows="3" /></label>
            <label class="text-xs text-slate-300">{{ tr('来源引用', 'Source reference') }}<input v-model="entryForm.source_ref" class="input-field mt-1" /></label>
            <label class="text-xs text-slate-300">{{ tr('证据时间，事实/观测必填', 'Evidence time, required for facts/observations') }}<input v-model="entryForm.evidence_at" type="datetime-local" class="input-field mt-1" /></label>
          </div>
          <button class="btn-primary" :disabled="saving" @click="addEntry">{{ tr('保存条目', 'Save item') }}</button>
        </section>

        <section v-if="sopOpen" class="rounded-lg border border-amber-700/50 bg-slate-900/50 p-4 space-y-3">
          <h3 class="font-medium text-slate-100">{{ tr('录入经反复验证的 SOP', 'Add a repeatedly validated SOP') }}</h3>
          <p class="text-xs text-amber-300">{{ tr('至少 3 次独立完整实测、跨 2 次会话。临时尝试请放在“进行中”。', 'At least three independent complete runs across two sessions. Keep temporary attempts in current work.') }}</p>
          <label class="block text-xs text-slate-300">{{ tr('Markdown 正文：目的、适用、工具、步骤、验收、验证依据', 'Markdown: purpose, applicability, tools, steps, acceptance, evidence') }}<textarea v-model="sopForm.content" class="input-field mt-1 font-mono" rows="9" /></label>
          <label class="block text-xs text-slate-300">{{ tr('来源引用', 'Source reference') }}<input v-model="sopForm.source_ref" class="input-field mt-1" /></label>
          <label class="block text-xs text-slate-300">{{ tr('来源工作条目，可留空', 'Source work item, optional') }}<select v-model="sopForm.candidate_entry_id" class="input-field mt-1"><option value="">—</option><option v-for="entry in grouped.work" :key="entry.id" :value="entry.id">{{ entry.key }} · {{ entry.content.slice(0, 60) }}</option></select></label>
          <div v-for="(row, index) in validationRows" :key="index" class="rounded border border-slate-700 p-3 grid gap-2 md:grid-cols-2">
            <label class="text-xs text-slate-300">{{ tr('实测时间', 'Run time') }}<input v-model="row.executed_at" type="datetime-local" class="input-field mt-1" /></label>
            <label class="text-xs text-slate-300">{{ tr('会话 ID', 'Session ID') }}<input v-model="row.session_id" class="input-field mt-1" /></label>
            <label class="text-xs text-slate-300">{{ tr('测试条件', 'Conditions') }}<input v-model="row.conditions" class="input-field mt-1" /></label>
            <label class="text-xs text-slate-300">{{ tr('观察结果', 'Observed result') }}<input v-model="row.observed_result" class="input-field mt-1" /></label>
            <label class="text-xs text-slate-300 md:col-span-2">{{ tr('原始结果引用', 'Raw evidence reference') }}<input v-model="row.evidence_ref" class="input-field mt-1" /></label>
          </div>
          <div class="flex gap-2"><button class="btn-secondary" @click="validationRows.push({ executed_at: '', session_id: '', conditions: '', observed_result: '', evidence_ref: '' })">{{ tr('增加实测', 'Add run') }}</button><button class="btn-primary" :disabled="saving" @click="publishSop">{{ tr('保存正式 SOP', 'Save formal SOP') }}</button></div>
        </section>

        <section v-for="category in order" :key="category" class="space-y-2">
          <h3 class="border-b border-slate-700 pb-2 font-semibold text-slate-100">{{ labels[category][locale === 'zh' ? 0 : 1] }} <span class="text-sm font-normal text-slate-400">{{ selected.counts[category] }}</span></h3>
          <p v-if="!grouped[category].length" class="text-sm text-slate-500">{{ tr('暂无', 'None yet') }}</p>
          <article v-for="entry in grouped[category]" :key="entry.id" class="rounded-lg border border-slate-700 bg-slate-900/40 p-3">
            <div class="flex flex-wrap items-start gap-2"><span class="rounded bg-blue-950 px-1.5 py-0.5 font-mono text-xs text-blue-300">{{ entry.key }}</span><p class="min-w-0 flex-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-slate-200">{{ entry.content }}</p><span v-if="entry.status !== 'active'" class="text-xs text-amber-300">{{ entry.status === 'needs_review' ? tr('待核实', 'Needs review') : tr('已归档', 'Archived') }}</span></div>
            <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400"><span>{{ tr('来源', 'Source') }}: {{ entry.source_ref }}</span><span v-if="entry.evidence_at">{{ when(entry.evidence_at) }}</span><span>r{{ entry.revision }}</span></div>
            <div class="mt-2 flex gap-3 text-xs"><button class="text-blue-300 hover:text-blue-200" @click="beginEdit(entry)">{{ tr('校正', 'Correct') }}</button><button class="text-slate-400 hover:text-slate-200" @click="showHistory(entry)">{{ tr('历史', 'History') }}</button></div>
          </article>
        </section>

        <section v-if="editing" class="rounded-lg border border-blue-700/50 bg-slate-900/50 p-4 space-y-3">
          <div class="flex justify-between"><h3 class="font-medium text-slate-100">{{ tr('校正', 'Correct') }} {{ editing.key }} · r{{ editing.revision }}</h3><button class="text-xs text-slate-400" @click="editing = null">{{ tr('取消', 'Cancel') }}</button></div>
          <label class="block text-xs text-slate-300">{{ tr('正文', 'Text') }}<textarea v-model="editForm.content" class="input-field mt-1" :disabled="editing.category === 'sop'" rows="4" /></label>
          <p v-if="editing.category === 'sop'" class="text-xs text-amber-300">{{ tr('修改或重新启用 SOP 需要提交新的完整验证证据；这里可标记待核实或归档。', 'Changing or reactivating an SOP needs fresh validation evidence; here you can mark it for review or archive it.') }}</p>
          <div class="grid gap-3 md:grid-cols-2"><label class="text-xs text-slate-300">{{ tr('新证据来源', 'New evidence source') }}<input v-model="editForm.source_ref" class="input-field mt-1" /></label><label class="text-xs text-slate-300">{{ tr('新证据时间', 'New evidence time') }}<input v-model="editForm.evidence_at" type="datetime-local" class="input-field mt-1" /></label></div>
          <label class="block text-xs text-slate-300">{{ tr('校正原因', 'Reason') }}<input v-model="editForm.reason" class="input-field mt-1" /></label>
          <label class="block text-xs text-slate-300">{{ tr('状态', 'Status') }}<select v-model="editForm.status" class="input-field mt-1"><option v-if="editing.category !== 'sop' || editing.status === 'active'" value="active">{{ tr('有效', 'Active') }}</option><option value="needs_review">{{ tr('待核实', 'Needs review') }}</option><option value="archived">{{ tr('归档', 'Archived') }}</option></select></label>
          <button class="btn-primary" :disabled="saving" @click="correctEntry">{{ tr('保存校正', 'Save correction') }}</button>
        </section>
        <section v-if="historyEntry" class="rounded-lg border border-slate-700 p-4 space-y-2"><h3 class="font-medium text-slate-100">{{ tr('修订历史', 'Revision history') }}</h3><div v-for="change in history" :key="change.revision" class="border-t border-slate-700 pt-2 text-xs text-slate-300"><span>r{{ change.revision }} · {{ when(change.created_at) }} · {{ change.reason }}</span><p class="mt-1 whitespace-pre-wrap">{{ change.snapshot.content }}</p></div></section>
      </section>
      <div v-else class="card h-fit text-sm text-slate-400">{{ tr('选择一份场景资料。', 'Select a scene document.') }}</div>
    </div>
  </div>
</template>

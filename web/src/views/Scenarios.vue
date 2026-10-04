<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import { useI18n } from '@/i18n'
import { useToast } from '@/stores/toast'
import SceneKnowledge from '@/components/SceneKnowledge.vue'
import type {
  Scenario, ScenarioDefinition, ScenarioItem, ScenarioRun, ScenarioVersion, Project,
} from '@/types'

const { locale } = useI18n()
const { success, error } = useToast()
const zh = computed(() => locale.value === 'zh')
const tr = (cn: string, en: string) => zh.value ? cn : en

const tab = ref<'knowledge' | 'catalog' | 'items'>('knowledge')
const loading = ref(false)
const saving = ref(false)
const scenarios = ref<Scenario[]>([])
const projects = ref<Project[]>([])
const items = ref<ScenarioItem[]>([])
const itemTotal = ref(0)
const itemSearch = ref('')
const itemScenarioFilter = ref('')
const selectedScenario = ref<Scenario | null>(null)
const versions = ref<ScenarioVersion[]>([])
const selectedItem = ref<ScenarioItem | null>(null)
const itemVersion = ref<ScenarioVersion | null>(null)
const itemVersions = ref<ScenarioVersion[]>([])
const runs = ref<ScenarioRun[]>([])
const evidence = ref('')
const upgradeVersion = ref<number | null>(null)
const upgradeReason = ref('')
const bindForm = ref({ scenario_slug: '', reason: '', parameters: '{}', environment: '{}' })
const editorMode = ref<'create' | 'version' | null>(null)
const itemEditor = ref(false)

const form = ref({
  slug: '', title: '', summary: '', aliases: '', project_id: '',
  applicability: '', exclusions: '', input_fields: '[]', required_environment: '{}',
  steps: '', verification: '', recovery: '', execution_ref: '', source_refs: '',
})
const itemForm = ref({
  scenario_slug: '', title: '', goal: '', mode: 'one_off' as 'one_off' | 'continuous',
  working_plan: '', phase: 'ready', state: '{}',
  parameters: '{}', environment: '{}', next_check_at: '',
})

onMounted(load)

async function load(): Promise<void> {
  loading.value = true
  try {
    const [catalog, active, projectList] = await Promise.all([
      api.listScenarios(), api.listScenarioItems(), api.listProjects(),
    ])
    scenarios.value = catalog.items
    items.value = active.items
    itemTotal.value = active.total
    projects.value = projectList
  } catch {
    // API client reports request failures.
  } finally {
    loading.value = false
  }
}

async function refreshCatalog(): Promise<void> {
  scenarios.value = (await api.listScenarios()).items
  if (selectedScenario.value) await openScenario(selectedScenario.value.slug)
}

async function refreshItems(): Promise<void> {
  const result = await api.listScenarioItems({
    query: itemSearch.value.trim() || undefined,
    scenario_slug: itemScenarioFilter.value || undefined,
  })
  items.value = result.items
  itemTotal.value = result.total
  const selectedId = selectedItem.value?.id
  if (selectedId) {
    if (items.value.some(item => item.id === selectedId)) {
      await openItem(selectedId)
    } else {
      selectedItem.value = null
      itemVersion.value = null
      runs.value = []
    }
  }
}

async function openScenario(slug: string): Promise<void> {
  const result = await api.getScenario(slug)
  selectedScenario.value = result.scenario
  versions.value = result.versions
  evidence.value = ''
}

async function openItem(id: string): Promise<void> {
  const [detail, history] = await Promise.all([api.getScenarioItem(id), api.listScenarioRuns(id)])
  selectedItem.value = detail.item
  itemVersion.value = detail.version
  runs.value = history.items
  itemVersions.value = detail.item.scenario_slug
    ? (await api.getScenario(detail.item.scenario_slug)).versions : []
  upgradeVersion.value = null
  upgradeReason.value = ''
  bindForm.value = {
    scenario_slug: '', reason: '',
    parameters: JSON.stringify(detail.item.parameters, null, 2),
    environment: JSON.stringify(detail.item.environment, null, 2),
  }
}

function lines(value: string): string[] {
  return value.split('\n').map(line => line.trim()).filter(Boolean)
}

function parseObject(value: string, label: string): Record<string, string> {
  let data: unknown
  try {
    data = JSON.parse(value)
  } catch {
    throw new Error(`${label}: ${tr('请输入有效 JSON', 'Enter valid JSON')}`)
  }
  if (!data || Array.isArray(data) || typeof data !== 'object'
    || Object.entries(data).some(([key, val]) => !key || typeof val !== 'string')) {
    throw new Error(`${label}: ${tr('需要字符串键值对象', 'Expected a string map')}`)
  }
  return data as Record<string, string>
}

function parseState(value: string): Record<string, unknown> {
  let data: unknown
  try {
    data = JSON.parse(value)
  } catch {
    throw new Error(tr('当前状态需要有效 JSON', 'State needs valid JSON'))
  }
  if (!data || Array.isArray(data) || typeof data !== 'object') {
    throw new Error(tr('当前状态需要 JSON 对象', 'State needs a JSON object'))
  }
  return data as Record<string, unknown>
}

function definition(): ScenarioDefinition {
  let inputFields: unknown
  try {
    inputFields = JSON.parse(form.value.input_fields)
  } catch {
    throw new Error(tr('输入字段需要有效 JSON 数组', 'Input fields need a valid JSON array'))
  }
  if (!Array.isArray(inputFields)) {
    throw new Error(tr('输入字段需要 JSON 数组', 'Input fields need a JSON array'))
  }
  return {
    applicability: form.value.applicability.trim(),
    exclusions: form.value.exclusions.trim(),
    input_fields: inputFields,
    required_environment: parseObject(form.value.required_environment, tr('适用环境', 'Environment')),
    steps: lines(form.value.steps),
    verification: lines(form.value.verification),
    recovery: lines(form.value.recovery),
    execution_ref: form.value.execution_ref.trim() || null,
    source_refs: lines(form.value.source_refs),
  }
}

function beginCreate(): void {
  editorMode.value = 'create'
  form.value = {
    slug: '', title: '', summary: '', aliases: '', project_id: '',
    applicability: '', exclusions: '', input_fields: '[]', required_environment: '{}',
    steps: '', verification: '', recovery: '', execution_ref: '', source_refs: '',
  }
}

function beginVersion(): void {
  const current = versions.value.find(version => version.version === selectedScenario.value?.current_version)
    || versions.value[0]
  if (!selectedScenario.value || !current) return
  const source = current.definition
  editorMode.value = 'version'
  form.value = {
    slug: selectedScenario.value.slug,
    title: selectedScenario.value.title,
    summary: selectedScenario.value.summary,
    aliases: selectedScenario.value.aliases.join(', '),
    project_id: selectedScenario.value.project_id || '',
    applicability: source.applicability,
    exclusions: source.exclusions,
    input_fields: JSON.stringify(source.input_fields, null, 2),
    required_environment: JSON.stringify(source.required_environment, null, 2),
    steps: source.steps.join('\n'),
    verification: source.verification.join('\n'),
    recovery: source.recovery.join('\n'),
    execution_ref: source.execution_ref || '',
    source_refs: source.source_refs.join('\n'),
  }
}

async function saveDefinition(): Promise<void> {
  if (!editorMode.value) return
  saving.value = true
  try {
    const data = definition()
    if (editorMode.value === 'create') {
      const created = await api.createScenario({
        slug: form.value.slug.trim(), title: form.value.title.trim(),
        summary: form.value.summary.trim(),
        aliases: form.value.aliases.split(',').map(value => value.trim()).filter(Boolean),
        project_id: form.value.project_id || null, definition: data,
      })
      success(tr('已保存场景草稿', 'Scenario draft saved'))
      editorMode.value = null
      await refreshCatalog()
      await openScenario(created.scenario.slug)
    } else {
      await api.createScenarioVersion(form.value.slug, data)
      success(tr('已创建新草稿版本', 'Draft version created'))
      editorMode.value = null
      await refreshCatalog()
    }
  } catch (err) {
    if (err instanceof Error && !err.message.startsWith('Request failed')) error(err.message)
  } finally {
    saving.value = false
  }
}

async function publish(version: ScenarioVersion): Promise<void> {
  if (!selectedScenario.value || !evidence.value.trim()) return
  saving.value = true
  try {
    await api.publishScenarioVersion(selectedScenario.value.slug, version.version, evidence.value.trim())
    success(tr('版本已发布', 'Version published'))
    await refreshCatalog()
  } catch {
    // API client reports request failures.
  } finally {
    saving.value = false
  }
}

async function activate(version: ScenarioVersion): Promise<void> {
  if (!selectedScenario.value) return
  try {
    await api.activateScenarioVersion(selectedScenario.value.slug, version.version)
    await refreshCatalog()
  } catch {
    // API client reports request failures.
  }
}

async function toggleScenario(scenario: Scenario): Promise<void> {
  try {
    await api.setScenarioEnabled(scenario.slug, scenario.status !== 'active')
    await refreshCatalog()
  } catch {
    // API client reports request failures.
  }
}

function beginItem(scenario: Scenario): void {
  tab.value = 'items'
  itemEditor.value = true
  itemForm.value = {
    scenario_slug: scenario.slug,
    title: '', goal: '', mode: 'one_off', working_plan: '', phase: 'ready', state: '{}',
    parameters: '{}', environment: '{}', next_check_at: '',
  }
}

function beginStandalone(): void {
  tab.value = 'items'
  itemEditor.value = true
  itemForm.value = {
    scenario_slug: '', title: '', goal: '', mode: 'continuous',
    working_plan: '', phase: 'ready', state: '{}',
    parameters: '{}', environment: '{}', next_check_at: '',
  }
}

async function startItem(): Promise<void> {
  saving.value = true
  try {
    const due = itemForm.value.next_check_at
      ? new Date(itemForm.value.next_check_at).toISOString() : null
    const result = await api.createScenarioItem({
      scenario_slug: itemForm.value.scenario_slug || null,
      title: itemForm.value.title.trim(), goal: itemForm.value.goal.trim(),
      working_plan: itemForm.value.scenario_slug ? null : itemForm.value.working_plan.trim(),
      mode: itemForm.value.mode,
      phase: itemForm.value.phase.trim(),
      state: parseState(itemForm.value.state),
      parameters: parseObject(itemForm.value.parameters, tr('参数', 'Parameters')),
      environment: parseObject(itemForm.value.environment, tr('环境', 'Environment')),
      next_check_at: due,
    })
    itemEditor.value = false
    success(tr('事项已创建', 'Item created'))
    await refreshItems()
    await openItem(result.item.id)
  } catch (err) {
    if (err instanceof Error && !err.message.startsWith('Request failed')) error(err.message)
  } finally {
    saving.value = false
  }
}

async function bindItem(): Promise<void> {
  if (!selectedItem.value || !bindForm.value.scenario_slug || !bindForm.value.reason.trim()) return
  saving.value = true
  try {
    await api.bindScenarioItem(selectedItem.value.id, {
      expected_revision: selectedItem.value.revision,
      scenario_slug: bindForm.value.scenario_slug,
      reason: bindForm.value.reason.trim(),
      parameters: parseObject(bindForm.value.parameters, tr('参数', 'Parameters')),
      environment: parseObject(bindForm.value.environment, tr('环境', 'Environment')),
    })
    success(tr('事项已绑定到已发布场景', 'Item bound to a published scenario'))
    await refreshItems()
  } catch (err) {
    if (err instanceof Error && !err.message.startsWith('Request failed')) error(err.message)
    await refreshItems().catch(() => undefined)
  } finally {
    saving.value = false
  }
}

async function setItemStatus(status: 'active' | 'paused' | 'completed'): Promise<void> {
  if (!selectedItem.value) return
  try {
    await api.updateScenarioItem(selectedItem.value.id, {
      expected_revision: selectedItem.value.revision, status,
    })
    await refreshItems()
  } catch {
    // Reload on revision conflicts so the user sees the current state.
    await refreshItems().catch(() => undefined)
  }
}

async function markDue(): Promise<void> {
  if (!selectedItem.value) return
  try {
    await api.updateScenarioItem(selectedItem.value.id, {
      expected_revision: selectedItem.value.revision,
      next_check_at: new Date().toISOString(),
    })
    success(tr('已设为待检查；等待外部执行器领取', 'Marked due for an external executor'))
    await refreshItems()
  } catch {
    await refreshItems().catch(() => undefined)
  }
}

async function upgradeItem(): Promise<void> {
  if (!selectedItem.value || !upgradeVersion.value || !upgradeReason.value.trim()) return
  try {
    await api.upgradeScenarioItem(selectedItem.value.id, {
      expected_revision: selectedItem.value.revision,
      version: upgradeVersion.value,
      reason: upgradeReason.value.trim(),
    })
    success(tr('事项已切换版本', 'Item version switched'))
    await refreshItems()
  } catch {
    await refreshItems().catch(() => undefined)
  }
}

function when(value: string | null): string {
  return value ? new Date(value).toLocaleString() : '—'
}

const itemStableVersions = computed(() => itemVersions.value.filter(version => version.published_at))
</script>

<template>
  <div class="space-y-6">
    <header class="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">{{ tr('高频场景', 'Scenarios') }}</h1>
        <p class="mt-1 max-w-3xl text-sm text-slate-400">
          {{ tr('逐条保存有来源的场景知识；经反复验证的方法才进入 SOP。持续事项单独跟踪。',
            'Keep sourced scene knowledge item by item; only repeatedly validated methods enter SOPs. Track continuing work separately.') }}
        </p>
      </div>
      <button v-if="tab === 'catalog'" class="btn-primary" @click="beginCreate">{{ tr('新建场景', 'New scenario') }}</button>
      <button v-else-if="tab === 'items'" class="btn-primary" @click="beginStandalone">{{ tr('新建独立事项', 'New standalone item') }}</button>
    </header>

    <div class="flex gap-2 border-b border-slate-700">
      <button class="px-4 py-2 text-sm" :class="tab === 'knowledge' ? 'border-b-2 border-blue-500 text-blue-300' : 'text-slate-400'" @click="tab = 'knowledge'">
        {{ tr('场景资料', 'Scene knowledge') }}
      </button>
      <button class="px-4 py-2 text-sm" :class="tab === 'catalog' ? 'border-b-2 border-blue-500 text-blue-300' : 'text-slate-400'" @click="tab = 'catalog'">
        {{ tr('流程版本', 'Procedure versions') }}
      </button>
      <button class="px-4 py-2 text-sm" :class="tab === 'items' ? 'border-b-2 border-blue-500 text-blue-300' : 'text-slate-400'" @click="tab = 'items'">
        {{ tr('进行中事项', 'Items') }}
      </button>
    </div>

    <SceneKnowledge v-if="tab === 'knowledge'" />

    <div v-if="loading" class="text-sm text-slate-400">{{ tr('正在加载…', 'Loading…') }}</div>

    <section v-if="editorMode" class="card space-y-4">
      <div class="flex items-center justify-between">
        <h2 class="text-lg font-semibold text-slate-100">
          {{ editorMode === 'create' ? tr('新场景草稿', 'New scenario draft') : tr('新流程版本', 'New procedure version') }}
        </h2>
        <button class="text-sm text-slate-400 hover:text-slate-100" @click="editorMode = null">{{ tr('取消', 'Cancel') }}</button>
      </div>
      <p class="text-xs text-slate-400">{{ tr('每行写一个步骤。密钥只写获取方式，不填写值。新版本不会改变已有事项。',
        'Write one step per line. Describe where to obtain credentials, never their values. Existing items keep their version.') }}</p>
      <div v-if="editorMode === 'create'" class="grid gap-3 md:grid-cols-2">
        <label class="text-sm text-slate-300">ID<input v-model="form.slug" class="input-field mt-1" placeholder="daily-report" /></label>
        <label class="text-sm text-slate-300">{{ tr('名称', 'Name') }}<input v-model="form.title" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('别名，逗号分隔', 'Aliases, comma separated') }}<input v-model="form.aliases" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('项目，可留空', 'Project, optional') }}
          <select v-model="form.project_id" class="input-field mt-1"><option value="">{{ tr('个人场景', 'Personal') }}</option><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select>
        </label>
        <label class="text-sm text-slate-300 md:col-span-2">{{ tr('用途', 'Purpose') }}<textarea v-model="form.summary" rows="2" class="input-field mt-1" /></label>
      </div>
      <div class="grid gap-3 md:grid-cols-2">
        <label class="text-sm text-slate-300">{{ tr('适用条件', 'Applicability') }}<textarea v-model="form.applicability" rows="3" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('不适用情况', 'Exclusions') }}<textarea v-model="form.exclusions" rows="3" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('输入字段 JSON 数组', 'Input fields JSON array') }}<textarea v-model="form.input_fields" rows="4" class="input-field mt-1 font-mono" placeholder='[{"name":"date","description":"Report date","required":true,"secret":false}]' /></label>
        <label class="text-sm text-slate-300">{{ tr('环境精确匹配 JSON', 'Required environment JSON') }}<textarea v-model="form.required_environment" rows="4" class="input-field mt-1 font-mono" placeholder='{"os":"ubuntu"}' /></label>
        <label class="text-sm text-slate-300">{{ tr('固定步骤，每行一个', 'Steps, one per line') }}<textarea v-model="form.steps" rows="5" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('验收方法，每行一个', 'Verification, one per line') }}<textarea v-model="form.verification" rows="5" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('失败与恢复，每行一个', 'Recovery, one per line') }}<textarea v-model="form.recovery" rows="4" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('执行入口或固定版本引用', 'Execution reference') }}<input v-model="form.execution_ref" class="input-field mt-1" placeholder="git://...@commit" /></label>
        <label class="text-sm text-slate-300 md:col-span-2">{{ tr('来源与证据引用，每行一个', 'Source references, one per line') }}<textarea v-model="form.source_refs" rows="2" class="input-field mt-1" /></label>
      </div>
      <button class="btn-primary" :disabled="saving" @click="saveDefinition">{{ tr('保存草稿', 'Save draft') }}</button>
    </section>

    <div v-if="tab === 'catalog'" class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
      <section class="space-y-3">
        <div v-if="!scenarios.length && !loading" class="card text-sm text-slate-400">{{ tr('还没有场景。先保存一份流程草稿。', 'No scenarios yet. Save a procedure draft to begin.') }}</div>
        <button v-for="scenario in scenarios" :key="scenario.id" class="card w-full text-left hover:border-blue-500" @click="openScenario(scenario.slug)">
          <div class="flex items-start justify-between gap-3">
            <div><h3 class="font-semibold text-slate-100">{{ scenario.title }}</h3><p class="mt-0.5 font-mono text-xs text-slate-400">{{ scenario.slug }}</p></div>
            <span class="rounded bg-slate-700 px-2 py-1 text-xs text-slate-200">{{ scenario.status }}<template v-if="scenario.current_version"> · v{{ scenario.current_version }}</template></span>
          </div>
          <p class="mt-3 text-sm text-slate-300">{{ scenario.summary }}</p>
          <p v-if="scenario.aliases.length" class="mt-2 text-xs text-slate-400">{{ tr('别名', 'Aliases') }}: {{ scenario.aliases.join(', ') }}</p>
        </button>
      </section>

      <section v-if="selectedScenario" class="card h-fit space-y-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div><h2 class="text-lg font-semibold text-slate-100">{{ selectedScenario.title }}</h2><p class="font-mono text-xs text-slate-400">{{ selectedScenario.slug }}</p></div>
          <div class="flex flex-wrap gap-2">
            <button class="btn-secondary" @click="beginVersion">{{ tr('新版本', 'New version') }}</button>
            <button v-if="selectedScenario.current_version" class="btn-secondary" @click="toggleScenario(selectedScenario)">
              {{ selectedScenario.status === 'active' ? tr('停用', 'Disable') : tr('启用', 'Enable') }}
            </button>
            <button v-if="selectedScenario.status === 'active'" class="btn-primary" @click="beginItem(selectedScenario)">{{ tr('建立事项', 'Start item') }}</button>
          </div>
        </div>
        <p class="text-sm text-slate-300">{{ selectedScenario.summary }}</p>
        <div v-for="version in versions" :key="version.id" class="rounded-lg border border-slate-700 bg-slate-900/50 p-4 text-sm">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <strong class="text-slate-100">v{{ version.version }} · {{ version.published_at ? tr('已发布', 'Published') : tr('草稿', 'Draft') }}</strong>
            <span v-if="selectedScenario.current_version === version.version" class="text-xs text-blue-300">{{ tr('当前默认', 'Current default') }}</span>
          </div>
          <p class="mt-2 text-slate-300">{{ version.definition.applicability }}</p>
          <p class="mt-1 text-xs text-amber-300">{{ tr('排除', 'Excludes') }}: {{ version.definition.exclusions }}</p>
          <div class="mt-3 grid gap-3 md:grid-cols-2">
            <div><p class="font-medium text-slate-200">{{ tr('执行步骤', 'Steps') }}</p><ol class="mt-1 list-inside list-decimal space-y-1 text-slate-400"><li v-for="step in version.definition.steps" :key="step">{{ step }}</li></ol></div>
            <div><p class="font-medium text-slate-200">{{ tr('验收', 'Verification') }}</p><ul class="mt-1 list-inside list-disc space-y-1 text-slate-400"><li v-for="step in version.definition.verification" :key="step">{{ step }}</li></ul></div>
          </div>
          <p v-if="version.validation_evidence" class="mt-3 text-xs text-emerald-300">{{ tr('发布证据', 'Validation evidence') }}: {{ version.validation_evidence }}</p>
          <div v-if="!version.published_at" class="mt-3 space-y-2">
            <textarea v-model="evidence" rows="2" class="input-field" :placeholder="tr('填写真实验收结果或证据引用后发布', 'Enter actual validation result or evidence reference')" />
            <button class="btn-success" :disabled="saving || !evidence.trim()" @click="publish(version)">{{ tr('发布流程版本', 'Publish version') }}</button>
          </div>
          <button v-else-if="selectedScenario.current_version !== version.version" class="btn-secondary mt-3" @click="activate(version)">{{ tr('设为默认版本', 'Make default') }}</button>
        </div>
      </section>
      <div v-else class="card h-fit text-sm text-slate-400">{{ tr('选择一个场景查看版本。', 'Select a scenario to inspect versions.') }}</div>
    </div>

    <section v-if="tab === 'items' && itemEditor" class="card space-y-4">
      <div class="flex items-center justify-between"><h2 class="text-lg font-semibold text-slate-100">{{ tr('建立事项', 'Start item') }}</h2><button class="text-sm text-slate-400" @click="itemEditor = false">{{ tr('取消', 'Cancel') }}</button></div>
      <div class="grid gap-3 md:grid-cols-2">
        <label class="text-sm text-slate-300">{{ tr('场景', 'Scenario') }}<select v-model="itemForm.scenario_slug" class="input-field mt-1"><option value="">{{ tr('独立事项，暂不绑定场景', 'Standalone, no scenario yet') }}</option><option v-for="scenario in scenarios.filter(value => value.status === 'active')" :key="scenario.id" :value="scenario.slug">{{ scenario.title }}</option></select></label>
        <label class="text-sm text-slate-300">{{ tr('类型', 'Mode') }}<select v-model="itemForm.mode" class="input-field mt-1"><option value="one_off">{{ tr('单次', 'One-off') }}</option><option value="continuous">{{ tr('持续', 'Continuous') }}</option></select></label>
        <label class="text-sm text-slate-300">{{ tr('事项名称', 'Item title') }}<input v-model="itemForm.title" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('下次检查时间，可留空', 'Next check, optional') }}<input v-model="itemForm.next_check_at" type="datetime-local" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300 md:col-span-2">{{ tr('本次目标', 'Goal') }}<textarea v-model="itemForm.goal" rows="2" class="input-field mt-1" /></label>
        <label v-if="!itemForm.scenario_slug" class="text-sm text-slate-300 md:col-span-2">{{ tr('当前工作计划', 'Working plan') }}<textarea v-model="itemForm.working_plan" rows="5" class="input-field mt-1" :placeholder="tr('写下当前执行步骤、检查方式和失败时的处理；以后可以绑定已验证场景。', 'Describe current steps, checks and recovery. You can bind a validated scenario later.')" /></label>
        <label class="text-sm text-slate-300">{{ tr('当前阶段', 'Current phase') }}<input v-model="itemForm.phase" class="input-field mt-1" /></label>
        <label class="text-sm text-slate-300">{{ tr('当前状态 JSON', 'Current state JSON') }}<textarea v-model="itemForm.state" rows="3" class="input-field mt-1 font-mono" /></label>
        <label class="text-sm text-slate-300">{{ tr('非敏感参数 JSON', 'Non-secret parameters JSON') }}<textarea v-model="itemForm.parameters" rows="3" class="input-field mt-1 font-mono" /></label>
        <label class="text-sm text-slate-300">{{ tr('当前环境 JSON', 'Current environment JSON') }}<textarea v-model="itemForm.environment" rows="3" class="input-field mt-1 font-mono" /></label>
      </div>
      <p class="text-xs text-slate-400">{{ tr('持续事项只有设置下次检查时间并连接外部执行器后才会被自动领取。', 'Continuous items need a next check time and an external executor to run automatically.') }}</p>
      <button class="btn-primary" :disabled="saving" @click="startItem">{{ tr('建立事项', 'Create item') }}</button>
    </section>

    <div v-if="tab === 'items'" class="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
      <section class="space-y-3">
        <div class="card space-y-2">
          <label class="block text-xs text-slate-300">{{ tr('按事项名称或目标查找', 'Find by item title or goal') }}<input v-model="itemSearch" class="input-field mt-1" :placeholder="tr('例如：家庭网络', 'For example: home network')" @keyup.enter="refreshItems" /></label>
          <label class="block text-xs text-slate-300">{{ tr('限定场景', 'Scenario filter') }}<select v-model="itemScenarioFilter" class="input-field mt-1" @change="refreshItems"><option value="">{{ tr('全部场景及独立事项', 'All scenarios and standalone items') }}</option><option v-for="scenario in scenarios" :key="scenario.id" :value="scenario.slug">{{ scenario.title }}</option></select></label>
          <div class="flex items-center justify-between gap-2"><span class="text-xs text-slate-400">{{ tr('匹配事项', 'Matching items') }}: {{ itemTotal }}</span><button class="btn-secondary" @click="refreshItems">{{ tr('查找', 'Find') }}</button></div>
        </div>
        <div v-if="!items.length && !loading" class="card text-sm text-slate-400">{{ tr('没有匹配事项。可调整查找条件，或建立独立事项。', 'No matching items. Adjust the search or start a standalone item.') }}</div>
        <button v-for="item in items" :key="item.id" class="card w-full text-left hover:border-blue-500" @click="openItem(item.id)">
          <div class="flex items-start justify-between gap-3"><div><h3 class="font-semibold text-slate-100">{{ item.title }}</h3><p class="mt-1 text-xs text-slate-400">{{ item.scenario_slug || tr('独立事项', 'Standalone') }} · {{ item.mode }}</p></div><span class="rounded bg-slate-700 px-2 py-1 text-xs text-slate-200">{{ item.status }}</span></div>
          <p class="mt-2 text-sm" :class="item.current_observation === 'alert' ? 'text-amber-300' : item.current_observation === 'normal' ? 'text-emerald-300' : 'text-slate-400'">{{ tr('当前检查', 'Current check') }}: {{ item.current_observation }}</p>
          <p class="mt-1 text-xs text-slate-400">{{ tr('最近成功检查', 'Last successful check') }}: {{ when(item.last_success_at) }} · {{ tr('下次', 'Next') }}: {{ when(item.next_check_at) }}</p>
        </button>
      </section>

      <section v-if="selectedItem" class="card h-fit space-y-4 text-sm">
        <div class="flex flex-wrap items-start justify-between gap-3"><div><h2 class="text-lg font-semibold text-slate-100">{{ selectedItem.title }}</h2><p class="mt-1 break-all font-mono text-xs text-slate-400">{{ selectedItem.id }}</p></div><span class="rounded bg-slate-700 px-2 py-1 text-xs">{{ selectedItem.status }}</span></div>
        <p class="text-slate-300">{{ selectedItem.goal }}</p>
        <div class="grid gap-2 text-slate-300 sm:grid-cols-2">
          <p>{{ tr('绑定版本', 'Pinned version') }}: {{ itemVersion ? `v${itemVersion.version}` : tr('尚未绑定', 'Unbound') }}</p>
          <p>{{ tr('当前阶段', 'Phase') }}: {{ selectedItem.phase }}</p>
          <p>{{ tr('当前结论', 'Observation') }}: {{ selectedItem.current_observation }}</p>
          <p>{{ tr('下次检查', 'Next check') }}: {{ when(selectedItem.next_check_at) }}</p>
          <p>{{ tr('最近成功检查', 'Last successful check') }}: {{ when(selectedItem.last_success_at) }}</p>
          <p>{{ tr('最近执行', 'Last run') }}: {{ when(selectedItem.last_run_at) }}</p>
        </div>
        <p v-if="selectedItem.last_success_summary" class="rounded bg-slate-900/60 p-3 text-slate-300">{{ selectedItem.last_success_summary }}</p>
        <div v-if="selectedItem.working_plan" class="rounded bg-slate-900/60 p-3 text-slate-300">
          <p class="mb-2 font-medium text-slate-200">{{ selectedItem.scenario_id ? tr('绑定前工作计划', 'Plan before binding') : tr('当前工作计划', 'Working plan') }}</p>
          <p class="whitespace-pre-wrap">{{ selectedItem.working_plan }}</p>
        </div>
        <div class="flex flex-wrap gap-2">
          <button v-if="selectedItem.status === 'active'" class="btn-secondary" @click="setItemStatus('paused')">{{ tr('暂停', 'Pause') }}</button>
          <button v-if="selectedItem.status === 'paused'" class="btn-secondary" @click="setItemStatus('active')">{{ tr('恢复', 'Resume') }}</button>
          <button v-if="selectedItem.status !== 'completed'" class="btn-secondary" @click="setItemStatus('completed')">{{ tr('结束', 'Complete') }}</button>
          <button v-if="selectedItem.mode === 'continuous' && selectedItem.status === 'active'" class="btn-secondary" @click="markDue">{{ tr('设为待检查', 'Mark due') }}</button>
        </div>
        <p v-if="selectedItem.lease_expires_at" class="text-xs text-amber-300">{{ tr('执行租约到期', 'Execution lease expires') }}: {{ when(selectedItem.lease_expires_at) }}</p>
        <div v-if="!selectedItem.scenario_id && selectedItem.status !== 'completed'" class="space-y-2 border-t border-slate-700 pt-4">
          <h3 class="font-medium text-slate-200">{{ tr('绑定到已验证场景', 'Bind to validated scenario') }}</h3>
          <p class="text-xs text-slate-400">{{ tr('已有运行记录会保留；绑定后的新运行固定使用所选场景版本。', 'Existing runs stay in history; future runs use the selected published version.') }}</p>
          <select v-model="bindForm.scenario_slug" class="input-field"><option value="">{{ tr('选择场景', 'Choose scenario') }}</option><option v-for="scenario in scenarios.filter(value => value.status === 'active')" :key="scenario.id" :value="scenario.slug">{{ scenario.title }}</option></select>
          <input v-model="bindForm.reason" class="input-field" :placeholder="tr('绑定原因', 'Reason for binding')" />
          <label class="block text-xs text-slate-300">{{ tr('场景输入参数 JSON', 'Scenario parameters JSON') }}<textarea v-model="bindForm.parameters" rows="2" class="input-field mt-1 font-mono" /></label>
          <label class="block text-xs text-slate-300">{{ tr('当前环境 JSON', 'Current environment JSON') }}<textarea v-model="bindForm.environment" rows="2" class="input-field mt-1 font-mono" /></label>
          <button class="btn-secondary" :disabled="saving || !bindForm.scenario_slug || !bindForm.reason.trim()" @click="bindItem">{{ tr('绑定场景', 'Bind scenario') }}</button>
        </div>
        <div v-if="selectedItem.status !== 'completed' && itemStableVersions.length > 1" class="space-y-2 border-t border-slate-700 pt-4">
          <h3 class="font-medium text-slate-200">{{ tr('显式切换版本', 'Switch pinned version') }}</h3>
          <select v-model="upgradeVersion" class="input-field"><option :value="null">{{ tr('选择版本', 'Choose version') }}</option><option v-for="version in itemStableVersions" :key="version.id" :value="version.version">v{{ version.version }}</option></select>
          <input v-model="upgradeReason" class="input-field" :placeholder="tr('切换原因', 'Reason for switching')" />
          <button class="btn-secondary" :disabled="!upgradeVersion || !upgradeReason.trim()" @click="upgradeItem">{{ tr('切换', 'Switch') }}</button>
        </div>
        <div class="border-t border-slate-700 pt-4">
          <h3 class="font-medium text-slate-200">{{ tr('当前状态', 'Current state') }}</h3>
          <pre class="mt-2 overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-300">{{ JSON.stringify(selectedItem.state, null, 2) }}</pre>
        </div>
        <div class="border-t border-slate-700 pt-4">
          <h3 class="font-medium text-slate-200">{{ tr('执行记录', 'Run history') }}</h3>
          <p v-if="!runs.length" class="mt-2 text-slate-400">{{ tr('尚无执行记录', 'No runs yet') }}</p>
          <div v-for="run in runs" :key="run.id" class="mt-2 rounded border border-slate-700 p-3">
            <p class="text-slate-200">{{ when(run.started_at) }} · {{ run.status }} · {{ run.observation || 'unknown' }}</p>
            <p v-if="run.summary" class="mt-1 text-slate-300">{{ run.summary }}</p>
            <p v-if="run.signal" class="mt-1 text-xs text-amber-300">{{ tr('变化', 'Signal') }}: {{ run.signal }} · {{ tr('建议通知', 'Notify') }}: {{ run.notification_recommended }}</p>
            <p v-for="entry in run.evidence" :key="entry" class="mt-1 break-all text-xs text-slate-400">{{ entry }}</p>
          </div>
        </div>
      </section>
      <div v-else class="card h-fit text-sm text-slate-400">{{ tr('选择一个事项查看状态和执行记录。', 'Select an item to inspect state and runs.') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '@/api/client'
import Badge from '@/components/Badge.vue'
import { LAYER_COLORS, MEMORY_TYPE_COLORS, STATUS_COLORS } from '@/types'
import type {
  MemoryGraphExplainResponse,
  MemoryListItem,
  ProjectAutomationGate,
  ProjectAutomationRun,
  ProjectQualityCasesResponse,
  ProjectQualitySnapshot,
  SearchResultItem,
} from '@/types'

interface EvalCase {
  id: string
  question: string
  expectedIds: string[]
  expectedTitle: string
}

interface EvalResult {
  caseId: string
  loading: boolean
  usedFallback: boolean
  items: EvalItem[]
  expectedRank: number | null
  explain: MemoryGraphExplainResponse | null
  error: string | null
}

interface EvalItem {
  id: string
  title: string
  type: string
  layer: string
  status?: string
  tags: string[]
  score?: number
  content?: string
}

const cases: EvalCase[] = [
  {
    id: 'git-workflow',
    question: 'Git 提交流程按什么规则？',
    expectedIds: [
      'c8f8ab62-f9df-4f28-a5f7-b737dc093387',
      'cf797642-2ce2-438b-8876-2d30f3ed2e32',
      '419a6821-327a-404d-ac9d-89a3a7ef0d10',
    ],
    expectedTitle: 'Git workflow / PR rules',
  },
  {
    id: 'home-network',
    question: '我的家庭网络架构是怎样？',
    expectedIds: ['9aadd753-3b79-41e4-beae-e06e160a2b47'],
    expectedTitle: '网络架构 - EdgeOne CDN 方案',
  },
]

const results = ref<Record<string, EvalResult>>({})
const runningAll = ref(false)
const projectCases = ref<ProjectQualityCasesResponse | null>(null)
const projectSnapshots = ref<ProjectQualitySnapshot[]>([])
const automationGate = ref<ProjectAutomationGate | null>(null)
const automationDryRun = ref<ProjectAutomationRun | null>(null)
const projectRunning = ref(false)
const projectProgress = ref(0)
const projectError = ref<string | null>(null)

const summary = computed(() => {
  const values = Object.values(results.value).filter(result => result.items.length || result.error)
  const passed = values.filter(result => result.expectedRank !== null && result.expectedRank <= 3).length
  return { total: values.length, passed }
})

function defaultResult(caseId: string): EvalResult {
  return {
    caseId,
    loading: false,
    usedFallback: false,
    items: [],
    expectedRank: null,
    explain: null,
    error: null,
  }
}

function normalizeListItem(item: MemoryListItem): EvalItem {
  return {
    id: item.id,
    title: item.title,
    type: item.type,
    layer: item.layer,
    status: item.status,
    tags: item.tags,
    content: (item as { content?: string }).content,
  }
}

function normalizeSearchItem(item: SearchResultItem): EvalItem {
  return {
    id: item.id,
    title: item.title,
    type: item.type,
    layer: item.layer,
    tags: item.tags,
    score: item.score,
    content: item.content,
  }
}

function rankExpected(items: EvalItem[], expectedIds: string[]): number | null {
  const index = items.findIndex(item => expectedIds.includes(item.id))
  return index >= 0 ? index + 1 : null
}

async function runEval(testCase: EvalCase): Promise<void> {
  results.value[testCase.id] = { ...defaultResult(testCase.id), loading: true }
  try {
    const list = await api.listMemories({
      query: testCase.question,
      status: 'active',
      limit: 20,
    })
    let items = list.items.map(normalizeListItem)
    let usedFallback = false
    if (items.length === 0) {
      const search = await api.searchMemories({
        query: testCase.question,
        top_k: 20,
        min_score: 0.3,
      })
      items = search.results.map(normalizeSearchItem)
      usedFallback = true
    }
    const rank = rankExpected(items, testCase.expectedIds)
    const explainTarget = rank ? items[rank - 1] : items[0]
    const explain = explainTarget
      ? await api.explainMemoryGraph(explainTarget.id, { include_inactive: true })
      : null
    results.value[testCase.id] = {
      caseId: testCase.id,
      loading: false,
      usedFallback,
      items: items.slice(0, 5),
      expectedRank: rank,
      explain,
      error: null,
    }
  } catch (error) {
    results.value[testCase.id] = {
      ...defaultResult(testCase.id),
      loading: false,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}

async function runAll(): Promise<void> {
  runningAll.value = true
  try {
    for (const testCase of cases) {
      await runEval(testCase)
    }
  } finally {
    runningAll.value = false
  }
}

function caseResult(caseId: string): EvalResult {
  return results.value[caseId] || defaultResult(caseId)
}

function statusText(result: EvalResult): string {
  if (result.loading) return 'Running'
  if (result.error) return 'Error'
  if (!result.items.length) return 'Not run'
  if (result.expectedRank !== null && result.expectedRank <= 3) return 'Pass'
  if (result.expectedRank !== null) return 'Weak'
  return 'Fail'
}

function statusClass(result: EvalResult): string {
  const status = statusText(result)
  if (status === 'Pass') return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-200'
  if (status === 'Weak') return 'border-amber-500/30 bg-amber-500/15 text-amber-200'
  if (status === 'Fail' || status === 'Error') return 'border-red-500/30 bg-red-500/15 text-red-200'
  return 'border-slate-600 bg-slate-700 text-slate-300'
}

function metric(snapshot: ProjectQualitySnapshot | undefined, name: string): string {
  const value = snapshot?.metrics[name]
  if (value === null || value === undefined) return '—'
  return name.includes('latency') || name.includes('token')
    ? value.toFixed(0)
    : `${(value * 100).toFixed(1)}%`
}

async function loadProjectQuality(): Promise<void> {
  projectError.value = null
  try {
    projectCases.value = await api.getProjectQualityCases()
    const [snapshots, gate] = await Promise.all([
      api.listProjectQualitySnapshots(projectCases.value.project_id),
      api.getProjectAutomationGate(projectCases.value.project_id),
    ])
    projectSnapshots.value = snapshots.items
    automationGate.value = gate
  } catch (error) {
    projectError.value = error instanceof Error ? error.message : String(error)
  }
}

async function runProjectQuality(): Promise<void> {
  if (!projectCases.value) return
  projectRunning.value = true
  projectProgress.value = 0
  projectError.value = null
  try {
    const collected: Array<Record<string, unknown>> = []
    for (const testCase of projectCases.value.cases) {
      const started = performance.now()
      const context = await api.compileProjectContext({
        project_id: projectCases.value.project_id,
        task: testCase.query,
        changed_paths: testCase.changed_paths || [],
        mode: testCase.mode === 'preflight' ? 'impact' : testCase.mode,
        limit: 10,
        token_budget: 6000,
        as_of: testCase.as_of || null,
        record_run: false,
      })
      const preflight = testCase.mode === 'preflight'
        ? await api.runProjectPreflight({
            project_id: projectCases.value.project_id,
            task: testCase.query,
            changed_paths: testCase.changed_paths || [],
            planned_actions: testCase.planned_actions || [],
            limit: 10,
          })
        : null
      collected.push({
        case_id: testCase.id,
        context,
        preflight,
        latency_ms: performance.now() - started,
        token_used: context.token_used,
      })
      projectProgress.value += 1
    }
    await api.createProjectQualitySnapshot({
      project_id: projectCases.value.project_id,
      results: collected,
      k: 10,
      trigger: 'manual',
      dry_run: true,
      idempotency_key: `web-eval-${crypto.randomUUID()}`,
    })
    await loadProjectQuality()
  } catch (error) {
    projectError.value = error instanceof Error ? error.message : String(error)
  } finally {
    projectRunning.value = false
  }
}

async function runAutomationDryRun(): Promise<void> {
  if (!projectCases.value) return
  projectError.value = null
  try {
    automationDryRun.value = await api.runProjectAutomationDryRun(projectCases.value.project_id)
    await loadProjectQuality()
  } catch (error) {
    projectError.value = error instanceof Error ? error.message : String(error)
  }
}

onMounted(loadProjectQuality)
</script>

<template>
  <div class="space-y-6">
    <header class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-2xl font-semibold text-slate-100">Memory Quality Eval</h1>
        <p class="mt-1 text-sm text-slate-400">
          Run fixed recall checks against the same retrieval path agents use.
        </p>
      </div>
      <button class="btn-primary" :disabled="runningAll" @click="runAll">
        {{ runningAll ? 'Running...' : 'Run all' }}
      </button>
    </header>

    <section class="grid gap-3 sm:grid-cols-3">
      <div class="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <div class="text-xs text-slate-500">Cases</div>
        <div class="mt-1 text-2xl font-semibold text-slate-100">{{ cases.length }}</div>
      </div>
      <div class="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <div class="text-xs text-slate-500">Run</div>
        <div class="mt-1 text-2xl font-semibold text-slate-100">{{ summary.total }}</div>
      </div>
      <div class="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <div class="text-xs text-slate-500">Pass@3</div>
        <div class="mt-1 text-2xl font-semibold text-slate-100">{{ summary.passed }}</div>
      </div>
    </section>

    <section class="space-y-4">
      <div
        v-for="testCase in cases"
        :key="testCase.id"
        class="rounded-lg border border-slate-700 bg-slate-800 p-4"
      >
        <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span :class="['rounded border px-2 py-0.5 text-xs', statusClass(caseResult(testCase.id))]">
                {{ statusText(caseResult(testCase.id)) }}
              </span>
              <span class="text-xs text-slate-500">{{ testCase.expectedTitle }}</span>
            </div>
            <h2 class="mt-2 text-base font-medium text-slate-100">{{ testCase.question }}</h2>
            <p class="mt-1 font-mono text-xs text-slate-500">
              expected: {{ testCase.expectedIds.join(', ') }}
            </p>
          </div>
          <button class="btn-secondary" :disabled="caseResult(testCase.id).loading" @click="runEval(testCase)">
            {{ caseResult(testCase.id).loading ? 'Running...' : 'Run' }}
          </button>
        </div>

        <div v-if="caseResult(testCase.id).error" class="mt-4 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
          {{ caseResult(testCase.id).error }}
        </div>

        <div v-if="caseResult(testCase.id).items.length" class="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div class="space-y-2">
            <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span>Expected rank: {{ caseResult(testCase.id).expectedRank || 'miss' }}</span>
              <span v-if="caseResult(testCase.id).usedFallback">semantic fallback</span>
            </div>
            <div
              v-for="(item, index) in caseResult(testCase.id).items"
              :key="item.id"
              class="rounded-lg border border-slate-700 bg-slate-900 p-3"
            >
              <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div class="min-w-0">
                  <div class="truncate text-sm font-medium text-slate-100">
                    {{ index + 1 }}. {{ item.title }}
                  </div>
                  <div class="mt-1 font-mono text-xs text-slate-500">{{ item.id }}</div>
                </div>
                <div class="flex shrink-0 flex-wrap gap-1.5">
                  <Badge :color="MEMORY_TYPE_COLORS[item.type as keyof typeof MEMORY_TYPE_COLORS]" size="sm">{{ item.type }}</Badge>
                  <Badge :color="LAYER_COLORS[item.layer as keyof typeof LAYER_COLORS]" size="sm">{{ item.layer }}</Badge>
                  <Badge v-if="item.status" :color="STATUS_COLORS[item.status as keyof typeof STATUS_COLORS]" size="sm">{{ item.status }}</Badge>
                  <span v-if="item.score !== undefined" class="rounded bg-slate-700/60 px-1.5 py-0.5 text-xs text-slate-300">
                    {{ item.score.toFixed(2) }}
                  </span>
                </div>
              </div>
              <p class="mt-2 line-clamp-2 text-xs text-slate-400">{{ item.content }}</p>
            </div>
          </div>

          <aside class="rounded-lg border border-slate-700 bg-slate-900 p-3">
            <h3 class="text-sm font-medium text-slate-100">Graph Explanation</h3>
            <div v-if="caseResult(testCase.id).explain" class="mt-3 space-y-3">
              <div class="flex flex-wrap gap-1.5">
                <span class="rounded bg-cyan-500/20 px-2 py-0.5 text-xs text-cyan-200">
                  {{ caseResult(testCase.id).explain?.temporal_assessment.classification }}
                </span>
                <span class="rounded bg-slate-700/70 px-2 py-0.5 text-xs text-slate-300">
                  {{ caseResult(testCase.id).explain?.temporal_assessment.confidence }}
                </span>
              </div>
              <div class="text-xs text-slate-400">
                feedback: {{ caseResult(testCase.id).explain?.feedback_summary.total }}
              </div>
              <pre class="max-h-72 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-300">{{ JSON.stringify(caseResult(testCase.id).explain?.temporal_assessment, null, 2) }}</pre>
            </div>
          </aside>
        </div>
      </div>
    </section>

    <section class="border-t border-slate-700 pt-6">
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 class="text-xl font-semibold text-slate-100">Project Context Quality</h2>
          <div class="mt-1 flex flex-wrap gap-3 text-xs text-slate-400">
            <span>{{ projectCases?.project_id || '—' }}</span>
            <span>{{ projectCases?.cases.length || 0 }} cases</span>
            <span>gate: {{ automationGate?.eligible ? 'eligible' : 'closed' }}</span>
            <span>automation: {{ automationGate?.feature_enabled ? 'enabled' : 'disabled' }}</span>
          </div>
        </div>
        <div class="flex gap-2">
          <button class="btn-secondary" :disabled="!projectCases || projectRunning" @click="runAutomationDryRun">
            Proposal dry-run
          </button>
          <button class="btn-primary" :disabled="!projectCases || projectRunning" @click="runProjectQuality">
            {{ projectRunning ? `${projectProgress}/${projectCases?.cases.length || 0}` : 'Run project eval' }}
          </button>
        </div>
      </div>

      <div v-if="projectError" class="mt-4 rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
        {{ projectError }}
      </div>

      <div class="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <div class="rounded border border-slate-700 bg-slate-800 p-3">
          <div class="text-xs text-slate-500">Recall@10</div>
          <div class="mt-1 text-lg font-semibold text-slate-100">{{ metric(projectSnapshots[0], 'recall_at_10') }}</div>
        </div>
        <div class="rounded border border-slate-700 bg-slate-800 p-3">
          <div class="text-xs text-slate-500">Evidence precision</div>
          <div class="mt-1 text-lg font-semibold text-slate-100">{{ metric(projectSnapshots[0], 'evidence_precision') }}</div>
        </div>
        <div class="rounded border border-slate-700 bg-slate-800 p-3">
          <div class="text-xs text-slate-500">Abstention</div>
          <div class="mt-1 text-lg font-semibold text-slate-100">{{ metric(projectSnapshots[0], 'abstention_accuracy') }}</div>
        </div>
        <div class="rounded border border-slate-700 bg-slate-800 p-3">
          <div class="text-xs text-slate-500">Preflight recall</div>
          <div class="mt-1 text-lg font-semibold text-slate-100">{{ metric(projectSnapshots[0], 'preflight_recall') }}</div>
        </div>
        <div class="rounded border border-slate-700 bg-slate-800 p-3">
          <div class="text-xs text-slate-500">p95 latency</div>
          <div class="mt-1 text-lg font-semibold text-slate-100">{{ metric(projectSnapshots[0], 'latency_p95_ms') }} ms</div>
        </div>
      </div>

      <div class="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,0.7fr)]">
        <div class="overflow-hidden rounded border border-slate-700">
          <table class="w-full text-left text-sm">
            <thead class="bg-slate-800 text-xs text-slate-400">
              <tr><th class="px-3 py-2">Snapshot</th><th class="px-3 py-2">Recall</th><th class="px-3 py-2">Preflight</th><th class="px-3 py-2">Status</th></tr>
            </thead>
            <tbody class="divide-y divide-slate-700 bg-slate-900/40">
              <tr v-for="snapshot in projectSnapshots.slice(0, 6)" :key="snapshot.id">
                <td class="px-3 py-2 text-xs text-slate-400">{{ new Date(snapshot.created_at).toLocaleString() }}</td>
                <td class="px-3 py-2 text-slate-200">{{ metric(snapshot, 'recall_at_10') }}</td>
                <td class="px-3 py-2 text-slate-200">{{ metric(snapshot, 'preflight_recall') }}</td>
                <td class="px-3 py-2"><span :class="snapshot.passed ? 'text-emerald-300' : 'text-red-300'">{{ snapshot.passed ? 'pass' : 'fail' }}</span></td>
              </tr>
              <tr v-if="!projectSnapshots.length"><td colspan="4" class="px-3 py-6 text-center text-slate-500">No snapshots</td></tr>
            </tbody>
          </table>
        </div>
        <div class="rounded border border-slate-700 bg-slate-900/40 p-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-medium text-slate-100">Automation gate</h3>
            <span :class="automationGate?.eligible ? 'text-emerald-300' : 'text-amber-300'">
              {{ automationGate?.eligible ? 'eligible' : 'closed' }}
            </span>
          </div>
          <div class="mt-3 text-xs text-slate-400">
            {{ automationGate?.snapshot_ids.length || 0 }}/{{ automationGate?.required_snapshots || 3 }} snapshots
          </div>
          <div v-if="automationDryRun" class="mt-4 grid grid-cols-2 gap-3 border-t border-slate-700 pt-4">
            <div><div class="text-xs text-slate-500">Sleep candidates</div><div class="mt-1 text-lg text-slate-100">{{ automationDryRun.plans.sleep.length }}</div></div>
            <div><div class="text-xs text-slate-500">Revalidations</div><div class="mt-1 text-lg text-slate-100">{{ automationDryRun.plans.revalidation.length }}</div></div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

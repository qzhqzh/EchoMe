<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '@/api/client'
import DiagnosticsTabs from '@/components/DiagnosticsTabs.vue'

interface RetrievalLog {
  id: string
  query: string
  client: string
  source: string
  status_filter: string | null
  limit: number
  lightweight_count: number
  semantic_count: number
  fallback_used: boolean
  expected_ids: string[]
  expected_rank: number | null
  top_results: Array<Record<string, any>>
  steps: Array<Record<string, any>>
  created_at: string
}

interface ContextRun {
  id: string
  project_id: string | null
  query: string
  mode: string
  route: string | null
  request_id: string | null
  client: string | null
  client_version: string | null
  fallback: string | null
  error_code: string | null
  token_budget: number
  token_used: number
  candidates: Record<string, number>
  selected: Record<string, string[]>
  trace: Record<string, any>
  status: string
  created_at: string
}

const sampleCases = [
  {
    label: 'Git workflow',
    query: 'Git 提交流程按什么规则？',
    expected_ids: [
      'c8f8ab62-f9df-4f28-a5f7-b737dc093387',
      'cf797642-2ce2-438b-8876-2d30f3ed2e32',
      '419a6821-327a-404d-ac9d-89a3a7ef0d10',
    ],
  },
  {
    label: 'Home network',
    query: '我的家庭网络架构是怎样？',
    expected_ids: ['9aadd753-3b79-41e4-beae-e06e160a2b47'],
  },
]

const query = ref(sampleCases[0].query)
const expectedIds = ref(sampleCases[0].expected_ids.join('\n'))
const running = ref(false)
const currentLog = ref<RetrievalLog | null>(null)
const logs = ref<RetrievalLog[]>([])
const loadingLogs = ref(false)
const activeView = ref<'retrieval' | 'context'>('retrieval')
const contextRuns = ref<ContextRun[]>([])
const selectedContextRun = ref<ContextRun | null>(null)
const loadingContextRuns = ref(false)

onMounted(() => {
  void loadLogs()
  void loadContextRuns()
})

function useSample(index: number): void {
  query.value = sampleCases[index].query
  expectedIds.value = sampleCases[index].expected_ids.join('\n')
}

async function loadContextRuns(): Promise<void> {
  loadingContextRuns.value = true
  try {
    const response = await api.listContextRuns({ limit: 100 })
    contextRuns.value = response.items
    if (!selectedContextRun.value && contextRuns.value.length) {
      selectedContextRun.value = contextRuns.value[0]
    }
  } finally {
    loadingContextRuns.value = false
  }
}

function parsedExpectedIds(): string[] {
  return expectedIds.value
    .split(/\s|,|，/)
    .map(item => item.trim())
    .filter(Boolean)
}

async function runDebug(): Promise<void> {
  running.value = true
  try {
    currentLog.value = await api.runRetrievalDebug({
      query: query.value,
      limit: 10,
      expected_ids: parsedExpectedIds(),
      client: 'web',
      source: 'retrieval_debugger',
    })
    await loadLogs()
  } finally {
    running.value = false
  }
}

async function loadLogs(): Promise<void> {
  loadingLogs.value = true
  try {
    const response = await api.listRetrievalLogs({ limit: 30 })
    logs.value = response.items
  } finally {
    loadingLogs.value = false
  }
}

function formatDate(value: string): string {
  return new Date(value).toLocaleString()
}

function resultStatus(log: RetrievalLog): string {
  if (!log.expected_ids.length) return 'recorded'
  if (log.expected_rank !== null && log.expected_rank <= 3) return 'pass'
  if (log.expected_rank !== null) return 'weak'
  return 'miss'
}

function statusClass(log: RetrievalLog): string {
  const status = resultStatus(log)
  if (status === 'pass') return 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30'
  if (status === 'weak') return 'bg-amber-500/15 text-amber-200 border-amber-500/30'
  if (status === 'miss') return 'bg-red-500/15 text-red-200 border-red-500/30'
  return 'bg-slate-700 text-slate-300 border-slate-600'
}

function contextStatusClass(run: ContextRun): string {
  if (run.error_code) return 'border-red-500/30 bg-red-500/15 text-red-200'
  if (run.fallback) return 'border-amber-500/30 bg-amber-500/15 text-amber-200'
  return 'border-emerald-500/30 bg-emerald-500/15 text-emerald-200'
}

function selectionCount(run: ContextRun): number {
  return Object.values(run.selected || {}).reduce((total, items) => total + items.length, 0)
}
</script>

<template>
  <div class="space-y-6">
    <DiagnosticsTabs />
    <header>
      <h1 class="text-2xl font-semibold text-slate-100">Logs</h1>
      <p class="mt-1 text-sm text-slate-400">Memory retrieval and context runtime records.</p>
    </header>

    <div class="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-1" role="tablist">
      <button
        class="rounded-md px-3 py-1.5 text-sm transition-colors"
        :class="activeView === 'retrieval' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'"
        role="tab"
        :aria-selected="activeView === 'retrieval'"
        @click="activeView = 'retrieval'"
      >
        Retrieval
      </button>
      <button
        class="rounded-md px-3 py-1.5 text-sm transition-colors"
        :class="activeView === 'context' ? 'bg-slate-700 text-white' : 'text-slate-400 hover:text-slate-200'"
        role="tab"
        :aria-selected="activeView === 'context'"
        @click="activeView = 'context'"
      >
        Context Runs
      </button>
    </div>

    <section v-if="activeView === 'retrieval'" class="rounded-lg border border-slate-700 bg-slate-800 p-4">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-start">
        <div class="min-w-0 flex-1 space-y-3">
          <div class="flex flex-wrap gap-2">
            <button
              v-for="(sample, index) in sampleCases"
              :key="sample.label"
              class="rounded border border-slate-600 bg-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:bg-slate-600"
              @click="useSample(index)"
            >
              {{ sample.label }}
            </button>
          </div>
          <label class="block">
            <span class="text-sm text-slate-300">Query</span>
            <input v-model="query" class="input mt-1 w-full" />
          </label>
          <label class="block">
            <span class="text-sm text-slate-300">Expected memory ids</span>
            <textarea v-model="expectedIds" class="input mt-1 h-20 w-full resize-none font-mono text-xs" />
          </label>
        </div>
        <button class="btn-primary" :disabled="running || !query.trim()" @click="runDebug">
          {{ running ? 'Running...' : 'Run debug' }}
        </button>
      </div>

      <div v-if="currentLog" class="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div class="space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <span :class="['rounded border px-2 py-0.5 text-xs', statusClass(currentLog)]">
              {{ resultStatus(currentLog) }}
            </span>
            <span class="text-xs text-slate-500">
              lightweight {{ currentLog.lightweight_count }} · semantic {{ currentLog.semantic_count }} · fallback {{ currentLog.fallback_used ? 'yes' : 'no' }}
            </span>
          </div>
          <div
            v-for="(item, index) in currentLog.top_results.slice(0, 8)"
            :key="item.id"
            class="rounded-lg border border-slate-700 bg-slate-900 p-3"
          >
            <div class="truncate text-sm font-medium text-slate-100">{{ index + 1 }}. {{ item.title }}</div>
            <div class="mt-1 font-mono text-xs text-slate-500">{{ item.id }}</div>
            <div class="mt-2 flex flex-wrap gap-1.5 text-xs text-slate-400">
              <span>{{ item.type }}</span>
              <span>{{ item.layer }}</span>
              <span v-if="item.score !== undefined">score {{ Number(item.score).toFixed(2) }}</span>
            </div>
          </div>
        </div>
        <pre class="max-h-96 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{{ JSON.stringify(currentLog.steps, null, 2) }}</pre>
      </div>
    </section>

    <section v-if="activeView === 'retrieval'" class="space-y-3">
      <div class="flex items-center justify-between">
        <h2 class="text-base font-semibold text-slate-100">Recent Logs</h2>
        <button class="btn-secondary" :disabled="loadingLogs" @click="loadLogs">
          {{ loadingLogs ? 'Loading...' : 'Refresh' }}
        </button>
      </div>
      <div v-if="logs.length === 0" class="rounded-lg border border-slate-700 bg-slate-800 p-4 text-sm text-slate-400">
        No retrieval logs yet.
      </div>
      <div v-else class="space-y-2">
        <button
          v-for="log in logs"
          :key="log.id"
          class="w-full rounded-lg border border-slate-700 bg-slate-800 p-3 text-left hover:bg-slate-750"
          @click="currentLog = log"
        >
          <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div class="min-w-0">
              <div class="truncate text-sm font-medium text-slate-100">{{ log.query }}</div>
              <div class="mt-1 text-xs text-slate-500">
                {{ formatDate(log.created_at) }} · {{ log.client }} / {{ log.source }}
              </div>
            </div>
            <span :class="['shrink-0 rounded border px-2 py-0.5 text-xs', statusClass(log)]">
              {{ resultStatus(log) }}
            </span>
          </div>
        </button>
      </div>
    </section>

    <section v-if="activeView === 'context'" class="grid min-h-[560px] gap-4 xl:grid-cols-[minmax(320px,0.8fr)_minmax(0,1.2fr)]">
      <div class="min-w-0 space-y-3">
        <div class="flex items-center justify-between">
          <h2 class="text-base font-semibold text-slate-100">Recent Context Runs</h2>
          <button class="btn-secondary" :disabled="loadingContextRuns" @click="loadContextRuns">
            {{ loadingContextRuns ? 'Loading...' : 'Refresh' }}
          </button>
        </div>
        <div v-if="contextRuns.length === 0" class="rounded-lg border border-slate-700 bg-slate-800 p-4 text-sm text-slate-400">
          No context runs recorded yet.
        </div>
        <div v-else class="max-h-[720px] space-y-2 overflow-y-auto pr-1">
          <button
            v-for="run in contextRuns"
            :key="run.id"
            class="w-full rounded-lg border p-3 text-left transition-colors"
            :class="selectedContextRun?.id === run.id ? 'border-cyan-500/50 bg-slate-750' : 'border-slate-700 bg-slate-800 hover:bg-slate-750'"
            @click="selectedContextRun = run"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <div class="line-clamp-2 text-sm font-medium text-slate-100">{{ run.query }}</div>
                <div class="mt-1 truncate font-mono text-xs text-slate-500">
                  {{ run.request_id || run.id }}
                </div>
              </div>
              <span :class="['shrink-0 rounded border px-2 py-0.5 text-xs', contextStatusClass(run)]">
                {{ run.error_code || run.fallback || 'ok' }}
              </span>
            </div>
            <div class="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
              <span>{{ run.route || run.mode }}</span>
              <span>{{ run.project_id || 'personal' }}</span>
              <span>{{ selectionCount(run) }} selected</span>
              <span>{{ run.token_used }} / {{ run.token_budget }} tokens</span>
            </div>
          </button>
        </div>
      </div>

      <aside class="min-w-0 rounded-lg border border-slate-700 bg-slate-800 p-4">
        <div v-if="selectedContextRun" class="space-y-5">
          <div>
            <div class="flex flex-wrap items-center gap-2">
              <span :class="['rounded border px-2 py-0.5 text-xs', contextStatusClass(selectedContextRun)]">
                {{ selectedContextRun.status }}
              </span>
              <span class="rounded bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
                {{ selectedContextRun.route || selectedContextRun.mode }}
              </span>
            </div>
            <h2 class="mt-3 text-base font-semibold text-slate-100">{{ selectedContextRun.query }}</h2>
            <dl class="mt-3 grid gap-3 text-xs sm:grid-cols-2">
              <div>
                <dt class="text-slate-500">Request ID</dt>
                <dd class="mt-1 break-all font-mono text-slate-300">{{ selectedContextRun.request_id || 'legacy run' }}</dd>
              </div>
              <div>
                <dt class="text-slate-500">Client</dt>
                <dd class="mt-1 text-slate-300">{{ selectedContextRun.client || 'unknown' }} {{ selectedContextRun.client_version || '' }}</dd>
              </div>
              <div>
                <dt class="text-slate-500">Project</dt>
                <dd class="mt-1 break-all text-slate-300">{{ selectedContextRun.project_id || 'personal' }}</dd>
              </div>
              <div>
                <dt class="text-slate-500">Created</dt>
                <dd class="mt-1 text-slate-300">{{ formatDate(selectedContextRun.created_at) }}</dd>
              </div>
            </dl>
          </div>

          <div>
            <h3 class="text-sm font-semibold text-slate-200">Selection</h3>
            <div class="mt-2 grid gap-2 sm:grid-cols-2">
              <div v-for="(ids, kind) in selectedContextRun.selected" :key="kind" class="rounded border border-slate-700 bg-slate-900 p-3">
                <div class="text-xs font-medium uppercase text-slate-400">{{ kind }}</div>
                <div class="mt-1 text-lg font-semibold text-slate-100">{{ ids.length }}</div>
              </div>
            </div>
          </div>

          <div>
            <h3 class="text-sm font-semibold text-slate-200">Runtime Trace</h3>
            <pre class="mt-2 max-h-[360px] overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{{ JSON.stringify({
              candidates: selectedContextRun.candidates,
              selected: selectedContextRun.selected,
              trace: selectedContextRun.trace,
              fallback: selectedContextRun.fallback,
              error_code: selectedContextRun.error_code,
            }, null, 2) }}</pre>
          </div>
        </div>
        <div v-else class="text-sm text-slate-400">Select a context run.</div>
      </aside>
    </section>
  </div>
</template>

<script setup lang="ts">
import cytoscape, { type Core, type EventObject } from 'cytoscape'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import type {
  ProjectArtifact,
  ProjectConstraint,
  ProjectKnowledgeGraph,
  ProjectWorkspaceSummary,
} from '@/types'

type Tab = 'constraints' | 'artifacts' | 'graph' | 'impact'

const route = useRoute()
const router = useRouter()
const { success } = useToast()
const projectId = computed(() => String(route.query.project_id || ''))
const tab = ref<Tab>('constraints')
const loading = ref(true)
const summary = ref<ProjectWorkspaceSummary | null>(null)
const constraints = ref<ProjectConstraint[]>([])
const artifacts = ref<ProjectArtifact[]>([])
const graph = ref<ProjectKnowledgeGraph | null>(null)
const selected = ref<Record<string, any> | null>(null)
const search = ref('')
const statusFilter = ref('')
const impactText = ref('')
const changedPaths = ref('')
const impactResult = ref<any>(null)
const analyzing = ref(false)
const showCreate = ref(false)
const createTitle = ref('')
const createStatement = ref('')
const createKind = ref('architecture')
const createStability = ref('evolving')
const graphEl = ref<HTMLDivElement | null>(null)
let cy: Core | null = null

const visibleConstraints = computed(() => {
  const q = search.value.trim().toLowerCase()
  return constraints.value.filter(item => {
    if (statusFilter.value && item.status !== statusFilter.value) return false
    return !q || `${item.title} ${item.statement} ${item.tags.join(' ')}`.toLowerCase().includes(q)
  })
})

const totalConstraints = computed(() =>
  Object.values(summary.value?.constraint_counts || {}).reduce((sum, count) => sum + count, 0),
)

async function loadAll(): Promise<void> {
  if (!projectId.value) {
    router.push('/projects')
    return
  }
  loading.value = true
  try {
    const [workspace, constraintData, artifactData] = await Promise.all([
      api.getProjectWorkspace(projectId.value),
      api.listProjectConstraints(projectId.value),
      api.listProjectArtifacts(projectId.value),
    ])
    summary.value = workspace
    constraints.value = constraintData.items
    artifacts.value = artifactData.items
  } finally {
    loading.value = false
  }
}

async function createConstraint(): Promise<void> {
  if (!createTitle.value.trim() || !createStatement.value.trim()) return
  await api.createProjectConstraint({
    project_id: projectId.value,
    title: createTitle.value.trim(),
    statement: createStatement.value.trim(),
    kind: createKind.value,
    status: 'active',
    stability: createStability.value,
    confidence: 1,
    source: 'manual',
  })
  showCreate.value = false
  createTitle.value = ''
  createStatement.value = ''
  success('Constraint created')
  await loadAll()
}

async function setConstraintStatus(item: ProjectConstraint, status: string): Promise<void> {
  await api.patchProjectConstraint(item.id, { status, last_verified_at: new Date().toISOString() })
  item.status = status as ProjectConstraint['status']
  success(`Constraint marked ${status}`)
}

async function loadGraph(): Promise<void> {
  graph.value = await api.getProjectKnowledgeGraph(projectId.value)
  await nextTick()
  renderGraph()
}

function renderGraph(): void {
  if (!graphEl.value || !graph.value) return
  cy?.destroy()
  const elements: any[] = graph.value.nodes.map(node => ({
    data: {
      id: node.id,
      label: node.title,
      nodeType: node.node_type,
      status: 'status' in node ? node.status : 'current',
      raw: node,
    },
  }))
  for (const edge of graph.value.edges) {
    const source = edge.edge_type === 'constraint' ? edge.source_constraint_id : edge.constraint_id
    const target = edge.edge_type === 'constraint' ? edge.target_constraint_id : edge.artifact_id
    if (source && target) {
      elements.push({ data: { id: edge.id, source, target, label: edge.relation, raw: edge } })
    }
  }
  cy = cytoscape({
    container: graphEl.value,
    elements,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': '#38bdf8',
          label: 'data(label)',
          color: '#e2e8f0',
          'font-size': 10,
          'text-wrap': 'ellipsis',
          'text-max-width': '110px',
          'text-valign': 'bottom',
          'text-margin-y': 8,
          width: 24,
          height: 24,
        },
      },
      { selector: 'node[nodeType = "artifact"]', style: { 'background-color': '#f59e0b', shape: 'round-rectangle', width: 30, height: 22 } },
      { selector: 'node[status = "proposed"]', style: { 'background-color': '#a78bfa' } },
      { selector: 'node[status = "uncertain"]', style: { 'background-color': '#fb7185' } },
      {
        selector: 'edge',
        style: {
          width: 1.5,
          'line-color': '#64748b',
          'target-arrow-color': '#64748b',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
          label: 'data(label)',
          color: '#94a3b8',
          'font-size': 8,
          'text-background-color': '#0f172a',
          'text-background-opacity': 0.8,
        },
      },
      { selector: ':selected', style: { 'border-width': 3, 'border-color': '#f8fafc', 'overlay-opacity': 0 } },
    ],
    layout: { name: 'cose', animate: false, fit: true, padding: 40, nodeRepulsion: () => 5000 },
    wheelSensitivity: 0.35,
    minZoom: 0.15,
    maxZoom: 4,
  })
  cy.on('tap', 'node, edge', (event: EventObject) => {
    selected.value = event.target.data('raw')
  })
}

async function analyzeImpact(): Promise<void> {
  if (!impactText.value.trim()) return
  analyzing.value = true
  try {
    impactResult.value = await api.analyzeProjectImpact({
      project_id: projectId.value,
      task: impactText.value.trim(),
      changed_paths: changedPaths.value.split('\n').map(item => item.trim()).filter(Boolean),
      depth: 2,
      limit: 30,
    })
  } finally {
    analyzing.value = false
  }
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  return `${(value / 1024).toFixed(1)} KB`
}

watch(tab, async value => {
  selected.value = null
  if (value === 'graph') await loadGraph()
})

onMounted(loadAll)
onBeforeUnmount(() => cy?.destroy())
</script>

<template>
  <div class="space-y-5">
    <header class="flex flex-wrap items-start justify-between gap-4 border-b border-slate-700 pb-5">
      <div>
        <button class="mb-2 text-xs text-sky-400 hover:text-sky-300" @click="router.push('/projects')">← Projects</button>
        <h1 class="text-2xl font-bold text-slate-100">{{ summary?.project.name || projectId }}</h1>
        <p class="mt-1 text-sm text-slate-400">{{ summary?.project.description || 'Project constraints and artifact evidence' }}</p>
      </div>
      <button class="btn-primary" @click="showCreate = !showCreate">New constraint</button>
    </header>

    <div v-if="loading" class="py-16 text-center text-slate-400">Loading project workspace...</div>

    <template v-else>
      <section class="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-slate-700 bg-slate-700 md:grid-cols-4">
        <div class="bg-slate-800 px-4 py-3"><p class="text-xs text-slate-400">Constraints</p><p class="mt-1 text-xl font-semibold text-slate-100">{{ totalConstraints }}</p></div>
        <div class="bg-slate-800 px-4 py-3"><p class="text-xs text-slate-400">Proposed</p><p class="mt-1 text-xl font-semibold text-violet-300">{{ summary?.constraint_counts.proposed || 0 }}</p></div>
        <div class="bg-slate-800 px-4 py-3"><p class="text-xs text-slate-400">Artifacts</p><p class="mt-1 text-xl font-semibold text-amber-300">{{ artifacts.length }}</p></div>
        <div class="bg-slate-800 px-4 py-3"><p class="text-xs text-slate-400">Relations</p><p class="mt-1 text-xl font-semibold text-sky-300">{{ (summary?.edge_count || 0) + (summary?.evidence_count || 0) }}</p></div>
      </section>

      <section v-if="showCreate" class="border-y border-slate-700 bg-slate-800/60 py-4">
        <div class="grid gap-3 md:grid-cols-[1fr_180px_160px]">
          <input v-model="createTitle" class="input-field" placeholder="Constraint title" />
          <select v-model="createKind" class="input-field"><option v-for="value in ['architecture','compatibility','process','functional','nonfunctional','security','data']" :key="value">{{ value }}</option></select>
          <select v-model="createStability" class="input-field"><option v-for="value in ['invariant','evolving','temporary']" :key="value">{{ value }}</option></select>
        </div>
        <textarea v-model="createStatement" class="input-field mt-3 min-h-24" placeholder="State the condition the project must continue to satisfy." />
        <div class="mt-3 flex justify-end gap-2"><button class="btn-secondary" @click="showCreate = false">Cancel</button><button class="btn-primary" @click="createConstraint">Create</button></div>
      </section>

      <nav class="flex gap-1 border-b border-slate-700">
        <button v-for="value in (['constraints','artifacts','graph','impact'] as Tab[])" :key="value" class="px-4 py-2.5 text-sm capitalize" :class="tab === value ? 'border-b-2 border-sky-400 text-sky-300' : 'text-slate-400 hover:text-slate-200'" @click="tab = value">{{ value }}</button>
      </nav>

      <section v-if="tab === 'constraints'">
        <div class="mb-4 flex flex-wrap gap-3"><input v-model="search" class="input-field min-w-64 flex-1" placeholder="Filter constraints" /><select v-model="statusFilter" class="input-field w-44"><option value="">All statuses</option><option v-for="value in ['active','proposed','uncertain','superseded','deprecated']" :key="value">{{ value }}</option></select></div>
        <div class="divide-y divide-slate-700 border-y border-slate-700">
          <article v-for="item in visibleConstraints" :key="item.id" class="grid gap-3 py-4 md:grid-cols-[1fr_auto]">
            <div><div class="flex flex-wrap items-center gap-2"><h3 class="font-medium text-slate-100">{{ item.title }}</h3><span class="rounded border border-slate-600 px-1.5 py-0.5 text-xs text-slate-400">{{ item.kind }}</span><span class="text-xs" :class="item.status === 'active' ? 'text-emerald-400' : item.status === 'proposed' ? 'text-violet-400' : 'text-amber-400'">{{ item.status }}</span></div><p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-300">{{ item.statement }}</p><p class="mt-2 text-xs text-slate-500">v{{ item.version }} · {{ item.stability }} · confidence {{ Math.round(item.confidence * 100) }}% · {{ item.source }}</p></div>
            <div class="flex items-start gap-2"><button v-if="item.status !== 'active'" class="btn-secondary px-2 py-1 text-xs" @click="setConstraintStatus(item, 'active')">Confirm</button><button v-if="item.status !== 'deprecated'" class="rounded p-2 text-xs text-slate-500 hover:bg-slate-700 hover:text-slate-300" title="Deprecate" @click="setConstraintStatus(item, 'deprecated')">Archive</button></div>
          </article>
          <p v-if="visibleConstraints.length === 0" class="py-12 text-center text-sm text-slate-500">No constraints match this view.</p>
        </div>
      </section>

      <section v-else-if="tab === 'artifacts'" class="overflow-x-auto border-y border-slate-700">
        <table class="w-full text-left text-sm"><thead class="bg-slate-800 text-xs text-slate-400"><tr><th class="px-3 py-2">Path</th><th class="px-3 py-2">Kind</th><th class="px-3 py-2">Revision</th><th class="px-3 py-2">Size</th><th class="px-3 py-2">Hash</th></tr></thead><tbody class="divide-y divide-slate-700"><tr v-for="item in artifacts" :key="item.id"><td class="px-3 py-3 font-mono text-xs text-slate-200">{{ item.logical_path }}</td><td class="px-3 py-3 text-slate-400">{{ item.kind }}</td><td class="px-3 py-3 text-slate-400">v{{ item.revision }}</td><td class="px-3 py-3 text-slate-400">{{ formatBytes(item.size_bytes) }}</td><td class="px-3 py-3 font-mono text-xs text-slate-500">{{ item.content_hash.slice(0, 12) }}</td></tr></tbody></table>
        <p v-if="artifacts.length === 0" class="py-12 text-center text-sm text-slate-500">Run echome_project_index to synchronize project artifacts.</p>
      </section>

      <section v-else-if="tab === 'graph'" class="grid min-h-[620px] gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div ref="graphEl" class="min-h-[620px] border border-slate-700 bg-slate-950" />
        <aside class="border-l border-slate-700 pl-4"><template v-if="selected"><h3 class="break-words font-semibold text-slate-100">{{ selected.title || selected.relation }}</h3><p v-if="selected.statement" class="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-300">{{ selected.statement }}</p><p v-if="selected.logical_path" class="mt-3 break-all font-mono text-xs text-amber-300">{{ selected.logical_path }}</p><dl class="mt-4 space-y-2 text-xs text-slate-400"><div v-for="(value, key) in selected" :key="key" class="grid grid-cols-[100px_1fr] gap-2"><dt>{{ key }}</dt><dd class="break-all text-slate-300">{{ typeof value === 'object' ? JSON.stringify(value) : value }}</dd></div></dl></template><p v-else class="text-sm text-slate-500">Select a constraint, artifact, or relation to inspect it.</p></aside>
      </section>

      <section v-else class="grid gap-5 lg:grid-cols-[380px_1fr]">
        <div><label class="text-xs font-medium text-slate-400">Proposed change</label><textarea v-model="impactText" class="input-field mt-2 min-h-32" placeholder="Describe a requirement, API, architecture, or implementation change." /><label class="mt-4 block text-xs font-medium text-slate-400">Changed paths, one per line</label><textarea v-model="changedPaths" class="input-field mt-2 min-h-24 font-mono" placeholder="hub/app/api/memories.py" /><button class="btn-primary mt-4 w-full" :disabled="analyzing" @click="analyzeImpact">{{ analyzing ? 'Analyzing...' : 'Analyze impact' }}</button></div>
        <div class="border-l border-slate-700 pl-5"><p v-if="!impactResult" class="py-12 text-center text-sm text-slate-500">Impact analysis follows artifact evidence and constraint relations up to two hops.</p><template v-else><h3 class="font-semibold text-slate-100">{{ impactResult.constraints.length }} affected constraints</h3><div class="mt-3 divide-y divide-slate-700"><article v-for="item in impactResult.constraints" :key="item.id" class="py-3"><div class="flex items-center justify-between gap-3"><p class="font-medium text-slate-200">{{ item.title }}</p><span class="text-xs text-sky-400">{{ item.status }}</span></div><p class="mt-1 text-sm text-slate-400">{{ item.statement }}</p><p class="mt-2 text-xs text-slate-500">{{ item.selection_reasons.join(' · ') }}</p></article></div><h3 class="mt-6 font-semibold text-slate-100">{{ impactResult.artifacts.length }} evidence artifacts</h3><p v-for="item in impactResult.artifacts" :key="item.id" class="mt-2 font-mono text-xs text-amber-300">{{ item.logical_path }}</p></template></div>
      </section>
    </template>
  </div>
</template>

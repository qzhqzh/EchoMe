<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import cytoscape from 'cytoscape'
import { api } from '@/api/client'
import Badge from '@/components/Badge.vue'
import DiagnosticsTabs from '@/components/DiagnosticsTabs.vue'
import { LAYER_COLORS, MEMORY_TYPE_COLORS, STATUS_COLORS } from '@/types'
import type { Memory, MemoryGraphEdge, MemoryGraphExplainResponse, MemoryGraphNode, SleepSessionItem } from '@/types'
import type { Core, ElementDefinition, EventObject } from 'cytoscape'

type ViewMode = 'graph' | 'list' | 'ai'
type GraphLayout = 'cose' | 'circle' | 'grid'
type SelectedGraphItem =
  | { kind: 'node'; node: MemoryGraphNode }
  | { kind: 'edge'; edge: MemoryGraphEdge }

const sessions = ref<SleepSessionItem[]>([])
const nodes = ref<MemoryGraphNode[]>([])
const edges = ref<MemoryGraphEdge[]>([])
const loading = ref(true)
const includeInactive = ref(false)
const statusFilter = ref('')
const searchQuery = ref('')
const relationFilter = ref('')
const nodeLimit = ref(80)
const viewMode = ref<ViewMode>('graph')
const copied = ref(false)
const graphContainer = ref<HTMLElement | null>(null)
const graphLayout = ref<GraphLayout>('cose')
const cy = ref<Core | null>(null)
const selectedItem = ref<SelectedGraphItem | null>(null)
const selectedNodeMemory = ref<Memory | null>(null)
const selectedNodeLoading = ref(false)
const selectedNodeExplain = ref<MemoryGraphExplainResponse | null>(null)
const selectedNodeExplainLoading = ref(false)
const feedbackSaving = ref(false)
const graphZoom = ref(1)

const activeNodes = computed(() => nodes.value.filter(node => ['active', 'ai_review', 'pending'].includes(node.status)).length)
const archivedNodes = computed(() => nodes.value.length - activeNodes.value)
const relationTypes = computed(() => Array.from(new Set(edges.value.map(edge => edge.relation))).sort())
const nodeById = computed(() => new Map(nodes.value.map(node => [node.id, node])))

const filteredNodes = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return nodes.value
  return nodes.value.filter(node => {
    return (
      node.title.toLowerCase().includes(query)
      || node.type.toLowerCase().includes(query)
      || node.layer.toLowerCase().includes(query)
      || node.status.toLowerCase().includes(query)
      || node.tags.some(tag => tag.toLowerCase().includes(query))
    )
  })
})

const filteredNodeIds = computed(() => new Set(filteredNodes.value.map(node => node.id)))
const filteredGraphEdges = computed(() => {
  return edges.value.filter(edge => {
    if (relationFilter.value && edge.relation !== relationFilter.value) return false
    return filteredNodeIds.value.has(edge.source_memory_id) && filteredNodeIds.value.has(edge.target_memory_id)
  })
})

const degreeByNodeId = computed(() => {
  const degree = new Map<string, number>()
  filteredGraphEdges.value.forEach(edge => {
    degree.set(edge.source_memory_id, (degree.get(edge.source_memory_id) || 0) + 1)
    degree.set(edge.target_memory_id, (degree.get(edge.target_memory_id) || 0) + 1)
  })
  return degree
})

const visibleNodes = computed(() => {
  return [...filteredNodes.value]
    .sort((a, b) => {
      const degreeDiff = (degreeByNodeId.value.get(b.id) || 0) - (degreeByNodeId.value.get(a.id) || 0)
      if (degreeDiff !== 0) return degreeDiff
      return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    })
    .slice(0, nodeLimit.value)
})
const visibleNodeIds = computed(() => new Set(visibleNodes.value.map(node => node.id)))
const visibleEdges = computed(() => {
  return edges.value.filter(edge => {
    if (relationFilter.value && edge.relation !== relationFilter.value) return false
    return visibleNodeIds.value.has(edge.source_memory_id) && visibleNodeIds.value.has(edge.target_memory_id)
  })
})

const selectedNodeEdges = computed(() => {
  if (!selectedItem.value || selectedItem.value.kind !== 'node') return []
  const nodeId = selectedItem.value.node.id
  return visibleEdges.value.filter(edge => edge.source_memory_id === nodeId || edge.target_memory_id === nodeId)
})

const selectedNeighborNodes = computed(() => {
  if (!selectedItem.value || selectedItem.value.kind !== 'node') return []
  const nodeId = selectedItem.value.node.id
  const ids = new Set<string>()
  selectedNodeEdges.value.forEach(edge => {
    if (edge.source_memory_id !== nodeId) ids.add(edge.source_memory_id)
    if (edge.target_memory_id !== nodeId) ids.add(edge.target_memory_id)
  })
  return Array.from(ids)
    .map(id => nodeById.value.get(id))
    .filter((node): node is MemoryGraphNode => Boolean(node))
})

const selectedAiGraph = computed(() => {
  if (!selectedItem.value) return aiReadableGraph.value
  if (selectedItem.value.kind === 'edge') {
    const edge = selectedItem.value.edge
    return JSON.stringify({
      selected: 'edge',
      edge: edgePayload(edge),
      source: nodePayload(nodeById.value.get(edge.source_memory_id)),
      target: nodePayload(nodeById.value.get(edge.target_memory_id)),
    }, null, 2)
  }

  const node = selectedItem.value.node
  const relatedNodeIds = new Set<string>([node.id])
  selectedNodeEdges.value.forEach(edge => {
    relatedNodeIds.add(edge.source_memory_id)
    relatedNodeIds.add(edge.target_memory_id)
  })
  return JSON.stringify({
    selected: 'node',
    node: nodePayload(node),
    memory_content: selectedNodeMemory.value?.content || null,
    graph_explanation: selectedNodeExplain.value
      ? {
          temporal_assessment: selectedNodeExplain.value.temporal_assessment,
          feedback_summary: selectedNodeExplain.value.feedback_summary,
          ai_summary: selectedNodeExplain.value.ai_summary,
          incoming_edges: selectedNodeExplain.value.incoming_edges.map(edgePayload),
          outgoing_edges: selectedNodeExplain.value.outgoing_edges.map(edgePayload),
          related_memories: selectedNodeExplain.value.related_memories.map(nodePayload).filter(Boolean),
        }
      : null,
    neighbors: Array.from(relatedNodeIds)
      .filter(id => id !== node.id)
      .map(id => nodePayload(nodeById.value.get(id)))
      .filter(Boolean),
    edges: selectedNodeEdges.value.map(edgePayload),
  }, null, 2)
})

const aiReadableGraph = computed(() => {
  const payload = {
    summary: {
      total_nodes: nodes.value.length,
      total_edges: edges.value.length,
      visible_nodes: visibleNodes.value.length,
      visible_edges: visibleEdges.value.length,
      filters: {
        include_inactive: includeInactive.value,
        query: searchQuery.value || null,
        relation: relationFilter.value || null,
        node_limit: nodeLimit.value,
      },
    },
    nodes: visibleNodes.value.map(node => ({
      id: node.id,
      title: node.title,
      type: node.type,
      layer: node.layer,
      status: node.status,
      sleep_state: node.sleep_state,
      tags: node.tags,
    })),
    edges: visibleEdges.value.map(edge => ({
      id: edge.id,
      relation: edge.relation,
      source_memory_id: edge.source_memory_id,
      source_title: findNodeTitle(edge.source_memory_id),
      target_memory_id: edge.target_memory_id,
      target_title: findNodeTitle(edge.target_memory_id),
      reason: edge.reason,
      sleep_session_id: edge.sleep_session_id,
    })),
  }
  return JSON.stringify(payload, null, 2)
})

onMounted(async () => {
  await loadData()
  await nextTick()
  renderGraph()
})

onBeforeUnmount(() => {
  destroyGraph()
})

watch([visibleNodes, visibleEdges, viewMode, graphLayout], async () => {
  if (viewMode.value !== 'graph') return
  await nextTick()
  renderGraph()
})

async function loadData(): Promise<void> {
  loading.value = true
  try {
    const [sessionRes, graphRes] = await Promise.all([
      api.listSleepSessions({
        status: statusFilter.value || undefined,
        limit: 50,
      }),
      api.getMemoryGraph({ include_inactive: includeInactive.value }),
    ])
    sessions.value = sessionRes.items
    nodes.value = graphRes.nodes
    edges.value = graphRes.edges
    selectedItem.value = null
    selectedNodeMemory.value = null
    selectedNodeExplain.value = null
  } finally {
    loading.value = false
  }
}

async function copyAiGraph(): Promise<void> {
  await navigator.clipboard.writeText(aiReadableGraph.value)
  copied.value = true
  window.setTimeout(() => {
    copied.value = false
  }, 1200)
}

async function loadSelectedNodeMemory(nodeId: string): Promise<void> {
  selectedNodeLoading.value = true
  selectedNodeMemory.value = null
  try {
    selectedNodeMemory.value = await api.getMemory(nodeId)
  } catch {
    selectedNodeMemory.value = null
  } finally {
    selectedNodeLoading.value = false
  }
}

async function loadSelectedNodeExplain(nodeId: string): Promise<void> {
  selectedNodeExplainLoading.value = true
  selectedNodeExplain.value = null
  try {
    selectedNodeExplain.value = await api.explainMemoryGraph(nodeId, { include_inactive: true })
  } catch {
    selectedNodeExplain.value = null
  } finally {
    selectedNodeExplainLoading.value = false
  }
}

async function submitFeedback(rating: string): Promise<void> {
  if (!selectedItem.value || selectedItem.value.kind !== 'node') return
  feedbackSaving.value = true
  try {
    await api.createMemoryFeedback({
      memory_id: selectedItem.value.node.id,
      rating,
      used_by: 'user',
      confidence: 'high',
      source: 'web',
      task_context: 'observability graph review',
    })
    await loadSelectedNodeExplain(selectedItem.value.node.id)
  } finally {
    feedbackSaving.value = false
  }
}

function formatDate(value: string | null): string {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function shortId(value: string): string {
  return value.slice(0, 8)
}

function findNodeTitle(id: string): string {
  return nodeById.value.get(id)?.title || shortId(id)
}

function nodePayload(node: MemoryGraphNode | undefined): object | null {
  if (!node) return null
  return {
    id: node.id,
    title: node.title,
    type: node.type,
    layer: node.layer,
    status: node.status,
    sleep_state: node.sleep_state,
    tags: node.tags,
    is_core: node.is_core,
    superseded_by: node.superseded_by,
    derived_from: node.derived_from,
  }
}

function edgePayload(edge: MemoryGraphEdge): object {
  return {
    id: edge.id,
    relation: edge.relation,
    source_memory_id: edge.source_memory_id,
    source_title: findNodeTitle(edge.source_memory_id),
    target_memory_id: edge.target_memory_id,
    target_title: findNodeTitle(edge.target_memory_id),
    reason: edge.reason,
    sleep_session_id: edge.sleep_session_id,
  }
}

function nodeColor(node: MemoryGraphNode): string {
  if (node.status === 'archived' || node.status === 'deprecated') return '#64748b'
  if (node.layer === 'L0') return '#f87171'
  if (node.layer === 'L1') return '#facc15'
  if (node.type === 'project') return '#2dd4bf'
  if (node.type === 'method') return '#60a5fa'
  return '#38bdf8'
}

function buildElements(): ElementDefinition[] {
  return [
    ...visibleNodes.value.map(node => ({
      group: 'nodes' as const,
      data: {
        id: node.id,
        label: node.title,
        type: node.type,
        layer: node.layer,
        status: node.status,
        color: nodeColor(node),
      },
      classes: node.status === 'archived' || node.status === 'deprecated' ? 'inactive' : '',
    })),
    ...visibleEdges.value.map(edge => ({
      group: 'edges' as const,
      data: {
        id: edge.id,
        source: edge.source_memory_id,
        target: edge.target_memory_id,
        label: edge.relation,
        relation: edge.relation,
      },
    })),
  ]
}

function renderGraph(): void {
  if (!graphContainer.value || loading.value || viewMode.value !== 'graph') return
  destroyGraph()
  cy.value = cytoscape({
    container: graphContainer.value,
    elements: buildElements(),
    minZoom: 0.2,
    maxZoom: 3,
    wheelSensitivity: 0.45,
    style: [
      {
        selector: 'node',
        style: {
          'background-color': 'data(color)',
          'border-color': '#0f172a',
          'border-width': 2,
          color: '#e2e8f0',
          'font-size': 9,
          label: 'data(label)',
          'min-zoomed-font-size': 7,
          'text-max-width': '110px',
          'text-valign': 'bottom',
          'text-wrap': 'ellipsis',
          'text-margin-y': 8,
          'text-opacity': 0.88,
          width: 24,
          height: 24,
        },
      },
      {
        selector: 'node[layer = "L1"]',
        style: { width: 34, height: 34, 'font-size': 10 },
      },
      {
        selector: 'node[layer = "L0"]',
        style: { width: 42, height: 42, 'font-size': 11 },
      },
      {
        selector: 'node.inactive',
        style: { opacity: 0.55 },
      },
      {
        selector: 'edge',
        style: {
          'curve-style': 'bezier',
          color: '#94a3b8',
          'font-size': 8,
          label: 'data(label)',
          'line-color': '#64748b',
          opacity: 0.82,
          'target-arrow-color': '#64748b',
          'target-arrow-shape': 'triangle',
          'text-background-color': '#020617',
          'text-background-opacity': 0.8,
          'text-background-padding': '2px',
          'text-rotation': 'autorotate',
          width: 1.6,
        },
      },
      {
        selector: 'node[labelHidden]',
        style: {
          'text-opacity': 0,
        },
      },
      {
        selector: 'edge[labelHidden]',
        style: {
          'text-opacity': 0,
        },
      },
      {
        selector: '.dimmed',
        style: { opacity: 0.38, 'text-opacity': 0.25 },
      },
      {
        selector: 'node.selected-node',
        style: {
          'border-color': '#f8fafc',
          'border-width': 4,
          'overlay-color': '#38bdf8',
          'overlay-opacity': 0.14,
          'overlay-padding': 7,
          opacity: 1,
          'text-opacity': 1,
        },
      },
      {
        selector: 'node.neighbor-node',
        style: {
          'border-color': '#38bdf8',
          'border-width': 3,
          opacity: 0.92,
          'text-opacity': 0.85,
        },
      },
      {
        selector: 'edge.focus-edge',
        style: {
          'line-color': '#38bdf8',
          'target-arrow-color': '#38bdf8',
          opacity: 0.92,
          width: 2.2,
        },
      },
      {
        selector: 'edge.selected-edge',
        style: {
          'line-color': '#38bdf8',
          'target-arrow-color': '#38bdf8',
          opacity: 1,
          width: 2.8,
        },
      },
    ],
    layout: {
      name: graphLayout.value,
      animate: false,
      fit: true,
      padding: 48,
      nodeRepulsion: 8000,
      idealEdgeLength: 120,
    },
  })

  cy.value.on('tap', 'node', (event: EventObject) => {
    const nodeId = event.target.id()
    const node = nodeById.value.get(nodeId)
    if (!node) return
    selectedItem.value = { kind: 'node', node }
    void loadSelectedNodeMemory(nodeId)
    void loadSelectedNodeExplain(nodeId)
    highlightNode(nodeId)
  })

  cy.value.on('tap', 'edge', (event: EventObject) => {
    const edgeId = event.target.id()
    const edge = visibleEdges.value.find(item => item.id === edgeId)
    if (!edge) return
    selectedItem.value = { kind: 'edge', edge }
    selectedNodeMemory.value = null
    selectedNodeExplain.value = null
    highlightEdge(edgeId)
  })

  cy.value.on('tap', (event: EventObject) => {
    if (event.target === cy.value) {
      selectedItem.value = null
      selectedNodeMemory.value = null
      selectedNodeExplain.value = null
      clearHighlight()
    }
  })

  cy.value.on('zoom', () => {
    syncGraphZoom()
  })
  syncGraphZoom()
}

function destroyGraph(): void {
  if (!cy.value) return
  cy.value.destroy()
  cy.value = null
}

function clearHighlight(): void {
  if (!cy.value) return
  cy.value.elements().removeClass('dimmed selected-node selected-edge neighbor-node focus-edge')
}

function highlightNode(nodeId: string): void {
  if (!cy.value) return
  const node = cy.value.getElementById(nodeId)
  const neighborhood = node.closedNeighborhood()
  clearHighlight()
  cy.value.elements().difference(neighborhood).addClass('dimmed')
  node.connectedEdges().addClass('focus-edge')
  node.neighborhood('node').addClass('neighbor-node')
  node.addClass('selected-node')
}

function highlightEdge(edgeId: string): void {
  if (!cy.value) return
  const edge = cy.value.getElementById(edgeId)
  clearHighlight()
  const focused = edge.union(edge.connectedNodes())
  cy.value.elements().difference(focused).addClass('dimmed')
  edge.connectedNodes().addClass('neighbor-node')
  edge.addClass('selected-edge')
}

function syncGraphZoom(): void {
  if (!cy.value) return
  graphZoom.value = cy.value.zoom()
  const hideLabels = graphZoom.value < 0.72
  cy.value.nodes().toggleClass('labelHidden', hideLabels)
  cy.value.edges().toggleClass('labelHidden', graphZoom.value < 1.05)
}

function fitGraph(): void {
  if (!cy.value) return
  cy.value.fit(undefined, 48)
  syncGraphZoom()
}

function zoomGraph(delta: number): void {
  if (!cy.value) return
  const current = cy.value.zoom()
  const next = Math.max(0.2, Math.min(3, current * delta))
  cy.value.zoom({
    level: next,
    renderedPosition: {
      x: cy.value.width() / 2,
      y: cy.value.height() / 2,
    },
  })
  syncGraphZoom()
}
</script>

<template>
  <div class="space-y-6">
    <DiagnosticsTabs />
    <div class="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">Memory Observability</h1>
        <p class="mt-1 text-sm text-slate-400">Sleep sessions, graph relationships, and AI-readable graph slices.</p>
      </div>
      <button class="btn-secondary" :disabled="loading" @click="loadData">
        Refresh
      </button>
    </div>

    <div class="grid grid-cols-1 gap-4 sm:grid-cols-4">
      <div class="card">
        <div class="text-2xl font-bold text-blue-400">{{ sessions.length }}</div>
        <div class="text-sm text-slate-400">Sleep sessions</div>
      </div>
      <div class="card">
        <div class="text-2xl font-bold text-emerald-400">{{ activeNodes }}</div>
        <div class="text-sm text-slate-400">Active nodes</div>
      </div>
      <div class="card">
        <div class="text-2xl font-bold text-slate-400">{{ archivedNodes }}</div>
        <div class="text-sm text-slate-400">Inactive nodes</div>
      </div>
      <div class="card">
        <div class="text-2xl font-bold text-cyan-400">{{ edges.length }}</div>
        <div class="text-sm text-slate-400">Relation edges</div>
      </div>
    </div>

    <div class="card space-y-4">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center">
        <div class="inline-flex rounded-lg border border-slate-700 bg-slate-900 p-1">
          <button
            v-for="mode in ['graph', 'list', 'ai']"
            :key="mode"
            :class="[
              'rounded-md px-3 py-1.5 text-sm transition-colors',
              viewMode === mode ? 'bg-blue-600 text-white' : 'text-slate-300 hover:bg-slate-700'
            ]"
            @click="viewMode = mode as ViewMode"
          >
            {{ mode }}
          </button>
        </div>
        <input
          v-model="searchQuery"
          class="input-field lg:max-w-xs"
          type="search"
          placeholder="Filter nodes by title, tag, type..."
        />
        <select v-model="relationFilter" class="input-field w-auto min-w-[160px]">
          <option value="">All relations</option>
          <option v-for="relation in relationTypes" :key="relation" :value="relation">{{ relation }}</option>
        </select>
        <select v-model.number="nodeLimit" class="input-field w-auto min-w-[140px]">
          <option :value="40">40 nodes</option>
          <option :value="80">80 nodes</option>
          <option :value="150">150 nodes</option>
          <option :value="300">300 nodes</option>
        </select>
        <select v-model="graphLayout" class="input-field w-auto min-w-[140px]">
          <option value="cose">cose layout</option>
          <option value="circle">circle layout</option>
          <option value="grid">grid layout</option>
        </select>
      </div>
      <div class="flex flex-col gap-3 sm:flex-row sm:items-center">
        <select v-model="statusFilter" class="input-field w-auto min-w-[180px]" @change="loadData">
          <option value="">All sleep statuses</option>
          <option value="draft">draft</option>
          <option value="proposed">proposed</option>
          <option value="approved">approved</option>
          <option value="applied">applied</option>
          <option value="rejected">rejected</option>
        </select>
        <label class="flex items-center gap-2 text-sm text-slate-300">
          <input
            v-model="includeInactive"
            type="checkbox"
            class="h-4 w-4 rounded border-slate-600 bg-slate-900"
            @change="loadData"
          />
          Include archived/deprecated memories
        </label>
        <span class="text-sm text-slate-400">
          showing {{ visibleNodes.length }}/{{ filteredNodes.length }} nodes, {{ visibleEdges.length }}/{{ edges.length }} edges
        </span>
      </div>
    </div>

    <div v-if="loading" class="grid gap-4">
      <div v-for="i in 3" :key="i" class="card animate-pulse">
        <div class="h-5 w-2/3 rounded bg-slate-700" />
        <div class="mt-3 h-12 rounded bg-slate-700" />
      </div>
    </div>

    <template v-else>
      <section v-if="viewMode === 'graph'" class="space-y-4">
        <div class="flex flex-wrap items-center gap-2">
          <button class="btn-secondary px-3 py-1.5 text-xs" @click="zoomGraph(1.35)">Zoom in</button>
          <button class="btn-secondary px-3 py-1.5 text-xs" @click="zoomGraph(0.74)">Zoom out</button>
          <button class="btn-secondary px-3 py-1.5 text-xs" @click="fitGraph">Fit</button>
          <span class="text-xs text-slate-400">zoom {{ graphZoom.toFixed(2) }}x</span>
        </div>
        <div class="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div class="card overflow-hidden p-0">
            <div ref="graphContainer" class="h-[640px] w-full bg-slate-950" />
          </div>

          <aside class="card h-[640px] overflow-auto">
            <div v-if="!selectedItem" class="space-y-3">
              <h2 class="text-base font-semibold text-slate-100">Selection Details</h2>
              <p class="text-sm text-slate-400">
                Click a node or edge in the graph to inspect metadata, relation direction, and AI-readable context.
              </p>
              <div class="rounded-lg border border-slate-700 bg-slate-900 p-3 text-xs text-slate-400">
                Nodes are colored by layer/type/status. Selected nodes highlight one-hop neighbors; selected edges highlight their source and target.
              </div>
            </div>

            <div v-else-if="selectedItem.kind === 'node'" class="space-y-4">
              <div>
                <h2 class="text-base font-semibold text-slate-100">{{ selectedItem.node.title }}</h2>
                <p class="mt-1 font-mono text-xs text-slate-500">{{ selectedItem.node.id }}</p>
              </div>
              <div class="flex flex-wrap gap-1.5">
                <Badge :color="MEMORY_TYPE_COLORS[selectedItem.node.type]" size="sm">{{ selectedItem.node.type }}</Badge>
                <Badge :color="LAYER_COLORS[selectedItem.node.layer]" size="sm">{{ selectedItem.node.layer }}</Badge>
                <Badge :color="STATUS_COLORS[selectedItem.node.status]" size="sm">{{ selectedItem.node.status }}</Badge>
                <span class="rounded bg-slate-700/60 px-1.5 py-0.5 text-xs text-slate-300">
                  sleep: {{ selectedItem.node.sleep_state }}
                </span>
                <span v-if="selectedItem.node.is_core" class="rounded bg-amber-500/20 px-1.5 py-0.5 text-xs text-amber-300">
                  core
                </span>
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">Tags</h3>
                <div class="mt-2 flex flex-wrap gap-1.5">
                  <span
                    v-for="tag in selectedItem.node.tags"
                    :key="tag"
                    class="rounded bg-slate-700/60 px-1.5 py-0.5 text-xs text-slate-300"
                  >
                    #{{ tag }}
                  </span>
                </div>
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">Memory Content</h3>
                <div v-if="selectedNodeLoading" class="mt-2 text-sm text-slate-400">
                  Loading memory details...
                </div>
                <pre v-else class="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{{ selectedNodeMemory?.content || 'No content loaded.' }}</pre>
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">Graph Explanation</h3>
                <div v-if="selectedNodeExplainLoading" class="mt-2 text-sm text-slate-400">
                  Loading graph explanation...
                </div>
                <div v-else-if="selectedNodeExplain" class="mt-2 rounded-lg border border-slate-700 bg-slate-900 p-3">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="rounded bg-cyan-500/20 px-2 py-0.5 text-xs text-cyan-300">
                      {{ selectedNodeExplain.temporal_assessment.classification }}
                    </span>
                    <span class="rounded bg-slate-700/70 px-2 py-0.5 text-xs text-slate-300">
                      confidence: {{ selectedNodeExplain.temporal_assessment.confidence }}
                    </span>
                    <span class="rounded bg-slate-700/70 px-2 py-0.5 text-xs text-slate-300">
                      in/out: {{ selectedNodeExplain.incoming_edges.length }}/{{ selectedNodeExplain.outgoing_edges.length }}
                    </span>
                  </div>
                  <p class="mt-2 text-xs text-slate-400">
                    {{ selectedNodeExplain.temporal_assessment.note }}
                  </p>
                  <div v-if="selectedNodeExplain.temporal_assessment.signals.length" class="mt-2">
                    <div class="text-xs text-slate-500">Signals</div>
                    <div class="mt-1 flex flex-wrap gap-1.5">
                      <span
                        v-for="signal in selectedNodeExplain.temporal_assessment.signals"
                        :key="signal"
                        class="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-200"
                      >
                        {{ signal }}
                      </span>
                    </div>
                  </div>
                  <div v-if="selectedNodeExplain.temporal_assessment.stable_signals.length" class="mt-2">
                    <div class="text-xs text-slate-500">Stable Signals</div>
                    <div class="mt-1 flex flex-wrap gap-1.5">
                      <span
                        v-for="signal in selectedNodeExplain.temporal_assessment.stable_signals"
                        :key="signal"
                        class="rounded bg-emerald-500/15 px-1.5 py-0.5 text-xs text-emerald-200"
                      >
                        {{ signal }}
                      </span>
                    </div>
                  </div>
                  <div class="mt-3 border-t border-slate-700 pt-3">
                    <div class="flex items-center justify-between gap-3">
                      <div class="text-xs text-slate-500">
                        Feedback: {{ selectedNodeExplain.feedback_summary.total }}
                      </div>
                      <div v-if="selectedNodeExplain.feedback_summary.last_feedback_at" class="text-xs text-slate-500">
                        {{ formatDate(selectedNodeExplain.feedback_summary.last_feedback_at) }}
                      </div>
                    </div>
                    <div v-if="Object.keys(selectedNodeExplain.feedback_summary.ratings).length" class="mt-2 flex flex-wrap gap-1.5">
                      <span
                        v-for="(count, rating) in selectedNodeExplain.feedback_summary.ratings"
                        :key="rating"
                        class="rounded bg-slate-700/60 px-1.5 py-0.5 text-xs text-slate-300"
                      >
                        {{ rating }}: {{ count }}
                      </span>
                    </div>
                    <div class="mt-2 flex flex-wrap gap-1.5">
                      <button class="rounded bg-emerald-500/15 px-2 py-1 text-xs text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-50" :disabled="feedbackSaving" @click="submitFeedback('helpful')">
                        Helpful
                      </button>
                      <button class="rounded bg-cyan-500/15 px-2 py-1 text-xs text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50" :disabled="feedbackSaving" @click="submitFeedback('important')">
                        Important
                      </button>
                      <button class="rounded bg-amber-500/15 px-2 py-1 text-xs text-amber-200 hover:bg-amber-500/25 disabled:opacity-50" :disabled="feedbackSaving" @click="submitFeedback('outdated')">
                        Outdated
                      </button>
                      <button class="rounded bg-orange-500/15 px-2 py-1 text-xs text-orange-200 hover:bg-orange-500/25 disabled:opacity-50" :disabled="feedbackSaving" @click="submitFeedback('conflicting')">
                        Conflicting
                      </button>
                      <button class="rounded bg-red-500/15 px-2 py-1 text-xs text-red-200 hover:bg-red-500/25 disabled:opacity-50" :disabled="feedbackSaving" @click="submitFeedback('wrong')">
                        Wrong
                      </button>
                      <button class="rounded bg-slate-600/40 px-2 py-1 text-xs text-slate-300 hover:bg-slate-600/60 disabled:opacity-50" :disabled="feedbackSaving" @click="submitFeedback('irrelevant')">
                        Irrelevant
                      </button>
                    </div>
                  </div>
                </div>
                <div v-else class="mt-2 text-sm text-slate-400">
                  No graph explanation loaded.
                </div>
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">Neighbor Nodes</h3>
                <div v-if="selectedNeighborNodes.length === 0" class="mt-2 text-sm text-slate-400">
                  No visible neighbor nodes.
                </div>
                <div v-else class="mt-2 space-y-2">
                  <div
                    v-for="neighbor in selectedNeighborNodes"
                    :key="neighbor.id"
                    class="rounded-lg border border-slate-700 bg-slate-900 p-2"
                  >
                    <div class="truncate text-sm text-slate-100">{{ neighbor.title }}</div>
                    <div class="mt-1 flex flex-wrap gap-1.5">
                      <Badge :color="MEMORY_TYPE_COLORS[neighbor.type]" size="sm">{{ neighbor.type }}</Badge>
                      <Badge :color="LAYER_COLORS[neighbor.layer]" size="sm">{{ neighbor.layer }}</Badge>
                      <Badge :color="STATUS_COLORS[neighbor.status]" size="sm">{{ neighbor.status }}</Badge>
                    </div>
                  </div>
                </div>
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">One-hop Relations</h3>
                <div v-if="selectedNodeEdges.length === 0" class="mt-2 text-sm text-slate-400">
                  No visible relations.
                </div>
                <div v-else class="mt-2 space-y-2">
                  <div v-for="edge in selectedNodeEdges" :key="edge.id" class="rounded-lg border border-slate-700 bg-slate-900 p-2">
                    <div class="text-xs text-cyan-300">{{ edge.relation }}</div>
                    <div class="mt-1 text-xs text-slate-300">
                      {{ findNodeTitle(edge.source_memory_id) }} → {{ findNodeTitle(edge.target_memory_id) }}
                    </div>
                    <p v-if="edge.reason" class="mt-1 text-xs text-slate-500">{{ edge.reason }}</p>
                  </div>
                </div>
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">AI Context</h3>
                <pre class="mt-2 max-h-52 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{{ selectedAiGraph }}</pre>
              </div>
            </div>

            <div v-else class="space-y-4">
              <div>
                <h2 class="text-base font-semibold text-slate-100">{{ selectedItem.edge.relation }}</h2>
                <p class="mt-1 font-mono text-xs text-slate-500">{{ selectedItem.edge.id }}</p>
              </div>
              <div class="rounded-lg border border-slate-700 bg-slate-900 p-3">
                <div class="text-xs text-slate-500">Source</div>
                <div class="mt-1 text-sm text-slate-100">{{ findNodeTitle(selectedItem.edge.source_memory_id) }}</div>
                <div class="mt-3 text-xs text-slate-500">Target</div>
                <div class="mt-1 text-sm text-slate-100">{{ findNodeTitle(selectedItem.edge.target_memory_id) }}</div>
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">Reason</h3>
                <p class="mt-2 text-sm text-slate-400">{{ selectedItem.edge.reason || 'No reason recorded.' }}</p>
              </div>
              <div class="text-xs text-slate-500">
                sleep session: {{ selectedItem.edge.sleep_session_id ? shortId(selectedItem.edge.sleep_session_id) : '-' }}
              </div>
              <div>
                <h3 class="text-sm font-medium text-slate-200">AI Context</h3>
                <pre class="mt-2 max-h-72 overflow-auto rounded-lg bg-slate-950 p-3 text-xs text-slate-300">{{ selectedAiGraph }}</pre>
              </div>
            </div>
          </aside>
        </div>
      </section>

      <section v-else-if="viewMode === 'ai'" class="space-y-3">
        <div class="flex items-center justify-between">
          <h2 class="text-base font-semibold text-slate-100">AI-readable Graph Slice</h2>
          <button class="btn-secondary" @click="copyAiGraph">{{ copied ? 'Copied' : 'Copy JSON' }}</button>
        </div>
        <pre class="max-h-[620px] overflow-auto rounded-lg border border-slate-700 bg-slate-950 p-4 text-xs text-slate-200">{{ selectedAiGraph }}</pre>
      </section>

      <template v-else>
        <section class="space-y-3">
          <h2 class="text-base font-semibold text-slate-100">Sleep Sessions</h2>
          <div v-if="sessions.length === 0" class="card text-sm text-slate-400">
            No sleep sessions found.
          </div>
          <div v-else class="space-y-3">
            <div v-for="session in sessions" :key="session.id" class="card">
              <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div class="min-w-0">
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="font-mono text-sm text-slate-200">{{ shortId(session.id) }}</span>
                    <span class="rounded border border-blue-500/30 bg-blue-500/20 px-2 py-0.5 text-xs text-blue-300">
                      {{ session.status }}
                    </span>
                    <span class="rounded border border-slate-600 bg-slate-700 px-2 py-0.5 text-xs text-slate-300">
                      {{ session.mode }}
                    </span>
                  </div>
                  <p class="mt-2 text-sm text-slate-400">
                    candidates: {{ session.candidate_count }} · project: {{ session.project_id || 'global/all' }}
                  </p>
                </div>
                <div class="text-right text-xs text-slate-500">
                  <div>created: {{ formatDate(session.created_at) }}</div>
                  <div>applied: {{ formatDate(session.applied_at) }}</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section class="grid grid-cols-1 gap-6 xl:grid-cols-2">
          <div class="space-y-3">
            <h2 class="text-base font-semibold text-slate-100">Memory Nodes</h2>
            <div v-if="visibleNodes.length === 0" class="card text-sm text-slate-400">
              No memory nodes found.
            </div>
            <div v-else class="space-y-3">
              <div v-for="node in visibleNodes" :key="node.id" class="card">
                <div class="min-w-0">
                  <h3 class="truncate text-sm font-medium text-slate-100">{{ node.title }}</h3>
                  <div class="mt-2 flex flex-wrap gap-1.5">
                    <Badge :color="MEMORY_TYPE_COLORS[node.type]" size="sm">{{ node.type }}</Badge>
                    <Badge :color="LAYER_COLORS[node.layer]" size="sm">{{ node.layer }}</Badge>
                    <Badge :color="STATUS_COLORS[node.status]" size="sm">{{ node.status }}</Badge>
                    <span class="rounded bg-slate-700/60 px-1.5 py-0.5 text-xs text-slate-300">
                      sleep: {{ node.sleep_state }}
                    </span>
                    <span v-if="node.is_core" class="rounded bg-amber-500/20 px-1.5 py-0.5 text-xs text-amber-300">
                      core
                    </span>
                  </div>
                  <p class="mt-2 truncate font-mono text-xs text-slate-500">{{ node.id }}</p>
                </div>
              </div>
            </div>
          </div>

          <div class="space-y-3">
            <h2 class="text-base font-semibold text-slate-100">Relation Edges</h2>
            <div v-if="visibleEdges.length === 0" class="card text-sm text-slate-400">
              No relation edges found.
            </div>
            <div v-else class="space-y-3">
              <div v-for="edge in visibleEdges" :key="edge.id" class="card">
                <div class="flex flex-wrap items-center gap-2 text-sm">
                  <span class="max-w-[12rem] truncate text-slate-100">{{ findNodeTitle(edge.source_memory_id) }}</span>
                  <span class="rounded bg-cyan-500/20 px-2 py-0.5 text-xs text-cyan-300">{{ edge.relation }}</span>
                  <span class="max-w-[12rem] truncate text-slate-100">{{ findNodeTitle(edge.target_memory_id) }}</span>
                </div>
                <p v-if="edge.reason" class="mt-2 text-xs text-slate-400">{{ edge.reason }}</p>
                <p class="mt-2 font-mono text-xs text-slate-500">
                  session: {{ edge.sleep_session_id ? shortId(edge.sleep_session_id) : '-' }}
                </p>
              </div>
            </div>
          </div>
        </section>
      </template>
    </template>
  </div>
</template>

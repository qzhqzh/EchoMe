export type MemoryType =
  | 'identity'
  | 'guardrail'
  | 'reasoning'
  | 'method'
  | 'stack'
  | 'style'
  | 'decision'
  | 'context'
  | 'template'
  | 'project'

export type MemoryLayer = 'L0' | 'L1' | 'L2'

export type MemoryStatus = 'active' | 'ai_review' | 'pending' | 'deprecated' | 'archived'

export type MemorySource = 'manual' | 'ai_suggested' | 'imported'

export interface Scope {
  global: boolean
  projects: string[]
  exclude_projects: string[]
}

export interface Memory {
  id: string
  title: string
  content: string
  type: MemoryType
  layer: MemoryLayer
  priority: number
  tags: string[]
  status: MemoryStatus
  scope: Scope
  source: MemorySource
  token_count: number
  created_at: string
  updated_at: string
}

export interface MemoryListItem {
  id: string
  title: string
  type: MemoryType
  layer: MemoryLayer
  priority: number
  tags: string[]
  status: MemoryStatus
  scope: Scope
  source: MemorySource
  token_count: number
  created_at: string
  updated_at: string
}

export interface MemoryListResponse {
  total: number
  offset: number
  limit: number
  items: MemoryListItem[]
}

export interface MemoryCreateRequest {
  title: string
  content: string
  type: MemoryType
  layer: MemoryLayer
  priority: number
  tags: string[]
  status: MemoryStatus
  scope: Scope
  source: MemorySource
}

export interface MemoryCreateResponse {
  id: string
  title: string
  token_count: number
  created_at: string
}

export interface SearchRequest {
  query: string
  type?: MemoryType | null
  layer?: MemoryLayer | null
  tags?: string[]
  project_id?: string | null
  top_k?: number
  min_score?: number
}

export interface SearchResultItem {
  id: string
  title: string
  content: string
  type: MemoryType
  layer: MemoryLayer
  score: number
  tags: string[]
}

export interface SearchResponse {
  results: SearchResultItem[]
  total_searched: number
}

export interface UnifiedContextResponse {
  schema_version: string
  scope: string
  task: string
  memories: Array<{
    id: string
    title: string
    content: string
    type: string
    layer: string
    status: string
    tags: string[]
    updated_at: string
    reliability?: ContextReliability
    intervention?: ContextIntervention
  }>
  unknowns: string[]
  retrieval_trace: Record<string, unknown>
  context_policy?: ContextPolicySummary
}

export interface ContextReliability {
  schema_version: number
  classification: string
  support_state: string
  confidence: number
  reason_codes: string[]
  evidence_refs: Array<Record<string, unknown>>
  source_watermark: Record<string, unknown>
  producer: string
  assessed_at: string
}

export interface ContextIntervention {
  action: 'inject' | 'inject_with_warning' | 'expand' | 'silent' | 'abstain'
  include: boolean
  reason: string
}

export interface ContextPolicySummary {
  schema_version: number
  requested_mode: 'off' | 'shadow' | 'enforce'
  effective_mode: 'off' | 'shadow' | 'enforce'
  enforced: boolean
  decision_counts: Record<string, number>
  would_exclude?: { memories: string[]; constraints: string[] }
  excluded?: { memories: string[]; constraints: string[] }
  source_mutation?: string
  fallback_reason?: string
}

export interface ContextPolicyReadiness {
  schema_version: 'echome.context-policy-readiness.v1'
  generated_at: string
  project_id: string | null
  window_days: number
  sample_limit: number | null
  evidence_truncated: boolean
  status: 'insufficient_data' | 'hold' | 'eligible_for_canary'
  eligible_for_canary: boolean
  auto_enforce: false
  reasons: string[]
  recommendations: string[]
  thresholds: Record<string, number>
  metrics: {
    observed_shadow_runs: number
    ignored_runs: number
    invalid_policy_trace_runs: number
    enforced_runs_excluded: number
    outcome_runs: number
    evaluated_intervention_runs: number
    intervention_runs: number
    would_exclude_runs: number
    would_exclude_items: number
    evaluation_coverage: number | null
    helpful_rate: number | null
    harmful_rate: number | null
    source_mutation_violations: number
    policy_effects: Record<string, number>
    task_outcomes: Record<string, number>
    latest_observed_at: string | null
  }
}

export interface Project {
  id: string
  name: string
  description: string | null
  git_remote: string | null
  path_patterns: string[]
}

export interface ProjectCreate {
  id: string
  name: string
  description?: string | null
  git_remote?: string | null
  path_patterns?: string[]
}

export type ConstraintStatus = 'proposed' | 'active' | 'uncertain' | 'superseded' | 'deprecated'
export type ConstraintStability = 'invariant' | 'evolving' | 'temporary'

export interface ProjectConstraint {
  id: string
  project_id: string
  title: string
  statement: string
  rationale: string | null
  kind: string
  status: ConstraintStatus
  stability: ConstraintStability
  confidence: number
  source: string
  tags: string[]
  version: number
  previous_version_id: string | null
  last_verified_at: string | null
  superseded_by: string | null
  created_at: string
  updated_at: string
  selection_reasons?: string[]
  reliability?: ContextReliability
  intervention?: ContextIntervention
}

export interface RetrievalReplayReport {
  schema_version: number
  generated_at: string
  read_only: boolean
  log_count: number
  scored_count: number
  regressed: number
  improved: number
  unchanged: number
  unscored: number
  average_top_k_jaccard: number | null
  passed: boolean
  items: Array<Record<string, unknown>>
}

export interface ProjectArtifact {
  id: string
  project_id: string
  logical_path: string
  kind: string
  title: string
  content_hash: string
  hash_algorithm: string
  size_bytes: number
  revision: number
  source_uri: string | null
  metadata: Record<string, unknown>
  status: string
  supersedes_id: string | null
  indexed_at: string
}

export interface ConstraintGraphEdge {
  id: string
  edge_type: 'constraint' | 'evidence'
  source_constraint_id?: string
  target_constraint_id?: string
  constraint_id?: string
  artifact_id?: string
  relation: string
  reason?: string | null
  locator?: Record<string, unknown>
  excerpt?: string | null
}

export interface ProjectKnowledgeGraph {
  project_id: string
  nodes: Array<(ProjectConstraint & { node_type: 'constraint' }) | (ProjectArtifact & { node_type: 'artifact' })>
  edges: ConstraintGraphEdge[]
}

export interface ProjectWorkspaceSummary {
  project: Project
  constraint_counts: Record<string, number>
  artifact_counts: Record<string, number>
  edge_count: number
  evidence_count: number
}

export interface ProjectQualityCase {
  id: string
  category: string
  query: string
  mode: 'local' | 'overview' | 'impact' | 'preflight'
  changed_paths?: string[]
  planned_actions?: string[]
  as_of?: string
  expected: Record<string, unknown>
}

export interface ProjectQualityCasesResponse {
  schema_version: number
  project_id: string
  description: string
  cases: ProjectQualityCase[]
}

export interface ProjectQualitySnapshot {
  id: string
  project_id: string
  dataset_schema_version: number
  k: number
  trigger: string
  dry_run: boolean
  passed: boolean
  metrics: Record<string, number | null>
  thresholds: Record<string, number>
  idempotency_key: string
  created_at: string
}

export interface ProjectAutomationGate {
  eligible: boolean
  feature_enabled: boolean
  proposal_only: boolean
  required_snapshots: number
  snapshot_ids: string[]
  failures: Array<Record<string, unknown>>
}

export interface ProjectAutomationRun {
  id: string
  project_id: string
  dry_run: boolean
  status: string
  gate: ProjectAutomationGate
  plans: {
    sleep: Array<Record<string, unknown>>
    revalidation: Array<Record<string, unknown>>
  }
  generated_proposal_ids: string[]
  apply_performed: boolean
  created_at: string
}

export interface ReviewItem extends MemoryListItem {
  ai_context?: string
  suggested_layer?: MemoryLayer
}

export interface ApproveRequest {
  layer?: string
  priority?: number
}

export interface SleepSessionItem {
  id: string
  project_id: string | null
  status: string
  mode: string
  candidate_count: number
  created_at: string
  updated_at: string
  applied_at: string | null
}

export interface SleepSessionsResponse {
  total: number
  offset: number
  limit: number
  items: SleepSessionItem[]
}

export interface MemoryGraphNode {
  id: string
  title: string
  type: MemoryType
  layer: MemoryLayer
  status: MemoryStatus
  tags: string[]
  is_core: boolean
  sleep_state: string
  superseded_by: string | null
  derived_from: unknown[]
  updated_at: string
}

export interface MemoryGraphEdge {
  id: string
  source_memory_id: string
  target_memory_id: string
  relation: string
  reason: string | null
  sleep_session_id: string | null
  created_by?: unknown
  created_at: string
}

export interface MemoryGraphResponse {
  nodes: MemoryGraphNode[]
  edges: MemoryGraphEdge[]
}

export interface TemporalAssessment {
  classification: string
  confidence: string
  signals: string[]
  stable_signals: string[]
  updated_age_days: number | null
  accessed_age_days: number | null
  project_activity_age_days: number | null
  note: string
}

export interface MemoryFeedbackSummary {
  total: number
  ratings: Record<string, number>
  last_feedback_at: string | null
}

export interface MemoryGraphExplainResponse {
  memory: MemoryGraphNode & {
    content?: string
    created_at?: string
    access_count?: number
    last_accessed_at?: string | null
  }
  temporal_assessment: TemporalAssessment
  incoming_edges: MemoryGraphEdge[]
  outgoing_edges: MemoryGraphEdge[]
  related_memories: MemoryGraphNode[]
  feedback_summary: MemoryFeedbackSummary
  ai_summary: Record<string, string>
}

export const MEMORY_TYPE_COLORS: Record<MemoryType, string> = {
  identity: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  guardrail: 'bg-red-500/20 text-red-300 border-red-500/30',
  reasoning: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
  method: 'bg-blue-500/20 text-blue-300 border-blue-500/30',
  stack: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  style: 'bg-pink-500/20 text-pink-300 border-pink-500/30',
  decision: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
  context: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30',
  template: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  project: 'bg-teal-500/20 text-teal-300 border-teal-500/30',
}

export const LAYER_COLORS: Record<MemoryLayer, string> = {
  L0: 'bg-red-500/20 text-red-300 border-red-500/30',
  L1: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30',
  L2: 'bg-slate-500/20 text-slate-300 border-slate-500/30',
}

export const STATUS_COLORS: Record<MemoryStatus, string> = {
  active: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  ai_review: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
  pending: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
  deprecated: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
  archived: 'bg-slate-600/20 text-slate-500 border-slate-600/30',
}

export const MEMORY_TYPES: MemoryType[] = [
  'identity', 'guardrail', 'reasoning', 'method', 'stack',
  'style', 'decision', 'context', 'template', 'project',
]

export const MEMORY_LAYERS: MemoryLayer[] = ['L0', 'L1', 'L2']

export const MEMORY_STATUSES: MemoryStatus[] = ['active', 'ai_review', 'pending', 'deprecated', 'archived']

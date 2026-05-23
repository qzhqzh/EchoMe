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

export interface ReviewItem extends MemoryListItem {
  ai_context?: string
  suggested_layer?: MemoryLayer
}

export interface ApproveRequest {
  layer?: string
  priority?: number
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

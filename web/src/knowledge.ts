import { api } from '@/api/client'

export type KnowledgeKind = 'project' | 'question' | 'entity' | 'relation' | 'predicate' | 'page' | 'source' | 'placement' | 'usage' | 'deliverable' | 'review' | 'acceptance'
export interface KRecord {
  id: string
  kind: KnowledgeKind
  revision: number
  status: string
  data: Record<string, any>
  overview_page_id?: string | null
  review_state: string
  warnings: string[]
  actor?: string
  current_revision?: number
  current_status?: string
  created_at: string
  updated_at: string
}
export interface KList { items: KRecord[]; total: number; next_offset: number | null }
export interface DirectoryEntry {
  entity_id: string
  placement_id: string | null
  name: string
  entity_kind: string
  summary: string
  child_count: number
  paths?: { names: string[]; incomplete: boolean }[]
}
export interface DirectoryPage { items: DirectoryEntry[]; total: number; next_offset: number | null; unplaced_total: number }
export interface KnowledgeNode {
  id: string; kind: KnowledgeKind; name: string; summary: string; status: string
  entity_kind?: string; revision: number; child_count: number
  via_id?: string; role?: string; knowledge_revision?: number
}
export interface KnowledgePath { nodes: KnowledgeNode[]; incomplete: boolean; placement_id?: string }
export interface KnowledgeChoice extends KnowledgeNode { path?: KnowledgePath }
export interface KnowledgeUse {
  usage_id: string; context: KnowledgeNode; project: KnowledgeNode | null; role: string
  knowledge_revision: number; current_revision: number; current_status: string; application_note: string
}
export interface KnowledgePage<T> { items: T[]; total: number; next_offset: number | null }
export interface KnowledgeSearchItem extends KnowledgeNode { category: string; snippet: string; locations: KnowledgePath[]; location_count: number }
export const searchCategories: Record<string, string> = { all: '全部', projects: '项目', questions: '问题', domains: '领域', knowledge: '知识', pages: '文档', sources: '资料', deliverables: '成果' }
export const entityNames: Record<string, string> = { topic: '领域', concept: '概念', method: '方法', tool: '工具', object: '对象' }
export const usageNames: Record<string, string> = { used: '使用', derived: '形成', to_research: '待研究' }
export const kindNames: Record<KnowledgeKind, string> = { project: '项目', question: '问题', entity: '知识', relation: '关系', predicate: '关系类型', page: '文档', source: '资料', placement: '目录位置', usage: '知识引用', deliverable: '成果', review: '审核', acceptance: '验收记录' }
export const stateNames: Record<string, string> = { draft: '草稿', active: '使用中', ready_for_review: '待验收', delivered: '已交付', open: '待处理', investigating: '研究中', resolved: '已解决', archived: '已归档', merged: '已合并', snoozed: '稍后处理', dismissed: '已忽略', disputed: '有争议', unreviewed: '未核对', reviewed: '已核对', submitted: '待验收', accepted: '已通过', rejected: '需改进', historical: '历史版本' }
export const issueNames: Record<string, string> = { duplicate: '可能重复', conflict: '结论冲突', overgeneralization: '范围过度泛化', page_mismatch: '正文与关系不一致', fragmentation: '划分过细', verification: '内容核对' }
export const titleOf = (record: KRecord): string => record.data.name || record.data.title || record.data.statement_md || record.data.label || kindNames[record.kind]
export const kb = {
  capture: (record: { kind: KnowledgeKind; data: Record<string, any> }, extra: { placement?: { parent_id: string | null }; context_id?: string; first_question?: string } = {}) => api.knowledge<{ record: KRecord; created: Record<string, string> }>('POST', '/capture', { record, ...extra }),
  choices: (params: { kinds: string; search?: string; exclude_id?: string; exclude_topics?: boolean; offset?: number; limit?: number }) => api.knowledge<KnowledgePage<KnowledgeChoice>>('GET', '/choices', undefined, params),
  removePlacement: (record: KRecord) => api.knowledge<KRecord>('POST', `/placements/${record.id}/remove`, { expected_revision: record.revision }),
  search: (params: { q: string; category?: string; offset?: number; limit?: number }) => api.knowledge<KnowledgePage<KnowledgeSearchItem> & { counts: Record<string, number> }>('GET', '/search', undefined, params),
  projectTree: (params: { parent_id?: string; independent?: boolean; offset?: number; limit?: number } = {}) => api.knowledge<KnowledgePage<KnowledgeNode> & { independent_total: number }>('GET', '/project-tree', undefined, params),
  connections: <T extends KnowledgePath | KnowledgeUse>(id: string, section: 'domains' | 'uses', offset = 0, limit = 3) => api.knowledge<KnowledgePage<T>>('GET', `/records/${id}/connections`, undefined, { section, offset, limit }),
  directory: (params: { parent_id?: string; unplaced?: boolean; search?: string; offset?: number; limit?: number } = {}) => api.knowledge<DirectoryPage>('GET', '/directory', undefined, params),
  list: (kind: KnowledgeKind, params: Record<string, any> = {}) => api.knowledge<KList>('GET', '/records', undefined, { kind, ...params }),
  query: (kind: KnowledgeKind, filters: Record<string, unknown>, params: Record<string, unknown> = {}) => api.knowledge<KList>('POST', '/query', { kind, filters, ...params }),
  get: (id: string, revision?: number) => api.knowledge<KRecord>('GET', `/records/${id}`, undefined, { revision }),
  create: (kind: KnowledgeKind, data: Record<string, any>, reviewKey?: string) => api.knowledge<KRecord>('POST', '/records', { kind, data }, undefined, reviewKey),
  update: (record: KRecord, data: Record<string, any>, reason = '', reviewKey?: string) => api.knowledge<KRecord>('PATCH', `/records/${record.id}`, { expected_revision: record.revision, data, reason }, undefined, reviewKey),
  backlinks: (id: string) => api.knowledge<KList>('GET', `/records/${id}/backlinks`),
  history: (id: string, offset = 0) => api.knowledge<{ items: { revision: number; data: Record<string, any>; reason: string; actor: string; created_at: string }[]; total: number; next_offset: number | null }>('GET', `/records/${id}/history`, undefined, { offset }),
}

export const templates: Partial<Record<KnowledgeKind, string>> = {
  project: '## 目标\n\n\n## 参考与约束\n\n\n## 交付标准\n\n',
  question: '## 背景\n\n\n## 探索与实践\n\n\n## 当前结论\n\n\n## 尚未解决\n\n',
  entity: '## 介绍\n\n\n## 适用条件\n\n\n## 方法与示例\n\n\n## 限制\n\n',
}

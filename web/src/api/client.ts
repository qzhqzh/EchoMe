import { useAuth } from '@/stores/auth'
import { useToast } from '@/stores/toast'
import { router } from '@/router'
import type {
  Memory,
  MemoryListResponse,
  MemoryCreateRequest,
  MemoryCreateResponse,
  SearchRequest,
  SearchResponse,
  UnifiedContextResponse,
  Project,
  ProjectCreate,
  ApproveRequest,
  MemoryGraphResponse,
  MemoryGraphExplainResponse,
  SleepSessionsResponse,
  ProjectArtifact,
  ProjectConstraint,
  ProjectKnowledgeGraph,
  ProjectWorkspaceSummary,
  ProjectAutomationGate,
  ProjectAutomationRun,
  ProjectQualityCasesResponse,
  ProjectQualitySnapshot,
} from '@/types'

class ApiClient {
  private refreshing = false
  private refreshPromise: Promise<boolean> | null = null

  private getBaseUrl(): string {
    const { getApiBase } = useAuth()
    const base = getApiBase()
    return base ? `${base}/api/v1` : '/api/v1'
  }

  private getHeaders(): Record<string, string> {
    const { getToken } = useAuth()
    const token = getToken()
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    return headers
  }

  /**
   * Try to refresh the JWT token. Returns true if successful.
   * Deduplicates concurrent refresh attempts.
   */
  private async tryRefresh(): Promise<boolean> {
    if (this.refreshing && this.refreshPromise) {
      return this.refreshPromise
    }
    this.refreshing = true
    this.refreshPromise = this._doRefresh()
    try {
      return await this.refreshPromise
    } finally {
      this.refreshing = false
      this.refreshPromise = null
    }
  }

  private async _doRefresh(): Promise<boolean> {
    const { getToken, setToken } = useAuth()
    const token = getToken()
    if (!token) return false
    try {
      const url = `${this.getBaseUrl().replace(/\/api\/v1$/, '')}/api/v1/auth/refresh`
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`,
        },
      })
      if (!response.ok) return false
      const data = await response.json()
      if (data.access_token) {
        setToken(data.access_token)
        return true
      }
      return false
    } catch {
      return false
    }
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: Record<string, string | number | boolean | undefined | null>,
    _retried = false,
  ): Promise<T> {
    const url = new URL(`${this.getBaseUrl()}${path}`, window.location.origin)

    if (params) {
      Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          url.searchParams.set(key, String(value))
        }
      })
    }

    const options: RequestInit = {
      method,
      headers: this.getHeaders(),
    }

    if (body && method !== 'GET') {
      options.body = JSON.stringify(body)
    }

    const response = await fetch(url.toString(), options)

    if (response.status === 401 && !_retried) {
      // Skip refresh for auth endpoints themselves
      const isAuthEndpoint = path.includes('/auth/')
      if (isAuthEndpoint) {
        const { clearToken } = useAuth()
        clearToken()
        router.push('/login')
        throw new Error('Unauthorized')
      }
      // Try refresh token
      const refreshed = await this.tryRefresh()
      if (refreshed) {
        return this.request<T>(method, path, body, params, true)
      }
      // Refresh failed — clear and redirect
      const { clearToken } = useAuth()
      clearToken()
      router.push('/login')
      throw new Error('Unauthorized')
    }

    if (response.status === 204) {
      return undefined as T
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => null)
      const message = errorData?.error?.message || errorData?.detail || `Request failed: ${response.status}`
      const { error } = useToast()
      error(message)
      throw new Error(message)
    }

    return response.json()
  }

  // --- Memories ---

  async listMemories(params?: {
    type?: string
    layer?: string
    status?: string
    tags?: string
    project_id?: string
    query?: string
    offset?: number
    limit?: number
  }): Promise<MemoryListResponse> {
    return this.request<MemoryListResponse>('GET', '/memories', undefined, params)
  }

  async getMemory(id: string): Promise<Memory> {
    return this.request<Memory>('GET', `/memories/${id}`)
  }

  async createMemory(data: MemoryCreateRequest): Promise<MemoryCreateResponse> {
    return this.request<MemoryCreateResponse>('POST', '/memories', data)
  }

  async updateMemory(id: string, data: MemoryCreateRequest): Promise<Memory> {
    return this.request<Memory>('PUT', `/memories/${id}`, data)
  }

  async patchMemory(id: string, data: Partial<MemoryCreateRequest>): Promise<Memory> {
    return this.request<Memory>('PATCH', `/memories/${id}`, data)
  }

  async deleteMemory(id: string, hard = false): Promise<void> {
    return this.request<void>('DELETE', `/memories/${id}`, undefined, { hard })
  }

  async searchMemories(data: SearchRequest): Promise<SearchResponse> {
    return this.request<SearchResponse>('POST', '/memories/search', data)
  }

  // --- Review ---

  async listPending(params?: { offset?: number; limit?: number; status?: string }): Promise<MemoryListResponse> {
    return this.request<MemoryListResponse>('GET', '/review/pending', undefined, params)
  }

  async approveMemory(id: string, data?: ApproveRequest): Promise<{ status: string; id: string }> {
    return this.request('POST', `/review/${id}/approve`, data || {})
  }

  async rejectMemory(id: string): Promise<{ status: string; id: string }> {
    return this.request('POST', `/review/${id}/reject`)
  }

  // --- Projects ---

  async listProjects(): Promise<Project[]> {
    return this.request<Project[]>('GET', '/projects')
  }

  async getProject(id: string): Promise<Project> {
    return this.request<Project>('GET', `/projects/${id}`)
  }

  async createProject(data: ProjectCreate): Promise<Project> {
    return this.request<Project>('POST', '/projects', data)
  }

  async updateProject(id: string, data: ProjectCreate): Promise<Project> {
    return this.request<Project>('PUT', `/projects/${id}`, data)
  }

  async deleteProject(id: string): Promise<void> {
    return this.request<void>('DELETE', `/projects/${id}`)
  }

  async getProjectWorkspace(projectId: string): Promise<ProjectWorkspaceSummary> {
    return this.request('GET', '/project-knowledge/workspace', undefined, { project_id: projectId })
  }

  async listProjectConstraints(projectId: string, params?: { status?: string; query?: string }): Promise<{ total: number; items: ProjectConstraint[] }> {
    return this.request('GET', '/project-knowledge/constraints', undefined, { project_id: projectId, ...params })
  }

  async createProjectConstraint(data: {
    project_id: string
    title: string
    statement: string
    rationale?: string | null
    kind?: string
    status?: string
    stability?: string
    confidence?: number
    source?: string
    tags?: string[]
  }): Promise<ProjectConstraint> {
    return this.request('POST', '/project-knowledge/constraints', data)
  }

  async patchProjectConstraint(id: string, data: Record<string, unknown>): Promise<ProjectConstraint> {
    return this.request('PATCH', `/project-knowledge/constraints/${id}`, data)
  }

  async listProjectArtifacts(projectId: string): Promise<{ total: number; items: ProjectArtifact[] }> {
    return this.request('GET', '/project-knowledge/artifacts', undefined, { project_id: projectId })
  }

  async getProjectKnowledgeGraph(projectId: string, includeInactive = false): Promise<ProjectKnowledgeGraph> {
    return this.request('GET', '/project-knowledge/graph', undefined, {
      project_id: projectId,
      include_inactive: includeInactive,
    })
  }

  async analyzeProjectImpact(data: {
    project_id: string
    task: string
    changed_paths: string[]
    constraint_ids?: string[]
    depth?: number
    limit?: number
  }): Promise<any> {
    return this.request('POST', '/project-knowledge/impact', data)
  }

  async getProjectQualityCases(): Promise<ProjectQualityCasesResponse> {
    return this.request('GET', '/project-knowledge/eval/cases')
  }

  async compileProjectContext(data: Record<string, unknown>): Promise<Record<string, any>> {
    return this.request('POST', '/project-knowledge/context', data)
  }

  async runProjectPreflight(data: Record<string, unknown>): Promise<Record<string, any>> {
    return this.request('POST', '/project-knowledge/preflight', data)
  }

  async createProjectQualitySnapshot(data: Record<string, unknown>): Promise<ProjectQualitySnapshot> {
    return this.request('POST', '/project-knowledge/eval/snapshots', data)
  }

  async listProjectQualitySnapshots(projectId: string): Promise<{ total: number; items: ProjectQualitySnapshot[] }> {
    return this.request('GET', '/project-knowledge/eval/snapshots', undefined, {
      project_id: projectId,
      limit: 20,
    })
  }

  async getProjectAutomationGate(projectId: string): Promise<ProjectAutomationGate> {
    return this.request('GET', '/project-knowledge/automation/gate', undefined, {
      project_id: projectId,
      required_snapshots: 3,
    })
  }

  async runProjectAutomationDryRun(projectId: string): Promise<ProjectAutomationRun> {
    return this.request('POST', '/project-knowledge/automation/proposals/run', {
      project_id: projectId,
      dry_run: true,
      required_snapshots: 3,
      include_sleep: true,
      include_revalidation: true,
      idempotency_key: `web-dry-run-${crypto.randomUUID()}`,
    })
  }

  // --- Health ---

  async health(): Promise<{ status: string; version: string }> {
    const { getApiBase } = useAuth()
    const base = getApiBase()
    const url = base ? `${base}/health` : '/health'
    const response = await fetch(url, { headers: this.getHeaders() })
    if (!response.ok) throw new Error(`Health check failed: ${response.status}`)
    return response.json()
  }

  // --- Auth ---

  async getGitHubAuthUrl(): Promise<{ url: string }> {
    return this.request<{ url: string }>('GET', '/auth/github')
  }

  async githubCallback(code: string): Promise<{
    access_token: string
    token_type: string
    expires_in: number
    user: { id: string; github_id: number; username: string; email: string | null; avatar_url: string | null; role: string; created_at: string; last_login_at: string | null }
  }> {
    return this.request('GET', '/auth/github/callback', undefined, { code })
  }

  async getMe(): Promise<{ id: string; github_id: number; username: string; email: string | null; avatar_url: string | null; role: string; created_at: string; last_login_at: string | null }> {
    return this.request('GET', '/auth/me')
  }

  async refreshToken(): Promise<{ access_token: string; expires_in: number }> {
    return this.request('POST', '/auth/refresh')
  }

  // --- Market ---

  async listMarketMemories(params?: Record<string, string | number>): Promise<{ total: number; offset: number; limit: number; items: any[] }> {
    return this.request('GET', '/market/memories', undefined, params)
  }

  async getMarketMemory(id: string): Promise<any> {
    return this.request('GET', `/market/memories/${id}`)
  }

  async forkMarketMemory(id: string): Promise<{ id: string; title: string; forked_from: string; message: string }> {
    return this.request('POST', `/market/memories/${id}/fork`)
  }

  async getMarketStats(): Promise<{ total_public: number; by_type: Record<string, number>; recent_count_7d: number }> {
    return this.request('GET', '/market/stats')
  }

  // --- Observability ---

  async listSleepSessions(params?: { status?: string; project_id?: string; offset?: number; limit?: number }): Promise<SleepSessionsResponse> {
    return this.request('GET', '/observability/sleep-sessions', undefined, params)
  }

  async getMemoryGraph(params?: { project_id?: string; include_inactive?: boolean }): Promise<MemoryGraphResponse> {
    return this.request('GET', '/observability/memory-graph', undefined, params)
  }

  async explainMemoryGraph(memoryId: string, params?: { include_inactive?: boolean }): Promise<MemoryGraphExplainResponse> {
    return this.request('GET', `/observability/memory-graph/explain/${memoryId}`, undefined, params)
  }

  async createMemoryFeedback(body: {
    memory_id: string
    rating: string
    note?: string | null
    task_context?: string | null
    used_by?: string
    confidence?: string
    source?: string
  }): Promise<any> {
    return this.request('POST', '/memory-feedback', body)
  }

  async runRetrievalDebug(body: {
    query: string
    status?: string
    project_id?: string | null
    limit?: number
    expected_ids?: string[]
    client?: string
    source?: string
  }): Promise<any> {
    return this.request('POST', '/retrieval-debug/query', body)
  }

  async getContext(body: {
    task: string
    mode?: 'auto' | 'personal' | 'project' | 'impact' | 'temporal'
    project_hint?: string
    changed_paths?: string[]
    limit?: number
    record_run?: boolean
    client?: string
  }): Promise<UnifiedContextResponse> {
    return this.request('POST', '/context', body)
  }

  async listRetrievalLogs(params?: { client?: string; limit?: number }): Promise<any> {
    return this.request('GET', '/retrieval-debug/logs', undefined, params)
  }

  async listContextRuns(params?: { project_id?: string; limit?: number }): Promise<any> {
    return this.request('GET', '/project-knowledge/context-runs', undefined, params)
  }

  // --- Admin ---

  async getAdminStats(): Promise<any> {
    return this.request('GET', '/admin/stats')
  }

  async getAdminUsers(params?: { offset?: number; limit?: number }): Promise<{ total: number; items: any[] }> {
    return this.request('GET', '/admin/users', undefined, params)
  }

  async updateUserRole(userId: string, role: string): Promise<any> {
    return this.request('PATCH', `/admin/users/${userId}/role`, { role })
  }

  async deleteAdminUser(userId: string): Promise<any> {
    return this.request('DELETE', `/admin/users/${userId}`)
  }

  async deleteAdminMemory(memoryId: string): Promise<any> {
    return this.request('DELETE', `/admin/memories/${memoryId}`)
  }
}

export const api = new ApiClient()

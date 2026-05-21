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
  Project,
  ProjectCreate,
  ApproveRequest,
} from '@/types'

class ApiClient {
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

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: Record<string, string | number | boolean | undefined | null>
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

    if (response.status === 401) {
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

  async listPending(params?: { offset?: number; limit?: number }): Promise<MemoryListResponse> {
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

  // --- Health ---

  async health(): Promise<{ status: string; version: string }> {
    return this.request('GET', '/health')
  }
}

export const api = new ApiClient()

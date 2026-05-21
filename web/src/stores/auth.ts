import { reactive } from 'vue'

const TOKEN_KEY = 'echome_token'
const API_BASE_KEY = 'echome_api_base'
const USER_KEY = 'echome_user'

export interface UserInfo {
  id: string
  github_id: number
  username: string
  email: string | null
  avatar_url: string | null
  role: string
  created_at: string
  last_login_at: string | null
}

interface AuthState {
  token: string | null
  apiBase: string
  user: UserInfo | null
}

const state: AuthState = reactive({
  token: localStorage.getItem(TOKEN_KEY),
  apiBase: localStorage.getItem(API_BASE_KEY) || '',
  user: JSON.parse(localStorage.getItem(USER_KEY) || 'null'),
})

export function useAuth() {
  function getToken(): string | null {
    return state.token
  }

  function setToken(token: string): void {
    state.token = token
    localStorage.setItem(TOKEN_KEY, token)
  }

  function clearToken(): void {
    state.token = null
    state.user = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  function isAuthenticated(): boolean {
    return !!state.token
  }

  function getApiBase(): string {
    return state.apiBase || ''
  }

  function setApiBase(url: string): void {
    state.apiBase = url
    if (url) {
      localStorage.setItem(API_BASE_KEY, url)
    } else {
      localStorage.removeItem(API_BASE_KEY)
    }
  }

  function getUser(): UserInfo | null {
    return state.user
  }

  function setUser(user: UserInfo): void {
    state.user = user
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  }

  return {
    state,
    getToken,
    setToken,
    clearToken,
    isAuthenticated,
    getApiBase,
    setApiBase,
    getUser,
    setUser,
  }
}

import { reactive } from 'vue'

const TOKEN_KEY = 'echome_token'
const API_BASE_KEY = 'echome_api_base'

interface AuthState {
  token: string | null
  apiBase: string
}

const state: AuthState = reactive({
  token: localStorage.getItem(TOKEN_KEY),
  apiBase: localStorage.getItem(API_BASE_KEY) || '',
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
    localStorage.removeItem(TOKEN_KEY)
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

  return {
    state,
    getToken,
    setToken,
    clearToken,
    isAuthenticated,
    getApiBase,
    setApiBase,
  }
}

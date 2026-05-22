<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useToast } from '@/stores/toast'
import { api } from '@/api/client'

const router = useRouter()
const route = useRoute()
const { setToken, setApiBase, setUser } = useAuth()
const { success, error } = useToast()

const token = ref('')
const apiBase = ref(localStorage.getItem('echome_api_base') || '')
const loading = ref(false)
const githubLoading = ref(false)
const showManual = ref(false)
const showAdvanced = ref(false)

// Handle GitHub OAuth callback
onMounted(async () => {
  const code = route.query.code as string | undefined
  if (code) {
    githubLoading.value = true
    try {
      if (apiBase.value.trim()) {
        setApiBase(apiBase.value.trim().replace(/\/$/, ''))
      }
      const data = await api.githubCallback(code)
      setToken(data.access_token)
      setUser(data.user)
      success(`Welcome, ${data.user.username}!`)
      router.push('/')
    } catch (e) {
      error('GitHub login failed. Please try again.')
    } finally {
      githubLoading.value = false
    }
  }
})

async function handleGitHubLogin(): Promise<void> {
  githubLoading.value = true
  try {
    if (apiBase.value.trim()) {
      setApiBase(apiBase.value.trim().replace(/\/$/, ''))
    } else {
      setApiBase('')
    }
    const data = await api.getGitHubAuthUrl()
    window.location.href = data.url
  } catch (e) {
    error('Failed to get GitHub auth URL. Is the Hub configured?')
    githubLoading.value = false
  }
}

async function handleTokenLogin(): Promise<void> {
  if (!token.value.trim()) {
    error('Please enter a token')
    return
  }

  loading.value = true

  try {
    if (apiBase.value.trim()) {
      setApiBase(apiBase.value.trim().replace(/\/$/, ''))
    } else {
      setApiBase('')
    }
    setToken(token.value.trim())

    // Try to fetch user info
    try {
      const user = await api.getMe()
      setUser(user)
    } catch {
      // Fallback: legacy token, just verify connectivity
      await api.health()
    }

    success('Connected to EchoMe Hub')
    router.push('/')
  } catch (e) {
    error('Failed to connect. Check your token and API URL.')
    const { clearToken } = useAuth()
    clearToken()
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-slate-900 p-4">
    <div class="w-full max-w-md">
      <!-- Logo -->
      <div class="mb-8 text-center">
        <div class="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-blue-600 shadow-lg shadow-blue-600/20">
          <span class="text-2xl font-bold text-white">E</span>
        </div>
        <h1 class="text-2xl font-bold text-slate-100">EchoMe Console</h1>
        <p class="mt-1 text-sm text-slate-400">Connect to your memory hub</p>
      </div>

      <!-- GitHub OAuth callback loading -->
      <div v-if="githubLoading" class="card text-center py-8">
        <svg class="mx-auto h-8 w-8 animate-spin text-blue-400" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <p class="mt-3 text-slate-300">Completing GitHub login...</p>
      </div>

      <!-- Login form -->
      <div v-else class="card space-y-5">
        <!-- GitHub OAuth button -->
        <button
          class="btn-primary w-full gap-2"
          :disabled="githubLoading"
          @click="handleGitHubLogin"
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
          </svg>
          Login with GitHub
        </button>

        <!-- Divider -->
        <div class="relative">
          <div class="absolute inset-0 flex items-center">
            <div class="w-full border-t border-slate-600"></div>
          </div>
          <div class="relative flex justify-center text-xs">
            <button
              class="bg-slate-800 px-3 text-slate-400 hover:text-slate-200 cursor-pointer"
              @click="showManual = !showManual"
            >
              {{ showManual ? 'Hide' : 'Or use'}} API token
            </button>
          </div>
        </div>

        <!-- Manual token login (collapsible) -->
        <form v-if="showManual" class="space-y-4" @submit.prevent="handleTokenLogin">
          <div>
            <label class="mb-1.5 block text-sm font-medium text-slate-300">API Token</label>
            <input
              v-model="token"
              type="password"
              class="input-field"
              placeholder="Enter your Bearer token or JWT"
              autocomplete="off"
            />
          </div>

          <button
            type="submit"
            class="w-full rounded-lg border border-slate-600 bg-slate-700 px-4 py-2.5 text-sm font-medium text-slate-200 hover:bg-slate-600 transition-colors"
            :disabled="loading"
          >
            <svg v-if="loading" class="mr-2 inline h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            {{ loading ? 'Connecting...' : 'Connect with Token' }}
          </button>
        </form>

        <!-- Advanced: Hub URL (hidden by default) -->
        <div class="pt-2">
          <button
            class="text-xs text-slate-500 hover:text-slate-400 cursor-pointer"
            @click="showAdvanced = !showAdvanced"
          >
            {{ showAdvanced ? '▾ Hide advanced' : '▸ Advanced settings' }}
          </button>
          <div v-if="showAdvanced" class="mt-2">
            <label class="mb-1.5 block text-xs font-medium text-slate-400">Hub URL</label>
            <input
              v-model="apiBase"
              type="url"
              class="input-field text-xs"
              placeholder="Leave empty (default: same origin)"
            />
            <p class="mt-1 text-xs text-slate-500">Only change this for local development</p>
          </div>
        </div>
      </div>

      <p class="mt-6 text-center text-xs text-slate-500">
        Authenticate via GitHub to access your memory hub.
      </p>
    </div>
  </div>
</template>

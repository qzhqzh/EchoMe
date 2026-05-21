<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuth } from '@/stores/auth'
import { useToast } from '@/stores/toast'
import { api } from '@/api/client'

const router = useRouter()
const { setToken, setApiBase } = useAuth()
const { success, error } = useToast()

const token = ref('')
const apiBase = ref(localStorage.getItem('echome_api_base') || '')
const loading = ref(false)

async function handleLogin(): Promise<void> {
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

    await api.health()
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

      <!-- Login form -->
      <form class="card space-y-5" @submit.prevent="handleLogin">
        <div>
          <label class="mb-1.5 block text-sm font-medium text-slate-300">API Token</label>
          <input
            v-model="token"
            type="password"
            class="input-field"
            placeholder="Enter your Bearer token"
            autocomplete="off"
          />
        </div>

        <div>
          <label class="mb-1.5 block text-sm font-medium text-slate-300">
            Hub URL <span class="text-slate-500">(optional)</span>
          </label>
          <input
            v-model="apiBase"
            type="url"
            class="input-field"
            placeholder="http://localhost:20000 (default: same origin)"
          />
          <p class="mt-1 text-xs text-slate-500">Leave empty for same-origin or dev proxy</p>
        </div>

        <button
          type="submit"
          class="btn-primary w-full"
          :disabled="loading"
        >
          <svg v-if="loading" class="mr-2 h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          {{ loading ? 'Connecting...' : 'Connect' }}
        </button>
      </form>

      <p class="mt-6 text-center text-xs text-slate-500">
        Token is stored in localStorage and used for Bearer auth.
      </p>
    </div>
  </div>
</template>

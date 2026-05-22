<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/i18n'
import { useAuth } from '@/stores/auth'
import { useToast } from '@/stores/toast'
import { api } from '@/api/client'

const { t } = useI18n()
const { getToken, getUser, setToken } = useAuth()
const { success, error } = useToast()

const user = computed(() => getUser())
const token = computed(() => getToken() || '')
const showToken = ref(false)
const refreshing = ref(false)

// Decode JWT to get expiration
const tokenExpiry = computed(() => {
  const t = token.value
  if (!t) return null
  try {
    const payload = JSON.parse(atob(t.split('.')[1]))
    if (payload.exp) {
      return new Date(payload.exp * 1000)
    }
  } catch {
    // not a valid JWT
  }
  return null
})

const tokenExpiryText = computed(() => {
  if (!tokenExpiry.value) return 'Unknown'
  const now = new Date()
  const diff = tokenExpiry.value.getTime() - now.getTime()
  if (diff <= 0) return 'Expired'
  const days = Math.floor(diff / (1000 * 60 * 60 * 24))
  if (days > 365) {
    const years = Math.floor(days / 365)
    return `~${years} year${years > 1 ? 's' : ''} remaining`
  }
  return `${days} day${days > 1 ? 's' : ''} remaining`
})

const maskedToken = computed(() => {
  const t = token.value
  if (!t) return ''
  if (t.length <= 20) return '***'
  return t.slice(0, 10) + '...' + t.slice(-10)
})

async function copyToken(): Promise<void> {
  try {
    await navigator.clipboard.writeText(token.value)
    success('Token copied to clipboard')
  } catch {
    // Fallback for non-HTTPS
    const textarea = document.createElement('textarea')
    textarea.value = token.value
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    success('Token copied to clipboard')
  }
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    success('Copied to clipboard')
  } catch {
    const textarea = document.createElement('textarea')
    textarea.value = text
    document.body.appendChild(textarea)
    textarea.select()
    document.execCommand('copy')
    document.body.removeChild(textarea)
    success('Copied to clipboard')
  }
}

async function refreshToken(): Promise<void> {
  refreshing.value = true
  try {
    const data = await api.refreshToken()
    setToken(data.access_token)
    success('Token refreshed successfully')
  } catch (e) {
    error('Failed to refresh token')
  } finally {
    refreshing.value = false
  }
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <h1 class="text-2xl font-bold text-slate-100">{{ t('settings_title') }}</h1>

    <!-- User Info -->
    <div class="card">
      <h2 class="mb-4 text-lg font-semibold text-slate-100">{{ t('settings_profile') }}</h2>
      <div v-if="user" class="flex items-start gap-4">
        <img
          v-if="user.avatar_url"
          :src="user.avatar_url"
          :alt="user.username"
          class="h-16 w-16 rounded-full"
        />
        <div v-else class="flex h-16 w-16 items-center justify-center rounded-full bg-blue-600 text-xl font-bold text-white">
          {{ user.username.charAt(0).toUpperCase() }}
        </div>
        <div class="space-y-1">
          <p class="text-lg font-medium text-slate-100">{{ user.username }}</p>
          <p class="text-sm text-slate-400">{{ user.email || t('settings_no_email') }}</p>
          <p class="text-sm text-slate-400">
            Role: <span class="rounded bg-slate-700 px-2 py-0.5 text-xs font-medium text-slate-200">{{ user.role }}</span>
          </p>
          <p class="text-xs text-slate-500">
            User ID: <code class="rounded bg-slate-700/50 px-1.5 py-0.5 text-slate-400 select-all">{{ user.id }}</code>
          </p>
          <p class="text-xs text-slate-500">
            {{ t('settings_member_since') }} {{ new Date(user.created_at).toLocaleDateString() }}
          </p>
        </div>
      </div>
    </div>

    <!-- Token Management -->
    <div class="card">
      <h2 class="mb-4 text-lg font-semibold text-slate-100">{{ t('settings_api_token') }}</h2>
      <p class="mb-3 text-sm text-slate-400">
        {{ t('settings_api_token_desc') }}
      </p>

      <!-- Token display -->
      <div class="mb-3 rounded-lg border border-slate-600 bg-slate-900 p-3">
        <div class="flex items-center gap-2">
          <code class="flex-1 break-all text-sm text-slate-300">
            {{ showToken ? token : maskedToken }}
          </code>
          <button
            class="shrink-0 rounded p-1.5 text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
            :title="showToken ? 'Hide token' : 'Show token'"
            @click="showToken = !showToken"
          >
            <!-- Eye icon -->
            <svg v-if="!showToken" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            <!-- Eye-off icon -->
            <svg v-else class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
            </svg>
          </button>
        </div>
      </div>

      <!-- Token info + actions -->
      <div class="flex flex-wrap items-center gap-3">
        <button
          class="btn-primary gap-2"
          @click="copyToken"
        >
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
          </svg>
          {{ t('settings_copy_token') }}
        </button>
        <button
          class="rounded-lg border border-slate-600 bg-slate-700 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-600 transition-colors disabled:opacity-50"
          :disabled="refreshing"
          @click="refreshToken"
        >
          {{ refreshing ? t('settings_refreshing') : t('settings_generate_new') }}
        </button>
        <span v-if="tokenExpiry" class="text-xs text-slate-500">
          {{ t('settings_expires') }} {{ tokenExpiry.toLocaleDateString() }} ({{ tokenExpiryText }})
        </span>
      </div>
    </div>

    <!-- CLI Configuration Guide -->
    <div class="card">
      <h2 class="mb-4 text-lg font-semibold text-slate-100">{{ t('settings_cli_config') }}</h2>
      <p class="mb-3 text-sm text-slate-400">
        {{ t('settings_cli_config_desc') }}
      </p>

      <div class="space-y-4">
        <!-- Option 1 -->
        <div>
          <h3 class="mb-1 text-sm font-medium text-slate-200">{{ t('settings_option1') }}</h3>
          <div class="group relative rounded-lg bg-slate-900 border border-slate-700 p-3">
            <code class="text-sm text-green-400">echome login</code>
            <button
              class="absolute right-2 top-2 rounded p-1 text-slate-500 opacity-0 group-hover:opacity-100 hover:bg-slate-700 hover:text-slate-200 transition-all"
              title="Copy command"
              @click="copyText('echome login')"
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </button>
            <p class="mt-1 text-xs text-slate-500">{{ t('settings_option1_hint') }}</p>
          </div>
        </div>

        <!-- Option 2 -->
        <div>
          <h3 class="mb-1 text-sm font-medium text-slate-200">{{ t('settings_option2') }}</h3>
          <div class="group relative rounded-lg bg-slate-900 border border-slate-700 p-3">
            <code class="block text-sm text-green-400">mkdir -p ~/.config/echome</code>
            <code class="block text-sm text-green-400 mt-1">cat &gt; ~/.config/echome/config.toml &lt;&lt;EOF</code>
            <code class="block text-sm text-slate-300 mt-1">hub_url = "https://echome.qzhqzh.com"</code>
            <code class="block text-sm text-slate-300">token = "{{ maskedToken }}"</code>
            <code class="block text-sm text-green-400">EOF</code>
            <button
              class="absolute right-2 top-2 rounded p-1 text-slate-500 opacity-0 group-hover:opacity-100 hover:bg-slate-700 hover:text-slate-200 transition-all"
              title="Copy config commands (with your token)"
              @click="copyText(`mkdir -p ~/.config/echome\ncat > ~/.config/echome/config.toml <<EOF\nhub_url = &quot;https://echome.qzhqzh.com&quot;\ntoken = &quot;${token}&quot;\nEOF`)"
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </button>
          </div>
        </div>

        <!-- Verify -->
        <div>
          <h3 class="mb-1 text-sm font-medium text-slate-200">{{ t('settings_verify') }}</h3>
          <div class="group relative rounded-lg bg-slate-900 border border-slate-700 p-3">
            <code class="text-sm text-green-400">echome whoami</code>
            <button
              class="absolute right-2 top-2 rounded p-1 text-slate-500 opacity-0 group-hover:opacity-100 hover:bg-slate-700 hover:text-slate-200 transition-all"
              title="Copy command"
              @click="copyText('echome whoami')"
            >
              <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

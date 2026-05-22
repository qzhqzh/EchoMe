<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from '@/i18n'
import { api } from '@/api/client'
import { useToast } from '@/stores/toast'
import MemoryForm from '@/components/MemoryForm.vue'
import type { MemoryCreateRequest, MemoryType } from '@/types'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const { success } = useToast()
const loading = ref(false)

// Support pre-selecting type via URL query: /memories/new?type=decision
const defaultType = computed(() => (route.query.type as MemoryType) || undefined)

async function handleCreate(data: MemoryCreateRequest): Promise<void> {
  loading.value = true
  try {
    const result = await api.createMemory(data)
    success(`Memory "${result.title}" created`)
    // Go back to where the user came from instead of jumping to detail page
    router.back()
  } catch {
    // handled by api client
  } finally {
    loading.value = false
  }
}

function handleCancel(): void {
  router.back()
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-6">
    <div>
      <button
        class="mb-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
        @click="router.push('/memories')"
      >
        &larr; {{ t('memory_new_back') }}
      </button>
      <h1 class="text-2xl font-bold text-slate-100">{{ t('memory_new_title') }}</h1>
      <p class="text-sm text-slate-400">{{ t('memory_new_subtitle') }}</p>
    </div>

    <div class="card">
      <MemoryForm
        :loading="loading"
        :default-type="defaultType"
        @submit="handleCreate"
        @cancel="handleCancel"
      />
    </div>
  </div>
</template>

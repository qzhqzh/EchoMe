<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '@/api/client'
const props = defineProps<{ resource: string; preview?: boolean; label?: string }>()
const url = ref(''), error = ref(''), isImage = ref(false)
let generation = 0
watch(() => props.resource, async resource => {
  const current = ++generation
  if (url.value.startsWith('blob:')) URL.revokeObjectURL(url.value)
  url.value = ''; error.value = ''
  if (/^https?:\/\//i.test(resource)) { url.value = resource; isImage.value = !!props.preview; return }
  if (!resource.startsWith('asset:')) { error.value = '本地文件引用：需在对应设备上打开'; return }
  try {
    const blob = await api.knowledgeBlob(resource.slice(6))
    if (current !== generation) return
    url.value = URL.createObjectURL(blob); isImage.value = blob.type.startsWith('image/')
  } catch (e) { error.value = String(e) }
}, { immediate: true })
onBeforeUnmount(() => { generation++; if (url.value.startsWith('blob:')) URL.revokeObjectURL(url.value) })
</script>
<template>
  <a v-if="url" :href="url" target="_blank" rel="noopener noreferrer" :download="!preview && resource.startsWith('asset:') ? label || 'download' : undefined" class="text-blue-300 underline underline-offset-4">
    <img v-if="preview && isImage" :src="url" :alt="label || '成果预览'" class="max-h-96 w-full rounded-lg object-contain bg-slate-950" />
    <span v-else>{{ label || '打开文件' }}</span>
  </a>
  <p v-else-if="error" class="break-all text-sm text-amber-300">{{ error }}<span class="block text-xs text-slate-500">{{ resource }}</span></p>
  <span v-else class="text-xs text-slate-500">加载文件…</span>
</template>

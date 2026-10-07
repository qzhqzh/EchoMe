<script setup lang="ts">
import { ref, watch } from 'vue'
import { api } from '@/api/client'
import { kb, templates, titleOf, type KRecord } from '@/knowledge'
import KnowledgeMarkdown from './KnowledgeMarkdown.vue'
import { useKnowledgeDraft } from '@/knowledge-draft'
const props = defineProps<{ owner: KRecord; page?: KRecord | null; readonly?: boolean }>()
const emit = defineEmits<{ saved: [] }>()
const editing = ref(false), busy = ref(false), error = ref(''), body = ref(''), reason = ref(''), preview = ref(false)
const reviewKey = ref('')
const dirty = () => editing.value && body.value !== (props.page?.data.body_md || '')
useKnowledgeDraft(dirty)
function cancel() { if (!dirty() || window.confirm('正文还没有保存，确定放弃修改？')) editing.value = false }
watch(() => props.page, page => { body.value = page?.data.body_md || ''; editing.value = false; error.value = '' }, { immediate: true })
function start() { body.value = props.page?.data.body_md || ''; editing.value = true }
async function save() {
  busy.value = true; error.value = ''
  try {
    if (props.page) await kb.update(props.page, { ...props.page.data, body_md: body.value }, reason.value, reviewKey.value)
    else await kb.create('page', { title: titleOf(props.owner), body_md: body.value, bindings: [{ target_id: props.owner.id, role: 'overview' }] })
    editing.value = false; emit('saved')
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function upload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return
  busy.value = true
  try {
    const uploaded = await api.knowledgeAsset(file)
    const label = file.name.replace(/[\[\]\\]/g, '')
    body.value += `\n${file.type.startsWith('image/') ? '!' : ''}[${label}](${uploaded.resource_ref})\n`
  } catch (e) { error.value = String(e) } finally { busy.value = false }
}
</script>
<template>
  <section class="rounded-xl border border-slate-700 bg-slate-800/50 p-5 sm:p-7 min-w-0">
    <div class="mb-5 flex flex-wrap items-center justify-between gap-3">
      <h2 class="font-semibold text-slate-100">{{ owner.kind === 'question' ? '研究与回答' : '介绍与说明' }} <router-link v-if="page" :to="`/knowledge/${page.id}`" class="ml-2 text-xs font-normal text-blue-300">文档 v{{ page.revision }} ↗</router-link></h2>
      <button v-if="!editing && !readonly" class="text-sm text-blue-300 hover:text-blue-200" @click="start">{{ page ? '编辑正文' : '写下说明' }}</button>
    </div>
    <template v-if="editing">
      <div class="mb-3 flex flex-wrap gap-3 text-sm text-blue-300">
        <button @click="preview = !preview">{{ preview ? '继续编辑' : '预览排版' }}</button>
        <button v-if="!body && templates[owner.kind]" @click="body = templates[owner.kind] || ''">插入章节提示</button>
        <label class="cursor-pointer">上传图片 / 文件<input type="file" class="sr-only" @change="upload" :disabled="busy" /></label>
      </div>
      <KnowledgeMarkdown v-if="preview" :body="body" />
      <textarea v-else v-model="body" aria-label="正文" class="min-h-80 w-full rounded-lg border border-slate-600 bg-slate-950 p-4 font-mono text-sm leading-7 text-slate-200 focus:border-blue-400 focus:outline-none" placeholder="支持标题、列表、表格、代码、图片和链接。无需填满所有章节。" />
      <input v-model="reason" aria-label="修改说明" placeholder="修改说明（可选）" class="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 p-3 text-sm" />
      <label v-if="page?.review_state === 'reviewed'" class="mt-3 block text-sm text-amber-200">修改已核对正文需要独立审核凭据<input v-model="reviewKey" type="password" autocomplete="off" class="mt-2 w-full rounded-lg border border-slate-700 bg-slate-900 p-3" /></label>
      <div class="mt-4 flex gap-3"><button class="rounded-lg bg-blue-600 px-4 py-2 text-white disabled:opacity-50" :disabled="busy" @click="save">{{ busy ? '保存中…' : '保存正文' }}</button><button class="px-3 text-slate-400" :disabled="busy" @click="cancel">取消</button></div>
    </template>
    <KnowledgeMarkdown v-else-if="page?.data.body_md" :body="page.data.body_md" />
    <p v-else class="text-sm text-slate-500">暂无正文。</p>
    <p v-if="error" role="alert" class="mt-4 text-sm text-rose-300">{{ error }}</p>
  </section>
</template>

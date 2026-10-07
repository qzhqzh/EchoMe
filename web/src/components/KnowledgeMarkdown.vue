<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { api } from '@/api/client'

const props = defineProps<{ body: string }>()
const html = ref('')
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })
const originalValidate = md.validateLink.bind(md)
md.validateLink = url => /^asset:[a-f0-9-]{36}$/i.test(url) || originalValidate(url)
const urls = new Set<string>()
let generation = 0
watch(() => props.body, async body => {
  const current = ++generation
  let rendered = md.render(body || '')
  const assets = [...new Set(body.match(/asset:[a-f0-9-]{36}/gi) || [])]
  const nextUrls: string[] = []
  for (const asset of assets) {
    try {
      const blob = await api.knowledgeBlob(asset.slice(6))
      const url = URL.createObjectURL(blob)
      nextUrls.push(url)
      rendered = rendered.split(asset).join(url)
    } catch { rendered = rendered.split(asset).join('#unavailable-asset') }
  }
  if (current !== generation) { nextUrls.forEach(URL.revokeObjectURL); return }
  urls.forEach(URL.revokeObjectURL); urls.clear()
  nextUrls.forEach(url => urls.add(url))
  // HTML input is disabled; sanitize the generated markup again and allow only safe content.
  html.value = DOMPurify.sanitize(rendered, {
    USE_PROFILES: { html: true }, FORBID_TAGS: ['style', 'form', 'input', 'iframe'],
    ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|blob):|\/(?!\/)|#)/i,
  })
}, { immediate: true })
onBeforeUnmount(() => { generation++; urls.forEach(URL.revokeObjectURL) })
</script>
<template><article class="knowledge-prose" v-html="html" /></template>
<style scoped>
.knowledge-prose { overflow-wrap: anywhere; line-height: 1.85; color: #cbd5e1; }
.knowledge-prose :deep(h1), .knowledge-prose :deep(h2), .knowledge-prose :deep(h3) { color: #f1f5f9; font-weight: 650; margin: 1.3em 0 .5em; }
.knowledge-prose :deep(h1) { font-size: 1.6rem; } .knowledge-prose :deep(h2) { font-size: 1.25rem; } .knowledge-prose :deep(h3) { font-size: 1.05rem; }
.knowledge-prose :deep(p) { margin: .7em 0; }
.knowledge-prose :deep(ul) { list-style: disc; padding-left: 1.5em; } .knowledge-prose :deep(ol) { list-style: decimal; padding-left: 1.5em; }
.knowledge-prose :deep(a) { color: #93c5fd; text-decoration: underline; }
.knowledge-prose :deep(pre) { overflow: auto; max-width: 100%; background: #020617; padding: 1em; border-radius: .6em; font-size: .82em; }
.knowledge-prose :deep(code) { color: #a5b4fc; }
.knowledge-prose :deep(blockquote) { border-left: 3px solid #64748b; padding-left: 1em; color: #94a3b8; }
.knowledge-prose :deep(table) { display: block; overflow-x: auto; border-collapse: collapse; } .knowledge-prose :deep(td), .knowledge-prose :deep(th) { border: 1px solid #475569; padding: .5em .8em; }
.knowledge-prose :deep(img) { max-height: 32rem; max-width: 100%; border-radius: .7rem; }
</style>

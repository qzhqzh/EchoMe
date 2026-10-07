<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { kb, stateNames, usageNames, type KnowledgePath, type KnowledgeUse } from '@/knowledge'
const props = defineProps<{ recordId: string; historical?: boolean }>()
const paths = ref<KnowledgePath[]>([]), uses = ref<KnowledgeUse[]>([])
const domainTotal = ref(0), useTotal = ref(0), domainNext = ref<number | null>(null), useNext = ref<number | null>(null)
const busy = ref(false), error = ref('')
let generation = 0
onBeforeUnmount(() => { generation++ })
async function load(section?: 'domains' | 'uses') {
  const current = ++generation; busy.value = true; error.value = ''
  try {
    const [domains, usage] = await Promise.all([
      section !== 'uses' ? kb.connections<KnowledgePath>(props.recordId, 'domains', section ? domainNext.value || 0 : 0) : null,
      section !== 'domains' ? kb.connections<KnowledgeUse>(props.recordId, 'uses', section ? useNext.value || 0 : 0) : null,
    ])
    if (current !== generation) return
    if (domains) { paths.value = section ? [...paths.value, ...domains.items] : domains.items; domainTotal.value = domains.total; domainNext.value = domains.next_offset }
    if (usage) { uses.value = section ? [...uses.value, ...usage.items] : usage.items; useTotal.value = usage.total; useNext.value = usage.next_offset }
  } catch (e) { if (current === generation) error.value = String(e) } finally { if (current === generation) busy.value = false }
}
watch(() => props.recordId, () => { paths.value = []; uses.value = []; load() }, { immediate: true })
</script>

<template>
  <section aria-label="知识关联" class="min-w-0">
    <p v-if="historical" class="mb-3 text-xs text-slate-500">以下为当前目录与引用关系；历史使用版本见各条引用记录。</p>
    <p v-if="error" role="alert" class="mb-3 break-words text-sm text-rose-300">{{ error }} <button class="underline" @click="load()">重试</button></p>
    <div class="grid gap-4 md:grid-cols-2">
      <section aria-label="所属领域" class="min-w-0 rounded-xl border border-indigo-400/15 bg-indigo-400/[0.03] p-4 sm:p-5">
        <h2 class="flex items-center gap-2 text-sm font-medium text-indigo-200"><span class="h-2 w-2 rounded-full bg-indigo-400" />所属领域<span class="ml-auto text-xs font-normal text-slate-500">{{ domainTotal }} 处收纳</span></h2>
        <div v-for="path in paths" :key="path.placement_id" class="mt-4 border-l border-indigo-400/30 pl-3">
          <p v-if="path.incomplete" class="mb-2 text-xs text-amber-300">部分上级已停用</p>
          <ol class="flex flex-wrap items-center gap-x-2 gap-y-2 text-sm">
            <li v-for="(node, index) in path.nodes.slice(0, -1)" :key="node.id + '-' + index" class="flex min-w-0 items-center gap-2"><span v-if="index" aria-hidden="true" class="text-slate-600">›</span><router-link :to="`/knowledge/${node.id}?from=domains`" class="break-words text-indigo-200 hover:underline">{{ node.name }}</router-link></li>
          </ol>
          <span v-if="path.nodes.length <= 1" class="text-xs text-slate-400">{{ path.incomplete ? '当前位置可在目录中调整' : '目录顶层' }}</span>
        </div>
        <p v-if="!paths.length && !busy && !error" class="mt-4 text-xs text-slate-500">尚未归入领域</p>
        <button v-if="domainNext !== null" :disabled="busy" class="mt-4 text-xs text-indigo-300 disabled:opacity-40" @click="load('domains')">查看更多领域</button>
      </section>
      <section aria-label="使用此知识" class="min-w-0 rounded-xl border border-teal-400/15 bg-teal-400/[0.03] p-4 sm:p-5">
        <h2 class="flex items-center gap-2 text-sm font-medium text-teal-200"><span class="h-2 w-2 rounded-full bg-teal-400" />应用于问题与项目<span class="ml-auto text-xs font-normal text-slate-500">{{ useTotal }} 条引用</span></h2>
        <article v-for="use in uses" :key="use.usage_id" class="mt-4 border-l border-teal-400/30 pl-3">
          <router-link v-if="use.project" :to="`/knowledge/${use.project.id}?from=projects`" class="mb-1 block break-words text-xs text-slate-500 hover:text-teal-200">{{ use.project.name }}{{ use.project.status === 'archived' ? '（已归档）' : '' }}</router-link>
          <p v-else class="mb-1 text-[11px] text-slate-500">{{ use.context.kind === 'question' ? '独立问题' : '项目直接引用' }}</p>
          <router-link :to="`/knowledge/${use.context.id}?from=projects`" class="block break-words text-sm leading-6 text-teal-100 hover:underline">{{ use.context.name }}</router-link>
          <div class="mt-2 flex flex-wrap items-center gap-3 text-[11px] text-slate-500"><span>{{ usageNames[use.role] }} v{{ use.knowledge_revision }}</span><span v-if="use.context.status === 'archived'">{{ stateNames[use.context.status] }}</span><span v-if="use.knowledge_revision !== use.current_revision" class="text-amber-300/80">历史版本</span><router-link :to="`/knowledge/${use.usage_id}?from=projects`" class="text-slate-400 hover:text-teal-200">使用记录 ↗</router-link></div>
        </article>
        <p v-if="!uses.length && !busy && !error" class="mt-4 text-xs text-slate-500">尚无问题或项目引用</p>
        <button v-if="useNext !== null" :disabled="busy" class="mt-4 text-xs text-teal-300 disabled:opacity-40" @click="load('uses')">查看更多引用</button>
      </section>
    </div>
    <p v-if="busy" class="mt-3 text-xs text-slate-500">读取关联…</p>
  </section>
</template>

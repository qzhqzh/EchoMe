<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { cardCategories, cardKinds, type CardKind, type CardText } from '@/cardCatalog'
import { useI18n } from '@/i18n'

const router = useRouter()
const { locale } = useI18n()
const label = (value: CardText): string => value[locale.value]
const tr = (zh: string, en: string): string => locale.value === 'zh' ? zh : en
const counts = reactive<Record<CardKind, number | null>>({ habits: null, skills: null, knowledge: null })
const latest = reactive<Record<CardKind, string>>({ habits: '', skills: '', knowledge: '' })
const loading = ref(true)

onMounted(async () => {
  const results = await Promise.allSettled(cardKinds.map(kind =>
    api.listMemories({ tags: cardCategories[kind].tag, limit: 1 }),
  ))
  results.forEach((result, index) => {
    if (result.status !== 'fulfilled') return
    const kind = cardKinds[index]
    counts[kind] = result.value.total
    latest[kind] = result.value.items[0]?.title || ''
  })
  loading.value = false
})
</script>

<template>
  <div class="mx-auto max-w-6xl space-y-7">
    <section class="relative overflow-hidden rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-indigo-950 via-slate-900 to-slate-900 p-6 sm:p-9">
      <div class="absolute -right-10 -top-14 h-52 w-52 rounded-full border border-indigo-400/15" aria-hidden="true" />
      <div class="absolute right-12 top-16 h-32 w-32 rounded-full border border-indigo-400/10" aria-hidden="true" />
      <div class="relative max-w-2xl">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-300">EchoMe · Card library</p>
        <h1 class="mt-3 text-3xl font-bold text-slate-50 sm:text-4xl">{{ tr('我的卡库', 'My card library') }}</h1>
        <p class="mt-3 text-sm leading-6 text-slate-300">
          {{ tr('把个人习惯、可复用操作和知识放在各自的卡册里。每张卡仍连接原始记忆，方便整理，也方便 AI 在相关任务中找到它。', 'Keep habits, reusable procedures, and knowledge in separate decks. Every card stays linked to its underlying memory.') }}
        </p>
      </div>
    </section>

    <div class="grid gap-5 md:grid-cols-3">
      <button
        v-for="(kind, index) in cardKinds"
        :key="kind"
        class="group flex min-h-72 flex-col rounded-2xl border border-slate-700 bg-slate-800/80 p-6 text-left shadow-lg transition duration-200 hover:-translate-y-1 hover:border-indigo-400/60 hover:shadow-indigo-950/30 focus:outline-none focus:ring-2 focus:ring-indigo-400"
        @click="router.push(`/cards/${kind}`)"
      >
        <div class="flex items-start justify-between">
          <div class="flex h-12 w-12 items-center justify-center rounded-xl border text-2xl"
               :class="kind === 'habits' ? 'border-indigo-400/30 bg-indigo-400/10 text-indigo-200' : kind === 'skills' ? 'border-amber-400/30 bg-amber-400/10 text-amber-200' : 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200'"
               aria-hidden="true">{{ kind === 'habits' ? '✦' : kind === 'skills' ? '◆' : '◇' }}</div>
          <span class="text-xs tabular-nums text-slate-500">{{ String(index + 1).padStart(2, '0') }}</span>
        </div>
        <h2 class="mt-7 text-2xl font-semibold text-slate-50">{{ label(cardCategories[kind].name) }}</h2>
        <p class="mt-2 text-sm leading-6 text-slate-300">{{ label(cardCategories[kind].description) }}</p>
        <div class="mt-auto border-t border-slate-700 pt-5">
          <p class="text-sm text-slate-200">{{ loading ? tr('正在读取...', 'Loading...') : counts[kind] === null ? tr('暂时无法读取', 'Unavailable') : `${counts[kind]} ${tr('张可用卡片（含待审核）', 'available cards (including review)')}` }}</p>
          <p class="mt-1 truncate text-xs text-slate-400">{{ latest[kind] || label(cardCategories[kind].example) }}</p>
          <span class="mt-4 inline-block text-sm font-medium text-indigo-300 group-hover:text-indigo-200">{{ tr('进入卡册 →', 'Open deck →') }}</span>
        </div>
      </button>
    </div>

    <p class="text-sm leading-6 text-slate-400">
      {{ tr('卡片用于查找与管理；是否在一次 AI 工作中使用，仍由记忆层级、作用范围和当前任务决定。', 'Cards help you find and manage memories. Layer, scope, and the current task determine when AI uses them.') }}
    </p>
  </div>
</template>

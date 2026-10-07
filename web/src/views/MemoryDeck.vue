<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import { cardCategories, type CardKind, type CardText } from '@/cardCatalog'
import Modal from '@/components/Modal.vue'
import { useI18n } from '@/i18n'
import { MEMORY_TYPES } from '@/types'
import type { MemoryCardRating, MemoryListItem, MemoryType } from '@/types'

const props = defineProps<{ kind?: CardKind }>()
const router = useRouter()
const { locale } = useI18n()
const tr = (zh: string, en: string): string => locale.value === 'zh' ? zh : en
const label = (value: CardText): string => value[locale.value]
const category = computed(() => props.kind ? cardCategories[props.kind] : null)
const backPath = computed(() => props.kind ? `/cards/${props.kind}` : '/cards')
const deckTitle = computed(() => category.value
  ? tr(`逐张核对${category.value.name.zh}`, `Review ${category.value.name.en.toLowerCase()}`)
  : tr('逐张核对记忆', 'Review memories'))

const batchSize = 8
const queue = ref<MemoryListItem[]>([])
const total = ref(0)
const skippedOffset = ref(0)
const reviewedThisSession = ref(0)
const statusFilter = ref<'all' | 'active' | 'ai_review'>('all')
const typeFilter = ref<MemoryType | ''>('')
const loading = ref(false)
const submitting = ref(false)
const loadError = ref(false)
const wrongDialogOpen = ref(false)
const wrongNote = ref('')
const lastFlaggedId = ref<string | null>(null)
const touchStart = ref<{ x: number; y: number } | null>(null)
let loadSequence = 0

const current = computed(() => queue.value[0] || null)
const roundFinished = computed(() => !loading.value && !current.value && total.value > 0 && skippedOffset.value > 0)

async function loadDeck(reset = false): Promise<void> {
  if (reset) {
    skippedOffset.value = 0
    reviewedThisSession.value = 0
    queue.value = []
    lastFlaggedId.value = null
  }
  const sequence = ++loadSequence
  loading.value = true
  loadError.value = false
  try {
    const response = await api.listMemories({
      card_review: 'unreviewed',
      tags: category.value?.tag,
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      type: typeFilter.value || undefined,
      offset: skippedOffset.value,
      limit: batchSize,
    })
    if (sequence !== loadSequence) return
    queue.value = response.items
    total.value = response.total
  } catch {
    if (sequence !== loadSequence) return
    loadError.value = true
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

onMounted(() => { void loadDeck(true) })
watch([statusFilter, typeFilter, () => props.kind], () => { void loadDeck(true) })

async function advance(reviewed: boolean): Promise<void> {
  queue.value.shift()
  if (reviewed) {
    total.value = Math.max(0, total.value - 1)
    reviewedThisSession.value += 1
  } else {
    skippedOffset.value += 1
  }
  if (queue.value.length === 0) await loadDeck()
}

async function submitRating(rating: MemoryCardRating, note?: string): Promise<void> {
  if (!current.value || submitting.value || loading.value) return
  const memoryId = current.value.id
  submitting.value = true
  try {
    await api.reviewMemoryCard({ memory_id: memoryId, rating, note: note || null })
    loadError.value = false
    wrongDialogOpen.value = false
    wrongNote.value = ''
    if (rating === 'wrong') lastFlaggedId.value = memoryId
    if (current.value?.id === memoryId) await advance(true)
  } catch {
    loadError.value = true
  } finally {
    submitting.value = false
  }
}

function skipCard(): void {
  if (!current.value || submitting.value || loading.value) return
  void advance(false)
}

function beginTouch(event: TouchEvent): void {
  if (submitting.value || loading.value || !current.value || event.touches.length !== 1) return
  const target = event.target
  if (target instanceof Element && target.closest('button, a, input, textarea, select')) return
  touchStart.value = { x: event.touches[0].clientX, y: event.touches[0].clientY }
}

function endTouch(event: TouchEvent): void {
  const start = touchStart.value
  touchStart.value = null
  if (!start || !current.value || submitting.value || loading.value) return
  const dx = event.changedTouches[0].clientX - start.x
  const dy = event.changedTouches[0].clientY - start.y
  if (Math.abs(dx) < 85 || Math.abs(dx) < Math.abs(dy) * 1.4) return
  if (dx > 0) void submitRating('helpful')
  else wrongDialogOpen.value = true
}

function closeWrongDialog(): void {
  if (submitting.value) return
  wrongDialogOpen.value = false
  wrongNote.value = ''
}
</script>

<template>
  <div class="mx-auto max-w-3xl space-y-5 pb-36 sm:pb-8">
    <div class="flex items-center justify-between gap-3">
      <button class="text-sm text-slate-400 hover:text-slate-200" @click="router.push(backPath)">← {{ category ? tr('返回卡册', 'Card collection') : tr('返回卡库', 'Card library') }}</button>
      <div class="flex items-center gap-3">
        <button class="text-xs text-slate-400 hover:text-slate-200" @click="router.push('/memories?status=pending')">{{ tr('待修正', 'Needs correction') }}</button>
        <span class="rounded-full border border-emerald-400/25 bg-emerald-400/10 px-3 py-1 text-xs font-medium text-emerald-200">{{ category ? label(category.name) : tr('记忆卡', 'Memory cards') }}</span>
      </div>
    </div>

    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold text-slate-100">{{ deckTitle }}</h1>
        <p class="mt-1 text-sm text-slate-400">{{ tr('有用或暂时无用只记录评价；有误会进入待修正。', 'Useful or not useful now records feedback; incorrect sends a memory for correction.') }}</p>
      </div>
      <div class="text-right text-sm text-slate-300">
        <p><span class="text-xl font-semibold text-emerald-300">{{ total }}</span> {{ tr('条待判断', 'to review') }}</p>
        <p class="text-xs text-slate-500">{{ tr('本轮已判断', 'Reviewed this round') }} {{ reviewedThisSession }}</p>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-2">
      <label class="text-xs text-slate-400">
        <span class="mb-1 block">{{ tr('状态', 'Status') }}</span>
        <select v-model="statusFilter" class="input-field w-full" :disabled="submitting">
          <option value="all">{{ tr('全部可用记忆', 'All available') }}</option>
          <option value="active">active</option>
          <option value="ai_review">ai_review</option>
        </select>
      </label>
      <label class="text-xs text-slate-400">
        <span class="mb-1 block">{{ tr('类型', 'Type') }}</span>
        <select v-model="typeFilter" class="input-field w-full" :disabled="submitting">
          <option value="">{{ tr('全部类型', 'All types') }}</option>
          <option v-for="type in MEMORY_TYPES" :key="type" :value="type">{{ type }}</option>
        </select>
      </label>
    </div>

    <div v-if="lastFlaggedId" class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
      <span>{{ tr('有误记忆已移入待修正，默认 AI 检索会避开它。', 'Incorrect memory moved to the correction queue and excluded from default AI retrieval.') }}</span>
      <button class="font-medium underline underline-offset-2" @click="router.push(`/memories/${lastFlaggedId}`)">{{ tr('查看并修正', 'Open to correct') }}</button>
    </div>

    <div v-if="loadError" class="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
      <span>{{ tr('操作或读取失败，请刷新卡片后重试。', 'Could not save or load. Refresh the deck and try again.') }}</span>
      <button class="font-medium underline underline-offset-2" @click="loadDeck(true)">{{ tr('刷新', 'Refresh') }}</button>
    </div>

    <div v-if="loading" class="min-h-96 animate-pulse rounded-3xl border border-slate-700 bg-slate-800/80 p-7">
      <div class="h-4 w-28 rounded bg-slate-700" />
      <div class="mt-8 h-7 w-3/4 rounded bg-slate-700" />
      <div class="mt-8 h-4 w-full rounded bg-slate-700" />
      <div class="mt-3 h-4 w-5/6 rounded bg-slate-700" />
    </div>

    <div v-else-if="!current" class="rounded-3xl border border-slate-700 bg-slate-800/70 px-6 py-16 text-center">
      <div class="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-400/10 text-3xl text-emerald-300" aria-hidden="true">✓</div>
      <h2 class="mt-5 text-xl font-semibold text-slate-100">{{ roundFinished ? tr('这一轮看完了', 'This round is done') : category ? tr('当前没有待判断的卡片', 'No cards waiting for review') : tr('这些记忆已看完', 'All caught up') }}</h2>
      <p class="mx-auto mt-2 max-w-md text-sm leading-6 text-slate-400">{{ roundFinished ? tr('跳过的卡片仍在队列里，可以从头再看。', 'Skipped cards remain in the queue. Start again when ready.') : category ? tr('可以返回卡册新增或收录卡片，也可以切换筛选条件。', 'Return to the collection to add cards, or change filters.') : tr('切换筛选条件，或等新记忆加入后再来。', 'Change filters or return when new memories are added.') }}</p>
      <button v-if="roundFinished" class="btn-primary mt-6" @click="loadDeck(true)">{{ tr('重看跳过的', 'Review skipped cards') }}</button>
      <button v-else-if="category" class="btn-secondary mt-6" @click="router.push(backPath)">{{ tr('返回卡册', 'Open collection') }}</button>
    </div>

    <div v-else class="space-y-4">
      <article
        :key="current.id"
        class="touch-pan-y overflow-hidden rounded-3xl border border-emerald-400/20 bg-gradient-to-br from-slate-800 via-slate-800 to-emerald-950/40 shadow-xl shadow-slate-950/20"
        @touchstart.passive="beginTouch"
        @touchend.passive="endTouch"
      >
        <div class="border-b border-slate-700/70 px-5 py-4 sm:px-7">
          <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span class="font-semibold tracking-widest text-emerald-300">ECHOME · {{ category ? label(category.cardLabel) : 'MEMORY' }}</span>
            <span class="rounded-full bg-slate-700/70 px-2.5 py-1 text-slate-300">{{ current.type }} · {{ current.layer }} · P{{ current.priority }}</span>
          </div>
          <h2 class="mt-5 break-words text-xl font-semibold leading-snug text-slate-50 sm:text-2xl">{{ current.title }}</h2>
          <p class="mt-2 text-xs text-slate-400">{{ current.scope.global ? tr('全局记忆', 'Global memory') : current.scope.projects.join(' · ') }} · {{ current.status }}</p>
        </div>

        <div class="px-5 py-5 sm:px-7">
          <div class="max-h-[43vh] min-h-36 overflow-y-auto whitespace-pre-wrap break-words pr-1 text-sm leading-7 text-slate-200 scrollbar-thin sm:text-base">{{ current.content }}</div>
          <div v-if="current.tags.length" class="mt-5 flex flex-wrap gap-1.5 border-t border-slate-700/70 pt-4">
            <span v-for="tag in current.tags.slice(0, 6)" :key="tag" class="rounded-full bg-slate-700/60 px-2.5 py-1 text-xs text-slate-300">#{{ tag }}</span>
            <span v-if="current.tags.length > 6" class="px-1 py-1 text-xs text-slate-400">+{{ current.tags.length - 6 }}</span>
          </div>
        </div>
        <div class="flex items-center justify-between border-t border-slate-700/70 px-5 py-3 text-xs text-slate-400 sm:px-7">
          <span>{{ tr('更新于', 'Updated') }} {{ new Date(current.updated_at).toLocaleDateString() }}</span>
          <button class="font-medium text-emerald-300 hover:text-emerald-200" @click="router.push(category ? `/cards/${props.kind}/${current.id}` : `/memories/${current.id}`)">{{ category ? tr('查看卡片 ↗', 'Open card ↗') : tr('查看原记忆 ↗', 'Open memory ↗') }}</button>
        </div>
      </article>

      <p class="text-center text-xs text-slate-500">{{ tr('右滑有用 · 左滑有误 · 上下滑动阅读', 'Swipe right for useful · left for incorrect · scroll to read') }}</p>
      <div class="fixed inset-x-0 bottom-0 z-20 grid grid-cols-2 gap-2 border-t border-slate-700 bg-slate-950/95 px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-3 backdrop-blur sm:static sm:grid-cols-4 sm:border-0 sm:bg-transparent sm:p-0">
        <button class="min-h-12 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-3 py-2 text-sm font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-50" :disabled="submitting" @click="submitRating('helpful')">{{ tr('有用 →', 'Useful →') }}</button>
        <button class="min-h-12 rounded-xl border border-slate-600 bg-slate-700/50 px-3 py-2 text-sm font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50" :disabled="submitting" @click="submitRating('irrelevant')">{{ tr('暂时无用', 'Not useful now') }}</button>
        <button class="min-h-12 rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-sm font-medium text-rose-200 hover:bg-rose-500/20 disabled:opacity-50" :disabled="submitting" @click="wrongDialogOpen = true">{{ tr('← 有误', '← Incorrect') }}</button>
        <button class="min-h-12 rounded-xl border border-slate-600 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800 disabled:opacity-50" :disabled="submitting" @click="skipCard">{{ tr('稍后', 'Later') }}</button>
      </div>
    </div>

    <Modal :open="wrongDialogOpen" :title="tr('标记这条记忆有误', 'Mark this memory incorrect')" @close="closeWrongDialog">
      <p class="text-sm leading-6 text-slate-300">{{ tr('确认后它会进入待修正队列，默认 AI 检索不会再使用。你可以先写下问题，稍后打开原记忆修改。', 'This moves the memory to the correction queue and removes it from default AI retrieval. Add a note now or edit the memory later.') }}</p>
      <label class="mt-4 block text-sm text-slate-300">
        {{ tr('哪里有误（可选）', 'What is wrong? (optional)') }}
        <textarea v-model="wrongNote" class="input-field mt-2 min-h-24 w-full" :maxlength="4000" :placeholder="tr('例如：旧地址已停用、步骤顺序有误', 'For example: old address is retired, steps are out of order')" />
      </label>
      <template #footer>
        <button class="btn-secondary" :disabled="submitting" @click="closeWrongDialog">{{ tr('取消', 'Cancel') }}</button>
        <button class="btn-danger" :disabled="submitting" @click="submitRating('wrong', wrongNote.trim())">{{ submitting ? tr('保存中…', 'Saving…') : tr('标记待修正', 'Flag for correction') }}</button>
      </template>
    </Modal>
  </div>
</template>

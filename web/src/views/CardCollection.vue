<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import { cardCategories, cardFieldValue, cardSteps, type CardField, type CardKind, type CardText } from '@/cardCatalog'
import Modal from '@/components/Modal.vue'
import { useI18n } from '@/i18n'
import { useToast } from '@/stores/toast'
import type { Memory, MemoryListItem } from '@/types'

const props = defineProps<{ kind: CardKind }>()
const route = useRoute()
const router = useRouter()
const { locale } = useI18n()
const { success, error } = useToast()
const tr = (zh: string, en: string): string => locale.value === 'zh' ? zh : en
const label = (value: CardText): string => value[locale.value]
const category = computed(() => cardCategories[props.kind])

const cards = ref<MemoryListItem[]>([])
const cardDetails = ref<Record<string, Memory>>({})
const selected = ref<Memory | null>(null)
const loadingCards = ref(false)
const loadingSelected = ref(false)
const saving = ref(false)
const showArchived = ref(false)
const showCreate = ref(false)
const showArchiveConfirm = ref(false)
const showImport = ref(false)
const showRuleEdit = ref(false)
const importQuery = ref('')
const importResults = ref<MemoryListItem[]>([])
const searching = ref(false)
const loadError = ref(false)

const newTitle = ref('')
const newValues = reactive<Record<string, string>>({})
const editPositive = ref('')
const editAvoid = ref('')

const selectedId = computed(() => String(route.params.id || ''))
const selectedIsCard = computed(() => selected.value?.tags.includes(category.value.tag) ?? false)
const previewField = computed(() => category.value.fields.find(field => field.key !== category.value.summaryField)?.key || '')
const positiveField = computed(() => category.value.fields.find(field => field.key === category.value.summaryField)!)
const avoidField = computed(() => category.value.fields.find(field => field.key === 'avoid')!)
const draftSteps = computed(() => cardSteps(newValues.procedure || ''))
const selectedFields = computed(() => category.value.fields
  .map(field => ({ field, value: selected.value ? labeledValue(selected.value.content, field) : '' }))
  .filter(item => item.value))
const hasStructuredFields = computed(() => category.value.fields
  .filter(field => field.required)
  .every(field => selectedFields.value.some(item => item.field.key === field.key)))
let listRequestId = 0

watch([showArchived, () => props.kind], () => { void loadCards() }, { immediate: true })
watch(selectedId, () => { showRuleEdit.value = false; void loadSelected() }, { immediate: true })
watch(() => props.kind, () => {
  showCreate.value = false
  newTitle.value = ''
  Object.keys(newValues).forEach(key => { newValues[key] = '' })
})

function cardPath(id: string): string {
  return `/cards/${props.kind}/${encodeURIComponent(id)}`
}

function matchingPrefix(line: string, field: CardField): string | undefined {
  return [field.prefix.zh, field.prefix.en].find(prefix =>
    line.toLowerCase().startsWith(`${prefix.toLowerCase()}:`) || line.toLowerCase().startsWith(`${prefix.toLowerCase()}：`),
  )
}

function labeledValue(content: string, field: CardField): string {
  const line = content.split('\n').map(value => value.trim()).find(value => matchingPrefix(value, field))
  const prefix = line && matchingPrefix(line, field)
  return line && prefix ? line.slice(prefix.length + 1).trim() : ''
}

function cardLine(content: string, fieldKey: string, maxLength = 150): string {
  const field = category.value.fields.find(item => item.key === fieldKey)
  if (!field) return ''
  const lines = content.split('\n').map(value => value.trim()).filter(Boolean)
  const line = labeledValue(content, field) || (fieldKey === category.value.summaryField ? lines.find(value => !value.startsWith('#')) || '' : '')
  const summary = fieldKey === 'procedure' ? cardSteps(line)[0] || line : line
  const clean = summary.replace(/^[-*\s]+/, '').replace(/\*\*/g, '')
  return clean.length > maxLength ? `${clean.slice(0, maxLength)}…` : clean
}

function cardSummary(item: MemoryListItem): string {
  return cardLine(cardDetails.value[item.id]?.content || '', category.value.summaryField)
}

function readableContent(content: string): string {
  return content.replace(/\*\*/g, '').replace(/^#{1,4}\s*/gm, '')
}

function statusLabel(status: Memory['status']): string {
  if (status === 'archived') return tr('已停用', 'Inactive')
  if (status === 'ai_review' || status === 'pending') return tr('待审核', 'Review')
  return tr('生效中', 'Active')
}

async function loadCards(): Promise<void> {
  loadingCards.value = true
  loadError.value = false
  const requestId = ++listRequestId
  try {
    const response = await api.listMemories({
      tags: category.value.tag,
      status: showArchived.value ? 'archived' : undefined,
      limit: 200,
    })
    if (requestId !== listRequestId) return
    cards.value = response.items
    const loaded = await Promise.allSettled(response.items.slice(0, 24).map(item => api.getMemory(item.id)))
    if (requestId !== listRequestId) return
    cardDetails.value = Object.fromEntries(
      loaded.flatMap(result => result.status === 'fulfilled' ? [[result.value.id, result.value]] : []),
    )
  } catch {
    if (requestId === listRequestId) {
      cards.value = []
      cardDetails.value = {}
      loadError.value = true
    }
  } finally {
    if (requestId === listRequestId) loadingCards.value = false
  }
}

async function loadSelected(): Promise<void> {
  if (!selectedId.value) {
    selected.value = null
    return
  }
  loadingSelected.value = true
  try {
    selected.value = await api.getMemory(selectedId.value)
  } catch {
    selected.value = null
  } finally {
    loadingSelected.value = false
  }
}

async function createCard(): Promise<void> {
  if (!newTitle.value.trim() || category.value.fields.some(field => field.required && !newValues[field.key]?.trim())) {
    error(tr('请填写所有必填项。', 'Fill in all required fields.'))
    return
  }
  let content: string
  try {
    content = category.value.fields
      .filter(field => newValues[field.key]?.trim())
      .map(field => `${label(field.prefix)}${locale.value === 'zh' ? '：' : ': '}${cardFieldValue(field, newValues[field.key], locale.value)}`)
      .join('\n\n')
  } catch (cause) {
    error(cause instanceof Error ? cause.message : tr('卡片格式有误。', 'Invalid card format.'))
    return
  }
  saving.value = true
  try {
    const created = await api.createMemory({
      title: newTitle.value.trim(),
      content,
      type: category.value.memoryType,
      layer: category.value.layer,
      priority: category.value.priority,
      tags: [category.value.tag],
      status: 'active',
      scope: { global: true, projects: [], exclude_projects: [] },
      source: 'manual',
    })
    showCreate.value = false
    newTitle.value = ''
    Object.keys(newValues).forEach(key => { newValues[key] = '' })
    success(tr('卡片已创建', 'Card created'))
    await loadCards()
    await router.push(cardPath(created.id))
  } catch {
    // The API client displays the error.
  } finally {
    saving.value = false
  }
}

function startRuleEdit(): void {
  if (!selected.value) return
  const positive = labeledValue(selected.value.content, positiveField.value)
  editPositive.value = props.kind === 'skills' ? cardSteps(positive).join('\n') : positive
  editAvoid.value = labeledValue(selected.value.content, avoidField.value)
  showRuleEdit.value = true
}

function updateLabeledLine(lines: string[], field: CardField, value: string, insertAfter?: CardField): void {
  const index = lines.findIndex(line => matchingPrefix(line.trim(), field))
  if (index >= 0) {
    if (value) lines[index] = `${label(field.prefix)}：${value}`
    else lines.splice(index, 1)
    return
  }
  if (!value) return
  const afterIndex = insertAfter ? lines.findIndex(line => matchingPrefix(line.trim(), insertAfter)) : -1
  lines.splice(afterIndex >= 0 ? afterIndex + 1 : 0, 0, `${label(field.prefix)}：${value}`)
}

async function saveCardRules(): Promise<void> {
  if (!selected.value || !editPositive.value.trim()) return
  const lines = selected.value.content.split('\n')
  let positive: string
  try {
    positive = cardFieldValue(positiveField.value, editPositive.value, locale.value)
  } catch (cause) {
    error(cause instanceof Error ? cause.message : tr('卡片格式有误。', 'Invalid card format.'))
    return
  }
  const avoid = cardFieldValue(avoidField.value, editAvoid.value, locale.value)
  updateLabeledLine(lines, positiveField.value, positive)
  updateLabeledLine(lines, avoidField.value, avoid, positiveField.value)
  const content = lines.join('\n')
  if (content === selected.value.content) {
    showRuleEdit.value = false
    return
  }
  saving.value = true
  try {
    selected.value = await api.patchMemory(selected.value.id, { content, expected_updated_at: selected.value.updated_at })
    showRuleEdit.value = false
    success(tr('卡片规则已更新', 'Card rules updated'))
    await loadCards()
  } catch {
    // The API client displays the error.
  } finally {
    saving.value = false
  }
}

async function addToCards(item: MemoryListItem | Memory): Promise<void> {
  if (item.tags.includes(category.value.tag)) return
  saving.value = true
  try {
    selected.value = await api.patchMemory(item.id, { tags: [...item.tags, category.value.tag] })
    success(tr('已加入卡册', 'Added to deck'))
    await loadCards()
    if (selectedId.value !== item.id) await router.push(cardPath(item.id))
  } catch {
    // The API client displays the error.
  } finally {
    saving.value = false
  }
}

async function setCardActive(active: boolean): Promise<void> {
  if (!selected.value) return
  saving.value = true
  try {
    selected.value = await api.patchMemory(selected.value.id, { status: active ? 'active' : 'archived' })
    showArchiveConfirm.value = false
    success(active ? tr('卡片已启用', 'Card enabled') : tr('卡片已停用', 'Card disabled'))
    await loadCards()
  } catch {
    // The API client displays the error.
  } finally {
    saving.value = false
  }
}

async function searchExisting(): Promise<void> {
  if (!importQuery.value.trim()) {
    importResults.value = []
    return
  }
  searching.value = true
  try {
    const response = await api.listMemories({ query: importQuery.value.trim(), status: 'active', limit: 30 })
    importResults.value = response.items.filter(item => !item.tags.includes(category.value.tag))
  } catch {
    importResults.value = []
  } finally {
    searching.value = false
  }
}

async function copyLink(): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(window.location.href)
    } else {
      const input = document.createElement('textarea')
      input.value = window.location.href
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.appendChild(input)
      input.select()
      const copied = document.execCommand('copy')
      input.remove()
      if (!copied) throw new Error('Copy failed')
    }
    success(tr('卡片链接已复制', 'Card link copied'))
  } catch {
    error(tr('复制失败，请从地址栏复制链接', 'Could not copy; use the address bar'))
  }
}
</script>

<template>
  <div class="mx-auto max-w-6xl space-y-6">
    <button class="text-sm text-slate-400 hover:text-slate-200" @click="router.push('/cards')">← {{ tr('返回卡库', 'Back to card library') }}</button>
    <template v-if="!selectedId">
      <section class="relative overflow-hidden rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-indigo-950 via-slate-900 to-slate-900 p-6 sm:p-8">
        <div class="absolute -right-12 -top-16 h-48 w-48 rounded-full border border-indigo-400/20" aria-hidden="true" />
        <div class="absolute -right-4 -top-8 h-48 w-48 rounded-full border border-indigo-400/10" aria-hidden="true" />
        <div class="relative max-w-2xl">
          <p class="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-300">EchoMe · {{ label(category.cardLabel) }}</p>
          <h1 class="mt-3 text-3xl font-bold text-slate-50">{{ label(category.deckName) }}</h1>
          <p class="mt-3 text-sm leading-6 text-slate-300">
            {{ label(category.description) }} {{ tr('卡片仍是你的记忆；停用后不再进入活跃上下文。', 'Each card is a memory; disabling it removes it from active context.') }}
          </p>
          <div class="mt-6 flex flex-wrap gap-3">
            <button class="btn-primary" @click="showCreate = true">+ {{ tr('新增', 'New ') }}{{ label(category.cardLabel) }}</button>
            <button class="btn-secondary" @click="showImport = !showImport">{{ tr('从已有记忆收录', 'Add existing memory') }}</button>
          </div>
        </div>
      </section>

      <section v-if="showCreate" class="card space-y-5">
        <div class="flex items-center justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-slate-100">{{ tr('创建', 'Create ') }}{{ label(category.cardLabel) }}</h2>
            <p class="mt-1 text-sm text-slate-400">{{ tr('一张卡只写一个可复用经验；带 * 的项目必填。', 'Keep one reusable idea per card. Fields marked * are required.') }}</p>
          </div>
          <button class="shrink-0 whitespace-nowrap text-sm text-slate-400 hover:text-slate-200" @click="showCreate = false">{{ tr('收起', 'Close') }}</button>
        </div>
        <div class="grid items-start gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
          <form class="grid gap-4 md:grid-cols-2" @submit.prevent="createCard">
            <label class="block space-y-1.5 md:col-span-2">
              <span class="text-sm font-medium text-slate-200">{{ tr('卡片名称', 'Card name') }} <span class="text-amber-300">*</span></span>
              <input v-model="newTitle" class="input-field" maxlength="100" :placeholder="label(category.example)" required />
              <span class="block text-xs text-slate-500">{{ tr('用具体短标题命名，最多 100 字。', 'Use a specific short title, up to 100 characters.') }}</span>
            </label>
            <label v-for="field in category.fields" :key="field.key" class="block space-y-1.5" :class="field.key === 'procedure' ? 'md:col-span-2' : ''">
              <span class="text-sm font-medium text-slate-200">{{ label(field.label) }} <span :class="field.required ? 'text-amber-300' : 'text-slate-500'">{{ field.required ? '*' : tr('· 可选', '· Optional') }}</span></span>
              <textarea v-model="newValues[field.key]" class="input-field resize-y" :class="field.key === 'procedure' ? 'min-h-36' : 'min-h-24'" :maxlength="field.maxLength" :placeholder="label(field.placeholder)" :required="field.required" />
              <span class="flex justify-between gap-2 text-xs leading-5 text-slate-500"><span>{{ label(field.hint) }}</span><span class="shrink-0 tabular-nums">{{ (newValues[field.key] || '').length }}/{{ field.maxLength }}</span></span>
              <span v-if="field.key === 'procedure' && draftSteps.length > 6" class="block text-xs text-amber-300">{{ tr('最多 6 步；更长的流程可拆成多张卡。', 'Use up to 6 steps; split longer workflows into more cards.') }}</span>
            </label>
            <div class="flex justify-end gap-2 md:col-span-2">
              <button type="button" class="btn-secondary" @click="showCreate = false">{{ tr('取消', 'Cancel') }}</button>
              <button type="submit" class="btn-primary" :disabled="saving || (kind === 'skills' && draftSteps.length > 6)">{{ tr('保存卡片', 'Save card') }}</button>
            </div>
            <p class="text-xs leading-5 text-slate-500 md:col-span-2">{{ tr('新卡默认适用于所有项目；创建后可在“编辑完整记忆”中调整层级和作用范围。', 'New cards apply to all projects by default. Edit the underlying memory to change its layer or scope.') }}</p>
          </form>

          <aside class="rounded-2xl border border-indigo-400/30 bg-gradient-to-br from-indigo-950/80 via-slate-900 to-slate-900 p-5 xl:sticky xl:top-6" aria-live="polite">
            <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-indigo-300">{{ tr('卡面预览', 'Card preview') }} · {{ label(category.cardLabel) }}</p>
            <h3 class="mt-5 break-words text-2xl font-semibold text-slate-50">{{ newTitle.trim() || tr('卡片名称', 'Card title') }}</h3>
            <p v-if="newValues[previewField]?.trim()" class="mt-3 whitespace-pre-line text-sm leading-6 text-indigo-200">{{ newValues[previewField].trim() }}</p>
            <div class="mt-6 border-t border-white/10 pt-5">
              <p class="text-xs font-semibold tracking-wider text-emerald-300">{{ label(category.positiveLabel) }}</p>
              <ol v-if="kind === 'skills' && draftSteps.length" class="mt-2 list-inside list-decimal space-y-1 text-sm leading-6 text-slate-100"><li v-for="(step, index) in draftSteps" :key="index">{{ step }}</li></ol>
              <p v-else class="mt-2 whitespace-pre-line break-words text-sm leading-6 text-slate-100">{{ newValues[category.summaryField]?.trim() || tr('填写后显示核心内容', 'The main guidance appears here') }}</p>
            </div>
            <div v-if="newValues.avoid?.trim()" class="mt-5 rounded-xl border border-amber-400/25 bg-amber-400/5 p-3">
              <p class="text-xs font-semibold text-amber-300">{{ label(category.negativeLabel) }}</p>
              <p class="mt-1 whitespace-pre-line break-words text-sm leading-6 text-amber-50">{{ newValues.avoid.trim() }}</p>
            </div>
            <p v-if="kind === 'skills' && newValues.verification?.trim()" class="mt-5 text-xs leading-5 text-slate-300"><span class="font-semibold text-indigo-200">{{ tr('验证：', 'Verify: ') }}</span>{{ newValues.verification.trim() }}</p>
            <p v-if="kind === 'knowledge' && newValues.evidence?.trim()" class="mt-5 text-xs leading-5 text-slate-300"><span class="font-semibold text-indigo-200">{{ tr('依据：', 'Evidence: ') }}</span>{{ newValues.evidence.trim() }}</p>
          </aside>
        </div>
      </section>

      <section v-if="showImport" class="card space-y-4">
        <div>
          <h2 class="text-lg font-semibold text-slate-100">{{ tr('从已有记忆收录', 'Add an existing memory') }}</h2>
          <p class="mt-1 text-sm text-slate-400">{{ tr('收录只增加卡片标签，原有内容、层级和作用范围保持不变。', 'Adding a card only adds a tag; the original content, layer, and scope stay the same.') }}</p>
        </div>
        <form class="flex gap-2" @submit.prevent="searchExisting">
          <input v-model="importQuery" class="input-field" :placeholder="tr('搜索标题或内容，例如“预览”', 'Search title or content, e.g. preview')" />
          <button type="submit" class="btn-secondary shrink-0" :disabled="searching">{{ tr('查找', 'Search') }}</button>
        </form>
        <div v-if="importResults.length" class="divide-y divide-slate-700 rounded-xl border border-slate-700">
          <div v-for="item in importResults" :key="item.id" class="flex flex-wrap items-center justify-between gap-3 p-3">
            <div class="min-w-0">
              <p class="truncate text-sm font-medium text-slate-100">{{ item.title }}</p>
              <p class="text-xs text-slate-400">{{ item.type }} · {{ item.layer }}</p>
            </div>
            <button class="btn-secondary shrink-0" :disabled="saving" @click="addToCards(item)">{{ tr('收录', 'Add') }}</button>
          </div>
        </div>
      </section>

      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 class="text-lg font-semibold text-slate-100">{{ showArchived ? tr('已停用', 'Inactive') : tr('可用卡片', 'Available cards') }}</h2>
          <p class="text-sm text-slate-400">{{ cards.length }} {{ tr('张卡片', 'cards') }}</p>
        </div>
        <button class="text-sm text-indigo-300 hover:text-indigo-200" @click="showArchived = !showArchived">
          {{ showArchived ? tr('查看生效中的卡片', 'View active cards') : tr('查看已停用的卡片', 'View inactive cards') }}
        </button>
      </div>

      <div v-if="loadingCards" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <div v-for="index in 3" :key="index" class="h-56 animate-pulse rounded-2xl bg-slate-800" />
      </div>
      <div v-else-if="loadError" class="card py-12 text-center text-slate-300">{{ tr('卡片暂时无法读取，请稍后重试。', 'Cards are unavailable right now. Please try again.') }}</div>
      <div v-else-if="!cards.length" class="card py-12 text-center">
        <p class="text-slate-200">{{ showArchived ? tr('没有已停用的卡片', 'No inactive cards') : tr('这个卡册还是空的', 'This deck is empty') }}</p>
        <p class="mt-2 text-sm text-slate-400">{{ tr('可以新建一张，或从已有记忆中收录。', 'Create a card or add an existing memory.') }}</p>
      </div>
      <div v-else class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        <button
          v-for="(item, index) in cards"
          :key="item.id"
          class="group flex min-h-56 flex-col rounded-2xl border border-indigo-500/30 bg-gradient-to-br from-slate-800 via-slate-800 to-indigo-950/60 p-5 text-left shadow-lg transition duration-200 hover:-translate-y-1 hover:border-indigo-400/70 hover:shadow-indigo-950/40 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          @click="router.push(cardPath(item.id))"
        >
          <div class="flex items-start justify-between gap-3">
            <span class="text-[11px] font-semibold uppercase tracking-[0.18em] text-indigo-300">{{ label(category.cardLabel) }}</span>
            <span class="text-xs tabular-nums text-slate-500">{{ String(index + 1).padStart(2, '0') }}</span>
          </div>
          <h3 class="mt-5 text-xl font-semibold leading-snug text-slate-50">{{ item.title }}</h3>
          <p v-if="cardDetails[item.id] && cardLine(cardDetails[item.id].content, previewField)" class="mt-2 line-clamp-1 text-xs text-indigo-200/80">{{ cardLine(cardDetails[item.id].content, previewField) }}</p>
          <p class="mt-2 line-clamp-3 text-sm leading-6 text-slate-300">{{ cardSummary(item) || tr('点击查看卡片的完整内容。', 'Open this card to see the full content.') }}</p>
          <div v-if="cardDetails[item.id] && cardLine(cardDetails[item.id].content, 'avoid')" class="mt-4 rounded-lg border border-amber-400/20 bg-amber-400/5 px-3 py-2 text-xs leading-5 text-amber-100">
            <span class="mr-2 font-semibold text-amber-300">{{ label(category.negativeLabel) }}</span>{{ cardLine(cardDetails[item.id].content, 'avoid') }}
          </div>
          <div class="mt-auto flex items-center justify-between gap-2 pt-5">
            <span class="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-300" :class="item.status === 'archived' ? 'border-slate-600 bg-slate-700 text-slate-300' : item.status === 'ai_review' ? 'border-amber-400/30 bg-amber-400/10 text-amber-200' : ''">{{ statusLabel(item.status) }}</span>
            <span class="text-xs text-slate-400 group-hover:text-indigo-200">{{ tr('打开卡片 →', 'Open card →') }}</span>
          </div>
        </button>
      </div>
    </template>

    <template v-else>
      <button class="text-sm text-slate-400 hover:text-slate-200" @click="router.push(`/cards/${kind}`)">← {{ tr('返回', 'Back to ') }}{{ label(category.name) }}</button>
      <div v-if="loadingSelected" class="card h-64 animate-pulse" />
      <div v-else-if="!selected" class="card py-12 text-center text-slate-400">{{ tr('未找到这张卡片。', 'Card not found.') }}</div>
      <div v-else class="grid items-start gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section class="flex min-h-[420px] flex-col rounded-3xl border border-indigo-400/40 bg-gradient-to-br from-indigo-900 via-slate-900 to-slate-950 p-7 shadow-2xl shadow-indigo-950/30 sm:p-9 lg:sticky lg:top-6">
          <div class="flex items-start justify-between gap-3">
            <span class="text-xs font-semibold uppercase tracking-[0.22em] text-indigo-200">EchoMe · {{ label(category.cardLabel) }}</span>
            <span class="rounded-full border border-white/20 px-3 py-1 text-xs text-slate-200">{{ statusLabel(selected.status) }}</span>
          </div>
          <div class="my-auto py-10">
            <div class="mb-7 flex h-14 w-14 items-center justify-center rounded-2xl border border-indigo-300/30 bg-indigo-300/10 text-2xl" aria-hidden="true">{{ kind === 'habits' ? '✦' : kind === 'skills' ? '◆' : '◇' }}</div>
            <h1 class="text-3xl font-bold leading-tight text-white sm:text-4xl">{{ selected.title }}</h1>
            <p v-if="cardLine(selected.content, previewField)" class="mt-3 max-w-md text-sm leading-6 text-indigo-200">{{ cardLine(selected.content, previewField) }}</p>
            <div class="mt-5 max-w-lg space-y-4">
              <div>
                <span class="text-xs font-semibold tracking-wider text-emerald-300">{{ label(category.positiveLabel) }}</span>
                <p class="mt-1 text-base leading-7 text-slate-100">{{ cardLine(selected.content, category.summaryField, 300) }}</p>
              </div>
              <div v-if="cardLine(selected.content, 'avoid')" class="rounded-xl border border-amber-400/25 bg-amber-400/5 p-4">
                <span class="text-xs font-semibold tracking-wider text-amber-300">{{ label(category.negativeLabel) }}</span>
                <p class="mt-1 text-sm leading-6 text-amber-50">{{ cardLine(selected.content, 'avoid', 300) }}</p>
              </div>
            </div>
          </div>
          <div class="flex flex-wrap items-center justify-between gap-3 border-t border-white/15 pt-5 text-xs text-slate-300">
            <span>{{ selected.scope.global ? tr('适用于所有项目', 'All projects') : tr('仅适用于关联项目', 'Linked projects only') }}</span>
            <span>{{ label(category.cardLabel) }}</span>
          </div>
        </section>

        <section class="space-y-5">
          <div v-if="!selectedIsCard" class="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100">
            <p>{{ tr('这条记忆还没有收进当前卡册。收录后会出现在卡片列表。', 'This memory is not in this deck yet. Add it to show it in the list.') }}</p>
            <button class="btn-secondary mt-3" :disabled="saving" @click="addToCards(selected)">{{ tr('收录为', 'Add as ') }}{{ label(category.cardLabel) }}</button>
          </div>
          <div class="card">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <h2 class="text-lg font-semibold text-slate-100">{{ tr('卡片内容', 'Card details') }}</h2>
              <span class="text-xs text-slate-500">{{ tr('源自个人记忆', 'Backed by personal memory') }}</span>
            </div>
            <div v-if="hasStructuredFields" class="mt-5 divide-y divide-slate-700/70">
              <div v-for="item in selectedFields" :key="item.field.key" class="py-4 first:pt-0 last:pb-0">
                <p class="text-xs font-semibold tracking-wider" :class="item.field.key === category.summaryField ? 'text-emerald-300' : item.field.key === 'avoid' ? 'text-amber-300' : 'text-indigo-300'">{{ label(item.field.label) }}</p>
                <ol v-if="item.field.key === 'procedure'" class="mt-2 list-inside list-decimal space-y-1 text-sm leading-7 text-slate-200"><li v-for="(step, index) in cardSteps(item.value)" :key="index">{{ step }}</li></ol>
                <p v-else class="mt-2 whitespace-pre-wrap break-words text-sm leading-7 text-slate-200">{{ item.value }}</p>
              </div>
            </div>
            <div v-else class="mt-4 whitespace-pre-wrap break-words text-sm leading-7 text-slate-300">{{ readableContent(selected.content) }}</div>
            <details v-if="hasStructuredFields" class="mt-5 border-t border-slate-700 pt-4 text-sm text-slate-400">
              <summary class="cursor-pointer hover:text-slate-200">{{ tr('查看完整原始记忆', 'View full original memory') }}</summary>
              <div class="mt-3 whitespace-pre-wrap break-words leading-7 text-slate-300">{{ readableContent(selected.content) }}</div>
            </details>
          </div>
          <form v-if="showRuleEdit && selectedIsCard" class="card space-y-4" @submit.prevent="saveCardRules">
            <h2 class="text-lg font-semibold text-slate-100">{{ tr('编辑正反规则', 'Edit do and avoid rules') }}</h2>
            <label class="block space-y-1.5">
              <span class="text-sm font-medium text-emerald-300">{{ label(category.positiveLabel) }}</span>
              <textarea v-model="editPositive" class="input-field min-h-24 resize-y" :maxlength="positiveField.maxLength" required />
              <span v-if="kind === 'skills'" class="block text-xs text-slate-500">{{ tr('每行一步，最多 6 步。', 'One step per line, up to 6.') }}</span>
            </label>
            <label class="block space-y-1.5">
              <span class="text-sm font-medium text-amber-300">{{ label(category.negativeLabel) }} {{ tr('（可选）', '(optional)') }}</span>
              <textarea v-model="editAvoid" class="input-field min-h-24 resize-y" :maxlength="avoidField.maxLength" :placeholder="label(avoidField.placeholder)" />
            </label>
            <p class="text-xs leading-5 text-slate-400">{{ tr('这里更新卡面的两条规则，原有案例、检查清单和详细说明会保留。', 'This updates the two rules on the card and preserves longer examples and notes.') }}</p>
            <div class="flex justify-end gap-2">
              <button type="button" class="btn-secondary" @click="showRuleEdit = false">{{ tr('取消', 'Cancel') }}</button>
              <button type="submit" class="btn-primary" :disabled="saving">{{ tr('保存规则', 'Save rules') }}</button>
            </div>
          </form>
          <div class="card space-y-4">
            <div class="flex flex-wrap gap-2">
              <span v-for="tag in selected.tags.filter(tag => tag !== category.tag)" :key="tag" class="rounded-full bg-slate-700 px-2.5 py-1 text-xs text-slate-300">#{{ tag }}</span>
            </div>
            <div class="flex flex-wrap gap-2">
              <button class="btn-secondary" @click="copyLink">{{ tr('复制卡片链接', 'Copy card link') }}</button>
              <button v-if="selectedIsCard" class="btn-secondary" @click="startRuleEdit">{{ tr('编辑正反规则', 'Edit do and avoid rules') }}</button>
              <button class="btn-secondary" @click="router.push(`/memories/${selected.id}`)">{{ tr('编辑完整记忆', 'Edit memory') }}</button>
              <button v-if="selectedIsCard && selected.status !== 'archived'" class="btn-danger" @click="showArchiveConfirm = true">{{ tr('停用卡片', 'Disable card') }}</button>
              <button v-if="selectedIsCard && selected.status === 'archived'" class="btn-success" :disabled="saving" @click="setCardActive(true)">{{ tr('重新启用', 'Enable again') }}</button>
            </div>
            <p class="text-xs leading-5 text-slate-500">{{ tr('停用会归档底层记忆，之后可重新启用。', 'Disabling archives the underlying memory. You can enable it again later.') }}</p>
          </div>
        </section>
      </div>
    </template>

    <Modal :open="showArchiveConfirm" :title="tr('停用这张卡片？', 'Disable this card?')" @close="showArchiveConfirm = false">
      <p class="text-sm text-slate-300">{{ tr('底层记忆会被归档，AI 不再将其视为活跃内容。你可以稍后重新启用。', 'The underlying memory will be archived and will no longer be active for AI. You can enable it again later.') }}</p>
      <template #footer>
        <button class="btn-secondary" @click="showArchiveConfirm = false">{{ tr('取消', 'Cancel') }}</button>
        <button class="btn-danger" :disabled="saving" @click="setCardActive(false)">{{ tr('确认停用', 'Disable') }}</button>
      </template>
    </Modal>
  </div>
</template>

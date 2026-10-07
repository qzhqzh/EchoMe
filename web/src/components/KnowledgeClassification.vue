<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { kb, type KRecord, type KnowledgePath } from '@/knowledge'
import { knowledgeError } from '@/knowledge-state'
import { useKnowledgeDraft } from '@/knowledge-draft'
import KnowledgeDialog from './KnowledgeDialog.vue'
import KnowledgeRecordPicker from './KnowledgeRecordPicker.vue'
const props = defineProps<{ owner: KRecord }>()
const emit = defineEmits<{ close: []; saved: [] }>()
const paths = ref<KnowledgePath[]>([]), next = ref<number | null>(null), total = ref(0), busy = ref(false), error = ref('')
const editing = ref<KRecord | null>(null), mode = ref<'move' | 'add' | null>(null), parent = ref<string | null>(null), removal = ref<KRecord | null>(null)
const dirty = computed(() => !!mode.value && (mode.value === 'add' ? !!parent.value : parent.value !== editing.value?.data.parent_id))
useKnowledgeDraft(() => dirty.value)
async function load(more = false) {
  busy.value = true; error.value = ''
  try { const result = await kb.connections<KnowledgePath>(props.owner.id, 'domains', more ? next.value || 0 : 0, 10); paths.value = more ? [...paths.value, ...result.items] : result.items; next.value = result.next_offset; total.value = result.total }
  catch (e) { error.value = knowledgeError(e) } finally { busy.value = false }
}
async function move(path: KnowledgePath) {
  busy.value = true; error.value = ''
  try { editing.value = await kb.get(path.placement_id!); parent.value = editing.value.data.parent_id; mode.value = 'move'; removal.value = null }
  catch (e) { error.value = knowledgeError(e) } finally { busy.value = false }
}
async function remove(path: KnowledgePath) {
  busy.value = true; error.value = ''
  try { const children = await kb.directory({ parent_id: path.placement_id!, limit: 1 }); if (children.total) throw new Error('此位置下还有内容，请移动整个位置，或先整理下级内容。'); removal.value = await kb.get(path.placement_id!); mode.value = null }
  catch (e) { error.value = knowledgeError(e) } finally { busy.value = false }
}
async function save() {
  busy.value = true; error.value = ''
  try {
    if (removal.value) {
      const children = await kb.directory({ parent_id: removal.value.id, limit: 1 })
      if (children.total) throw new Error('此位置下新增了内容，请重新读取后整理。')
      await kb.removePlacement(removal.value)
    } else if (mode.value === 'move' && editing.value) await kb.update(editing.value, { ...editing.value.data, parent_id: parent.value }, '移动目录位置，保留下级内容')
    else await kb.create('placement', { entity_id: props.owner.id, parent_id: parent.value })
    mode.value = null
    emit('saved')
  } catch (e) { error.value = knowledgeError(e) } finally { busy.value = false }
}
onMounted(() => load())
</script>
<template>
  <KnowledgeDialog title="管理所属领域" :busy="busy" :dirty="dirty" @close="emit('close')">
    <p class="mb-4 break-words text-sm text-slate-400">{{ owner.data.name }} · {{ total }} 处收纳</p>
    <ul class="space-y-3"><li v-for="path in paths" :key="path.placement_id" class="rounded-lg border border-slate-700 p-3"><p class="break-words text-sm leading-6 text-slate-300">{{ path.incomplete ? '部分上级已停用 / ' : '' }}{{ path.nodes.map(n => n.name).join(' / ') }}</p><div class="mt-3 flex gap-5 text-xs"><button :disabled="busy" class="text-blue-300" @click="move(path)">移动到其他领域</button><button v-if="owner.data.entity_kind !== 'topic'" :disabled="busy" class="text-slate-500" @click="remove(path)">移除此分类</button></div></li></ul>
    <p v-if="!paths.length && !busy && !error" class="py-4 text-sm text-slate-500">还没有分类位置。</p>
    <button v-if="next !== null" :disabled="busy" class="mt-3 text-xs text-blue-300" @click="load(true)">加载更多位置</button>
    <button v-if="!mode && !removal" :disabled="busy" class="mt-5 text-sm text-blue-300" @click="mode = 'add'; parent = null; editing = null">＋ 添加分类位置</button>
    <form v-if="mode" class="mt-5 space-y-4 border-t border-slate-700 pt-5" @submit.prevent="save"><h3 class="text-sm text-slate-200">{{ mode === 'move' ? '移动当前位置' : '添加一个位置' }}</h3><KnowledgeRecordPicker v-model="parent" :kinds="['placement']" label="目标领域" empty-label="目录顶层" :exclude-id="owner.id" :disabled="busy" /><p v-if="owner.data.entity_kind === 'topic' && mode === 'move'" class="text-xs text-slate-500">下级领域和知识会一起移动，已有引用保持关联。</p><div class="flex gap-4 text-sm"><button :disabled="busy" class="rounded-lg bg-blue-600 px-4 py-2 disabled:opacity-40">保存位置</button><button type="button" :disabled="busy" class="text-slate-400" @click="mode = null">取消</button></div></form>
    <section v-if="removal" class="mt-5 rounded-lg border border-amber-400/30 p-4"><p class="text-sm text-amber-200">移除此分类位置？知识正文与使用记录会保留。</p><div class="mt-4 flex gap-4 text-sm"><button :disabled="busy" class="text-amber-200" @click="save">确认移除</button><button :disabled="busy" class="text-slate-400" @click="removal = null">取消</button></div></section>
    <p v-if="busy" class="mt-3 text-xs text-slate-500">处理中…</p><p v-if="error" role="alert" class="mt-4 text-sm text-rose-300">{{ error }}</p>
  </KnowledgeDialog>
</template>

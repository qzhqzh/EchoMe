<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api } from '@/api/client'
import { kb, kindNames, issueNames, type KnowledgeKind, type KRecord } from '@/knowledge'
import { knowledgeError } from '@/knowledge-state'
import { useKnowledgeDraft } from '@/knowledge-draft'
import KnowledgeDialog from './KnowledgeDialog.vue'
import KnowledgeRecordPicker from './KnowledgeRecordPicker.vue'

const props = defineProps<{ kind: KnowledgeKind; context?: KRecord; record?: KRecord; preset?: Record<string, any>; placementParentId?: string; requireParent?: boolean }>()
const emit = defineEmits<{ saved: [record: KRecord]; close: [] }>()
interface Field { key: string; label: string; type?: 'area' | 'select' | 'reference'; options?: string[]; kinds?: KnowledgeKind[]; required?: boolean; hint?: string }
const f = (key: string, label: string, type?: Field['type'], extra: Partial<Field> = {}): Field => ({ key, label, type, ...extra })
const specs: Record<KnowledgeKind, Field[]> = {
  project: [f('name', '项目名称', undefined, { required: true }), f('summary', '简短介绍', 'area'), f('status', '进展', 'select', { options: ['draft', 'active', 'ready_for_review', 'delivered', 'archived'] })],
  question: [f('title', '要解决什么问题？', undefined, { required: true }), f('project_id', '所属项目（可独立存在）', 'reference', { kinds: ['project'] }), f('status', '进展', 'select', { options: ['open', 'investigating', 'resolved', 'archived'] }), f('resolution_note', '结论或关闭原因', 'area')],
  entity: [f('name', '知识名称', undefined, { required: true }), f('entity_kind', '类型', 'select', { options: ['topic', 'concept', 'tool', 'method', 'object'] }), f('summary', '简短介绍', 'area', { hint: '先保持粗粒度；完整介绍在详情正文中补充。' }), f('personal_note', '我的理解与疑问', 'area')],
  predicate: [f('code', '稳定英文标识', undefined, { required: true, hint: '例如 suitable_for；建立后保持含义不变。' }), f('label', '显示名称', undefined, { required: true }), f('description', '这类关系的含义', 'area'), f('family', '用途', 'select', { options: ['assertion', 'navigation'] }), f('value_kind', '关联到', 'select', { options: ['entity', 'scalar'] })],
  relation: [f('subject_id', '主体知识', 'reference', { kinds: ['entity'], required: true }), f('predicate_id', '关系类型', 'reference', { kinds: ['predicate'], required: true }), f('object_entity_id', '客体知识', 'reference', { kinds: ['entity'] }), f('statement_md', '完整陈述', 'area'), f('perspective', '结论范围', 'select', { options: ['unspecified', 'personal', 'general'], hint: '一次实践的结论通常先记为个人经验。' })],
  page: [f('title', '文档标题', undefined, { required: true }), f('body_md', '正文（Markdown）', 'area')],
  source: [f('title', '资料标题', undefined, { required: true }), f('source_kind', '来源类型', 'select', { options: ['url', 'file', 'publication', 'practice', 'page'] }), f('origin_ref', '链接或已知出处'), f('retention', '保留方式', 'select', { options: ['reference', 'excerpt', 'internal_version'] }), f('content_text', '实际摘录', 'area'), f('page_id', '引用内部文档', 'reference', { kinds: ['page'] })],
  placement: [f('entity_id', '放入目录的知识', 'reference', { kinds: ['entity'], required: true }), f('parent_id', '上级位置（留空为顶层）', 'reference', { kinds: ['placement'] })],
  usage: [f('knowledge_id', '选择已有知识', 'reference', { kinds: ['entity', 'relation'], required: true }), f('role', '引用用途', 'select', { options: ['used', 'to_research', 'derived'] }), f('application_note', '这次的条件、用法与结果', 'area'), f('page_id', '同时固定介绍文档版本', 'reference', { kinds: ['page'] }), f('deliverable_id', '关联本次成果', 'reference', { kinds: ['deliverable'] })],
  deliverable: [f('title', '成果名称', undefined, { required: true }), f('resource_ref', '实际文件或可访问链接', undefined, { required: true, hint: '登记已经存在的成果。也可使用下面的文件上传。' }), f('format', '文件格式'), f('reproduction_page_id', '复现步骤文档', 'reference', { kinds: ['page'] })],
  review: [f('title', '需要核对的问题', undefined, { required: true }), f('issue_kind', '风险类型', 'select', { options: Object.keys(issueNames) }), f('explanation', '为什么需要核对？有什么依据？', 'area', { required: true })],
  acceptance: [f('criteria_page_id', '验收标准文档', 'reference', { kinds: ['page'] }), f('checks', '实际检查结果', 'area'), f('note', '意见与仍有的限制', 'area'), f('state', '验收结果', 'select', { options: ['submitted', 'accepted', 'rejected'] })],
}
const labels: Record<string, string> = { topic: '领域 / 主题', concept: '概念', tool: '工具', method: '方法', object: '对象', entity: '知识实体', scalar: '数值或文本', assertion: '表达知识陈述', navigation: '目录与导航', personal: '个人实践', general: '通用结论', unspecified: '尚未判断', reference: '仅登记出处', excerpt: '保存必要摘录', internal_version: '固定内部文档版本', url: '网页', file: '文件', publication: '出版物', practice: '实践记录', page: '内部文档', used: '实际使用', to_research: '准备研究', derived: '研究中形成', draft: '草稿', active: '进行中', ready_for_review: '待验收', delivered: '已交付', archived: '归档', open: '待研究', investigating: '研究中', resolved: '已解决', submitted: '提交待验收', accepted: '通过验收', rejected: '需要改进', ...issueNames }
const data = reactive<Record<string, any>>({ ...props.record?.data, ...props.preset })
const recordLabel = computed(() => props.kind === 'entity' && data.entity_kind === 'topic' ? '领域' : kindNames[props.kind])
const options = ref<KRecord[]>([]), loading = ref(true), busy = ref(false), error = ref(''), reviewKey = ref(''), previews = ref(''), scalar = ref(''), sourceId = ref(''), quote = ref(''), locator = ref(''), suggestion = ref('none')
const advanced = ref(!!props.record), placementParent = ref<string | null>(props.placementParentId || null), firstQuestion = ref(''), baseline = ref('')
const refreshVersions = reactive<Record<string, boolean>>({})
const optionalFields = new Set(['status', 'resolution_note', 'personal_note', 'page_id', 'deliverable_id'])
const hasAdvanced = computed(() => !props.record && fields.value.some(field => optionalFields.has(field.key)))
function snapshot() { return JSON.stringify({ data, previews: previews.value, scalar: scalar.value, source: sourceId.value, quote: quote.value, locator: locator.value, placementParent: placementParent.value, firstQuestion: firstQuestion.value, refreshVersions }) }
const dirty = computed(() => !!baseline.value && snapshot() !== baseline.value)
useKnowledgeDraft(() => dirty.value)
function remember(record: KRecord) { options.value = [...options.value.filter(r => r.id !== record.id), record] }
function pinnedVersion(key: string) { return props.record?.data[key.replace(/_id$/, '_revision')] as number | undefined }
function currentVersion(key: string) { return options.value.find(r => r.id === data[key])?.revision }
const fields = computed(() => specs[props.kind].filter(field => {
  if (props.kind === 'entity' && data.entity_kind === 'topic' && field.key === 'entity_kind') return false
  if (props.kind === 'source') {
    if (field.key === 'content_text') return data.retention === 'excerpt' || data.retention === 'snapshot'
    if (field.key === 'page_id') return data.retention === 'internal_version'
  }
  if (props.kind === 'relation' && field.key === 'object_entity_id') return predicate.value?.data.value_kind !== 'scalar'
  return !(props.context && field.key === 'project_id')
}).map(field => props.kind === 'entity' && field.key === 'name'
  ? { ...field, label: recordLabel.value + '名称' }
  : props.kind === 'entity' && field.key === 'entity_kind'
    ? { ...field, options: field.options?.filter(option => option !== 'topic') }
    : field))
const predicate = computed(() => options.value.find(r => r.id === data.predicate_id))
const needReview = computed(() => (props.kind === 'acceptance' && data.state !== 'submitted') || (props.kind === 'project' && data.status === 'delivered') || props.record?.review_state === 'reviewed')
onMounted(() => {
  if (props.kind === 'entity' && !data.entity_kind) data.entity_kind = 'concept'
  for (const field of specs[props.kind]) if (field.type === 'select' && !data[field.key]) data[field.key] = field.options?.[0]
  if (props.kind === 'question' && props.context?.kind === 'project') data.project_id = props.context.id
  if (props.kind === 'usage' && props.context) data.context_id = props.context.id
  if (props.kind === 'source' && props.context) data.context_ids = [props.context.id]
  if (props.kind === 'page' && props.context) data.bindings = [{ target_id: props.context.id, role: 'supplementary' }]
  if (props.kind === 'relation' && props.context?.kind === 'entity') data.subject_id = props.context.id
  if (props.kind === 'deliverable' && props.context) data[props.context.kind === 'project' ? 'project_id' : 'question_id'] = props.context.id
  if (props.kind === 'review' && props.context) data.targets = [{ id: props.context.id, revision: props.context.revision }]
  if (props.kind === 'acceptance' && props.context) { data.deliverable_id = props.context.id; data.deliverable_revision = props.context.revision }
  previews.value = (data.preview_refs || []).join('\n'); scalar.value = data.object_value?.value || ''
  loading.value = false; baseline.value = snapshot()
})
watch(predicate, () => { if (predicate.value?.data.value_kind === 'scalar') data.object_entity_id = null })
async function upload(event: Event, preview = false) {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return
  busy.value = true
  try { const asset = await api.knowledgeAsset(file); if (preview) previews.value += (previews.value ? '\n' : '') + asset.resource_ref; else data.resource_ref = asset.resource_ref }
  catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function save() {
  busy.value = true; error.value = ''
  try {
    const body = { ...data }
    for (const field of fields.value) if (field.type === 'reference' && field.required && !body[field.key]) throw new Error('请先选择' + field.label + '。')
    if (props.requireParent && !placementParent.value) throw new Error('请选择一个上级领域位置。')
    const ids = [...new Set([...fields.value.filter(f => f.type === 'reference').map(f => body[f.key]), sourceId.value].filter(Boolean))] as string[]
    for (const id of ids) if (!options.value.some(r => r.id === id)) remember(await kb.get(id))
    for (const field of specs[props.kind]) if (field.type === 'reference' && !body[field.key]) body[field.key] = null
    for (const field of ['knowledge', 'page', 'deliverable', 'reproduction_page', 'criteria_page']) {
      if (body[field + '_id']) {
        const previous = props.record?.data
        if (previous && previous[field + '_id'] === body[field + '_id'] && previous[field + '_revision'] && !refreshVersions[field + '_id']) body[field + '_revision'] = previous[field + '_revision']
        else {
          const target = options.value.find(r => r.id === body[field + '_id']) || (props.context?.id === body[field + '_id'] ? props.context : undefined)
          body[field + '_revision'] = target?.revision || body[field + '_revision']
        }
      } else if (field + '_revision' in body) body[field + '_revision'] = null
    }
    if (props.kind === 'source' && body.retention !== 'internal_version') { body.page_id = null; body.page_revision = null }
    if (props.kind === 'source' && ['reference', 'internal_version'].includes(body.retention)) body.content_text = ''
    if (props.kind === 'deliverable') body.preview_refs = previews.value.split('\n').map(s => s.trim()).filter(Boolean)
    if (props.kind === 'relation') {
      body.object_value = predicate.value?.data.value_kind === 'scalar' ? { type: 'string', value: scalar.value } : null
      if (sourceId.value) body.evidence = [...(body.evidence || []), { source_id: sourceId.value, source_revision: options.value.find(r => r.id === sourceId.value)?.revision, locator: locator.value, quote: quote.value, role: 'supports' }]
    }
    if (props.kind === 'review') body.proposal = { operation: suggestion.value, target_id: props.context?.id || null }
    let result: KRecord
    if (!props.record && ['project', 'question', 'entity'].includes(props.kind)) {
      result = (await kb.capture({ kind: props.kind, data: body }, {
        ...(props.kind === 'entity' && (body.entity_kind === 'topic' || placementParent.value) ? { placement: { parent_id: placementParent.value } } : {}),
        ...(props.kind === 'entity' && props.context && ['project', 'question'].includes(props.context.kind) ? { context_id: props.context.id } : {}),
        ...(props.kind === 'project' && firstQuestion.value.trim() ? { first_question: firstQuestion.value.trim() } : {}),
      })).record
    } else result = props.record ? await kb.update(props.record, body, 'Web editor', reviewKey.value) : await kb.create(props.kind, body, reviewKey.value)
    baseline.value = snapshot()
    emit('saved', result)
  } catch (e) { error.value = knowledgeError(e) } finally { busy.value = false }
}
</script>
<template>
  <KnowledgeDialog :title="(record ? '编辑' : '新建') + recordLabel" :dirty="dirty" :busy="busy" @close="emit('close')" v-slot="{ requestClose }">
      <form class="space-y-4" @submit.prevent="save">
        <template v-for="field in fields" :key="field.key"><div v-if="record || advanced || !optionalFields.has(field.key)" class="block text-sm text-slate-300">
          <span>{{ field.label }} <span v-if="field.required" class="text-blue-300">*</span></span>
          <textarea v-if="field.type === 'area'" v-model="data[field.key]" :aria-label="field.label" :required="field.required" :rows="field.key === 'body_md' ? 12 : 3" class="kb-input" />
          <KnowledgeRecordPicker v-else-if="field.type === 'reference'" v-model="data[field.key]" :kinds="field.kinds || []" :label="field.label" :required="field.required" :exclude-id="record?.id" :exclude-topics="kind === 'usage' && field.key === 'knowledge_id'" :empty-label="field.key === 'project_id' ? '独立问题，不关联项目' : undefined" :disabled="busy || (!!record && kind === 'usage' && field.key === 'knowledge_id')" @selected="remember" />
          <select v-else-if="field.type === 'select'" v-model="data[field.key]" :aria-label="field.label" class="kb-input"><option v-for="option in field.options" :key="option" :value="option">{{ labels[option] || option }}</option></select>
          <input v-else v-model="data[field.key]" :aria-label="field.label" :required="field.required" :maxlength="field.key === 'resource_ref' ? 4000 : 256" class="kb-input" />
          <span v-if="field.hint" class="mt-1 block text-xs leading-5 text-slate-500">{{ field.hint }}</span>
          <p v-if="record && kind === 'usage' && field.key === 'knowledge_id'" class="mt-2 text-xs leading-5 text-slate-500">更换知识请新建引用，保留这次使用的历史。</p>
          <p v-if="field.type === 'reference' && pinnedVersion(field.key) && record?.data[field.key] === data[field.key]" class="mt-2 text-xs text-slate-500">{{ refreshVersions[field.key] ? '将引用当前' : '固定引用' }} v{{ refreshVersions[field.key] ? currentVersion(field.key) : pinnedVersion(field.key) }}<button v-if="currentVersion(field.key) && currentVersion(field.key) !== pinnedVersion(field.key)" type="button" class="ml-3 text-blue-300" @click="refreshVersions[field.key] = !refreshVersions[field.key]">{{ refreshVersions[field.key] ? '保留原版本' : `改用当前 v${currentVersion(field.key)}` }}</button></p>
        </div></template>
        <label v-if="kind === 'project' && !record" class="block text-sm text-slate-300">首个问题（可选）<input v-model="firstQuestion" aria-label="首个问题" maxlength="256" class="kb-input" placeholder="这个项目首先要解决什么？" /></label>
        <div v-if="kind === 'entity' && !record" class="text-sm text-slate-300"><span>{{ data.entity_kind === 'topic' ? '上级领域' : '所属领域（可选）' }}</span><KnowledgeRecordPicker v-model="placementParent" :kinds="['placement']" label="所属领域位置" :required="requireParent" :empty-label="data.entity_kind === 'topic' ? '作为顶层领域' : '暂不分类'" :disabled="busy" @selected="remember" /></div>
        <button v-if="hasAdvanced" type="button" :aria-expanded="advanced" class="text-sm text-slate-400" @click="advanced = !advanced">{{ advanced ? '收起更多设置' : '更多设置' }}</button>
        <template v-if="kind === 'relation'">
          <label v-if="predicate?.data.value_kind === 'scalar'" class="block text-sm text-slate-300">具体值<input v-model="scalar" required class="kb-input" /></label>
          <details class="rounded-lg border border-slate-700 p-4 text-sm text-slate-400"><summary class="cursor-pointer">补充证据（可以稍后添加）</summary><div class="mt-3">来源<KnowledgeRecordPicker v-model="sourceId" :kinds="['source']" label="证据来源" @selected="remember" /></div><label class="mt-3 block">定位<input v-model="locator" class="kb-input" placeholder="章节、段落、页码或时间点" /></label><label class="mt-3 block">实际引文<textarea v-model="quote" class="kb-input" /></label></details>
        </template>
        <template v-if="kind === 'deliverable'">
          <label class="block text-sm text-blue-300">上传源文件<input type="file" class="mt-2 block w-full text-xs text-slate-400" @change="upload($event)" :disabled="busy" /></label>
          <label class="block text-sm text-slate-300">预览链接（每行一个）<textarea v-model="previews" class="kb-input" /></label>
          <label class="block text-sm text-blue-300">添加预览图<input type="file" accept="image/png,image/jpeg,image/webp" class="mt-2 block w-full text-xs text-slate-400" @change="upload($event, true)" :disabled="busy" /></label>
        </template>
        <label v-if="kind === 'review'" class="block text-sm text-slate-300">建议处理<select v-model="suggestion" class="kb-input"><option value="none">先讨论 / 补证据</option><option value="verify">核对当前版本</option><option value="archive">确认有误后停止复用</option></select></label>
        <label v-if="needReview" class="block rounded-lg border border-amber-500/30 p-4 text-sm text-amber-200">独立审核凭据<input v-model="reviewKey" type="password" autocomplete="off" class="kb-input" required /><span class="mt-2 block text-xs text-slate-400">用于确认验收或修改已核对内容，只用于本次请求，不存入浏览器。</span></label>
        <p v-if="error" role="alert" class="whitespace-pre-wrap break-words text-sm text-rose-300">{{ error }}</p>
        <div class="flex justify-end gap-3 border-t border-slate-700 pt-5"><button type="button" :disabled="busy" class="px-4 text-slate-400 disabled:opacity-30" @click="requestClose">取消</button><button type="submit" :disabled="busy || loading" class="rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white disabled:opacity-50">{{ busy ? '保存中…' : '保存' + recordLabel }}</button></div>
      </form>
  </KnowledgeDialog>
</template>
<style scoped>.kb-input { display: block; width: 100%; margin-top: .5rem; padding: .65rem .8rem; border: 1px solid #475569; border-radius: .5rem; background: #020617; color: #e2e8f0; } .kb-input:focus { outline: 2px solid #3b82f6; outline-offset: 1px; }</style>

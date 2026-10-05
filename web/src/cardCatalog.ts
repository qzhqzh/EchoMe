import type { MemoryLayer, MemoryType } from '@/types'

export type CardKind = 'habits' | 'skills' | 'knowledge'

export interface CardText {
  zh: string
  en: string
}

export interface CardField {
  key: string
  label: CardText
  prefix: CardText
  placeholder: CardText
  hint: CardText
  required: boolean
  maxLength: number
}

export interface CardCategory {
  kind: CardKind
  tag: string
  name: CardText
  deckName: CardText
  description: CardText
  cardLabel: CardText
  positiveLabel: CardText
  negativeLabel: CardText
  example: CardText
  memoryType: MemoryType
  layer: MemoryLayer
  priority: number
  summaryField: string
  fields: CardField[]
}

export const cardKinds: CardKind[] = ['habits', 'skills', 'knowledge']

export const cardCategories: Record<CardKind, CardCategory> = {
  habits: {
    kind: 'habits',
    tag: 'card:habit',
    name: { zh: '习惯卡', en: 'Habit cards' },
    deckName: { zh: '我的习惯卡', en: 'My habit cards' },
    description: { zh: '记录 AI 在特定时机应该做和不要做的事。', en: 'What AI should do and avoid at the right moment.' },
    cardLabel: { zh: '习惯卡', en: 'Habit card' },
    positiveLabel: { zh: '应该做', en: 'Do' },
    negativeLabel: { zh: '不要做', en: 'Avoid' },
    example: { zh: '例如：功能展示', en: 'For example: Feature preview' },
    memoryType: 'style',
    layer: 'L1',
    priority: 7,
    summaryField: 'action',
    fields: [
      { key: 'trigger', label: { zh: '何时触发', en: 'When should it apply?' }, prefix: { zh: '适用时机', en: 'When' }, placeholder: { zh: 'Web 项目完成可预览的改动后', en: 'After a previewable web change' }, hint: { zh: '写具体场景，不写“任何时候”。', en: 'Name a specific situation, not “always”.' }, required: true, maxLength: 400 },
      { key: 'action', label: { zh: '应该做', en: 'What should AI do?' }, prefix: { zh: '执行习惯', en: 'Do' }, placeholder: { zh: '先给我可点击、已验证的预览链接', en: 'First provide a verified, clickable preview link' }, hint: { zh: '以动词开头，写 AI 能执行的动作。', en: 'Start with an action the AI can perform.' }, required: true, maxLength: 500 },
      { key: 'avoid', label: { zh: '不要做 / 常见坑', en: 'What should AI avoid?' }, prefix: { zh: '不要做', en: 'Avoid' }, placeholder: { zh: '不要提供未经验证的地址或只写 localhost', en: 'Do not give an unverified URL or localhost alone' }, hint: { zh: '仅在有真实反例时写具体禁忌，不必为填满卡片而编造。', en: 'Add a concrete pitfall only when one is known.' }, required: false, maxLength: 500 },
    ],
  },
  skills: {
    kind: 'skills',
    tag: 'card:skill',
    name: { zh: '技能卡', en: 'Skill cards' },
    deckName: { zh: '我的技能卡', en: 'My skill cards' },
    description: { zh: '保存可重复的操作步骤、避坑要点和验证方式。', en: 'Reusable steps, pitfalls to avoid, and checks.' },
    cardLabel: { zh: '技能卡', en: 'Skill card' },
    positiveLabel: { zh: '应该做', en: 'Do' },
    negativeLabel: { zh: '不要做', en: 'Avoid' },
    example: { zh: '例如：Blender 模型迭代', en: 'For example: Blender model iteration' },
    memoryType: 'method',
    layer: 'L2',
    priority: 5,
    summaryField: 'procedure',
    fields: [
      { key: 'scenario', label: { zh: '适用任务', en: 'Use when' }, prefix: { zh: '适用任务', en: 'Use when' }, placeholder: { zh: '例如：收到视频主题，需要开始制作时', en: 'When a video topic is ready for production' }, hint: { zh: '说明输入或前提，方便下一次判断能否复用。', en: 'State the input or prerequisite for reuse.' }, required: true, maxLength: 400 },
      { key: 'procedure', label: { zh: '应该做的步骤', en: 'Steps to follow' }, prefix: { zh: '操作步骤', en: 'Steps' }, placeholder: { zh: '先写剧本并确认主题\n按剧本拆分镜头\n制作后对照剧本检查', en: 'Draft and confirm the script\nBreak it into shots\nCheck the result against the script' }, hint: { zh: '每行一步，最多 6 步；保存时自动编号。', en: 'One step per line, up to 6; numbering is automatic.' }, required: true, maxLength: 1200 },
      { key: 'avoid', label: { zh: '不要做 / 常见坑', en: 'What should AI avoid?' }, prefix: { zh: '不要做', en: 'Avoid' }, placeholder: { zh: '不要跳过剧本直接生成，也不要自行增加关键情节', en: 'Do not skip the script or invent major plot points' }, hint: { zh: '只记录遇到过的坑及替代做法的边界。', en: 'Record a known pitfall and its boundary.' }, required: false, maxLength: 500 },
      { key: 'verification', label: { zh: '验证方式', en: 'How to verify' }, prefix: { zh: '验证方式', en: 'Verify' }, placeholder: { zh: '成片与已确认的剧本、分镜一致', en: 'The result matches the approved script and shots' }, hint: { zh: '写可观察的结果，不写“感觉不错”。', en: 'Name an observable result.' }, required: true, maxLength: 500 },
    ],
  },
  knowledge: {
    kind: 'knowledge',
    tag: 'card:knowledge',
    name: { zh: '知识卡', en: 'Knowledge cards' },
    deckName: { zh: '我的知识卡', en: 'My knowledge cards' },
    description: { zh: '保留结论、适用条件、误用边界与来源。', en: 'Claims, conditions, misuse boundaries, and sources.' },
    cardLabel: { zh: '知识卡', en: 'Knowledge card' },
    positiveLabel: { zh: '可用知识', en: 'Use' },
    negativeLabel: { zh: '避免误用', en: 'Avoid misuse' },
    example: { zh: '例如：为什么采用 WG 分层网络', en: 'For example: Why use layered WG networks' },
    memoryType: 'reasoning',
    layer: 'L2',
    priority: 5,
    summaryField: 'claim',
    fields: [
      { key: 'claim', label: { zh: '核心结论', en: 'Key idea' }, prefix: { zh: '核心结论', en: 'Claim' }, placeholder: { zh: '例如：救援层应与日常访问层分开', en: 'For example: Keep the rescue layer separate from daily access' }, hint: { zh: '一张卡只写一个可复用结论。', en: 'Keep one reusable claim per card.' }, required: true, maxLength: 500 },
      { key: 'applicability', label: { zh: '适用条件', en: 'Applies when' }, prefix: { zh: '适用条件', en: 'Applies when' }, placeholder: { zh: '例如：家庭网络有多处节点且需要远程救援', en: 'For multi-site home networks needing remote recovery' }, hint: { zh: '说清结论成立的前提，避免当作通用定律。', en: 'State the conditions under which the claim holds.' }, required: true, maxLength: 400 },
      { key: 'avoid', label: { zh: '不适用 / 常见误区', en: 'When not to apply it' }, prefix: { zh: '避免误用', en: 'Avoid misuse' }, placeholder: { zh: '不要把救援通道当作日常大流量主通道', en: 'Do not use the rescue path as the main high-volume route' }, hint: { zh: '有明确反例或例外时再填写。', en: 'Add a real exception or misuse boundary when known.' }, required: false, maxLength: 500 },
      { key: 'evidence', label: { zh: '依据或来源', en: 'Evidence or source' }, prefix: { zh: '依据或来源', en: 'Evidence' }, placeholder: { zh: '例如：家庭网络 2026-10 实测；或具体资料链接', en: 'For example: Home network test in 2026-10 or a source link' }, hint: { zh: '写会话、实测、项目资料或可核对链接；个人经验也请标明。', en: 'Name a session, test, project note, or verifiable source.' }, required: true, maxLength: 500 },
    ],
  },
}

export function cardSteps(value: string): string[] {
  return value
    .replace(/[；;]\s*(?=\d+[.)]\s*)/g, '\n')
    .split(/\r?\n/)
    .map(line => line.trim().replace(/^(?:\d+[.)]|[-*])\s*/, '').trim())
    .filter(Boolean)
}

export function cardFieldValue(field: CardField, value: string, language: 'zh' | 'en'): string {
  if (field.key === 'procedure') {
    const steps = cardSteps(value)
    if (!steps.length) throw new Error(language === 'zh' ? '请填写至少一个具体操作步骤。' : 'Add at least one concrete step.')
    if (steps.length > 6) throw new Error(language === 'zh' ? '操作步骤最多填写 6 步；更多内容建议拆成另一张卡。' : 'Use up to 6 steps; split longer procedures into another card.')
    const formatted = steps.map((step, index) => `${index + 1}. ${step}`).join(language === 'zh' ? '；' : '; ')
    if (formatted.length > field.maxLength) throw new Error(language === 'zh' ? '操作步骤内容过长，请拆分成多张卡。' : 'The steps are too long; split them into more cards.')
    return formatted
  }
  return value.trim().replace(/\s*\r?\n+\s*/g, language === 'zh' ? '；' : '; ')
}

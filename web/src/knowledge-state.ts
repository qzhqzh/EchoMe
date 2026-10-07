import { useAuth } from '@/stores/auth'

function key(part: string) {
  const auth = useAuth()
  return `echome:knowledge:${auth.getApiBase()}:${auth.getUser()?.id || 'anonymous'}:${part}`
}
function read<T>(storage: Storage, part: string, fallback: T): T {
  try { return JSON.parse(storage.getItem(key(part)) || 'null') ?? fallback } catch { return fallback }
}
function write(storage: Storage, part: string, value: unknown) {
  try { storage.setItem(key(part), JSON.stringify(value)) } catch { /* Browsing still works with storage disabled. */ }
}
export function expansion(id: string): boolean | undefined {
  const state = read<Record<string, boolean>>(sessionStorage, 'expanded', {})
  return state[id] ?? (state[id.split(':')[0] + ':collapsed'] ? false : undefined)
}
export function rememberExpansion(id: string, value: boolean) {
  const state = read<Record<string, boolean>>(sessionStorage, 'expanded', {})
  state[id] = value
  // Keep only a bounded set of browsing preferences, never knowledge content.
  write(sessionStorage, 'expanded', Object.fromEntries(Object.entries(state).slice(-1000)))
}
export function collapseFamily(family: string) {
  const state = read<Record<string, boolean>>(sessionStorage, 'expanded', {})
  for (const id of Object.keys(state)) if (id.startsWith(family + ':')) state[id] = false
  state[family + ':collapsed'] = true
  write(sessionStorage, 'expanded', state)
}
export function recentIds(): string[] {
  const value = read<unknown>(localStorage, 'recent', [])
  return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string').slice(0, 6) : []
}
export function rememberVisit(id: string) { write(localStorage, 'recent', [id, ...recentIds().filter(value => value !== id)].slice(0, 6)) }
export function clearVisits() { write(localStorage, 'recent', []) }

export function knowledgeError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  if (message.includes('Directory move would create a cycle')) return '不能放到自己或自己的下级领域中，请重新选择位置。'
  if (message.includes('Directory position has active children')) return '此位置下还有内容，请移动整个位置，或先整理下级内容。'
  if (message.includes('Entity already exists at this directory location')) return '这个位置已经收纳了该知识，请选择其他位置。'
  if (message.includes('Record changed')) return '内容已被其他人或 AI 更新。请重新读取后再修改。'
  return message
}

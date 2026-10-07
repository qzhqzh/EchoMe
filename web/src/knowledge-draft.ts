import { onBeforeUnmount, onMounted } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'

export function useKnowledgeDraft(dirty: () => boolean) {
  const allowLeave = () => !dirty() || window.confirm('还有未保存的修改，离开后将丢失。确定离开？')
  onBeforeRouteLeave(allowLeave)
  onBeforeRouteUpdate(allowLeave)
  function unload(event: BeforeUnloadEvent) { if (dirty()) { event.preventDefault(); event.returnValue = '' } }
  onMounted(() => window.addEventListener('beforeunload', unload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', unload))
}

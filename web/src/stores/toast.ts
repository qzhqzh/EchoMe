import { reactive } from 'vue'

export type ToastType = 'success' | 'error' | 'info' | 'warning'

export interface Toast {
  id: number
  message: string
  type: ToastType
  duration: number
}

interface ToastState {
  toasts: Toast[]
  nextId: number
}

const state: ToastState = reactive({
  toasts: [],
  nextId: 1,
})

export function useToast() {
  function show(message: string, type: ToastType = 'info', duration = 3000): void {
    const id = state.nextId++
    state.toasts.push({ id, message, type, duration })

    setTimeout(() => {
      dismiss(id)
    }, duration)
  }

  function dismiss(id: number): void {
    const idx = state.toasts.findIndex(t => t.id === id)
    if (idx > -1) {
      state.toasts.splice(idx, 1)
    }
  }

  function success(message: string): void {
    show(message, 'success')
  }

  function error(message: string): void {
    show(message, 'error', 5000)
  }

  function info(message: string): void {
    show(message, 'info')
  }

  function warning(message: string): void {
    show(message, 'warning', 4000)
  }

  return {
    state,
    show,
    dismiss,
    success,
    error,
    info,
    warning,
  }
}

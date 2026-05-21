<script setup lang="ts">
import { useToast } from '@/stores/toast'

const { state, dismiss } = useToast()

function getIcon(type: string): string {
  switch (type) {
    case 'success': return 'M5 13l4 4L19 7'
    case 'error': return 'M6 18L18 6M6 6l12 12'
    case 'warning': return 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z'
    default: return 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z'
  }
}

function getColors(type: string): string {
  switch (type) {
    case 'success': return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
    case 'error': return 'border-red-500/30 bg-red-500/10 text-red-300'
    case 'warning': return 'border-amber-500/30 bg-amber-500/10 text-amber-300'
    default: return 'border-blue-500/30 bg-blue-500/10 text-blue-300'
  }
}
</script>

<template>
  <div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
    <transition-group
      enter-active-class="transition-all duration-300 ease-out"
      enter-from-class="opacity-0 translate-y-2 scale-95"
      enter-to-class="opacity-100 translate-y-0 scale-100"
      leave-active-class="transition-all duration-200 ease-in"
      leave-from-class="opacity-100 translate-y-0 scale-100"
      leave-to-class="opacity-0 translate-y-2 scale-95"
    >
      <div
        v-for="toast in state.toasts"
        :key="toast.id"
        :class="[
          'flex items-center gap-3 rounded-lg border px-4 py-3 shadow-lg backdrop-blur-sm min-w-[300px] max-w-[400px]',
          getColors(toast.type)
        ]"
      >
        <svg class="h-5 w-5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" :d="getIcon(toast.type)" />
        </svg>
        <p class="flex-1 text-sm">{{ toast.message }}</p>
        <button
          class="shrink-0 rounded p-0.5 opacity-60 hover:opacity-100 transition-opacity"
          @click="dismiss(toast.id)"
        >
          <svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
    </transition-group>
  </div>
</template>

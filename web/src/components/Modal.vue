<script setup lang="ts">
defineProps<{
  open: boolean
  title?: string
}>()

const emit = defineEmits<{
  close: []
}>()

function handleOverlayClick(): void {
  emit('close')
}
</script>

<template>
  <Teleport to="body">
    <transition
      enter-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      enter-to-class="opacity-100"
      leave-active-class="transition-opacity duration-150"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <!-- Overlay -->
        <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="handleOverlayClick" />

        <!-- Modal content -->
        <div class="relative w-full max-w-lg rounded-xl border border-slate-700 bg-slate-800 shadow-2xl">
          <!-- Header -->
          <div v-if="title" class="flex items-center justify-between border-b border-slate-700 px-6 py-4">
            <h3 class="text-lg font-semibold text-slate-100">{{ title }}</h3>
            <button
              class="rounded-lg p-1 text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
              @click="emit('close')"
            >
              <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Body -->
          <div class="px-6 py-4">
            <slot />
          </div>

          <!-- Footer -->
          <div v-if="$slots.footer" class="flex items-center justify-end gap-3 border-t border-slate-700 px-6 py-4">
            <slot name="footer" />
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

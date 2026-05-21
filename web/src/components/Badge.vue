<script setup lang="ts">
defineProps<{
  color?: string
  size?: 'sm' | 'md'
}>()
</script>

<template>
  <span
    :class="[
      'inline-flex items-center rounded-md border font-medium',
      size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-0.5 text-xs',
      color || 'bg-slate-500/20 text-slate-300 border-slate-500/30'
    ]"
  >
    <slot />
  </span>
</template>

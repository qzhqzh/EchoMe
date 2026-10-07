<script setup lang="ts">
import { onMounted, ref } from 'vue'
defineProps<{ title: string; dirty?: boolean; busy?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>(), discard = ref(false)
onMounted(() => dialog.value?.showModal())
function requestClose(dirty?: boolean, busy?: boolean) { if (!busy) { if (dirty) discard.value = true; else emit('close') } }
</script>
<template>
  <dialog ref="dialog" :aria-label="title" class="m-auto max-h-[92dvh] w-[calc(100%-1.5rem)] max-w-2xl overflow-y-auto rounded-2xl border border-slate-600 bg-slate-900 p-5 text-slate-200 shadow-2xl backdrop:bg-black/70 sm:p-7" @cancel.prevent="requestClose(dirty, busy)" @click="event => { if (event.target === dialog) { const box = dialog!.getBoundingClientRect(); if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) requestClose(dirty, busy) } }">
    <header class="mb-5 flex items-center justify-between gap-4"><h2 class="text-xl font-semibold text-white">{{ title }}</h2><button type="button" aria-label="关闭" :disabled="busy" class="rounded p-2 text-xl text-slate-400 disabled:opacity-30" @click="requestClose(dirty, busy)">×</button></header>
    <div v-if="discard" role="alert" class="mb-5 rounded-xl border border-amber-400/30 bg-amber-400/5 p-4"><p class="text-sm text-amber-200">还有未保存的修改</p><div class="mt-3 flex gap-4 text-sm"><button type="button" class="text-blue-300" @click="discard = false">继续编辑</button><button type="button" class="text-slate-400" @click="emit('close')">放弃修改</button></div></div>
    <slot :request-close="() => requestClose(dirty, busy)" />
  </dialog>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import Sidebar from './Sidebar.vue'

const sidebarOpen = ref(false)

function toggleSidebar(): void {
  sidebarOpen.value = !sidebarOpen.value
}

function closeSidebar(): void {
  sidebarOpen.value = false
}
</script>

<template>
  <div class="flex h-screen overflow-hidden bg-slate-900">
    <!-- Mobile overlay -->
    <div
      v-if="sidebarOpen"
      class="fixed inset-0 z-30 bg-black/50 lg:hidden"
      @click="closeSidebar"
    />

    <!-- Sidebar -->
    <Sidebar
      :open="sidebarOpen"
      @close="closeSidebar"
    />

    <!-- Main content -->
    <div class="flex flex-1 flex-col overflow-hidden">
      <!-- Mobile header -->
      <header class="flex items-center gap-3 border-b border-slate-700 bg-slate-800/50 px-4 py-3 lg:hidden">
        <button
          class="rounded-lg p-2 text-slate-400 hover:bg-slate-700 hover:text-slate-200"
          @click="toggleSidebar"
        >
          <svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        <span class="text-lg font-semibold text-slate-100">EchoMe</span>
      </header>

      <!-- Page content -->
      <main class="flex-1 overflow-y-auto p-4 lg:p-6">
        <slot />
      </main>
    </div>
  </div>
</template>

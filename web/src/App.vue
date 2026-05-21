<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import Layout from '@/components/Layout.vue'
import Toast from '@/components/Toast.vue'

const route = useRoute()
const isPublicPage = computed(() => route.meta.public)
</script>

<template>
  <Layout v-if="!isPublicPage">
    <router-view />
  </Layout>
  <router-view v-else />
  <Toast />
</template>

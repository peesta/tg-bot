<script setup>
import { computed, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from './components/AppLayout.vue'
import ConfirmHost from './components/ConfirmHost.vue'
import ToastHost from './components/ToastHost.vue'
import { store } from './store.js'

const route = useRoute()
const isPublic = computed(() => route.meta.public)

// Тема на <html>: её видят и окна, которые выводятся поверх страницы.
watchEffect(() => {
  document.documentElement.className = store.user?.role === 'admin' ? 'theme-admin' : 'theme-employee'
})
</script>

<template>
  <RouterView v-if="isPublic || !store.user" />
  <AppLayout v-else />
  <ConfirmHost />
  <ToastHost />
</template>

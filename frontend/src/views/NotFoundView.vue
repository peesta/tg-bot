<script setup>
import { CircleHelp } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
</script>

<template>
  <EmptyState :icon="CircleHelp" text="Такой страницы нет">
    <RouterLink to="/" class="btn btn-primary">На главную</RouterLink>
  </EmptyState>
</template>

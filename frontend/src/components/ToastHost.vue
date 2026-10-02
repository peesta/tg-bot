<script setup>
import { CircleAlert, CircleCheck, X } from 'lucide-vue-next'
import { dismissToast, store } from '../store.js'
</script>

<template>
  <div class="toasts" aria-live="polite">
    <div v-for="item in store.toasts" :key="item.id" class="toast" :class="`toast-${item.type}`" role="status">
      <CircleAlert v-if="item.type === 'error'" class="icon" :size="24" :stroke-width="1.75" />
      <CircleCheck v-else class="icon" :size="24" :stroke-width="1.75" />
      <span>{{ item.message }}</span>
      <button class="btn btn-ghost" type="button" aria-label="Закрыть" @click="dismissToast(item.id)">
        <X class="icon" :size="22" :stroke-width="1.75" />
      </button>
    </div>
  </div>
</template>

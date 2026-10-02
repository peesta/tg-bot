<script setup>
import { Search, X } from 'lucide-vue-next'

const model = defineModel({ type: String, default: '' })
defineProps({ placeholder: { type: String, default: 'Поиск по названию' } })
</script>

<template>
  <label class="search">
    <Search class="icon" :size="22" :stroke-width="1.75" />
    <input v-model="model" class="input" type="search" :placeholder="placeholder" :aria-label="placeholder">
    <button v-if="model" class="btn btn-ghost btn-small btn-icon clear" type="button" aria-label="Очистить" @click="model = ''">
      <X class="icon" :size="22" :stroke-width="1.75" />
    </button>
  </label>
</template>

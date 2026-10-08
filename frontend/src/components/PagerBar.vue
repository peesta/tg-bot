<script setup>
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'

defineProps({ page: { type: Number, required: true }, pages: { type: Number, required: true } })
const emit = defineEmits(['change'])
</script>

<template>
  <nav v-if="pages > 1" class="pager" aria-label="Страницы">
    <button class="btn btn-secondary" type="button" :disabled="page <= 1" @click="emit('change', page - 1)">
      <ChevronLeft class="icon" :size="24" :stroke-width="1.75" /> Назад
    </button>
    <span class="muted">стр. {{ page }} из {{ pages }}</span>
    <button class="btn btn-secondary" type="button" :disabled="page >= pages" @click="emit('change', page + 1)">
      Далее <ChevronRight class="icon" :size="24" :stroke-width="1.75" />
    </button>
  </nav>
</template>

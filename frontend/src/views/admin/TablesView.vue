<script setup>
import { onMounted, ref } from 'vue'
import { Sheet } from 'lucide-vue-next'
import PageHeader from '../../components/PageHeader.vue'
import { api } from '../../api.js'
import { plural } from '../../dates.js'

const tables = ref(null)

onMounted(async () => {
  tables.value = await api.get('/admin/tables')
})
</script>

<template>
  <PageHeader title="База данных" subtitle="Нажмите на таблицу, чтобы посмотреть и изменить её" />
  <div class="banner banner-info mb">
    <span>Правки здесь идут прямо в базу и записываются в журнал изменений. Перед большой правкой сделайте резервную копию.</span>
  </div>
  <div v-if="tables" class="cards-grid">
    <RouterLink v-for="table in tables" :key="table.name" :to="`/admin/tables/${table.name}`" class="pick-card">
      <span class="row"><Sheet class="icon" :size="28" :stroke-width="1.75" /><span class="pick-card-title">{{ table.title }}</span></span>
      <span class="muted">{{ table.description }}</span>
      <span><b>{{ table.count }}</b> {{ plural(table.count, 'строка', 'строки', 'строк') }}</span>
    </RouterLink>
  </div>
</template>

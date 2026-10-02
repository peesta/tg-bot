<script setup>
import { onMounted, ref } from 'vue'
import { History } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import PagerBar from '../components/PagerBar.vue'
import { api } from '../api.js'
import { formatDate, formatTime } from '../dates.js'
import { authorName } from '../labels.js'

const data = ref(null)

async function load(page = 1) {
  data.value = await api.get('/history', { page })
}

onMounted(() => load())
</script>

<template>
  <PageHeader title="История списаний" subtitle="Новые записи сверху" />
  <template v-if="data">
    <EmptyState v-if="!data.items.length" :icon="History" text="Списаний пока не было" />
    <template v-else>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Дата</th><th>Товар</th><th class="num">Шт.</th><th>Причина</th><th>Сотрудник</th></tr></thead>
          <tbody>
            <tr v-for="record in data.items" :key="record.id">
              <td class="nowrap">{{ formatDate(record.created_at) }}<br><span class="muted">{{ formatTime(record.created_at) }}</span></td>
              <td>{{ record.product_name }}</td>
              <td class="num">{{ record.quantity }}</td>
              <td>{{ record.reason || 'не указана' }}</td>
              <td>{{ authorName(record) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <PagerBar :page="data.page" :pages="data.pages" @change="load" />
    </template>
  </template>
</template>

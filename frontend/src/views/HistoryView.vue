<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { History } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import PagerBar from '../components/PagerBar.vue'
import { api } from '../api.js'
import { formatDate, formatTime } from '../dates.js'
import { OPERATION_TITLES, authorName, deliveryPlace } from '../labels.js'

// '' — все операции: поставки, разморозка, продажи, списания.
const FILTERS = [
  { value: '', title: 'Все операции', empty: 'Операций пока не было' },
  { value: 'sale', title: 'Продажа', empty: 'Продаж пока не было' },
  { value: 'write_off', title: 'Списание', empty: 'Списаний пока не было' },
]

const route = useRoute()
const router = useRouter()
const type = ref(FILTERS.some((item) => item.value === route.query.type) ? route.query.type : '')
const data = ref(null)

const filter = computed(() => FILTERS.find((item) => item.value === type.value))

async function load(page = 1) {
  data.value = await api.get('/history', { page, type: type.value })
}

function reason(record) {
  if (record.operation_type !== 'write_off') return ''
  return record.reason || 'не указана'
}

watch(type, () => {
  router.replace({ query: type.value ? { type: type.value } : {} })
  data.value = null
  load()
})

onMounted(() => load())
</script>

<template>
  <PageHeader title="История операций" subtitle="Новые записи сверху" />
  <div class="toolbar">
    <div class="segmented" role="tablist" aria-label="Какие операции показать">
      <button
        v-for="item in FILTERS" :key="item.value" type="button" role="tab"
        :aria-selected="type === item.value" :class="{ active: type === item.value }" @click="type = item.value"
      >{{ item.title }}</button>
    </div>
  </div>

  <template v-if="data">
    <EmptyState v-if="!data.items.length" :icon="History" :text="filter.empty" />
    <template v-else>
      <div class="table-wrap">
        <table class="table table-stack">
          <thead>
            <tr>
              <th>Дата</th>
              <th v-if="!type">Операция</th>
              <th>Товар</th>
              <th class="num">Шт.</th>
              <th v-if="type !== 'sale'">Причина</th>
              <th>Сотрудник</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="record in data.items" :key="record.id">
              <td class="nowrap" data-label="Дата">{{ formatDate(record.created_at) }} <br><span class="muted">{{ formatTime(record.created_at) }}</span></td>
              <td v-if="!type" data-label="Операция">
                <span class="badge" :class="`badge-${record.operation_type}`">{{ OPERATION_TITLES[record.operation_type] }}</span>
                <template v-if="deliveryPlace(record)"> <br><span class="muted nowrap">{{ deliveryPlace(record) }}</span></template>
              </td>
              <td class="cell-title">{{ record.product_name }}</td>
              <td class="num" data-label="Шт.">{{ record.quantity }}</td>
              <td v-if="type !== 'sale'" :class="{ 'cell-empty': !reason(record) }" data-label="Причина">{{ reason(record) }}</td>
              <td data-label="Сотрудник">{{ authorName(record) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <PagerBar :page="data.page" :pages="data.pages" @change="load" />
    </template>
  </template>
</template>

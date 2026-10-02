<script setup>
import { computed, onMounted, ref } from 'vue'
import { Boxes, RefreshCw, Snowflake } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import SearchBox from '../components/SearchBox.vue'
import { api } from '../api.js'
import { formatDate } from '../dates.js'
import { matches } from '../search.js'

const data = ref(null)
const tab = ref('fridge')
const query = ref('')

const filter = (items) => items.filter((item) => matches(item.product_name, query.value))
const groups = computed(() => [
  { key: 'fresh', title: 'Годные', tone: '', items: filter(data.value.fresh) },
  { key: 'today', title: 'Срок истекает сегодня', tone: 'card-warning', items: filter(data.value.today) },
  { key: 'expired', title: 'Просрочено', tone: 'card-danger', items: filter(data.value.expired) },
].filter((group) => group.items.length))
const freezer = computed(() => filter(data.value.freezer))

async function load() {
  data.value = await api.get('/stock')
}

onMounted(load)
</script>

<template>
  <PageHeader title="Остатки" subtitle="Партии в холодильнике и запас в морозильнике">
    <button class="btn btn-secondary" type="button" @click="load">
      <RefreshCw class="icon" :size="24" :stroke-width="1.75" /> Обновить
    </button>
  </PageHeader>
  <div class="toolbar">
    <div class="segmented">
      <button type="button" :class="{ active: tab === 'fridge' }" @click="tab = 'fridge'">Холодильник</button>
      <button type="button" :class="{ active: tab === 'freezer' }" @click="tab = 'freezer'">Морозильник</button>
    </div>
    <SearchBox v-model="query" />
  </div>

  <template v-if="data && tab === 'fridge'">
    <EmptyState v-if="!groups.length" :icon="Boxes" text="В холодильнике нет партий" />
    <section v-for="group in groups" :key="group.key" class="card" :class="group.tone">
      <div class="card-header"><h2>{{ group.title }}</h2><span class="muted">{{ group.items.length }} парт.</span></div>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>Товар</th><th class="num">Шт.</th><th>Годен до</th><th>Разморожено</th></tr></thead>
          <tbody>
            <tr v-for="batch in group.items" :key="batch.id">
              <td>{{ batch.product_name }}</td>
              <td class="num">{{ batch.quantity }}</td>
              <td class="nowrap">{{ formatDate(batch.expiration_date) }}</td>
              <td class="nowrap muted">{{ formatDate(batch.date_added) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </template>

  <template v-if="data && tab === 'freezer'">
    <EmptyState v-if="!freezer.length" :icon="Snowflake" text="В морозильнике пусто" />
    <div v-else class="table-wrap">
      <table class="table">
        <thead><tr><th>Товар</th><th class="num">Шт.</th><th class="num">Хранится после разморозки</th></tr></thead>
        <tbody>
          <tr v-for="item in freezer" :key="item.id">
            <td>{{ item.product_name }}</td>
            <td class="num">{{ item.quantity }}</td>
            <td class="num muted">{{ item.fridge_storage_time ? `${item.fridge_storage_time} дн.` : '—' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>

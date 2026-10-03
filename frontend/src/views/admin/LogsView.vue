<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChevronDown, ScrollText } from 'lucide-vue-next'
import DatePicker from '../../components/DatePicker.vue'
import EmptyState from '../../components/EmptyState.vue'
import PageHeader from '../../components/PageHeader.vue'
import PagerBar from '../../components/PagerBar.vue'
import SearchBox from '../../components/SearchBox.vue'
import { api } from '../../api.js'
import { formatDate, formatDateTime, formatDatesInText, formatTime } from '../../dates.js'
import { CHANGE_TITLES, OPERATION_TITLES, authorName, deliveryPlace } from '../../labels.js'

const TABS = [
  ['operations', 'Операции'],
  ['changes', 'Изменения'],
  ['errors', 'Ошибки'],
  ['server', 'Журнал сервера'],
]

const route = useRoute()
const router = useRouter()
const tab = ref(TABS.some(([key]) => key === route.query.tab) ? route.query.tab : 'operations')
const data = ref(null)
const users = ref([])
const opened = ref(new Set())
const filters = reactive({ type: '', user: '', q: '', date_from: null, date_to: null })
const changesQuery = ref('')
const lines = ref(100)

async function load(page = 1) {
  data.value = null
  if (tab.value === 'operations') data.value = await api.get('/admin/logs/operations', { ...filters, page })
  if (tab.value === 'changes') data.value = await api.get('/admin/logs/changes', { q: changesQuery.value, page })
  if (tab.value === 'errors') data.value = await api.get('/admin/logs/errors', { page })
  if (tab.value === 'server') data.value = await api.get('/admin/logs/server', { lines: lines.value })
}

function resetFilters() {
  Object.assign(filters, { type: '', user: '', q: '', date_from: null, date_to: null })
  load()
}

function toggle(id) {
  const next = new Set(opened.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  opened.value = next
}

watch(tab, () => {
  router.replace({ query: { tab: tab.value } })
  load()
})

let timer = null
watch(changesQuery, () => {
  clearTimeout(timer)
  timer = setTimeout(() => load(), 300)
})

onMounted(async () => {
  load()
  users.value = await api.get('/admin/users')
})
</script>

<template>
  <PageHeader title="Логи" subtitle="Что делали сотрудники, что меняли в базе и какие были ошибки" />
  <div class="tabs" role="tablist">
    <button v-for="[key, title] in TABS" :key="key" type="button" :class="{ active: tab === key }" @click="tab = key">{{ title }}</button>
  </div>

  <!-- Операции: поставки, разморозка, продажи, списания -->
  <template v-if="tab === 'operations'">
    <form class="card form-grid mb" @submit.prevent="load()">
      <label class="field"><span class="field-label">Операция</span>
        <select v-model="filters.type" class="input">
          <option value="">Все</option>
          <option v-for="(title, code) in OPERATION_TITLES" :key="code" :value="code">{{ title }}</option>
        </select></label>
      <label class="field"><span class="field-label">Сотрудник</span>
        <select v-model="filters.user" class="input">
          <option value="">Все</option>
          <option v-for="person in users" :key="person.id" :value="person.id">{{ person.full_name }}</option>
        </select></label>
      <label class="field"><span class="field-label">Товар или причина</span>
        <input v-model="filters.q" class="input" type="search"></label>
      <div class="field"><span class="field-label">С даты</span><DatePicker v-model="filters.date_from" aria-label="С даты" /></div>
      <div class="field"><span class="field-label">По дату</span><DatePicker v-model="filters.date_to" aria-label="По дату" /></div>
      <div class="form-actions">
        <button class="btn btn-primary" type="submit">Показать</button>
        <button class="btn btn-ghost" type="button" @click="resetFilters">Сбросить</button>
      </div>
    </form>
    <template v-if="data">
      <EmptyState v-if="!data.items.length" :icon="ScrollText" text="Записей не найдено" />
      <template v-else>
        <p class="muted mb-s">Найдено: {{ data.total }}</p>
        <div class="table-wrap">
          <table class="table table-stack">
            <thead><tr><th>Дата</th><th>Операция</th><th>Товар</th><th class="num">Шт.</th><th>Причина</th><th>Сотрудник</th></tr></thead>
            <tbody>
              <tr v-for="row in data.items" :key="row.id">
                <td class="nowrap" data-label="Дата">{{ formatDate(row.created_at) }} <br><span class="muted">{{ formatTime(row.created_at) }}</span></td>
                <td data-label="Операция">
                  <span class="badge" :class="`badge-${row.operation_type}`">{{ OPERATION_TITLES[row.operation_type] }}</span>
                  <template v-if="deliveryPlace(row)"> <br><span class="muted nowrap">{{ deliveryPlace(row) }}</span></template>
                </td>
                <td class="cell-title">{{ row.product_name }}<template v-if="row.batch_id"> <br><span class="muted">партия № {{ row.batch_id }}</span></template></td>
                <td class="num" data-label="Шт.">{{ row.quantity }}</td>
                <td :class="{ 'cell-empty': !row.reason }" data-label="Причина">{{ row.reason || '' }}</td>
                <td data-label="Сотрудник">{{ authorName(row) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <PagerBar :page="data.page" :pages="data.pages" @change="load" />
      </template>
    </template>
  </template>

  <!-- Изменения: сотрудники, товары, правки таблиц, импорт -->
  <template v-if="tab === 'changes'">
    <div class="toolbar"><SearchBox v-model="changesQuery" placeholder="Поиск по подробностям или имени" /></div>
    <template v-if="data">
      <EmptyState v-if="!data.items.length" :icon="ScrollText" text="Изменений не найдено" />
      <template v-else>
        <section class="card">
          <ul class="timeline">
            <li v-for="row in data.items" :key="row.id" class="change">
              <span class="change-head">
                <span class="timeline-time">{{ formatDateTime(row.created_at) }}</span>
                <b>{{ CHANGE_TITLES[row.action] || row.action }}</b>
                <span class="muted">{{ authorName(row) }}</span>
              </span>
              <span>{{ formatDatesInText(row.details) }}</span>
            </li>
          </ul>
        </section>
        <PagerBar :page="data.page" :pages="data.pages" @change="load" />
      </template>
    </template>
  </template>

  <!-- Ошибки -->
  <template v-if="tab === 'errors' && data">
    <EmptyState v-if="!data.items.length" :icon="ScrollText" text="Ошибок не было" />
    <div v-else class="stack">
      <section v-for="error in data.items" :key="error.id" class="card">
        <button class="row error-toggle" type="button" @click="toggle(error.id)">
          <span class="muted nowrap">{{ formatDateTime(error.created_at) || 'дата неизвестна' }}</span>
          <b>{{ error.error_type }}</b>
          <span class="spacer">{{ error.error_message.split('\n')[0] }}</span>
          <ChevronDown class="icon" :size="24" :stroke-width="1.75" />
        </button>
        <pre v-if="opened.has(error.id)" class="log mt-s">{{ error.error_message }}</pre>
      </section>
      <PagerBar :page="data.page" :pages="data.pages" @change="load" />
    </div>
  </template>

  <!-- Журнал сервера -->
  <template v-if="tab === 'server' && data">
    <div class="toolbar">
      <span class="muted">Файл {{ data.file }}, новые строки сверху</span>
      <span class="spacer" />
      <div class="segmented">
        <button v-for="count in data.options" :key="count" type="button" :class="{ active: lines === count }" @click="lines = count; load()">{{ count }}</button>
      </div>
    </div>
    <pre v-if="data.lines.length" class="log">{{ formatDatesInText(data.lines.join('\n')) }}</pre>
    <EmptyState v-else :icon="ScrollText" :text="data.exists ? 'Журнал пуст' : 'Файла журнала пока нет: он появится после запуска через python main.py'" />
  </template>
</template>

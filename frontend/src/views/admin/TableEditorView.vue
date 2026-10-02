<script setup>
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Info, Plus, RefreshCw } from 'lucide-vue-next'
import DataGrid from '../../components/DataGrid.vue'
import PageHeader from '../../components/PageHeader.vue'
import PagerBar from '../../components/PagerBar.vue'
import SearchBox from '../../components/SearchBox.vue'
import { api } from '../../api.js'
import { toast } from '../../store.js'

const route = useRoute()
const data = ref(null)
const grid = ref(null)
const query = ref('')
const sort = ref(null)
const desc = ref(false)
const page = ref(1)
let searchTimer = null

const url = () => `/admin/tables/${route.params.name}`

async function load() {
  data.value = await api.get(url(), {
    page: page.value, q: query.value, sort: sort.value,
    desc: sort.value ? desc.value : null,
  })
}

function sortBy(name) {
  if (sort.value === name) desc.value = !desc.value
  else {
    sort.value = name
    desc.value = false
  }
  load()
}

function goTo(number) {
  page.value = number
  load()
}

async function save(row, column, value) {
  const updated = await api.patch(`${url()}/rows/${row.__rowid}`, { values: { [column.name]: value } })
  Object.assign(row, updated)
}

async function insert(values) {
  await api.post(`${url()}/rows`, { values })
  toast('Строка добавлена')
  load()
}

async function remove(row) {
  await api.delete(`${url()}/rows/${row.__rowid}`)
  toast('Строка удалена')
  load()
}

watch(query, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    load()
  }, 300)
})

onMounted(load)
</script>

<template>
  <RouterLink to="/admin/tables" class="btn btn-ghost back-link">
    <ArrowLeft class="icon" :size="24" :stroke-width="1.75" /> Все таблицы
  </RouterLink>
  <template v-if="data">
    <PageHeader :title="data.title" :subtitle="`${data.description} · ${data.total} строк`" />
    <div v-if="data.note" class="banner banner-info mb">
      <Info class="icon" :size="26" :stroke-width="1.75" /><span>{{ data.note }}</span>
    </div>
    <div class="toolbar">
      <SearchBox v-model="query" placeholder="Поиск по всем столбцам" />
      <span class="spacer" />
      <button class="btn btn-secondary" type="button" @click="load">
        <RefreshCw class="icon" :size="24" :stroke-width="1.75" /> Обновить
      </button>
      <button v-if="data.can_insert" class="btn btn-primary" type="button" @click="grid.startAdd()">
        <Plus class="icon" :size="24" :stroke-width="1.75" /> Добавить строку
      </button>
    </div>
    <p class="muted mb-s">
      Нажмите на ячейку, чтобы изменить её. Поля со звёздочкой обязательны.
    </p>
    <DataGrid
      ref="grid" :columns="data.columns" :rows="data.items" :start="(data.page - 1) * 50 + 1"
      :sort="sort" :desc="desc" :save="save" :insert="data.can_insert ? insert : null" :remove="remove"
      @sort="sortBy"
    />
    <PagerBar :page="data.page" :pages="data.pages" @change="goTo" />
  </template>
</template>

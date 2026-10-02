<script setup>
import { computed, onMounted, ref } from 'vue'
import { Plus, Search, Tag, Trash2 } from 'lucide-vue-next'
import EmptyState from '../../components/EmptyState.vue'
import ModalDialog from '../../components/ModalDialog.vue'
import PageHeader from '../../components/PageHeader.vue'
import SearchBox from '../../components/SearchBox.vue'
import { api } from '../../api.js'
import { matches } from '../../search.js'
import { confirmAction, toast } from '../../store.js'

const products = ref(null)
const query = ref('')
const form = ref(null) // { id?, name, fridge_storage_time, freezer_storage_time, category }
const sending = ref(false)

const shown = computed(() => (products.value || []).filter(
  (product) => matches(product.name, query.value) || matches(product.category, query.value),
))
const categories = computed(() => [...new Set((products.value || []).map((p) => p.category).filter(Boolean))])
const editing = computed(() => products.value?.find((product) => product.id === form.value?.id))

async function load() {
  products.value = await api.get('/admin/products')
}

function openNew() {
  form.value = { name: '', fridge_storage_time: 2, freezer_storage_time: null, category: '' }
}

function openEdit(product) {
  form.value = { ...product, category: product.category || '' }
}

function numberOrNull(value) {
  return value === '' || value === null || value === undefined ? null : Number(value)
}

async function save() {
  sending.value = true
  const body = {
    name: form.value.name,
    fridge_storage_time: Number(form.value.fridge_storage_time),
    freezer_storage_time: numberOrNull(form.value.freezer_storage_time),
    category: form.value.category || null,
  }
  try {
    if (form.value.id) {
      await api.put(`/admin/products/${form.value.id}`, body)
      toast(`Товар «${body.name}» сохранён. Новый срок действует для новых разморозок`)
    } else {
      await api.post('/admin/products', body)
      toast(`Товар «${body.name}» добавлен`)
    }
    form.value = null
    load()
  } catch (error) {
    toast(error.message, 'error')
  } finally {
    sending.value = false
  }
}

async function remove() {
  const product = editing.value
  const ok = await confirmAction({
    title: `Удалить «${product.name}»?`,
    message: 'Товар пропадёт из справочника. История операций сохранится.',
    confirmText: 'Удалить',
    danger: true,
  })
  if (!ok) return
  try {
    await api.delete(`/admin/products/${product.id}`)
    toast(`Товар «${product.name}» удалён`)
    form.value = null
    load()
  } catch (error) {
    toast(error.message, 'error')
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="Товары" subtitle="Что можно заморозить и сколько оно хранится">
    <button class="btn btn-primary" type="button" @click="openNew">
      <Plus class="icon" :size="24" :stroke-width="1.75" /> Добавить товар
    </button>
  </PageHeader>
  <div class="toolbar"><SearchBox v-model="query" placeholder="Поиск по названию или категории" /></div>

  <template v-if="products">
    <div v-if="shown.length" class="table-wrap">
      <table class="table">
        <thead>
          <tr><th>Название</th><th>Категория</th><th class="num">После разморозки</th><th class="num">В морозильнике хранится</th><th class="num">Остаток в морозильнике</th></tr>
        </thead>
        <tbody>
          <tr v-for="product in shown" :key="product.id" class="clickable" @click="openEdit(product)">
            <td><b>{{ product.name }}</b></td>
            <td>{{ product.category || '—' }}</td>
            <td class="num">{{ product.fridge_storage_time }} дн.</td>
            <td class="num">{{ product.freezer_storage_time ? `${product.freezer_storage_time} дн.` : '—' }}</td>
            <td class="num">{{ product.freezer_quantity }} шт.</td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-else-if="query" :icon="Search" :text="`По запросу «${query}» товаров нет`" />
    <EmptyState v-else :icon="Tag" text="Справочник пуст. Добавьте первый товар" />
  </template>

  <ModalDialog v-if="form" :title="form.id ? form.name || 'Товар' : 'Новый товар'" @close="form = null">
    <form id="product-form" class="stack" @submit.prevent="save">
      <label class="field"><span class="field-label">Название</span>
        <input v-model="form.name" class="input" maxlength="60" required></label>
      <div class="form-grid">
        <label class="field"><span class="field-label">Срок после разморозки, дней</span>
          <input v-model="form.fridge_storage_time" class="input" type="number" inputmode="numeric" min="1" max="365" required></label>
        <label class="field"><span class="field-label">Срок в морозильнике, дней</span>
          <input v-model="form.freezer_storage_time" class="input" type="number" inputmode="numeric" min="1" max="3650" placeholder="необязательно"></label>
      </div>
      <label class="field"><span class="field-label">Категория</span>
        <input v-model="form.category" class="input" maxlength="60" list="categories" placeholder="необязательно"></label>
      <datalist id="categories"><option v-for="category in categories" :key="category" :value="category" /></datalist>
      <p v-if="form.id" class="muted">
        В морозильнике: {{ editing?.freezer_quantity ?? 0 }} шт. Новое название появится и у остатков.
      </p>
    </form>
    <template #footer>
      <button v-if="form.id" class="btn btn-ghost-danger" type="button" :disabled="editing?.freezer_quantity > 0" @click="remove">
        <Trash2 class="icon" :size="24" :stroke-width="1.75" /> Удалить
      </button>
      <button class="btn btn-secondary" type="button" @click="form = null">Отмена</button>
      <button class="btn btn-primary" type="submit" form="product-form" :disabled="sending">Сохранить</button>
    </template>
  </ModalDialog>
</template>

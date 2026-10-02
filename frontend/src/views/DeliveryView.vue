<script setup>
import { computed, onMounted, ref } from 'vue'
import { Search, Tag } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import ModalDialog from '../components/ModalDialog.vue'
import PageHeader from '../components/PageHeader.vue'
import QuantityInput from '../components/QuantityInput.vue'
import SearchBox from '../components/SearchBox.vue'
import { api } from '../api.js'
import { plural } from '../dates.js'
import { matches } from '../search.js'
import { toast } from '../store.js'

const products = ref(null)
const query = ref('')
const selected = ref(null)
const quantity = ref(1)
const sending = ref(false)

const shown = computed(() => (products.value || []).filter(
  (product) => matches(product.name, query.value) || matches(product.category, query.value),
))

async function load() {
  products.value = await api.get('/catalog')
}

function open(product) {
  selected.value = product
  quantity.value = 1
}

async function deliver() {
  sending.value = true
  try {
    const result = await api.post('/delivery', { product_id: selected.value.id, quantity: quantity.value })
    toast(`В морозильник добавлено: ${result.product_name} — ${result.quantity} шт\nТеперь в морозильнике: ${result.in_freezer} шт`)
    selected.value = null
    load()
  } catch (error) {
    toast(error.message, 'error')
  } finally {
    sending.value = false
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="Добавить заморозку" subtitle="Поставка в морозильник: выберите товар из справочника" />
  <div class="toolbar"><SearchBox v-model="query" placeholder="Поиск по названию или категории" /></div>

  <template v-if="products">
    <div v-if="shown.length" class="cards-grid">
      <button v-for="product in shown" :key="product.id" class="pick-card" type="button" @click="open(product)">
        <span class="pick-card-title">{{ product.name }}</span>
        <span>Сейчас в морозильнике: <b>{{ product.freezer_quantity }} шт.</b></span>
        <span class="muted">
          Хранится {{ product.fridge_storage_time }} {{ plural(product.fridge_storage_time, 'день', 'дня', 'дней') }} после разморозки
        </span>
        <span v-if="product.category" class="badge">{{ product.category }}</span>
      </button>
    </div>
    <EmptyState v-else-if="query" :icon="Search" :text="`По запросу «${query}» товаров нет`" />
    <EmptyState v-else :icon="Tag" text="Справочник товаров пуст. Товары добавляет администратор" />
  </template>

  <ModalDialog v-if="selected" :title="selected.name" @close="selected = null">
    <div class="stack">
      <p class="muted">Сейчас в морозильнике {{ selected.freezer_quantity }} шт.</p>
      <div class="field">
        <span class="field-label">Сколько добавить?</span>
        <QuantityInput v-model="quantity" />
      </div>
    </div>
    <template #footer>
      <button class="btn btn-secondary" type="button" @click="selected = null">Отмена</button>
      <button class="btn btn-primary" type="button" :disabled="sending" @click="deliver">Добавить {{ quantity }} шт.</button>
    </template>
  </ModalDialog>
</template>

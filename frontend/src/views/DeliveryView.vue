<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refrigerator, Search, Snowflake, Tag } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import ModalDialog from '../components/ModalDialog.vue'
import PageHeader from '../components/PageHeader.vue'
import QuantityInput from '../components/QuantityInput.vue'
import SearchBox from '../components/SearchBox.vue'
import { api } from '../api.js'
import { formatDate, plural } from '../dates.js'
import { matches } from '../search.js'
import { toast } from '../store.js'

// Куда добавить поставку; по умолчанию — в морозильник.
const DESTINATIONS = [
  { value: 'freezer', title: 'Морозильник', icon: Snowflake },
  { value: 'fridge', title: 'Холодильник', icon: Refrigerator },
]

const products = ref(null)
const query = ref('')
const selected = ref(null)
const destination = ref('freezer')
const quantity = ref(1)
const sending = ref(false)

const shown = computed(() => (products.value || []).filter(
  (product) => matches(product.name, query.value) || matches(product.category, query.value),
))
const canSend = computed(() => !sending.value && (destination.value === 'freezer' || Boolean(selected.value?.expires)))

async function load() {
  products.value = await api.get('/catalog')
}

function open(product) {
  selected.value = product
  destination.value = 'freezer'
  quantity.value = 1
}

async function deliver() {
  sending.value = true
  try {
    const result = await api.post('/delivery', {
      product_id: selected.value.id, quantity: quantity.value, destination: destination.value,
    })
    toast(result.destination === 'fridge'
      ? `В холодильник добавлено: ${result.product_name} — ${result.quantity} шт\nГоден до: ${formatDate(result.expiration_date)}`
        + (result.batch_quantity > result.quantity ? `\nВ сегодняшней партии теперь: ${result.batch_quantity} шт` : '')
      : `В морозильник добавлено: ${result.product_name} — ${result.quantity} шт\nТеперь в морозильнике: ${result.in_freezer} шт`)
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
  <PageHeader title="Поставка товара" subtitle="Выберите товар из справочника — поставку можно добавить в морозильник или сразу в холодильник" />
  <div class="toolbar"><SearchBox v-model="query" placeholder="Поиск по названию или категории" /></div>

  <template v-if="products">
    <div v-if="shown.length" class="cards-grid">
      <button v-for="product in shown" :key="product.id" class="pick-card" type="button" @click="open(product)">
        <span class="pick-card-title">{{ product.name }}</span>
        <span>В морозильнике: <b>{{ product.freezer_quantity }} шт.</b></span>
        <span>В холодильнике: <b>{{ product.fridge_quantity }} шт.</b></span>
        <span class="muted">
          Хранится {{ product.fridge_storage_time }} {{ plural(product.fridge_storage_time, 'день', 'дня', 'дней') }} в холодильнике
        </span>
        <span v-if="product.category" class="badge">{{ product.category }}</span>
      </button>
    </div>
    <EmptyState v-else-if="query" :icon="Search" :text="`По запросу «${query}» товаров нет`" />
    <EmptyState v-else :icon="Tag" text="Справочник товаров пуст. Товары добавляет администратор" />
  </template>

  <ModalDialog v-if="selected" :title="selected.name" @close="selected = null">
    <div class="stack">
      <p class="muted">
        Сейчас в морозильнике {{ selected.freezer_quantity }} шт., в холодильнике {{ selected.fridge_quantity }} шт.
      </p>
      <div class="field">
        <span class="field-label">Куда добавить?</span>
        <div class="segmented segmented-wide" role="radiogroup" aria-label="Куда добавить">
          <button
            v-for="place in DESTINATIONS" :key="place.value" type="button" role="radio"
            :aria-checked="destination === place.value" :class="{ active: destination === place.value }"
            @click="destination = place.value"
          >
            <component :is="place.icon" class="icon" :size="22" :stroke-width="1.75" /> {{ place.title }}
          </button>
        </div>
        <span v-if="destination === 'freezer'" class="field-hint">Товар добавится к запасу в морозильнике</span>
        <span v-else-if="selected.expires" class="field-hint">
          Годен до {{ formatDate(selected.expires) }}. Если сегодня этот товар уже клали в холодильник,
          количество добавится к той же партии
        </span>
        <span v-else class="error-text">У товара не задан срок хранения в холодильнике — его задаёт администратор</span>
      </div>
      <div class="field">
        <span class="field-label">Сколько добавить?</span>
        <QuantityInput v-model="quantity" />
      </div>
    </div>
    <template #footer>
      <button class="btn btn-secondary" type="button" @click="selected = null">Отмена</button>
      <button class="btn btn-primary" type="button" :disabled="!canSend" @click="deliver">Добавить {{ quantity }} шт.</button>
    </template>
  </ModalDialog>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { PackageOpen, Search } from 'lucide-vue-next'
import EmptyState from '../components/EmptyState.vue'
import ModalDialog from '../components/ModalDialog.vue'
import PageHeader from '../components/PageHeader.vue'
import QuantityInput from '../components/QuantityInput.vue'
import SearchBox from '../components/SearchBox.vue'
import { api } from '../api.js'
import { formatDate, formatDateTime } from '../dates.js'
import { matches } from '../search.js'
import { toast } from '../store.js'

const items = ref(null)
const query = ref('')
const selected = ref(null)
const quantity = ref(1)
const sending = ref(false)

const shown = computed(() => (items.value || []).filter((item) => matches(item.product_name, query.value)))

async function load() {
  items.value = await api.get('/freezer')
}

function open(item) {
  selected.value = item
  quantity.value = 1
}

async function defrost() {
  sending.value = true
  try {
    const batch = await api.post('/defrost', { product_id: selected.value.id, quantity: quantity.value })
    toast(
      `Добавлено: ${batch.product_name} — ${batch.quantity} шт\n`
      + `Дата разморозки: ${formatDateTime(batch.defrosted_at)}\n`
      + `Годен до: ${formatDate(batch.expiration_date)}`,
    )
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
  <PageHeader title="Разморозить" subtitle="Выберите товар — партия с датой «годен до» появится в холодильнике" />
  <div class="toolbar"><SearchBox v-model="query" /></div>

  <template v-if="items">
    <div v-if="shown.length" class="cards-grid">
      <button v-for="item in shown" :key="item.id" class="pick-card" type="button" @click="open(item)">
        <span class="pick-card-title">{{ item.product_name }}</span>
        <span>В морозильнике: <b>{{ item.quantity }} шт.</b></span>
        <span v-if="item.expires" class="muted">После разморозки годен до {{ formatDate(item.expires) }}</span>
        <span v-else class="badge badge-expired">Нет в справочнике</span>
      </button>
    </div>
    <EmptyState v-else-if="query" :icon="Search" :text="`По запросу «${query}» в морозильнике ничего нет`" />
    <EmptyState v-else :icon="PackageOpen" text="В морозильнике нет продуктов. Добавьте их в разделе «Поставка товара»" />
  </template>

  <ModalDialog v-if="selected" :title="selected.product_name" @close="selected = null">
    <div class="stack">
      <p class="muted">
        В морозильнике {{ selected.quantity }} шт.
        <template v-if="selected.expires">После разморозки годен до {{ formatDate(selected.expires) }}.</template>
      </p>
      <div class="field">
        <span class="field-label">Сколько разморозить?</span>
        <QuantityInput v-model="quantity" :max="selected.quantity" show-all />
      </div>
    </div>
    <template #footer>
      <button class="btn btn-secondary" type="button" @click="selected = null">Отмена</button>
      <button class="btn btn-primary" type="button" :disabled="sending || !selected.expires" @click="defrost">
        Разморозить {{ quantity }} шт.
      </button>
    </template>
  </ModalDialog>
</template>

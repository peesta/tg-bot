<script setup>
import { computed, onMounted, ref } from 'vue'
import { Boxes, Search } from 'lucide-vue-next'
import BatchDialog from './BatchDialog.vue'
import EmptyState from './EmptyState.vue'
import SearchBox from './SearchBox.vue'
import StatusBadge from './StatusBadge.vue'
import { api, refreshExpiringCount } from '../api.js'
import { formatDate } from '../dates.js'
import { matches } from '../search.js'

// Партии холодильника карточками; нажатие — окно списания или продажи.
defineProps({ only: { type: String, required: true } }) // write_off, sale

const batches = ref(null)
const query = ref('')
const selected = ref(null)

const shown = computed(() => (batches.value || []).filter((batch) => matches(batch.product_name, query.value)))

async function load() {
  batches.value = await api.get('/batches')
}

function done() {
  selected.value = null
  load()
  refreshExpiringCount()
}

onMounted(load)
</script>

<template>
  <div class="toolbar"><SearchBox v-model="query" /></div>

  <template v-if="batches">
    <div v-if="shown.length" class="cards-grid">
      <button
        v-for="batch in shown" :key="batch.id" class="pick-card" :class="`status-${batch.status}`"
        type="button" @click="selected = batch"
      >
        <span class="pick-card-title">{{ batch.product_name }} — {{ batch.quantity }} шт.</span>
        <span>Годен до {{ formatDate(batch.expiration_date) }}</span>
        <span class="row"><StatusBadge :status="batch.status" /><span class="muted">партия № {{ batch.id }}</span></span>
      </button>
    </div>
    <EmptyState v-else-if="query" :icon="Search" :text="`По запросу «${query}» партий нет`" />
    <EmptyState v-else :icon="Boxes" text="В холодильнике нет партий" />
  </template>

  <BatchDialog v-if="selected" :batch="selected" :only="only" @close="selected = null" @done="done" />
</template>

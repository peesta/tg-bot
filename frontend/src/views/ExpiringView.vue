<script setup>
import { computed, onMounted, ref } from 'vue'
import { ChevronRight, CircleCheck, Trash2 } from 'lucide-vue-next'
import BatchDialog from '../components/BatchDialog.vue'
import EmptyState from '../components/EmptyState.vue'
import PageHeader from '../components/PageHeader.vue'
import { api, refreshExpiringCount } from '../api.js'
import { formatDate } from '../dates.js'
import { confirmAction, toast } from '../store.js'

const data = ref(null)
const selected = ref(null)

const all = computed(() => (data.value ? [...data.value.expired, ...data.value.today] : []))
const total = computed(() => all.value.reduce((sum, batch) => sum + batch.quantity, 0))
const sections = computed(() => [
  { key: 'today', title: 'Срок истекает сегодня', tone: 'card-warning', batches: data.value.today, totals: data.value.today_totals },
  { key: 'expired', title: 'Срок уже истёк', tone: 'card-danger', batches: data.value.expired, totals: data.value.expired_totals },
].filter((section) => section.batches.length))

async function load() {
  data.value = await api.get('/expiring')
  refreshExpiringCount()
}

async function clearAll() {
  const ok = await confirmAction({
    title: 'Списать всё?',
    message: `Партий: ${all.value.length}, всего ${total.value} шт. Причина: «Просрочено».`,
    confirmText: 'Списать всё',
    danger: true,
  })
  if (!ok) return
  try {
    const result = await api.post('/expiring/clear')
    toast(result.message)
  } catch (error) {
    toast(error.message, 'error')
  }
  load()
}

function done() {
  selected.value = null
  load()
}

onMounted(load)
</script>

<template>
  <PageHeader title="Скоро испортится" subtitle="Срок истекает сегодня или уже истёк. Нажмите на партию, чтобы списать или продать">
    <button v-if="all.length" class="btn btn-danger" type="button" @click="clearAll">
      <Trash2 class="icon" :size="24" :stroke-width="1.75" /> Списать всё ({{ all.length }} парт.)
    </button>
  </PageHeader>

  <template v-if="data">
    <EmptyState v-if="!all.length" :icon="CircleCheck" text="Ничего не портится: сегодня ни у одной партии не заканчивается срок, просроченных нет" />
    <section v-for="section in sections" :key="section.key" class="card" :class="section.tone">
      <h2>{{ section.title }}</h2>
      <ul class="summary">
        <li v-for="item in section.totals" :key="item.product_name">
          <span>{{ item.product_name }}</span><b>{{ item.quantity }} шт</b>
        </li>
      </ul>
      <div class="table-wrap">
        <table class="table table-stack">
          <thead><tr><th>Товар</th><th class="num">Шт.</th><th>Годен до</th><th>Партия</th><th /></tr></thead>
          <tbody>
            <tr v-for="batch in section.batches" :key="batch.id" class="clickable" @click="selected = batch">
              <td class="cell-title">{{ batch.product_name }}</td>
              <td class="num" data-label="Шт.">{{ batch.quantity }}</td>
              <td class="nowrap" data-label="Годен до">{{ formatDate(batch.expiration_date) }}</td>
              <td class="muted" data-label="Партия">№ {{ batch.id }}</td>
              <td class="actions cell-arrow">
                <button class="btn btn-secondary btn-small btn-icon" type="button" aria-label="Списать или продать" @click.stop="selected = batch">
                  <ChevronRight class="icon" :size="24" :stroke-width="1.75" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </template>

  <BatchDialog v-if="selected" :batch="selected" @close="selected = null" @done="done" />
</template>

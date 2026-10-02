<script setup>
import { computed, onMounted, ref } from 'vue'
import { CircleCheck, Hourglass, TriangleAlert } from 'lucide-vue-next'
import PageHeader from '../components/PageHeader.vue'
import { api } from '../api.js'
import { formatDateTime, formatDatesInText, formatTime } from '../dates.js'
import { OPERATION_TITLES, CHANGE_TITLES, authorName } from '../labels.js'
import { WORK_NAV } from '../nav.js'
import { store } from '../store.js'

const data = ref(null)
const isAdmin = computed(() => store.user.role === 'admin')
const tiles = WORK_NAV.filter((item) => item.to !== '/')

const statCards = computed(() => {
  const stats = data.value?.stats
  if (!stats) return []
  return [
    { value: stats.products, label: 'товаров в справочнике', to: '/admin/products' },
    { value: stats.freezer_quantity, label: `шт. в морозильнике, ${stats.freezer_items} поз.`, to: '/stock' },
    { value: stats.fridge_batches, label: `партий в холодильнике, ${stats.fridge_quantity} шт.`, to: '/stock' },
    { value: stats.expiring_today, label: 'истекает сегодня', to: '/expiring', tone: stats.expiring_today && 'warning' },
    { value: stats.expired, label: 'просрочено', to: '/expiring', tone: stats.expired && 'danger' },
    { value: stats.operations_today, label: 'операций сегодня', to: '/admin/logs' },
    { value: stats.errors_today, label: 'ошибок сегодня', to: '/admin/logs?tab=errors', tone: stats.errors_today && 'danger' },
  ]
})

onMounted(async () => {
  data.value = await api.get('/dashboard')
})
</script>

<template>
  <template v-if="data">
    <!-- Сотрудник: крупные плитки и свои действия за сегодня -->
    <div v-if="!isAdmin" class="stack">
      <PageHeader :title="`Здравствуйте, ${store.user.full_name}!`" subtitle="Что нужно сделать?" />

      <RouterLink
        v-if="data.expiring_today || data.expired" to="/expiring" class="banner"
        :class="data.expired ? 'banner-danger' : 'banner-warning'"
      >
        <TriangleAlert class="icon" :size="34" :stroke-width="1.75" />
        <div>
          <h2>Скоро испортится</h2>
          <span>
            <template v-if="data.expiring_today">Сегодня истекает срок: {{ data.expiring_today }} парт.</template>
            <template v-if="data.expiring_today && data.expired"> · </template>
            <template v-if="data.expired">Просрочено: {{ data.expired }} парт.</template>
          </span>
        </div>
      </RouterLink>
      <div v-else class="banner banner-ok">
        <CircleCheck class="icon" :size="34" :stroke-width="1.75" />
        <div><h2>Ничего не портится</h2><span class="muted">Сегодня ни у одной партии не заканчивается срок</span></div>
      </div>

      <div class="tiles">
        <RouterLink v-for="item in tiles" :key="item.to" :to="item.to" class="tile">
          <span class="tile-icon"><component :is="item.icon" :size="32" :stroke-width="1.75" /></span>
          <span class="tile-title">{{ item.label }}</span>
          <span v-if="item.badge && store.expiringCount" class="badge-count">{{ store.expiringCount }}</span>
        </RouterLink>
      </div>

      <section class="card">
        <h2>Мои действия сегодня</h2>
        <ul v-if="data.my_operations.length" class="timeline">
          <li v-for="operation in data.my_operations" :key="operation.id">
            <span class="timeline-time">{{ formatTime(operation.created_at) }}</span>
            <span class="badge" :class="`badge-${operation.operation_type}`">{{ OPERATION_TITLES[operation.operation_type] }}</span>
            <span>{{ operation.product_name }} — {{ operation.quantity }} шт<template v-if="operation.reason"> · {{ operation.reason }}</template></span>
          </li>
        </ul>
        <p v-else class="muted">Сегодня вы ещё ничего не делали.</p>
      </section>
    </div>

    <!-- Администратор: сводка и последние события -->
    <div v-else class="stack">
      <PageHeader title="Обзор" :subtitle="`${store.user.full_name}, вот что происходит сейчас`">
        <RouterLink to="/expiring" class="btn btn-secondary">
          <Hourglass class="icon" :size="24" :stroke-width="1.75" /> Скоро испортится
        </RouterLink>
      </PageHeader>

      <div class="stats">
        <RouterLink v-for="card in statCards" :key="card.label" :to="card.to" class="stat" :class="card.tone && `stat-${card.tone}`">
          <span class="stat-value">{{ card.value }}</span>
          <span class="stat-label">{{ card.label }}</span>
        </RouterLink>
      </div>

      <div class="grid-2">
        <section class="card">
          <div class="card-header"><h2>Последние операции</h2><RouterLink to="/admin/logs">Все</RouterLink></div>
          <ul v-if="data.operations.length" class="timeline">
            <li v-for="operation in data.operations" :key="operation.id">
              <span class="timeline-time">{{ formatDateTime(operation.created_at) }}</span>
              <span class="badge" :class="`badge-${operation.operation_type}`">{{ OPERATION_TITLES[operation.operation_type] }}</span>
              <span>{{ operation.product_name }} — {{ operation.quantity }} шт · {{ authorName(operation) }}</span>
            </li>
          </ul>
          <p v-else class="muted">Операций пока не было.</p>
        </section>
        <section class="card">
          <div class="card-header"><h2>Последние изменения</h2><RouterLink to="/admin/logs?tab=changes">Все</RouterLink></div>
          <ul v-if="data.changes.length" class="timeline">
            <li v-for="change in data.changes" :key="change.id">
              <span class="timeline-time">{{ formatDateTime(change.created_at) }}</span>
              <span><b>{{ CHANGE_TITLES[change.action] || change.action }}</b> · {{ authorName(change) }}<br>
                <span class="muted">{{ formatDatesInText(change.details) }}</span></span>
            </li>
          </ul>
          <p v-else class="muted">Изменений пока не было.</p>
        </section>
      </div>
    </div>
  </template>
</template>

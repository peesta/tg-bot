<script setup>
import { computed, onMounted, ref } from 'vue'
import { Download, ExternalLink, Upload } from 'lucide-vue-next'
import PageHeader from '../../components/PageHeader.vue'
import { api } from '../../api.js'
import { plural } from '../../dates.js'
import { confirmAction } from '../../store.js'

const settings = ref(null)
const result = ref(null)
const running = ref(false)

// «Товары», «Морозильник» и «Холодильник» — названия листов приходят с сервера.
const sheetList = computed(() => {
  const titles = Object.values(settings.value?.sheets || {}).map((title) => `«${title}»`)
  return `${titles.slice(0, -1).join(', ')} и ${titles.at(-1)}`
})

async function run(action) {
  const ok = await confirmAction(action === 'export'
    ? {
      title: 'Выгрузить в Google Таблицу?',
      message: `Листы ${sheetList.value} будут очищены и заполнены данными из базы.`,
      confirmText: 'Выгрузить',
    }
    : {
      title: 'Загрузить из Google Таблицы?',
      message: 'Товары, морозильник и холодильник в базе будут заменены данными из таблицы. Перед заменой сохранится копия базы.',
      confirmText: 'Загрузить',
      danger: true,
    })
  if (!ok) return
  running.value = true
  result.value = null
  try {
    result.value = { action, ...(await api.post(`/admin/google/${action}`)) }
  } catch (error) {
    result.value = { action, error: error.message, errors: error.data?.errors }
  } finally {
    running.value = false
  }
}

onMounted(async () => {
  settings.value = await api.get('/admin/google')
})
</script>

<template>
  <PageHeader title="Google Таблица" subtitle="Выгрузка и загрузка товаров, морозильника и холодильника">
    <a v-if="settings?.url" :href="settings.url" target="_blank" rel="noopener" class="btn btn-secondary">
      <ExternalLink class="icon" :size="24" :stroke-width="1.75" /> Открыть таблицу
    </a>
  </PageHeader>

  <div v-if="result" class="banner mb" :class="result.counts ? 'banner-ok' : 'banner-danger'">
    <div class="stack stack-tight">
      <template v-if="result.counts">
        <b>{{ result.action === 'export' ? 'Экспорт завершён' : 'Импорт завершён' }}</b>
        <span v-for="(count, table) in result.counts" :key="table">{{ settings?.sheets[table] || table }}: {{ count }} {{ plural(count, 'строка', 'строки', 'строк') }}</span>
        <span v-if="result.backup" class="muted">Копия базы до импорта: {{ result.backup }}</span>
      </template>
      <template v-else>
        <b>{{ result.error }}</b>
        <span v-for="line in result.errors || []" :key="line">{{ line }}</span>
      </template>
    </div>
  </div>

  <section v-if="settings" class="card">
    <h2 class="mb-s">Настройки</h2>
    <dl class="details">
      <dt>Таблица</dt>
      <dd>
        <a v-if="settings.table" :href="settings.url" target="_blank" rel="noopener">{{ settings.table }}</a>
        <span v-else class="badge badge-expired">не задана — добавьте GOOGLE_TABLE в .env</span>
      </dd>
      <dt>Ключ доступа</dt>
      <dd>
        <span v-if="settings.has_credentials">{{ settings.credentials_file }} найден</span>
        <span v-else class="badge badge-expired">нет файла {{ settings.credentials_file }}</span>
      </dd>
      <template v-if="settings.email">
        <dt>Дайте доступ «Редактор» для</dt><dd>{{ settings.email }}</dd>
      </template>
    </dl>
  </section>

  <div class="grid-2 mt">
    <section class="card stack">
      <h2>Экспорт</h2>
      <p class="muted">
        Листы {{ sheetList }} будут заполнены текущими данными: названия столбцов по-русски, даты — ДД.ММ.ГГГГ.
        Остальные листы не трогаются.
      </p>
      <button class="btn btn-primary" type="button" :disabled="running" @click="run('export')">
        <Upload class="icon" :size="24" :stroke-width="1.75" /> Выгрузить в таблицу
      </button>
    </section>
    <section class="card stack">
      <h2>Импорт</h2>
      <p class="muted">Заменяет товары, морозильник и холодильник. При ошибке в любой строке база не меняется.</p>
      <button class="btn btn-danger" type="button" :disabled="running" @click="run('import')">
        <Download class="icon" :size="24" :stroke-width="1.75" /> Загрузить из таблицы
      </button>
    </section>
  </div>
</template>

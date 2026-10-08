<script setup>
import { onMounted, ref } from 'vue'
import { DatabaseBackup, Download, Plus, RotateCcw, Trash2 } from 'lucide-vue-next'
import EmptyState from '../../components/EmptyState.vue'
import PageHeader from '../../components/PageHeader.vue'
import { api } from '../../api.js'
import { formatDateTime } from '../../dates.js'
import { confirmAction, toast } from '../../store.js'

const files = ref(null)

async function load() {
  files.value = await api.get('/admin/backups')
}

async function create() {
  try {
    const result = await api.post('/admin/backups')
    toast(`Копия сохранена: ${result.name}`)
    load()
  } catch (error) {
    toast(error.message, 'error')
  }
}

async function restore(file) {
  const ok = await confirmAction({
    title: 'Восстановить базу из копии?',
    message: `Товары, остатки, сотрудники и журнал операций станут как в копии ${file.name}. Журнал изменений и ошибки сохранятся. Текущее состояние сохранится отдельной копией.`,
    confirmText: 'Восстановить',
    danger: true,
  })
  if (!ok) return
  try {
    const result = await api.post(`/admin/backups/${file.name}/restore`)
    toast(`База восстановлена. Прежнее состояние — в копии ${result.saved}`)
    load()
  } catch (error) {
    toast(error.message, 'error')
  }
}

async function download(file) {
  try {
    await api.download(`/admin/backups/${file.name}`, file.name)
  } catch (error) {
    toast(error.message, 'error')
  }
}

async function remove(file) {
  const ok = await confirmAction({ title: `Удалить копию ${file.name}?`, confirmText: 'Удалить', danger: true })
  if (!ok) return
  try {
    await api.delete(`/admin/backups/${file.name}`)
    load()
  } catch (error) {
    toast(error.message, 'error')
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="Резервные копии" subtitle="Копии базы создаются и перед импортом из Google Таблицы">
    <button class="btn btn-primary" type="button" @click="create">
      <Plus class="icon" :size="24" :stroke-width="1.75" /> Сделать копию сейчас
    </button>
  </PageHeader>
  <template v-if="files">
    <EmptyState v-if="!files.length" :icon="DatabaseBackup" text="Копий пока нет" />
    <div v-else class="table-wrap">
      <table class="table table-stack">
        <thead><tr><th>Файл</th><th>Создана</th><th class="num">Размер</th><th /></tr></thead>
        <tbody>
          <tr v-for="file in files" :key="file.name">
            <td class="cell-title">{{ file.name }}</td>
            <td class="nowrap" data-label="Создана">{{ formatDateTime(file.created_at) }}</td>
            <td class="num nowrap" data-label="Размер">{{ (file.size / 1024).toFixed(1) }} КБ</td>
            <td class="actions">
              <button class="btn btn-secondary btn-small" type="button" @click="download(file)">
                <Download class="icon" :size="22" :stroke-width="1.75" /> Скачать
              </button>
              <button class="btn btn-warning btn-small" type="button" @click="restore(file)">
                <RotateCcw class="icon" :size="22" :stroke-width="1.75" /> Восстановить
              </button>
              <button class="btn btn-ghost-danger btn-small btn-icon" type="button" :aria-label="`Удалить ${file.name}`" @click="remove(file)">
                <Trash2 class="icon" :size="22" :stroke-width="1.75" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>
</template>

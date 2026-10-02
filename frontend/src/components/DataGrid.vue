<script setup>
import { ref } from 'vue'
import { ArrowDown, ArrowUp, Check, Trash2, X } from 'lucide-vue-next'
import CellEditor from './CellEditor.vue'
import { formatDate, formatDateTime, todayISO } from '../dates.js'
import { confirmAction, toast } from '../store.js'

// Таблица как в Excel: номера строк, сетка, закреплённая шапка.
// Нажатие на ячейку — правка на месте, «Да/Нет» переключается сразу.
const props = defineProps({
  columns: { type: Array, required: true },
  rows: { type: Array, required: true },
  start: { type: Number, default: 1 },
  sort: { type: String, default: null },
  desc: { type: Boolean, default: false },
  save: { type: Function, required: true }, // (row, column, value) => Promise
  insert: { type: Function, default: null }, // (values) => Promise
  remove: { type: Function, required: true }, // (row) => Promise
})
const emit = defineEmits(['sort'])

const active = ref(null) // { rowid, name, draft }
const savingKey = ref(null)
const adding = ref(false)
const newRow = ref({})
const inserting = ref(false)

function optionLabel(column, value) {
  const option = column.options?.find((item) => item.value === value)
  return option ? option.label : value
}

function display(column, value) {
  if (value === null || value === undefined || value === '') return ''
  switch (column.kind) {
    case 'date': return formatDate(value)
    case 'datetime': return formatDateTime(value)
    case 'longtext': return String(value).split('\n')[0]
    default: return column.options ? optionLabel(column, value) : value
  }
}

function key(row, column) {
  return `${row.__rowid}:${column.name}`
}

function isActive(row, column) {
  return active.value && active.value.rowid === row.__rowid && active.value.name === column.name
}

async function store(row, column, value) {
  savingKey.value = key(row, column)
  try {
    await props.save(row, column, value)
  } catch (error) {
    toast(error.message, 'error')
  } finally {
    savingKey.value = null
  }
}

function activate(row, column) {
  if (column.readonly || savingKey.value) return
  if (column.kind === 'bool') {
    store(row, column, !row[column.name])
    return
  }
  if (isActive(row, column)) return
  active.value = { rowid: row.__rowid, name: column.name, draft: row[column.name] }
}

async function commit(row, column) {
  const editing = active.value
  if (!editing || editing.rowid !== row.__rowid || editing.name !== column.name) return
  active.value = null
  const value = typeof editing.draft === 'string' && column.kind !== 'longtext'
    ? editing.draft.trim()
    : editing.draft
  if (value === row[column.name] || (value === '' && row[column.name] === null)) return
  await store(row, column, value === '' ? null : value)
}

function cancel() {
  active.value = null
}

function defaults() {
  const now = new Date()
  const time = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  return Object.fromEntries(
    props.columns.filter((column) => !column.readonly).map((column) => {
      if (column.kind === 'date') return [column.name, todayISO()]
      if (column.kind === 'datetime') return [column.name, `${todayISO()} ${time}`]
      if (column.kind === 'bool') return [column.name, true]
      return [column.name, null]
    }),
  )
}

function startAdd() {
  active.value = null
  newRow.value = defaults()
  adding.value = true
}

async function saveNew() {
  inserting.value = true
  try {
    await props.insert({ ...newRow.value })
    adding.value = false
  } catch (error) {
    toast(error.message, 'error')
  } finally {
    inserting.value = false
  }
}

async function askRemove(row, number) {
  const ok = await confirmAction({
    title: `Удалить строку ${number}?`,
    message: 'Строка удалится из базы. Изменение запишется в журнал.',
    confirmText: 'Удалить',
    danger: true,
  })
  if (!ok) return
  try {
    await props.remove(row)
  } catch (error) {
    toast(error.message, 'error')
  }
}

defineExpose({ startAdd })
</script>

<template>
  <div class="sheet-wrap">
    <table class="sheet">
      <thead>
        <tr>
          <th class="rownum" aria-label="Номер строки" />
          <th
            v-for="column in columns" :key="column.name"
            :class="{ num: column.kind === 'int' }" @click="emit('sort', column.name)"
          >
            {{ column.label }}<span v-if="column.required && !column.readonly" class="required"> *</span>
            <template v-if="sort === column.name">
              <ArrowDown v-if="desc" class="icon sort" :size="20" :stroke-width="1.75" />
              <ArrowUp v-else class="icon sort" :size="20" :stroke-width="1.75" />
            </template>
          </th>
          <th class="actions-col" aria-label="Действия" />
        </tr>
      </thead>
      <tbody>
        <tr v-if="adding" class="new-row">
          <td class="rownum">+</td>
          <td v-for="column in columns" :key="column.name" class="cell">
            <span v-if="column.readonly" class="muted">выдаст база</span>
            <CellEditor v-else v-model="newRow[column.name]" :column="column" mode="form" />
          </td>
          <td class="actions-col">
            <div class="row">
              <button class="btn btn-primary btn-small btn-icon" type="button" aria-label="Сохранить строку" :disabled="inserting" @click="saveNew">
                <Check class="icon" :size="22" :stroke-width="2" />
              </button>
              <button class="btn btn-ghost btn-small btn-icon" type="button" aria-label="Отменить" @click="adding = false">
                <X class="icon" :size="22" :stroke-width="2" />
              </button>
            </div>
          </td>
        </tr>
        <tr v-for="(row, index) in rows" :key="row.__rowid">
          <td class="rownum">{{ start + index }}</td>
          <td
            v-for="column in columns" :key="column.name" class="cell"
            :class="{
              readonly: column.readonly,
              active: isActive(row, column),
              saving: savingKey === key(row, column),
              num: column.kind === 'int' && !column.options,
            }"
            :title="column.kind === 'longtext' ? row[column.name] : undefined"
            @click="activate(row, column)"
          >
            <CellEditor
              v-if="isActive(row, column)" v-model="active.draft" :column="column"
              @commit="commit(row, column)" @cancel="cancel"
            />
            <span
              v-else-if="column.kind === 'bool'"
              :class="row[column.name] ? 'bool-yes' : 'bool-no'"
            >{{ row[column.name] ? 'Да' : 'Нет' }}</span>
            <template v-else>{{ display(column, row[column.name]) }}</template>
          </td>
          <td class="actions-col">
            <button
              class="btn btn-ghost-danger btn-small btn-icon" type="button"
              :aria-label="`Удалить строку ${start + index}`" @click="askRemove(row, start + index)"
            >
              <Trash2 class="icon" :size="22" :stroke-width="1.75" />
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

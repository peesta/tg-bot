<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { Check, X } from 'lucide-vue-next'
import DatePicker from './DatePicker.vue'
import ModalDialog from './ModalDialog.vue'

// Поле для одной ячейки. mode="cell" — правка в таблице: сохраняется по
// Enter, по уходу из поля или выбору в календаре. mode="form" — новая строка:
// значение просто обновляется, сохраняет кнопка строки.
const model = defineModel({ default: null })
const props = defineProps({
  column: { type: Object, required: true },
  mode: { type: String, default: 'cell' },
})
const emit = defineEmits(['commit', 'cancel'])

const input = ref(null)
const inCell = computed(() => props.mode === 'cell')

const datePart = computed({
  get: () => (model.value ? String(model.value).slice(0, 10) : null),
  set: (value) => {
    model.value = value ? `${value} ${timePart.value || '00:00'}` : null
  },
})
const timePart = computed({
  get: () => (model.value ? String(model.value).slice(11, 16) : ''),
  set: (value) => {
    if (datePart.value) model.value = `${datePart.value} ${value || '00:00'}`
  },
})

function setNumber(value) {
  model.value = value === '' ? null : Number(value)
}

function commit() {
  if (inCell.value) emit('commit')
}

function cancel() {
  if (inCell.value) emit('cancel')
}

onMounted(async () => {
  await nextTick()
  if (inCell.value && input.value) {
    input.value.focus()
    if (input.value.select && input.value.tagName === 'INPUT') input.value.select()
  }
})
</script>

<template>
  <!-- Дата: только календарь -->
  <DatePicker
    v-if="column.kind === 'date'"
    v-model="model" :auto-open="inCell" :clearable="!column.required" :aria-label="column.label"
    @picked="commit" @close="cancel"
  />

  <!-- Дата и время: календарь и время, сохранение кнопкой -->
  <div v-else-if="column.kind === 'datetime'" class="datetime-editor">
    <DatePicker v-model="datePart" :clearable="!column.required" :aria-label="column.label" />
    <input v-model="timePart" class="input" type="time" aria-label="Время" :disabled="!datePart">
    <template v-if="inCell">
      <button class="btn btn-primary btn-small btn-icon" type="button" aria-label="Сохранить" @click="emit('commit')">
        <Check class="icon" :size="22" :stroke-width="2" />
      </button>
      <button class="btn btn-ghost btn-small btn-icon" type="button" aria-label="Отмена" @click="emit('cancel')">
        <X class="icon" :size="22" :stroke-width="2" />
      </button>
    </template>
  </div>

  <!-- Выбор из списка: товар, сотрудник, роль, операция -->
  <select
    v-else-if="column.options"
    ref="input" v-model="model" class="input" :aria-label="column.label"
    @change="commit" @blur="cancel" @keydown.esc="cancel"
  >
    <option v-if="!column.required" :value="null">— пусто —</option>
    <option v-else-if="model === null" :value="null" disabled>Выберите…</option>
    <option v-for="option in column.options" :key="option.value" :value="option.value">{{ option.label }}</option>
  </select>

  <!-- Да / нет -->
  <label v-else-if="column.kind === 'bool'" class="switch">
    <input v-model="model" type="checkbox" @change="commit">
    <span class="switch-track" />
    <span>{{ model ? 'Да' : 'Нет' }}</span>
  </label>

  <!-- Число -->
  <input
    v-else-if="column.kind === 'int'"
    ref="input" class="input" type="number" inputmode="numeric" :min="column.minimum ?? undefined"
    :value="model" :aria-label="column.label"
    @input="setNumber($event.target.value)" @keydown.enter.prevent="commit" @keydown.esc="cancel" @blur="commit"
  >

  <!-- Длинный текст: отдельное окно, в ячейке не помещается -->
  <template v-else-if="column.kind === 'longtext'">
    <ModalDialog v-if="inCell" :title="column.label" wide @close="emit('cancel')">
      <textarea ref="input" v-model="model" class="input" rows="12" />
      <template #footer>
        <button class="btn btn-secondary" type="button" @click="emit('cancel')">Отмена</button>
        <button class="btn btn-primary" type="button" @click="emit('commit')">Сохранить</button>
      </template>
    </ModalDialog>
    <textarea v-else v-model="model" class="input" rows="3" :aria-label="column.label" />
  </template>

  <!-- Текст -->
  <input
    v-else
    ref="input" v-model="model" class="input" type="text" :aria-label="column.label"
    @keydown.enter.prevent="commit" @keydown.esc="cancel" @blur="commit"
  >
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { MONTHS, WEEKDAYS, formatDate, monthMatrix, parseISODate, todayISO } from '../dates.js'

// Дата выбирается только в календаре, без ручного ввода.
// Значение — ГГГГ-ММ-ДД (как хранит сервер), на экране — ДД.ММ.ГГГГ.
const model = defineModel({ type: String, default: null })
const props = defineProps({
  placeholder: { type: String, default: 'ДД.ММ.ГГГГ' },
  clearable: { type: Boolean, default: true },
  autoOpen: { type: Boolean, default: false },
  ariaLabel: { type: String, default: 'Дата' },
})
// picked — дата выбрана, close — календарь закрыт без выбора.
const emit = defineEmits(['picked', 'close'])

const open = ref(false)
const field = ref(null)
const popup = ref(null)
const view = ref({ year: 0, month: 0 })
const position = ref({ top: '0px', left: '0px' })
const today = todayISO()

const days = computed(() => monthMatrix(view.value.year, view.value.month))

function place() {
  if (!field.value || !popup.value) return
  const rect = field.value.getBoundingClientRect()
  // Ширина календаря — 400px, на телефоне — по ширине экрана (см. base.css).
  const width = popup.value.offsetWidth
  const height = popup.value.offsetHeight
  const left = Math.min(Math.max(rect.left, 8), window.innerWidth - width - 8)
  let top = rect.bottom + 8
  if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 8)
  position.value = { top: `${top}px`, left: `${Math.max(left, 8)}px` }
}

function onPointerDown(event) {
  if (!popup.value?.contains(event.target) && !field.value?.contains(event.target)) hide()
}

function onKey(event) {
  if (event.key === 'Escape') hide()
}

function listen(on) {
  const method = on ? 'addEventListener' : 'removeEventListener'
  document[method]('pointerdown', onPointerDown, true)
  document[method]('keydown', onKey)
  window[method]('resize', place)
  window[method]('scroll', place, true)
}

async function show() {
  const date = parseISODate(model.value) || new Date()
  view.value = { year: date.getFullYear(), month: date.getMonth() }
  open.value = true
  listen(true)
  await nextTick()
  place()
}

function close() {
  open.value = false
  listen(false)
}

function hide() {
  if (!open.value) return
  close()
  emit('close')
}

function shift(step) {
  const date = new Date(view.value.year, view.value.month + step, 1)
  view.value = { year: date.getFullYear(), month: date.getMonth() }
  nextTick(place)
}

function pick(iso) {
  model.value = iso
  close()
  emit('picked', iso)
}

onMounted(() => {
  if (props.autoOpen) show()
})
onBeforeUnmount(() => listen(false))
</script>

<template>
  <button
    ref="field" class="date-field" :class="{ open }" type="button" :aria-label="ariaLabel"
    @click="open ? hide() : show()"
  >
    <span v-if="model">{{ formatDate(model) }}</span>
    <span v-else class="placeholder">{{ placeholder }}</span>
    <CalendarDays class="icon" :size="22" :stroke-width="1.75" />
  </button>
  <Teleport to="body">
    <div
      v-if="open" ref="popup" class="calendar" :style="position"
      role="dialog" aria-label="Выбор даты"
    >
      <div class="calendar-head">
        <button class="btn btn-ghost btn-icon" type="button" aria-label="Предыдущий месяц" @click="shift(-1)">
          <ChevronLeft class="icon" :size="26" :stroke-width="1.75" />
        </button>
        <span class="calendar-month">{{ MONTHS[view.month] }} {{ view.year }}</span>
        <button class="btn btn-ghost btn-icon" type="button" aria-label="Следующий месяц" @click="shift(1)">
          <ChevronRight class="icon" :size="26" :stroke-width="1.75" />
        </button>
      </div>
      <div class="calendar-grid">
        <span v-for="weekday in WEEKDAYS" :key="weekday" class="calendar-weekday">{{ weekday }}</span>
        <button
          v-for="day in days" :key="day.iso" type="button" class="calendar-day"
          :class="{ outside: !day.inMonth, today: day.iso === today, selected: day.iso === model }"
          :aria-label="formatDate(day.iso)" @click="pick(day.iso)"
        >{{ day.day }}</button>
      </div>
      <div class="calendar-foot">
        <button class="btn btn-secondary" type="button" @click="pick(today)">Сегодня</button>
        <button v-if="clearable && model" class="btn btn-ghost" type="button" @click="pick(null)">Очистить</button>
      </div>
    </div>
  </Teleport>
</template>

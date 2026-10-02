<script setup>
import { computed, ref } from 'vue'
import ModalDialog from './ModalDialog.vue'
import QuantityInput from './QuantityInput.vue'
import StatusBadge from './StatusBadge.vue'
import { api } from '../api.js'
import { formatDate } from '../dates.js'
import { toast } from '../store.js'

// Списание или продажа одной партии.
const props = defineProps({ batch: { type: Object, required: true } })
const emit = defineEmits(['close', 'done'])

const REASONS = [
  ['expired', 'Просрочено'],
  ['damaged', 'Повреждено'],
  ['staff', 'Для сотрудника'],
  ['other', 'Другая причина'],
]

const mode = ref('write_off')
const reason = ref(props.batch.status === 'fresh' ? null : 'expired')
const reasonText = ref('')
const quantity = ref(Math.min(1, props.batch.quantity))
const sending = ref(false)

const canSend = computed(() => {
  if (sending.value) return false
  if (mode.value === 'sale') return true
  if (!reason.value) return false
  return reason.value !== 'other' || reasonText.value.trim().length > 0
})

async function send() {
  sending.value = true
  const whole = quantity.value === props.batch.quantity
  try {
    const result = mode.value === 'sale'
      ? await api.post(`/batches/${props.batch.id}/sale`, { quantity: quantity.value, whole })
      : await api.post(`/batches/${props.batch.id}/write-off`, {
        quantity: quantity.value, whole, reason: reason.value, reason_text: reasonText.value,
      })
    toast(result.message)
    emit('done')
  } catch (error) {
    toast(error.message, 'error')
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <ModalDialog :title="batch.product_name" @close="emit('close')">
    <div class="stack">
      <div class="row">
        <span>{{ batch.quantity }} шт. · годен до {{ formatDate(batch.expiration_date) }} · партия № {{ batch.id }}</span>
        <StatusBadge :status="batch.status" />
      </div>

      <div class="segmented" role="tablist">
        <button type="button" :class="{ active: mode === 'write_off' }" @click="mode = 'write_off'">Списать</button>
        <button type="button" :class="{ active: mode === 'sale' }" @click="mode = 'sale'">Продано</button>
      </div>

      <div v-if="mode === 'write_off'" class="field">
        <span class="field-label">Причина списания</span>
        <div class="choices">
          <button
            v-for="[code, title] in REASONS" :key="code" type="button" class="choice"
            :class="{ active: reason === code }" @click="reason = code"
          >{{ title }}</button>
        </div>
        <input
          v-if="reason === 'other'" v-model="reasonText" class="input" maxlength="200"
          placeholder="Напишите причину" aria-label="Другая причина"
        >
      </div>

      <div class="field">
        <span class="field-label">Количество (в партии {{ batch.quantity }} шт.)</span>
        <QuantityInput v-model="quantity" :max="batch.quantity" show-all />
      </div>
    </div>
    <template #footer>
      <button class="btn btn-secondary" type="button" @click="emit('close')">Отмена</button>
      <button
        class="btn" :class="mode === 'sale' ? 'btn-primary' : 'btn-danger'" type="button"
        :disabled="!canSend" @click="send"
      >{{ mode === 'sale' ? 'Продано' : 'Списать' }} {{ quantity }} шт.</button>
    </template>
  </ModalDialog>
</template>

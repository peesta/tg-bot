<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import { X } from 'lucide-vue-next'

defineProps({ title: { type: String, required: true }, wide: Boolean })
const emit = defineEmits(['close'])

function onKey(event) {
  if (event.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKey))
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" @click.self="emit('close')">
      <div class="modal" :class="{ 'modal-wide': wide }" role="dialog" aria-modal="true" :aria-label="title">
        <div class="modal-head">
          <h2>{{ title }}</h2>
          <button class="btn btn-ghost btn-icon" type="button" aria-label="Закрыть" @click="emit('close')">
            <X class="icon" :size="26" :stroke-width="1.75" />
          </button>
        </div>
        <div class="modal-body"><slot /></div>
        <div v-if="$slots.footer" class="modal-foot"><slot name="footer" /></div>
      </div>
    </div>
  </Teleport>
</template>

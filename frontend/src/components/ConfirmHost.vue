<script setup>
import { store } from '../store.js'
import ModalDialog from './ModalDialog.vue'

function answer(value) {
  store.confirmation.resolve(value)
  store.confirmation = null
}
</script>

<template>
  <ModalDialog v-if="store.confirmation" :title="store.confirmation.title" @close="answer(false)">
    <p v-if="store.confirmation.message" class="muted">{{ store.confirmation.message }}</p>
    <template #footer>
      <button class="btn btn-secondary" type="button" @click="answer(false)">Отмена</button>
      <button
        class="btn" :class="store.confirmation.danger ? 'btn-danger' : 'btn-primary'"
        type="button" @click="answer(true)"
      >{{ store.confirmation.confirmText }}</button>
    </template>
  </ModalDialog>
</template>

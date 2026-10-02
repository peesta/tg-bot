<script setup>
import { ref } from 'vue'
import PageHeader from '../components/PageHeader.vue'
import { api } from '../api.js'
import { formatDateTime } from '../dates.js'
import { ROLE_TITLES } from '../labels.js'
import { store, toast } from '../store.js'

const current = ref('')
const next = ref('')
const repeat = ref('')
const error = ref('')

async function changePassword() {
  error.value = ''
  if (next.value !== repeat.value) {
    error.value = 'Пароли не совпадают'
    return
  }
  try {
    await api.post('/auth/password', { current_password: current.value, new_password: next.value })
    current.value = next.value = repeat.value = ''
    toast('Пароль изменён. Вход на других устройствах сброшен.')
  } catch (failure) {
    error.value = failure.message
  }
}
</script>

<template>
  <PageHeader title="Профиль" />
  <div class="grid-2">
    <section class="card stack">
      <h2>Учётная запись</h2>
      <dl class="details">
        <dt>Имя</dt><dd>{{ store.user.full_name }}</dd>
        <dt>Логин</dt><dd>{{ store.user.username }}</dd>
        <dt>Роль</dt><dd>{{ ROLE_TITLES[store.user.role] }}</dd>
        <dt>Прошлый вход</dt><dd>{{ formatDateTime(store.user.last_login) || '—' }}</dd>
      </dl>
      <p class="muted">Имя и логин меняет администратор.</p>
    </section>
    <form class="card stack" @submit.prevent="changePassword">
      <h2>Сменить пароль</h2>
      <label class="field"><span class="field-label">Текущий пароль</span>
        <input v-model="current" class="input" type="password" autocomplete="current-password" required></label>
      <label class="field"><span class="field-label">Новый пароль</span>
        <input v-model="next" class="input" type="password" autocomplete="new-password" required></label>
      <label class="field"><span class="field-label">Повторите новый пароль</span>
        <input v-model="repeat" class="input" type="password" autocomplete="new-password" required></label>
      <p v-if="error" class="error-text" role="alert">{{ error }}</p>
      <div class="form-actions"><button class="btn btn-primary" type="submit">Сохранить пароль</button></div>
    </form>
  </div>
</template>

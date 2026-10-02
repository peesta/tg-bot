<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogIn, Snowflake } from 'lucide-vue-next'
import { api } from '../api.js'
import { store } from '../store.js'

const route = useRoute()
const router = useRouter()
const username = ref('')
const password = ref('')
const error = ref('')
const sending = ref(false)

async function submit() {
  error.value = ''
  sending.value = true
  try {
    store.user = await api.post('/auth/login', { username: username.value, password: password.value })
    store.userLoaded = true
    const next = typeof route.query.next === 'string' && route.query.next.startsWith('/') ? route.query.next : '/'
    router.push(next)
  } catch (failure) {
    error.value = failure.message
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <form class="login-card stack" @submit.prevent="submit">
      <div class="login-brand">
        <div class="login-mark"><Snowflake :size="40" :stroke-width="1.75" /></div>
        <h1>Учёт сроков годности</h1>
        <p class="muted">Войдите под своей учётной записью</p>
      </div>
      <label class="field">
        <span class="field-label">Логин</span>
        <input v-model="username" class="input" autocomplete="username" autocapitalize="none" required>
      </label>
      <label class="field">
        <span class="field-label">Пароль</span>
        <input v-model="password" class="input" type="password" autocomplete="current-password" required>
      </label>
      <p v-if="error" class="error-text" role="alert">{{ error }}</p>
      <button class="btn btn-primary btn-block" type="submit" :disabled="sending">
        <LogIn class="icon" :size="24" :stroke-width="1.75" /> Войти
      </button>
      <p class="muted">Регистрации нет: учётную запись выдаёт администратор.</p>
    </form>
  </main>
</template>

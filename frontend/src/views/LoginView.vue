<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogIn, RotateCcw, Snowflake } from 'lucide-vue-next'
import { api, BROWSER_BACKEND, resetBrowserDatabase } from '../api.js'
import { confirmAction, store } from '../store.js'

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

async function resetDatabase() {
  const ok = await confirmAction({
    title: 'Вернуть начальные данные?',
    message: 'Все изменения, сделанные в этом браузере, будут стёрты: товары, остатки, сотрудники, журналы и копии базы.',
    confirmText: 'Стереть и начать заново',
    danger: true,
  })
  if (ok) await resetBrowserDatabase()
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
      <template v-if="BROWSER_BACKEND">
        <p class="muted">Демо-версия: база хранится в этом браузере, другие посетители ваших изменений не видят.</p>
        <button class="btn btn-ghost btn-block" type="button" @click="resetDatabase">
          <RotateCcw class="icon" :size="24" :stroke-width="1.75" /> Вернуть начальные данные
        </button>
      </template>
    </form>
  </main>
</template>

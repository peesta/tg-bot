<script setup>
import { computed, onMounted, ref } from 'vue'
import { Lock, Plus } from 'lucide-vue-next'
import ModalDialog from '../../components/ModalDialog.vue'
import PageHeader from '../../components/PageHeader.vue'
import { api } from '../../api.js'
import { formatDateTime } from '../../dates.js'
import { ROLE_TITLES } from '../../labels.js'
import { store, toast } from '../../store.js'

const users = ref(null)
const form = ref(null) // новый: { full_name, username, password, role }; правка: + id, is_active
const sending = ref(false)

const isSelf = computed(() => form.value?.id === store.user.id)

async function load() {
  users.value = await api.get('/admin/users')
}

function openNew() {
  form.value = { full_name: '', username: '', password: '', role: 'employee' }
}

function openEdit(person) {
  form.value = { ...person, username: person.username || '', password: '' }
}

async function save() {
  sending.value = true
  try {
    if (form.value.id) {
      const original = users.value.find((person) => person.id === form.value.id)
      const body = {}
      for (const key of ['full_name', 'username', 'role', 'is_active']) {
        if (form.value[key] !== original[key] && !(key === 'username' && !form.value.username)) body[key] = form.value[key]
      }
      if (form.value.password) body.password = form.value.password
      await api.patch(`/admin/users/${form.value.id}`, body)
      toast('Сохранено')
    } else {
      await api.post('/admin/users', form.value)
      toast(`${form.value.full_name} может входить на сайт с логином «${form.value.username}»`)
    }
    form.value = null
    load()
  } catch (error) {
    toast(error.message, 'error')
  } finally {
    sending.value = false
  }
}

onMounted(load)
</script>

<template>
  <PageHeader title="Сотрудники" subtitle="Регистрации нет: сотрудников добавляет администратор">
    <button class="btn btn-primary" type="button" @click="openNew">
      <Plus class="icon" :size="24" :stroke-width="1.75" /> Добавить сотрудника
    </button>
  </PageHeader>

  <div v-if="users" class="table-wrap">
    <table class="table table-stack">
      <thead><tr><th>Имя</th><th>Логин</th><th>Роль</th><th>Доступ</th><th>Последний вход</th></tr></thead>
      <tbody>
        <tr v-for="person in users" :key="person.id" class="clickable" :class="{ 'row-muted': !person.is_active }" @click="openEdit(person)">
          <td class="cell-title"><b>{{ person.full_name }}</b><span v-if="person.id === store.user.id" class="muted"> (вы)</span></td>
          <td data-label="Логин">{{ person.username || '—' }}</td>
          <td data-label="Роль"><span class="badge" :class="{ 'badge-admin': person.role === 'admin' }">{{ ROLE_TITLES[person.role] }}</span></td>
          <td data-label="Доступ">
            <span v-if="!person.is_active" class="badge badge-off">Отключён</span>
            <span v-else-if="!person.username" class="badge badge-today">Нет логина</span>
            <span v-else class="badge badge-fresh">Есть</span>
          </td>
          <td class="nowrap muted" data-label="Последний вход">{{ formatDateTime(person.last_login) || '—' }}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <ModalDialog v-if="form" :title="form.id ? form.full_name : 'Новый сотрудник'" @close="form = null">
    <form id="user-form" class="stack" @submit.prevent="save">
      <p v-if="isSelf" class="banner banner-info">
        <Lock class="icon" :size="26" :stroke-width="1.75" />
        <span>Это вы. Свою роль и доступ изменить нельзя — это делает другой администратор.</span>
      </p>
      <label class="field"><span class="field-label">Имя (видно в журнале)</span>
        <input v-model="form.full_name" class="input" maxlength="60" required></label>
      <div class="form-grid">
        <label class="field"><span class="field-label">Логин</span>
          <input v-model="form.username" class="input" maxlength="32" autocapitalize="none" autocomplete="off" :required="!form.id"></label>
        <label class="field"><span class="field-label">{{ form.id ? 'Новый пароль' : 'Пароль' }}</span>
          <input v-model="form.password" class="input" type="text" autocomplete="new-password" :required="!form.id"
                 :placeholder="form.id ? 'пусто — не менять' : ''"></label>
      </div>
      <div class="field">
        <span class="field-label">Роль</span>
        <div class="segmented">
          <button
            v-for="(title, role) in ROLE_TITLES" :key="role" type="button" :disabled="isSelf"
            :class="{ active: form.role === role }" @click="form.role = role"
          >{{ title }}</button>
        </div>
      </div>
      <label v-if="form.id" class="switch">
        <input v-model="form.is_active" type="checkbox" :disabled="isSelf">
        <span class="switch-track" />
        <span>{{ form.is_active ? 'Доступ к сайту есть' : 'Доступ отключён' }}</span>
      </label>
    </form>
    <template #footer>
      <button class="btn btn-secondary" type="button" @click="form = null">Отмена</button>
      <button class="btn btn-primary" type="submit" form="user-form" :disabled="sending">
        {{ form.id ? 'Сохранить' : 'Добавить' }}
      </button>
    </template>
  </ModalDialog>
</template>

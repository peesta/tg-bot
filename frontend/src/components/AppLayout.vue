<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LogOut, Menu, Snowflake, UserRound } from 'lucide-vue-next'
import NoticeDialog from './NoticeDialog.vue'
import { api, refreshExpiringCount } from '../api.js'
import { ADMIN_NAV, WORK_NAV } from '../nav.js'
import { store } from '../store.js'

const route = useRoute()
const router = useRouter()
const drawerOpen = ref(false)

function isActive(item) {
  return item.exact ? route.path === item.to : route.path.startsWith(item.to)
}

async function logout() {
  await api.post('/auth/logout').catch(() => {})
  store.user = null
  store.notice = null
  router.push('/login')
}

async function loadNotice() {
  try {
    // Если сайт открыт сразу на «Скоро испортится», там тот же список.
    const notice = await api.get('/notice', { skip: route.path === '/expiring' })
    if (notice.show) store.notice = notice
  } catch {
    // уведомление не важнее страницы
  }
}

function onKey(event) {
  if (event.key === 'Escape') drawerOpen.value = false
}

watch(() => route.fullPath, () => {
  drawerOpen.value = false
  refreshExpiringCount()
})

onMounted(() => {
  document.addEventListener('keydown', onKey)
  refreshExpiringCount()
  loadNotice()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <!-- Сотрудник: узкое меню с крупными значками — удобно пальцем.
       На телефоне меню выезжает слева по кнопке. -->
  <div v-if="store.user.role !== 'admin'" class="shell" :class="{ 'drawer-open': drawerOpen }">
    <nav class="rail" aria-label="Меню">
      <div class="rail-brand">
        <Snowflake :size="32" :stroke-width="1.75" aria-hidden="true" />
        <span class="rail-brand-text">Учёт сроков</span>
      </div>
      <RouterLink
        v-for="item in WORK_NAV" :key="item.to" :to="item.to"
        class="rail-link" :class="{ active: isActive(item) }"
      >
        <component :is="item.icon" class="icon" :size="30" :stroke-width="1.75" />
        <span class="rail-lines"><span v-for="line in item.lines" :key="line">{{ line }}</span></span>
        <span class="rail-label">{{ item.label }}</span>
        <span v-if="item.badge && store.expiringCount" class="badge-count">{{ store.expiringCount }}</span>
      </RouterLink>
    </nav>
    <div class="sidebar-backdrop" @click="drawerOpen = false" />
    <div class="main">
      <header class="topbar">
        <button class="btn btn-ghost btn-icon menu-button" type="button" aria-label="Меню" @click="drawerOpen = true">
          <Menu class="icon" :size="28" :stroke-width="1.75" />
        </button>
        <span class="topbar-title">Учёт сроков</span>
        <span class="role-chip">Сотрудник</span>
        <div class="topbar-user">
          <RouterLink to="/profile" class="btn btn-ghost" :aria-label="`Профиль: ${store.user.full_name}`">
            <UserRound class="icon" :size="24" :stroke-width="1.75" /> <span class="topbar-text">{{ store.user.full_name }}</span>
          </RouterLink>
          <button class="btn btn-ghost" type="button" aria-label="Выйти" @click="logout">
            <LogOut class="icon" :size="24" :stroke-width="1.75" /> <span class="topbar-text">Выйти</span>
          </button>
        </div>
      </header>
      <main class="content"><RouterView /></main>
    </div>
  </div>

  <!-- Администратор: панель с разделами «Работа» и «Администрирование» -->
  <div v-else class="shell" :class="{ 'drawer-open': drawerOpen }">
    <aside class="sidebar" aria-label="Меню">
      <div class="sidebar-brand">
        <Snowflake :size="32" :stroke-width="1.75" />
        <div><strong>Учёт сроков</strong><span>Администратор</span></div>
      </div>
      <nav class="sidebar-nav">
        <div class="sidebar-section">Работа</div>
        <RouterLink
          v-for="item in WORK_NAV" :key="item.to" :to="item.to"
          class="sidebar-link" :class="{ active: isActive(item) }"
        >
          <component :is="item.icon" class="icon" :size="24" :stroke-width="1.75" />
          {{ item.label }}
          <span v-if="item.badge && store.expiringCount" class="badge-count">{{ store.expiringCount }}</span>
        </RouterLink>
        <div class="sidebar-section">Администрирование</div>
        <RouterLink
          v-for="item in ADMIN_NAV" :key="item.to" :to="item.to"
          class="sidebar-link" :class="{ active: isActive(item) }"
        >
          <component :is="item.icon" class="icon" :size="24" :stroke-width="1.75" />
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <div class="sidebar-backdrop" @click="drawerOpen = false" />
    <div class="main">
      <header class="topbar">
        <button class="btn btn-ghost btn-icon menu-button" type="button" aria-label="Меню" @click="drawerOpen = true">
          <Menu class="icon" :size="28" :stroke-width="1.75" />
        </button>
        <span class="topbar-title topbar-title-phone">Учёт сроков</span>
        <span class="role-chip">Администратор</span>
        <div class="topbar-user">
          <RouterLink to="/profile" class="btn btn-ghost" :aria-label="`Профиль: ${store.user.full_name}`">
            <UserRound class="icon" :size="24" :stroke-width="1.75" /> <span class="topbar-text">{{ store.user.full_name }}</span>
          </RouterLink>
          <button class="btn btn-ghost" type="button" aria-label="Выйти" @click="logout">
            <LogOut class="icon" :size="24" :stroke-width="1.75" /> <span class="topbar-text">Выйти</span>
          </button>
        </div>
      </header>
      <main class="content"><RouterView /></main>
    </div>
  </div>

  <NoticeDialog />
</template>

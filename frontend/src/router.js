import { createRouter, createWebHistory } from 'vue-router'
import { api, setUnauthorizedHandler } from './api.js'
import { store } from './store.js'

const routes = [
  { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true, title: 'Вход' } },
  { path: '/', component: () => import('./views/DashboardView.vue'), meta: { title: 'Главная' } },
  { path: '/expiring', component: () => import('./views/ExpiringView.vue'), meta: { title: 'Скоро испортится' } },
  { path: '/defrost', component: () => import('./views/DefrostView.vue'), meta: { title: 'Достать из заморозки' } },
  { path: '/delivery', component: () => import('./views/DeliveryView.vue'), meta: { title: 'Добавить заморозку' } },
  { path: '/write-off', component: () => import('./views/WriteOffView.vue'), meta: { title: 'Списание и продажа' } },
  { path: '/stock', component: () => import('./views/StockView.vue'), meta: { title: 'Остатки' } },
  { path: '/history', component: () => import('./views/HistoryView.vue'), meta: { title: 'История списаний' } },
  { path: '/profile', component: () => import('./views/ProfileView.vue'), meta: { title: 'Профиль' } },
  { path: '/admin/products', component: () => import('./views/admin/ProductsView.vue'), meta: { admin: true, title: 'Товары' } },
  { path: '/admin/users', component: () => import('./views/admin/UsersView.vue'), meta: { admin: true, title: 'Сотрудники' } },
  { path: '/admin/tables', component: () => import('./views/admin/TablesView.vue'), meta: { admin: true, title: 'База данных' } },
  { path: '/admin/tables/:name', component: () => import('./views/admin/TableEditorView.vue'), meta: { admin: true, title: 'База данных' } },
  { path: '/admin/logs', component: () => import('./views/admin/LogsView.vue'), meta: { admin: true, title: 'Логи' } },
  { path: '/admin/google', component: () => import('./views/admin/GoogleView.vue'), meta: { admin: true, title: 'Google Таблица' } },
  { path: '/admin/backups', component: () => import('./views/admin/BackupsView.vue'), meta: { admin: true, title: 'Резервные копии' } },
  { path: '/:pathMatch(.*)*', component: () => import('./views/NotFoundView.vue'), meta: { title: 'Нет такой страницы' } },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

async function loadUser() {
  if (store.userLoaded) return
  try {
    store.user = await api.get('/auth/me')
  } catch {
    store.user = null
  }
  store.userLoaded = true
}

router.beforeEach(async (to) => {
  await loadUser()
  if (to.meta.public) {
    return store.user ? '/' : true
  }
  if (!store.user) {
    return { path: '/login', query: to.fullPath !== '/' ? { next: to.fullPath } : {} }
  }
  if (to.meta.admin && store.user.role !== 'admin') {
    return '/'
  }
  return true
})

router.afterEach((to) => {
  document.title = `${to.meta.title || 'Учёт сроков'} · Учёт сроков`
})

setUnauthorizedHandler(() => {
  const current = router.currentRoute.value
  if (!current.meta.public) {
    router.push({ path: '/login', query: { next: current.fullPath } })
  }
})

import { createRouter, createWebHistory } from 'vue-router'
import { api, setUnauthorizedHandler } from './api.js'
import { store } from './store.js'

const routes = [
  { path: '/login', component: () => import('./views/LoginView.vue'), meta: { public: true } },
  { path: '/', component: () => import('./views/DashboardView.vue') },
  { path: '/expiring', component: () => import('./views/ExpiringView.vue') },
  { path: '/defrost', component: () => import('./views/DefrostView.vue') },
  { path: '/delivery', component: () => import('./views/DeliveryView.vue') },
  { path: '/write-off', component: () => import('./views/WriteOffView.vue') },
  { path: '/stock', component: () => import('./views/StockView.vue') },
  { path: '/history', component: () => import('./views/HistoryView.vue') },
  { path: '/profile', component: () => import('./views/ProfileView.vue') },
  { path: '/admin/products', component: () => import('./views/admin/ProductsView.vue'), meta: { admin: true } },
  { path: '/admin/users', component: () => import('./views/admin/UsersView.vue'), meta: { admin: true } },
  { path: '/admin/tables', component: () => import('./views/admin/TablesView.vue'), meta: { admin: true } },
  { path: '/admin/tables/:name', component: () => import('./views/admin/TableEditorView.vue'), meta: { admin: true } },
  { path: '/admin/logs', component: () => import('./views/admin/LogsView.vue'), meta: { admin: true } },
  { path: '/admin/google', component: () => import('./views/admin/GoogleView.vue'), meta: { admin: true } },
  { path: '/admin/backups', component: () => import('./views/admin/BackupsView.vue'), meta: { admin: true } },
  { path: '/:pathMatch(.*)*', component: () => import('./views/NotFoundView.vue') },
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

setUnauthorizedHandler(() => {
  const current = router.currentRoute.value
  if (!current.meta.public) {
    router.push({ path: '/login', query: { next: current.fullPath } })
  }
})

import { reactive } from 'vue'

// Общее состояние: вошедший сотрудник, всплывающие сообщения, подтверждения.
export const store = reactive({
  user: null,
  userLoaded: false,
  expiringCount: 0,
  notice: null,
  toasts: [],
  confirmation: null,
})

let toastId = 0

export function toast(message, type = 'success') {
  const id = (toastId += 1)
  store.toasts.push({ id, message, type })
  setTimeout(() => dismissToast(id), type === 'error' ? 7000 : 4000)
}

export function dismissToast(id) {
  store.toasts = store.toasts.filter((item) => item.id !== id)
}

/** Окно подтверждения вместо window.confirm. Возвращает Promise<boolean>. */
export function confirmAction({ title, message = '', confirmText = 'Да', danger = false }) {
  return new Promise((resolve) => {
    store.confirmation = { title, message, confirmText, danger, resolve }
  })
}

export function isAdmin() {
  return store.user?.role === 'admin'
}

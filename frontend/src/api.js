import { store } from './store.js'

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message)
    this.status = status
    this.data = data
  }
}

let onUnauthorized = () => {}

/** Что делать, когда сессия закончилась (задаёт роутер). */
export function setUnauthorizedHandler(handler) {
  onUnauthorized = handler
}

async function request(method, url, body) {
  const response = await fetch(`/api${url}`, {
    method,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      // Сервер принимает изменения только с этим заголовком (защита от чужих сайтов).
      'X-Requested-With': 'XMLHttpRequest',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await response.json().catch(() => ({}))
  if (response.status === 401 && !url.startsWith('/auth/')) {
    store.user = null
    onUnauthorized()
  }
  if (!response.ok) {
    throw new ApiError(data.detail || 'Не удалось выполнить запрос', response.status, data)
  }
  return data
}

function query(params) {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== null && value !== undefined && value !== '') search.set(key, value)
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

export const api = {
  get: (url, params) => request('GET', url + query(params)),
  post: (url, body = {}) => request('POST', url, body),
  put: (url, body) => request('PUT', url, body),
  patch: (url, body) => request('PATCH', url, body),
  delete: (url) => request('DELETE', url),
}

/** Обновляет число партий на значке «Скоро испортится». */
export async function refreshExpiringCount() {
  try {
    const data = await api.get('/expiring')
    store.expiringCount = data.today.length + data.expired.length
  } catch {
    // значок не важнее страницы
  }
}

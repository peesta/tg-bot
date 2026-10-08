import { store } from './store.js'

// Сборка для Cloudflare Pages (npm run build:pages): сервера нет, запросы
// обрабатывает Python в браузере, у каждого посетителя своя база.
export const BROWSER_BACKEND = import.meta.env.VITE_BACKEND === 'browser'

async function send(url, options) {
  if (BROWSER_BACKEND) {
    const { browserFetch } = await import('./browser-backend/client.js')
    return browserFetch(url, options)
  }
  return fetch(url, { ...options, credentials: 'same-origin' })
}

/** Браузерная версия: стирает базу этого браузера, страница откроется с начальными данными. */
export async function resetBrowserDatabase() {
  if (BROWSER_BACKEND) {
    const client = await import('./browser-backend/client.js')
    await client.resetBrowserDatabase()
  }
}

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
  const response = await send(`/api${url}`, {
    method,
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
  /** Скачивает файл (резервную копию) под именем name. */
  async download(url, name) {
    const response = await send(`/api${url}`, { method: 'GET' })
    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      throw new ApiError(data.detail || 'Не удалось скачать файл', response.status, data)
    }
    const link = document.createElement('a')
    link.href = URL.createObjectURL(await response.blob())
    link.download = name
    link.click()
    setTimeout(() => URL.revokeObjectURL(link.href), 1000)
  },
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

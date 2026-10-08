// Связь страницы с worker.js: запросы к /api обрабатывает Python в браузере.
let worker = null
let nextId = 1
const pending = new Map()

function getWorker() {
  if (worker) return worker
  worker = new Worker(new URL('./worker.js', import.meta.url), { type: 'module' })
  worker.onmessage = ({ data }) => {
    if (data.type === 'reset') {
      location.reload()
      return
    }
    const call = pending.get(data.id)
    if (!call) return
    pending.delete(data.id)
    if (data.error) call.reject(new Error(data.error))
    else call.resolve(data.result)
  }
  worker.onerror = (event) => {
    for (const call of pending.values()) call.reject(new Error(event.message || 'Не удалось запустить сайт'))
    pending.clear()
  }
  return worker
}

function call(message) {
  return new Promise((resolve, reject) => {
    const id = nextId++
    pending.set(id, { resolve, reject })
    getWorker().postMessage({ ...message, id })
  })
}

/** Как fetch, но ответ даёт Python в этом браузере. */
export async function browserFetch(url, { method = 'GET', headers = {}, body } = {}) {
  const result = await call({ type: 'request', method, url, headers, body })
  return new Response(result.status === 204 ? null : result.body, {
    status: result.status,
    headers: result.headers,
  })
}

/** Стирает базу этого браузера и перезагружает страницу с начальными данными. */
export async function resetBrowserDatabase() {
  await call({ type: 'reset' })
  location.reload()
}

// Сайт без сервера: Pyodide (Python в браузере) запускает тот же FastAPI из
// api/ и storage/. База SQLite — в папке /data, которая хранится в IndexedDB
// этого браузера: у каждого посетителя своя база, начальные данные у всех
// одинаковые (frontend/public/seed.db, если он есть, иначе пустая база
// с admin/admin и employee/employee).
import { scrypt } from '@noble/hashes/scrypt.js'
import serverPy from './server.py?raw'
import itsdangerousUrl from './itsdangerous-2.2.0-py3-none-any.whl?url'

const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/'
const DATA_DIR = '/data'
const APP_DIR = '/home/pyodide/app'
const SQLITE_MAGIC = 'SQLite format 3\0'

const sources = import.meta.glob(['../../../api/*.py', '../../../storage/*.py'], {
  query: '?raw', import: 'default', eager: true,
})

// Другие вкладки этого же браузера: после записи они перечитывают базу.
const channel = new BroadcastChannel('uchet-database')
let queue = Promise.resolve()
let pyodide
let handle

/** Всё по очереди: запросы и сохранение базы не мешают друг другу. */
function enqueue(task) {
  const result = queue.then(task)
  queue = result.catch(() => {})
  return result
}

function syncfs(populate) {
  return new Promise((resolve, reject) => {
    pyodide.FS.syncfs(populate, (error) => (error ? reject(error) : resolve()))
  })
}

function exists(path) {
  return pyodide.FS.analyzePath(path).exists
}

async function loadSeed() {
  try {
    const response = await fetch('/seed.db')
    const bytes = new Uint8Array(await response.arrayBuffer())
    // Cloudflare Pages на отсутствующий файл отдаёт index.html — проверяем, что это база.
    if (!response.ok || new TextDecoder().decode(bytes.subarray(0, 16)) !== SQLITE_MAGIC) return
    pyodide.FS.writeFile(`${DATA_DIR}/database.db`, bytes)
  } catch {
    // нет стартовой базы — сайт создаст пустую
  }
}

async function start() {
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`)
  pyodide = await loadPyodide({ indexURL: PYODIDE_URL })
  // hashlib.scrypt (пароли) в Pyodide нет — server.py берёт его отсюда.
  pyodide.registerJsModule('browser_crypto', {
    scrypt: (password, salt, N, r, p, dkLen) => scrypt(password, salt, { N, r, p, dkLen }),
  })
  await pyodide.loadPackage(['fastapi', 'pydantic'])
  // itsdangerous (подпись сессий) в Pyodide не входит — wheel лежит рядом.
  const wheel = await (await fetch(itsdangerousUrl)).arrayBuffer()
  const sitePackages = pyodide.runPython('import site; site.getsitepackages()[0]')
  pyodide.unpackArchive(wheel, 'wheel', { extractDir: sitePackages })

  for (const [path, text] of Object.entries(sources)) {
    const target = `${APP_DIR}/${path.replace('../../../', '')}`
    pyodide.FS.mkdirTree(target.slice(0, target.lastIndexOf('/')))
    pyodide.FS.writeFile(target, text)
  }
  pyodide.FS.writeFile(`${APP_DIR}/browser_server.py`, serverPy)

  pyodide.FS.mkdirTree(DATA_DIR)
  pyodide.FS.mount(pyodide.FS.filesystems.IDBFS, {}, DATA_DIR)
  await syncfs(true)
  if (!exists(`${DATA_DIR}/database.db`)) await loadSeed()

  pyodide.runPython(`
import os, sys
sys.path.insert(0, ${JSON.stringify(APP_DIR)})
os.chdir(${JSON.stringify(APP_DIR)})
import browser_server
browser_server.start()
`)
  handle = pyodide.globals.get('browser_server').handle
  await syncfs(false)
}

const ready = enqueue(start)

let saveTimer = null

async function save(notify) {
  await syncfs(false)
  if (notify) channel.postMessage('changed')
}

/** Изменения сохраняются в IndexedDB сразу; после чтения — с задержкой
 * (чтение тоже пишет журналы, но терять их не страшно). */
function scheduleSave(method) {
  clearTimeout(saveTimer)
  if (method !== 'GET') return enqueue(() => save(true))
  saveTimer = setTimeout(() => enqueue(() => save(false)), 1000)
}

async function request({ method, url, headers, body }) {
  const result = await handle(method, url, JSON.stringify(headers || {}), body ?? null)
  try {
    const response = result.toJs({ dict_converter: Object.fromEntries })
    return { status: response.status, headers: response.headers, body: response.body }
  } finally {
    result.destroy()
  }
}

function removeTree(path) {
  for (const name of pyodide.FS.readdir(path)) {
    if (name === '.' || name === '..') continue
    const child = `${path}/${name}`
    if (pyodide.FS.isDir(pyodide.FS.stat(child).mode)) {
      removeTree(child)
      pyodide.FS.rmdir(child)
    } else {
      pyodide.FS.unlink(child)
    }
  }
}

/** Стирает базу посетителя: после перезагрузки страницы — начальные данные. */
async function reset() {
  removeTree(DATA_DIR)
  await syncfs(false)
  channel.postMessage('reset')
}

channel.onmessage = ({ data }) => {
  if (data === 'changed') {
    enqueue(async () => {
      await syncfs(true)
      pyodide.runPython('browser_server.load_cookies()')
    })
  }
  // Сброс в другой вкладке: эту вкладку перезагрузит client.js.
  if (data === 'reset') self.postMessage({ type: 'reset' })
}

self.onmessage = async ({ data }) => {
  const { id, type } = data
  try {
    await ready
    let result
    if (type === 'request') {
      result = await enqueue(() => request(data))
      scheduleSave(data.method)
    } else if (type === 'reset') {
      result = await enqueue(reset)
    }
    const transfer = result?.body ? [result.body.buffer] : []
    self.postMessage({ id, result }, transfer)
  } catch (error) {
    console.error(error)
    self.postMessage({ id, error: String(error?.message || error) })
  }
}

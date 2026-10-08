// Даты приходят с сервера как в базе: ГГГГ-ММ-ДД или ГГГГ-ММ-ДД ЧЧ:ММ[:СС].
// Формат ДД.ММ.ГГГГ — только здесь, на клиенте.

export const MONTHS = [
  'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
  'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
]
export const WEEKDAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/

function pad(number) {
  return String(number).padStart(2, '0')
}

/** 2026-08-03 (или 2026-08-03 14:30) → 03.08.2026 */
export function formatDate(text) {
  const match = ISO_DATE.exec(text || '')
  return match ? `${match[3]}.${match[2]}.${match[1]}` : ''
}

/** 2026-08-03 14:30[:15] → 03.08.2026 14:30 */
export function formatDateTime(text) {
  const date = formatDate(text)
  const time = /\d{2}:\d{2}/.exec((text || '').slice(10))
  return time ? `${date} ${time[0]}` : date
}

/** 2026-08-03 14:30 → 14:30 */
export function formatTime(text) {
  const time = /\d{2}:\d{2}/.exec((text || '').slice(10))
  return time ? time[0] : ''
}

/** Все даты ГГГГ-ММ-ДД внутри текста (например, журнала) → ДД.ММ.ГГГГ */
export function formatDatesInText(text) {
  return (text || '').replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, '$3.$2.$1')
}

export function toISODate(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

export function todayISO() {
  return toISODate(new Date())
}

/** ГГГГ-ММ-ДД → Date в местном времени (new Date('2026-08-03') дал бы UTC) */
export function parseISODate(text) {
  const match = ISO_DATE.exec(text || '')
  if (!match) return null
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
  return date.getMonth() === Number(match[2]) - 1 ? date : null
}

/** 42 дня (6 недель с понедельника) для календаря на месяц month (0–11). */
export function monthMatrix(year, month) {
  const first = new Date(year, month, 1)
  const shift = (first.getDay() + 6) % 7 // понедельник — 0
  const days = []
  for (let index = 0; index < 42; index += 1) {
    const date = new Date(year, month, 1 - shift + index)
    days.push({
      iso: toISODate(date),
      day: date.getDate(),
      inMonth: date.getMonth() === month,
    })
  }
  return days
}

/** «3 дня», «1 день», «5 дней» */
export function plural(number, one, few, many) {
  const n = Math.abs(number) % 100
  const last = n % 10
  if (n > 10 && n < 20) return many
  if (last === 1) return one
  if (last >= 2 && last <= 4) return few
  return many
}

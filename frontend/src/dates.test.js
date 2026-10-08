import { describe, expect, it } from 'vitest'
import {
  formatDate, formatDateTime, formatDatesInText, formatTime, monthMatrix,
  parseISODate, plural, toISODate,
} from './dates.js'

describe('даты', () => {
  it('показывает даты как ДД.ММ.ГГГГ', () => {
    expect(formatDate('2026-08-03')).toBe('03.08.2026')
    expect(formatDate('2026-08-03 14:30')).toBe('03.08.2026')
    expect(formatDate(null)).toBe('')
    expect(formatDateTime('2026-08-03 14:30:15')).toBe('03.08.2026 14:30')
    expect(formatDateTime('2026-08-03')).toBe('03.08.2026')
    expect(formatTime('2026-08-03 09:05')).toBe('09:05')
  })

  it('меняет даты внутри текста журнала', () => {
    expect(formatDatesInText('Годен до: 2026-10-01 → 2026-10-05')).toBe(
      'Годен до: 01.10.2026 → 05.10.2026',
    )
  })

  it('разбирает дату в местном времени', () => {
    const date = parseISODate('2026-03-01')
    expect([date.getFullYear(), date.getMonth(), date.getDate()]).toEqual([2026, 2, 1])
    expect(toISODate(date)).toBe('2026-03-01')
    expect(parseISODate('2026-02-30')).toBeNull()
    expect(parseISODate('abc')).toBeNull()
  })

  it('строит календарь с понедельника', () => {
    const days = monthMatrix(2026, 9) // октябрь 2026, 1-е — четверг
    expect(days).toHaveLength(42)
    expect(days[0]).toEqual({ iso: '2026-09-28', day: 28, inMonth: false })
    expect(days[3]).toEqual({ iso: '2026-10-01', day: 1, inMonth: true })
    expect(days.filter((day) => day.inMonth)).toHaveLength(31)
  })

  it('склоняет слова', () => {
    expect([1, 2, 5, 11, 21, 22].map((n) => plural(n, 'день', 'дня', 'дней'))).toEqual(
      ['день', 'дня', 'дней', 'дней', 'день', 'дня'],
    )
  })
})

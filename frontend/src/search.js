/** Поиск без учёта регистра и разницы между «е» и «ё». */
export function normalize(text) {
  return String(text ?? '').toLocaleLowerCase('ru').replaceAll('ё', 'е')
}

export function matches(text, query) {
  return normalize(text).includes(normalize(query).trim())
}

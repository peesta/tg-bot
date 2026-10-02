// Русские названия для значений из базы.

export const OPERATION_TITLES = {
  delivery: 'Заморозка',
  defrost: 'Разморозка',
  sale: 'Продажа',
  write_off: 'Списание',
}

export const ROLE_TITLES = {
  admin: 'Администратор',
  employee: 'Сотрудник',
}

export const CHANGE_TITLES = {
  user_added: 'Добавлен сотрудник',
  user_role: 'Изменена роль',
  user_access: 'Изменён доступ',
  account_changed: 'Учётная запись',
  product_added: 'Добавлен товар',
  product_edited: 'Изменён товар',
  product_deleted: 'Удалён товар',
  stock_replaced: 'Импорт из Google Таблицы',
  google_export: 'Экспорт в Google Таблицу',
  row_added: 'Добавлена строка',
  row_changed: 'Изменена строка',
  row_deleted: 'Удалена строка',
  backup_created: 'Создана копия базы',
  backup_restored: 'База восстановлена',
  backup_deleted: 'Удалена копия базы',
}

export const STATUS_TITLES = {
  fresh: 'Годно',
  today: 'Истекает сегодня',
  expired: 'Просрочено',
}

export function authorName(record) {
  if (record.full_name) return record.full_name
  if (record.created_by === 0 || record.user_id === null) return 'Система'
  return `№ ${record.created_by ?? record.user_id}`
}

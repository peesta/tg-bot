import {
  Boxes, DatabaseBackup, FileSpreadsheet, History, Hourglass, House,
  PackageOpen, ReceiptText, ScrollText, Sheet, Snowflake, Tag, Users,
} from 'lucide-vue-next'

// lines — подпись в узком меню сотрудника, по строкам.
export const WORK_NAV = [
  { to: '/', label: 'Главная', lines: ['Главная'], icon: House, exact: true },
  { to: '/expiring', label: 'Скоро испортится', lines: ['Скоро', 'испортится'], icon: Hourglass, badge: true },
  { to: '/defrost', label: 'Достать из заморозки', lines: ['Достать из', 'заморозки'], icon: PackageOpen },
  { to: '/delivery', label: 'Добавить заморозку', lines: ['Добавить', 'заморозку'], icon: Snowflake },
  { to: '/write-off', label: 'Списание и продажа', lines: ['Списание', 'и продажа'], icon: ReceiptText },
  { to: '/stock', label: 'Остатки', lines: ['Остатки'], icon: Boxes },
  { to: '/history', label: 'История списаний', lines: ['История', 'списаний'], icon: History },
]

export const ADMIN_NAV = [
  { to: '/admin/products', label: 'Товары', icon: Tag },
  { to: '/admin/users', label: 'Сотрудники', icon: Users },
  { to: '/admin/tables', label: 'База данных', icon: Sheet },
  { to: '/admin/logs', label: 'Логи', icon: ScrollText },
  { to: '/admin/google', label: 'Google Таблица', icon: FileSpreadsheet },
  { to: '/admin/backups', label: 'Резервные копии', icon: DatabaseBackup },
]

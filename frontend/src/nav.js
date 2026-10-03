import {
  DatabaseBackup, FileSpreadsheet, History, Hourglass, House, PackageOpen,
  Refrigerator, ScrollText, Sheet, ShoppingCart, Tag, Trash2, Truck, Users,
} from 'lucide-vue-next'

// lines — подпись в узком меню сотрудника на планшете, по строкам.
export const WORK_NAV = [
  { to: '/', label: 'Главная', lines: ['Главная'], icon: House, exact: true },
  { to: '/expiring', label: 'Скоро испортится', lines: ['Скоро', 'испортится'], icon: Hourglass, badge: true },
  { to: '/defrost', label: 'Разморозить', lines: ['Разморозить'], icon: PackageOpen },
  { to: '/delivery', label: 'Поставка товара', lines: ['Поставка', 'товара'], icon: Truck },
  { to: '/write-off', label: 'Списание', lines: ['Списание'], icon: Trash2 },
  { to: '/sale', label: 'Продажа', lines: ['Продажа'], icon: ShoppingCart },
  { to: '/stock', label: 'Холодильник', lines: ['Холодильник'], icon: Refrigerator },
  { to: '/history', label: 'История операций', lines: ['История', 'операций'], icon: History },
]

export const ADMIN_NAV = [
  { to: '/admin/products', label: 'Товары', icon: Tag },
  { to: '/admin/users', label: 'Сотрудники', icon: Users },
  { to: '/admin/tables', label: 'База данных', icon: Sheet },
  { to: '/admin/logs', label: 'Логи', icon: ScrollText },
  { to: '/admin/google', label: 'Google Таблица', icon: FileSpreadsheet },
  { to: '/admin/backups', label: 'Резервные копии', icon: DatabaseBackup },
]

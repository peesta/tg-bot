from aiogram.fsm.state import State, StatesGroup


class DefrostStates(StatesGroup):
    search = State()
    quantity = State()


class DeliveryStates(StatesGroup):
    search = State()
    quantity = State()


class WriteOffStates(StatesGroup):
    search = State()
    reason = State()
    quantity = State()


class ProductStates(StatesGroup):
    search = State()
    name = State()
    storage_time = State()
    edit_storage_time = State()
    rename = State()


class UserStates(StatesGroup):
    telegram_id = State()
    full_name = State()
    role = State()


class NotifyStates(StatesGroup):
    time = State()

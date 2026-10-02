from aiogram import Router

from telegram.handlers import (
    common, defrost, delivery, expiring, history, menu, products, settings,
    stock, users, write_off,
)
from telegram.middlewares import (
    AccessMiddleware, ResetStateMiddleware, SafeCallbackAnswerMiddleware,
)


router = Router()

router.message.outer_middleware(AccessMiddleware())
router.callback_query.outer_middleware(AccessMiddleware())
router.callback_query.middleware(SafeCallbackAnswerMiddleware())
router.callback_query.middleware(ResetStateMiddleware())

router.include_routers(
    menu.router,
    defrost.router,
    delivery.router,
    expiring.router,
    write_off.router,
    stock.router,
    history.router,
    settings.router,
    products.router,
    users.router,
    common.router,  # последним: необработанные сообщения, кнопки и ошибки
)

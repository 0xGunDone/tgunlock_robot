from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup


MAIN_MENU_BUTTONS = [
    "💰 Баланс",
    "🧦 Мои прокси",
    "🖥 Устройства",
    "⭐ Пополнить",
    "🤝 Рефералы",
    "❓ Помощь",
]

ADMIN_MENU_BUTTONS = [
    "📊 Статистика",
    "👤 Пользователи",
    "🧦 Прокси",
    "💳 Платежи",
    "🔗 Рефералы",
    "⚙️ Настройки",
    "📦 Экспорт",
    "📣 Рассылка",
    "⬅️ Назад",
]


def main_menu_kb() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=btn)] for btn in MAIN_MENU_BUTTONS]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu_kb() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=btn)] for btn in ADMIN_MENU_BUTTONS]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def proxy_actions_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Купить новый прокси", callback_data="proxy:buy")],
        [InlineKeyboardButton(text="Обновить пароль", callback_data="proxy:passwd")],
        [InlineKeyboardButton(text="Удалить прокси", callback_data="proxy:delete")],
        [InlineKeyboardButton(text="Показать список", callback_data="proxy:list")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxies_select_kb(action: str, proxies: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        label = f"{p['login']} ({p['ip']}:{p['port']})"
        buttons.append([
            InlineKeyboardButton(text=label, callback_data=f"proxy:{action}:{p['id']}")
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def broadcast_filters_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Всем", callback_data="broadcast:all")],
        [InlineKeyboardButton(text="Активные 7д", callback_data="broadcast:active7")],
        [InlineKeyboardButton(text="С активными прокси", callback_data="broadcast:active_proxies")],
        [InlineKeyboardButton(text="Баланс > 0", callback_data="broadcast:balance_pos")],
        [InlineKeyboardButton(text="Отмена", callback_data="broadcast:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_inline_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="💰 Баланс", callback_data="menu:balance"),
            InlineKeyboardButton(text="🧦 Мои прокси", callback_data="menu:proxies"),
        ],
        [
            InlineKeyboardButton(text="🖥 Устройства", callback_data="menu:devices"),
            InlineKeyboardButton(text="⭐ Пополнить", callback_data="menu:topup"),
        ],
        [
            InlineKeyboardButton(text="🤝 Рефералы", callback_data="menu:referrals"),
            InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_menu_inline_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
            InlineKeyboardButton(text="👤 Пользователи", callback_data="admin:users"),
        ],
        [
            InlineKeyboardButton(text="🧦 Прокси", callback_data="admin:proxies"),
            InlineKeyboardButton(text="💳 Платежи", callback_data="admin:payments"),
        ],
        [
            InlineKeyboardButton(text="🔗 Рефералы", callback_data="admin:referrals"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin:settings"),
        ],
        [
            InlineKeyboardButton(text="📦 Экспорт", callback_data="admin:export"),
            InlineKeyboardButton(text="📣 Рассылка", callback_data="admin:broadcast"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxy_actions_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Купить новый прокси", callback_data="proxy:buy")],
        [InlineKeyboardButton(text="Обновить пароль", callback_data="proxy:passwd")],
        [InlineKeyboardButton(text="Удалить прокси", callback_data="proxy:delete")],
        [InlineKeyboardButton(text="Показать список", callback_data="proxy:list")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
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

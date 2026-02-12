from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_inline_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🧦 Мои прокси", callback_data="menu:proxies"),
            InlineKeyboardButton(text="➕ Купить прокси", callback_data="proxy:buy"),
        ],
        [
            InlineKeyboardButton(text="⭐ Пополнить", callback_data="menu:topup"),
            InlineKeyboardButton(text="🤝 Рефералы", callback_data="menu:referrals"),
        ],
        [
            InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help"),
        ],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="🛠 Админка", callback_data="menu:admin")])
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


def admin_referrals_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Создать ссылку", callback_data="admin:ref_create")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_user_actions_kb(user_id: int, blocked: bool) -> InlineKeyboardMarkup:
    block_label = "Разблок" if blocked else "Блок"
    buttons = [
        [
            InlineKeyboardButton(text="+10", callback_data=f"admin_user:delta:{user_id}:10"),
            InlineKeyboardButton(text="+100", callback_data=f"admin_user:delta:{user_id}:100"),
        ],
        [
            InlineKeyboardButton(text="-10", callback_data=f"admin_user:delta:{user_id}:-10"),
            InlineKeyboardButton(text="-100", callback_data=f"admin_user:delta:{user_id}:-100"),
        ],
        [
            InlineKeyboardButton(text="Свой баланс", callback_data=f"admin_user:custom:{user_id}"),
            InlineKeyboardButton(text="Обновить", callback_data=f"admin_user:refresh:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=block_label, callback_data=f"admin_user:block:{user_id}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"admin_user:delete:{user_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_settings_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="Цена создания", callback_data="admin_settings:proxy_create_price"),
            InlineKeyboardButton(text="Цена в день", callback_data="admin_settings:proxy_day_price"),
        ],
        [
            InlineKeyboardButton(text="Free credit", callback_data="admin_settings:free_credit"),
            InlineKeyboardButton(text="Stars rate", callback_data="admin_settings:stars_rate"),
        ],
        [
            InlineKeyboardButton(text="Бонус пригл.", callback_data="admin_settings:ref_bonus_inviter"),
            InlineKeyboardButton(text="Бонус приглаш.", callback_data="admin_settings:ref_bonus_invited"),
        ],
        [
            InlineKeyboardButton(text="Лимит прокси", callback_data="admin_settings:max_active_proxies"),
        ],
        [
            InlineKeyboardButton(text="Referral on/off", callback_data="admin_settings:referral_enabled"),
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxies_list_kb(proxies: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        buttons.append(
            [
                InlineKeyboardButton(text=p["login"], callback_data=f"proxy:show:{p['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"proxy:delete:{p['id']}"),
            ]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxy_detail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:proxies")]]
    )


def proxies_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Купить прокси", callback_data="proxy:buy")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
        ]
    )


def proxy_delete_confirm_kb(proxy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"proxy:delete_confirm:{proxy_id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="menu:proxies"),
            ]
        ]
    )


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

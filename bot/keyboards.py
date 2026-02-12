from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_inline_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(text="🛰 Мои прокси", callback_data="menu:proxies"),
            InlineKeyboardButton(text="➕ Купить прокси", callback_data="proxy:buy"),
        ],
        [
            InlineKeyboardButton(text="⭐ Пополнить", callback_data="menu:topup"),
            InlineKeyboardButton(text="🤝 Рефералы", callback_data="menu:referrals"),
        ],
        [
            InlineKeyboardButton(text="🔍 Проверить", callback_data="menu:check"),
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
            InlineKeyboardButton(text="🛰 Прокси", callback_data="admin:proxies"),
            InlineKeyboardButton(text="💳 Платежи", callback_data="admin:payments"),
        ],
        [
            InlineKeyboardButton(text="🔗 Рефералы", callback_data="admin:referrals"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin:settings"),
        ],
        [
            InlineKeyboardButton(text="📡 MTProxy", callback_data="admin:mtproxy"),
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
            InlineKeyboardButton(text="+500", callback_data=f"admin_user:delta:{user_id}:500"),
        ],
        [
            InlineKeyboardButton(text="-10", callback_data=f"admin_user:delta:{user_id}:-10"),
            InlineKeyboardButton(text="-100", callback_data=f"admin_user:delta:{user_id}:-100"),
            InlineKeyboardButton(text="-500", callback_data=f"admin_user:delta:{user_id}:-500"),
        ],
        [
            InlineKeyboardButton(text="Свой баланс", callback_data=f"admin_user:custom:{user_id}"),
            InlineKeyboardButton(text="Обнулить", callback_data=f"admin_user:reset:{user_id}"),
        ],
        [
            InlineKeyboardButton(text=block_label, callback_data=f"admin_user:block:{user_id}"),
            InlineKeyboardButton(text="Удалить", callback_data=f"admin_user:delete:{user_id}"),
        ],
        [
            InlineKeyboardButton(text="Прокси", callback_data=f"admin_user:proxies:{user_id}"),
            InlineKeyboardButton(text="Вкл все", callback_data=f"admin_user:enable_all:{user_id}"),
            InlineKeyboardButton(text="Выкл все", callback_data=f"admin_user:disable_all:{user_id}"),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _bool_label(value: str | None) -> str:
    return "Вкл" if (value or "0") == "1" else "Выкл"


def admin_settings_kb(settings: dict[str, str]) -> InlineKeyboardMarkup:
    def val(key: str, default: str = "") -> str:
        return settings.get(key, default)

    buttons = [
        [
            InlineKeyboardButton(
                text=f"Цена создания: {val('proxy_create_price', '0')} ₽",
                callback_data="admin_settings_edit:proxy_create_price",
            ),
            InlineKeyboardButton(
                text=f"Цена/день: {val('proxy_day_price', '0')} ₽",
                callback_data="admin_settings_edit:proxy_day_price",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"Free credit: {val('free_credit', '0')} ₽",
                callback_data="admin_settings_edit:free_credit",
            ),
            InlineKeyboardButton(
                text=f"Лимит прокси: {val('max_active_proxies', '0')}",
                callback_data="admin_settings_edit:max_active_proxies",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"Курс Stars: {val('stars_rate', '1')} ₽/⭐",
                callback_data="admin_settings_edit:stars_rate",
            ),
            InlineKeyboardButton(
                text="URL покупки Stars",
                callback_data="admin_settings_edit:stars_buy_url",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"Подсказка Stars: {_bool_label(val('stars_buy_hint_enabled', '0'))}",
                callback_data="admin_settings_toggle:stars_buy_hint_enabled",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"Рефералка: {_bool_label(val('referral_enabled', '1'))}",
                callback_data="admin_settings_toggle:referral_enabled",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"Бонус пригл.: {val('ref_bonus_inviter', '0')} ₽",
                callback_data="admin_settings_edit:ref_bonus_inviter",
            ),
            InlineKeyboardButton(
                text=f"Бонус приглаш.: {val('ref_bonus_invited', '0')} ₽",
                callback_data="admin_settings_edit:ref_bonus_invited",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"MTProto: {_bool_label(val('mtproto_enabled', '1'))}",
                callback_data="admin_settings_toggle:mtproto_enabled",
            ),
        ],
        [
            InlineKeyboardButton(
                text=f"MTProto host: {val('mtproto_host', '') or '—'}",
                callback_data="admin_settings_edit:mtproto_host",
            ),
            InlineKeyboardButton(
                text=f"MTProto port: {val('mtproto_port', '9443')}",
                callback_data="admin_settings_edit:mtproto_port",
            ),
        ],
        [
            InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def mtproxy_status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:mtproxy_refresh")],
            [InlineKeyboardButton(text="📄 Логи", callback_data="admin:mtproxy_logs")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin")],
        ]
    )


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Как включить/выключить", callback_data="help:toggle")],
            [InlineKeyboardButton(text="Не подключается", callback_data="help:fail")],
            [InlineKeyboardButton(text="Как оплатить", callback_data="help:pay")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")],
        ]
    )


def help_detail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:help")],
        ]
    )


def admin_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Поиск", callback_data="admin_users:search")],
            [
                InlineKeyboardButton(text="С активными прокси", callback_data="admin_users:active_proxies"),
                InlineKeyboardButton(text="Баланс = 0", callback_data="admin_users:zero_balance"),
            ],
            [
                InlineKeyboardButton(text="Есть отключённые", callback_data="admin_users:disabled_proxies"),
                InlineKeyboardButton(text="Новые 24ч", callback_data="admin_users:new24"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin")],
        ]
    )


def admin_users_list_kb(users: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for u in users:
        label = f"{u['label']}"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"admin_user:open:{u['id']}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:users")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_export_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Users", callback_data="admin_export:users"),
                InlineKeyboardButton(text="Users balances", callback_data="admin_export:users_balances"),
            ],
            [
                InlineKeyboardButton(text="Proxies", callback_data="admin_export:proxies"),
                InlineKeyboardButton(text="Payments", callback_data="admin_export:payments"),
            ],
            [
                InlineKeyboardButton(text="Referrals", callback_data="admin_export:referrals"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:admin")],
        ]
    )


def admin_user_proxies_kb(proxies: list[dict], user_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        label = f"{p['login']} ({p['status']})"
        buttons.append(
            [
                InlineKeyboardButton(text=label, callback_data=f"admin_proxy:show:{p['id']}"),
                InlineKeyboardButton(text="🗑", callback_data=f"admin_proxy:delete:{p['id']}"),
            ]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_user:open:{user_id}")])
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


def topup_quick_kb() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="📅 На 7 дней", callback_data="topup:days:7")],
        [
            InlineKeyboardButton(text="100 ₽", callback_data="topup:amount:100"),
            InlineKeyboardButton(text="300 ₽", callback_data="topup:amount:300"),
            InlineKeyboardButton(text="500 ₽", callback_data="topup:amount:500"),
        ],
        [
            InlineKeyboardButton(text="1000 ₽", callback_data="topup:amount:1000"),
            InlineKeyboardButton(text="2000 ₽", callback_data="topup:amount:2000"),
            InlineKeyboardButton(text="5000 ₽", callback_data="topup:amount:5000"),
        ],
        [InlineKeyboardButton(text="✍️ Ввести сумму", callback_data="topup:custom")],
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

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

STYLE_SUCCESS = "success"
STYLE_PRIMARY = STYLE_SUCCESS
STYLE_DANGER = "danger"


def _btn(
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
) -> InlineKeyboardButton:
    data: dict = {"text": text}
    if style is None:
        style = STYLE_SUCCESS
    if callback_data is not None:
        data["callback_data"] = callback_data
    if url is not None:
        data["url"] = url
    if style:
        data["style"] = style
    return InlineKeyboardButton(**data)


def main_menu_inline_kb(is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [
            _btn("🛰 Мои прокси", callback_data="menu:proxies", style=STYLE_PRIMARY),
            _btn("➕ Купить прокси", callback_data="proxy:buy", style=STYLE_SUCCESS),
        ],
        [
            _btn("⭐ Пополнить", callback_data="menu:topup", style=STYLE_SUCCESS),
            _btn("🤝 Рефералы", callback_data="menu:referrals", style=STYLE_PRIMARY),
        ],
        [
            _btn("🔍 Проверить", callback_data="menu:check", style=STYLE_PRIMARY),
            _btn("💬 Поддержка", callback_data="menu:support", style=STYLE_PRIMARY),
        ],
        [
            _btn("❓ Помощь", callback_data="menu:help", style=STYLE_PRIMARY),
        ],
    ]
    if is_admin:
        buttons.append([_btn("🛠 Админка", callback_data="menu:admin", style=STYLE_PRIMARY)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER)]]
    )


def support_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("❌ Отмена", callback_data="menu:main", style=STYLE_DANGER)]]
    )


def support_admin_reply_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("❌ Отмена", callback_data="support:reply_cancel", style=STYLE_DANGER)]]
    )


def support_admin_ticket_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("Ответить", callback_data=f"support:reply:{ticket_id}", style=STYLE_SUCCESS),
                _btn("Закрыть", callback_data=f"support:close:{ticket_id}", style=STYLE_DANGER),
            ]
        ]
    )


def admin_menu_inline_kb() -> InlineKeyboardMarkup:
    buttons = [
        [
            _btn("📊 Статистика", callback_data="admin:stats", style=STYLE_PRIMARY),
            _btn("👤 Пользователи", callback_data="admin:users", style=STYLE_PRIMARY),
        ],
        [
            _btn("🛰 Прокси", callback_data="admin:proxies", style=STYLE_PRIMARY),
            _btn("💳 Платежи", callback_data="admin:payments", style=STYLE_PRIMARY),
        ],
        [
            _btn("🔗 Рефералы", callback_data="admin:referrals", style=STYLE_PRIMARY),
            _btn("⚙️ Настройки", callback_data="admin:settings", style=STYLE_PRIMARY),
        ],
        [
            _btn("📡 MTProxy", callback_data="admin:mtproxy", style=STYLE_PRIMARY),
            _btn("💳 FreeKassa", callback_data="admin:freekassa", style=STYLE_PRIMARY),
        ],
        [
            _btn("📦 Экспорт", callback_data="admin:export", style=STYLE_PRIMARY),
            _btn("📣 Рассылка", callback_data="admin:broadcast", style=STYLE_PRIMARY),
        ],
        [
            _btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_referrals_kb() -> InlineKeyboardMarkup:
    buttons = [
        [_btn("Создать ссылку", callback_data="admin:ref_create", style=STYLE_SUCCESS)],
        [_btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_referrals_list_kb(codes: list[str]) -> InlineKeyboardMarkup:
    buttons = []
    for code in codes:
        buttons.append([_btn(f"🗑 Удалить {code}", callback_data=f"admin_ref_del:{code}", style=STYLE_DANGER)])
    buttons.append([_btn("Создать ссылку", callback_data="admin:ref_create", style=STYLE_SUCCESS)])
    buttons.append([_btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_ref_delete_confirm_kb(code: str) -> InlineKeyboardMarkup:
    buttons = [
        [_btn("✅ Удалить", callback_data=f"admin_ref_del_confirm:{code}", style=STYLE_DANGER)],
        [_btn("❌ Отмена", callback_data="admin:referrals", style=STYLE_DANGER)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_user_actions_kb(user_id: int, blocked: bool) -> InlineKeyboardMarkup:
    block_label = "Разблок" if blocked else "Блок"
    block_style = STYLE_SUCCESS if blocked else STYLE_DANGER
    buttons = [
        [
            _btn("+10", callback_data=f"admin_user:delta:{user_id}:10", style=STYLE_SUCCESS),
            _btn("+100", callback_data=f"admin_user:delta:{user_id}:100", style=STYLE_SUCCESS),
            _btn("+500", callback_data=f"admin_user:delta:{user_id}:500", style=STYLE_SUCCESS),
        ],
        [
            _btn("-10", callback_data=f"admin_user:delta:{user_id}:-10", style=STYLE_DANGER),
            _btn("-100", callback_data=f"admin_user:delta:{user_id}:-100", style=STYLE_DANGER),
            _btn("-500", callback_data=f"admin_user:delta:{user_id}:-500", style=STYLE_DANGER),
        ],
        [
            _btn("Свой баланс", callback_data=f"admin_user:custom:{user_id}", style=STYLE_PRIMARY),
            _btn("Обнулить", callback_data=f"admin_user:reset:{user_id}", style=STYLE_DANGER),
        ],
        [
            _btn(block_label, callback_data=f"admin_user:block:{user_id}", style=block_style),
            _btn("Удалить", callback_data=f"admin_user:delete:{user_id}", style=STYLE_DANGER),
        ],
        [
            _btn("Прокси", callback_data=f"admin_user:proxies:{user_id}", style=STYLE_PRIMARY),
            _btn("Вкл все", callback_data=f"admin_user:enable_all:{user_id}", style=STYLE_SUCCESS),
            _btn("Выкл все", callback_data=f"admin_user:disable_all:{user_id}", style=STYLE_DANGER),
        ],
        [
            _btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _bool_label(value: str | None) -> str:
    return "Вкл" if (value or "0") == "1" else "Выкл"


def admin_settings_kb(settings: dict[str, str]) -> InlineKeyboardMarkup:
    def val(key: str, default: str = "") -> str:
        return settings.get(key, default)

    def toggle_style(key: str, default: str = "0") -> str:
        return STYLE_SUCCESS if val(key, default) == "1" else STYLE_DANGER

    buttons = [
        [
            _btn(
                f"Цена создания: {val('proxy_create_price', '0')} ₽",
                callback_data="admin_settings_edit:proxy_create_price",
                style=STYLE_PRIMARY,
            ),
            _btn(
                f"Цена/день: {val('proxy_day_price', '0')} ₽",
                callback_data="admin_settings_edit:proxy_day_price",
                style=STYLE_PRIMARY,
            ),
        ],
        [
            _btn(
                f"Free credit: {val('free_credit', '0')} ₽",
                callback_data="admin_settings_edit:free_credit",
                style=STYLE_PRIMARY,
            ),
            _btn(
                f"Лимит прокси: {val('max_active_proxies', '0')}",
                callback_data="admin_settings_edit:max_active_proxies",
                style=STYLE_PRIMARY,
            ),
        ],
        [
            _btn(
                f"Курс Stars: {val('stars_rate', '1')} ₽/⭐",
                callback_data="admin_settings_edit:stars_rate",
                style=STYLE_PRIMARY,
            ),
            _btn(
                f"Stars: {_bool_label(val('stars_enabled', '1'))}",
                callback_data="admin_settings_toggle:stars_enabled",
                style=toggle_style("stars_enabled", "1"),
            ),
        ],
        [
            _btn(
                "URL покупки Stars",
                callback_data="admin_settings_edit:stars_buy_url",
                style=STYLE_PRIMARY,
            ),
            _btn(
                f"FreeKassa: {_bool_label(val('freekassa_enabled', '0'))}",
                callback_data="admin_settings_toggle:freekassa_enabled",
                style=toggle_style("freekassa_enabled", "0"),
            ),
        ],
        [
            _btn(
                f"Подсказка Stars: {_bool_label(val('stars_buy_hint_enabled', '0'))}",
                callback_data="admin_settings_toggle:stars_buy_hint_enabled",
                style=toggle_style("stars_buy_hint_enabled", "0"),
            ),
        ],
        [
            _btn(
                f"Фон: {_bool_label(val('bg_enabled', '1'))}",
                callback_data="admin_settings_toggle:bg_enabled",
                style=toggle_style("bg_enabled", "1"),
            ),
            _btn(
                "Сменить фон",
                callback_data="admin_settings_edit:bg_image",
                style=STYLE_PRIMARY,
            ),
        ],
        [
            _btn(
                f"Оферта: {_bool_label(val('offer_enabled', '1'))}",
                callback_data="admin_settings_toggle:offer_enabled",
                style=toggle_style("offer_enabled", "1"),
            ),
            _btn(
                f"Политика: {_bool_label(val('policy_enabled', '1'))}",
                callback_data="admin_settings_toggle:policy_enabled",
                style=toggle_style("policy_enabled", "1"),
            ),
        ],
        [
            _btn(
                "URL оферты",
                callback_data="admin_settings_edit:offer_url",
                style=STYLE_PRIMARY,
            ),
            _btn(
                "URL политики",
                callback_data="admin_settings_edit:policy_url",
                style=STYLE_PRIMARY,
            ),
        ],
        [
            _btn(
                f"FK СБП: {_bool_label(val('freekassa_method_44_enabled', '1'))}",
                callback_data="admin_settings_toggle:freekassa_method_44_enabled",
                style=toggle_style("freekassa_method_44_enabled", "1"),
            ),
            _btn(
                f"FK Карта: {_bool_label(val('freekassa_method_36_enabled', '1'))}",
                callback_data="admin_settings_toggle:freekassa_method_36_enabled",
                style=toggle_style("freekassa_method_36_enabled", "1"),
            ),
        ],
        [
            _btn(
                f"FK SberPay: {_bool_label(val('freekassa_method_43_enabled', '1'))}",
                callback_data="admin_settings_toggle:freekassa_method_43_enabled",
                style=toggle_style("freekassa_method_43_enabled", "1"),
            ),
        ],
        [
            _btn(
                f"Рефералка: {_bool_label(val('referral_enabled', '1'))}",
                callback_data="admin_settings_toggle:referral_enabled",
                style=toggle_style("referral_enabled", "1"),
            ),
        ],
        [
            _btn(
                f"Бонус пригл.: {val('ref_bonus_inviter', '0')} ₽",
                callback_data="admin_settings_edit:ref_bonus_inviter",
                style=STYLE_PRIMARY,
            ),
            _btn(
                f"Бонус приглаш.: {val('ref_bonus_invited', '0')} ₽",
                callback_data="admin_settings_edit:ref_bonus_invited",
                style=STYLE_PRIMARY,
            ),
        ],
        [
            _btn(
                f"MTProto: {_bool_label(val('mtproto_enabled', '1'))}",
                callback_data="admin_settings_toggle:mtproto_enabled",
                style=toggle_style("mtproto_enabled", "1"),
            ),
        ],
        [
            _btn(
                f"MTProto host: {val('mtproto_host', '') or '—'}",
                callback_data="admin_settings_edit:mtproto_host",
                style=STYLE_PRIMARY,
            ),
            _btn(
                f"MTProto port: {val('mtproto_port', '9443')}",
                callback_data="admin_settings_edit:mtproto_port",
                style=STYLE_PRIMARY,
            ),
        ],
        [
            _btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def mtproxy_status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🔄 Обновить", callback_data="admin:mtproxy_refresh", style=STYLE_PRIMARY)],
            [_btn("📄 Логи", callback_data="admin:mtproxy_logs", style=STYLE_PRIMARY)],
            [_btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER)],
        ]
    )


def freekassa_status_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🔄 Обновить", callback_data="admin:freekassa_refresh", style=STYLE_PRIMARY)],
            [_btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER)],
        ]
    )


def help_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("Как включить/выключить", callback_data="help:toggle", style=STYLE_PRIMARY)],
            [_btn("Не подключается", callback_data="help:fail", style=STYLE_PRIMARY)],
            [_btn("Как оплатить", callback_data="help:pay", style=STYLE_PRIMARY)],
            [_btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER)],
        ]
    )


def help_detail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⬅️ Назад", callback_data="menu:help", style=STYLE_DANGER)],
        ]
    )


def admin_users_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🔎 Поиск", callback_data="admin_users:search", style=STYLE_PRIMARY)],
            [
                _btn("С активными прокси", callback_data="admin_users:active_proxies", style=STYLE_PRIMARY),
                _btn("Баланс = 0", callback_data="admin_users:zero_balance", style=STYLE_PRIMARY),
            ],
            [
                _btn("Есть отключённые", callback_data="admin_users:disabled_proxies", style=STYLE_PRIMARY),
                _btn("Новые 24ч", callback_data="admin_users:new24", style=STYLE_PRIMARY),
            ],
            [_btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER)],
        ]
    )


def admin_users_list_kb(users: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for u in users:
        label = f"{u['label']}"
        buttons.append([_btn(label, callback_data=f"admin_user:open:{u['id']}", style=STYLE_PRIMARY)])
    buttons.append([_btn("⬅️ Назад", callback_data="admin:users", style=STYLE_DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_export_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("Users", callback_data="admin_export:users", style=STYLE_PRIMARY),
                _btn("Users balances", callback_data="admin_export:users_balances", style=STYLE_PRIMARY),
            ],
            [
                _btn("Proxies", callback_data="admin_export:proxies", style=STYLE_PRIMARY),
                _btn("Payments", callback_data="admin_export:payments", style=STYLE_PRIMARY),
            ],
            [
                _btn("Referrals", callback_data="admin_export:referrals", style=STYLE_PRIMARY),
            ],
            [_btn("⬅️ Назад", callback_data="menu:admin", style=STYLE_DANGER)],
        ]
    )


def admin_user_proxies_kb(proxies: list[dict], user_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        label = f"{p['login']} ({p['status']})"
        buttons.append(
            [
                _btn(label, callback_data=f"admin_proxy:show:{p['id']}", style=STYLE_PRIMARY),
                _btn("🗑", callback_data=f"admin_proxy:delete:{p['id']}", style=STYLE_DANGER),
            ]
        )
    buttons.append([_btn("⬅️ Назад", callback_data=f"admin_user:open:{user_id}", style=STYLE_DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxies_list_kb(proxies: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        buttons.append(
            [
                _btn(p["login"], callback_data=f"proxy:show:{p['id']}", style=STYLE_PRIMARY),
                _btn("🗑", callback_data=f"proxy:delete:{p['id']}", style=STYLE_DANGER),
            ]
        )
    buttons.append([_btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxy_detail_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_btn("⬅️ Назад", callback_data="menu:proxies", style=STYLE_DANGER)]]
    )


def proxies_empty_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("➕ Купить прокси", callback_data="proxy:buy", style=STYLE_SUCCESS)],
            [_btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER)],
        ]
    )


def proxy_delete_confirm_kb(proxy_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("✅ Да, удалить", callback_data=f"proxy:delete_confirm:{proxy_id}", style=STYLE_DANGER),
                _btn("❌ Отмена", callback_data="menu:proxies", style=STYLE_DANGER),
            ]
        ]
    )


def topup_method_kb(stars_enabled: bool, freekassa_enabled: bool) -> InlineKeyboardMarkup:
    buttons = []
    if stars_enabled:
        buttons.append([_btn("⭐ Stars", callback_data="topup:method:stars", style=STYLE_PRIMARY)])
    if freekassa_enabled:
        buttons.append([_btn("💳 FreeKassa", callback_data="topup:method:freekassa", style=STYLE_PRIMARY)])
    buttons.append([_btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def freekassa_method_kb(
    amount: int,
    fee_percent: float = 12.5,
    enable_44: bool = True,
    enable_36: bool = True,
    enable_43: bool = True,
) -> InlineKeyboardMarkup:
    total = amount * (1 + fee_percent / 100)
    total_str = f"{total:.2f}".rstrip("0").rstrip(".")
    buttons = []
    if enable_44:
        buttons.append(
            [_btn(f"СБП QR (НСПК) — {total_str} ₽", callback_data="fk:pay:44", style=STYLE_PRIMARY)]
        )
    if enable_36:
        buttons.append(
            [_btn(f"Банковская карта РФ — {total_str} ₽", callback_data="fk:pay:36", style=STYLE_PRIMARY)]
        )
    if enable_43:
        buttons.append(
            [_btn(f"СберPay — {total_str} ₽", callback_data="fk:pay:43", style=STYLE_PRIMARY)]
        )
    buttons.append([_btn("⬅️ Назад", callback_data="fk:amounts_back", style=STYLE_DANGER)])
    buttons.append([_btn("⬅️ В главное меню", callback_data="menu:main", style=STYLE_DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def freekassa_amount_kb(fee_percent: float = 12.5) -> InlineKeyboardMarkup:
    def label(amount: int) -> str:
        fee = amount * (1 + fee_percent / 100)
        fee_str = f"{fee:.2f}".rstrip("0").rstrip(".")
        return f"{amount} ₽ ({fee_str} ₽)"

    buttons = [
        [_btn("📅 На 7 дней", callback_data="topup:days:freekassa:7", style=STYLE_PRIMARY)],
        [
            _btn(label(100), callback_data="topup:amount:freekassa:100", style=STYLE_SUCCESS),
            _btn(label(300), callback_data="topup:amount:freekassa:300", style=STYLE_SUCCESS),
            _btn(label(500), callback_data="topup:amount:freekassa:500", style=STYLE_SUCCESS),
        ],
        [
            _btn(label(1000), callback_data="topup:amount:freekassa:1000", style=STYLE_SUCCESS),
            _btn(label(2000), callback_data="topup:amount:freekassa:2000", style=STYLE_SUCCESS),
            _btn(label(5000), callback_data="topup:amount:freekassa:5000", style=STYLE_SUCCESS),
        ],
        [_btn("✍️ Ввести сумму", callback_data="topup:custom:freekassa", style=STYLE_PRIMARY)],
        [_btn("⬅️ К способам оплаты", callback_data="menu:topup", style=STYLE_DANGER)],
        [_btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def topup_quick_kb(method: str, show_method_back: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [_btn("📅 На 7 дней", callback_data=f"topup:days:{method}:7", style=STYLE_PRIMARY)],
        [
            _btn("100 ₽", callback_data=f"topup:amount:{method}:100", style=STYLE_SUCCESS),
            _btn("300 ₽", callback_data=f"topup:amount:{method}:300", style=STYLE_SUCCESS),
            _btn("500 ₽", callback_data=f"topup:amount:{method}:500", style=STYLE_SUCCESS),
        ],
        [
            _btn("1000 ₽", callback_data=f"topup:amount:{method}:1000", style=STYLE_SUCCESS),
            _btn("2000 ₽", callback_data=f"topup:amount:{method}:2000", style=STYLE_SUCCESS),
            _btn("5000 ₽", callback_data=f"topup:amount:{method}:5000", style=STYLE_SUCCESS),
        ],
        [_btn("✍️ Ввести сумму", callback_data=f"topup:custom:{method}", style=STYLE_PRIMARY)],
    ]
    if show_method_back:
        buttons.append([_btn("⬅️ К способам оплаты", callback_data="menu:topup", style=STYLE_DANGER)])
    buttons.append([_btn("⬅️ Назад", callback_data="menu:main", style=STYLE_DANGER)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def freekassa_pay_kb(payment_id: int, pay_url: str) -> InlineKeyboardMarkup:
    buttons = [
        [_btn("✅ Оплатить", url=pay_url, style=STYLE_SUCCESS)],
        [_btn("❌ Отменить", callback_data=f"fk:cancel:{payment_id}", style=STYLE_DANGER)],
        [_btn("⬅️ Назад", callback_data="menu:topup", style=STYLE_DANGER)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def proxies_select_kb(action: str, proxies: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for p in proxies:
        label = f"{p['login']} ({p['ip']}:{p['port']})"
        buttons.append([
            _btn(label, callback_data=f"proxy:{action}:{p['id']}", style=STYLE_PRIMARY)
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def broadcast_filters_kb() -> InlineKeyboardMarkup:
    buttons = [
        [_btn("Всем", callback_data="broadcast:all", style=STYLE_PRIMARY)],
        [_btn("Активные 7д", callback_data="broadcast:active7", style=STYLE_PRIMARY)],
        [_btn("С активными прокси", callback_data="broadcast:active_proxies", style=STYLE_PRIMARY)],
        [_btn("Баланс > 0", callback_data="broadcast:balance_pos", style=STYLE_PRIMARY)],
        [_btn("Отмена", callback_data="broadcast:cancel", style=STYLE_DANGER)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

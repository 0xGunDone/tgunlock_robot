from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class UserStates(StatesGroup):
    waiting_topup_amount = State()


class AdminStates(StatesGroup):
    waiting_user_query = State()
    waiting_user_action = State()
    waiting_balance_delta = State()
    waiting_proxy_user = State()
    waiting_setting_input = State()
    waiting_broadcast_text = State()
    waiting_referral_link = State()
    ref_code = State()
    ref_owner = State()
    ref_bonus_inviter = State()
    ref_bonus_invited = State()
    ref_limit_total = State()
    ref_limit_per_user = State()

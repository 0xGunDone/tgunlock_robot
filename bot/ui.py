from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardMarkup
from bot import dao

_BG_PATH = Path(__file__).resolve().parents[1] / "bg.jpg"
_CAPTION_LIMIT = 1000


def clip_caption(text: str, limit: int = _CAPTION_LIMIT) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def get_bg_file() -> FSInputFile | None:
    if _BG_PATH.exists():
        return FSInputFile(str(_BG_PATH))
    return None


async def send_or_edit_bg_message(
    bot: Bot,
    chat_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
    message_id: int | None = None,
) -> int:
    caption = clip_caption(text)
    bg = get_bg_file()

    if message_id and bg:
        try:
            await bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return message_id
        except Exception as exc:
            if "message is not modified" in str(exc).lower():
                return message_id
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
            except Exception:
                pass

    if bg:
        msg = await bot.send_photo(
            chat_id=chat_id,
            photo=bg,
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return msg.message_id

    if message_id:
        try:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
                disable_web_page_preview=True,
            )
            return message_id
        except Exception:
            pass

    msg = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        disable_web_page_preview=True,
    )
    return msg.message_id


async def send_bg_to_user(
    bot: Bot,
    db,
    user_row,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    parse_mode: str | None = None,
) -> None:
    if not user_row:
        return
    try:
        last_id = user_row["last_menu_message_id"]
    except Exception:
        last_id = None
    msg_id = await send_or_edit_bg_message(
        bot,
        user_row["tg_id"],
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
        message_id=last_id,
    )
    await dao.update_user_last_menu_message_id(db, user_row["tg_id"], msg_id)

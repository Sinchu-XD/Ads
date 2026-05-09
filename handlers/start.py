from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from utils.logger import logger
from database.db import SessionLocal, UserSettings
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
from handlers.starter import log_new_user

router = Router()

FORCE_SUB_CHANNEL = "@PronovaUpdates"
START_PHOTO_URL = "https://g.co/gemini/share/50ec1a972280"
PREMIUM_DURATION_DAYS = 30


# ==========================================
# MEMBERSHIP CHECK
# ==========================================
async def check_membership(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=FORCE_SUB_CHANNEL, user_id=user_id)
        return member.status not in ("left", "kicked", "banned")
    except Exception as e:
        logger.warning(f"[start] Force sub check failed: {e}")
        return False


# ==========================================
# CHECK PREMIUM STATUS FROM DB
# ==========================================
async def get_premium_status(user_id: int) -> tuple[bool, datetime | None]:
    """Returns (is_premium, expiry_datetime)"""
    async with SessionLocal() as db:
        res = await db.execute(
            select(UserSettings).filter(UserSettings.telegram_user_id == user_id)
        )
        settings = res.scalars().first()

        if not settings or not settings.is_premium:
            return False, None

        if settings.premium_granted_at:
            expiry = settings.premium_granted_at + timedelta(days=PREMIUM_DURATION_DAYS)
            if datetime.now(timezone.utc) > expiry:
                # ✅ Auto-revoke expired premium
                settings.is_premium = False
                await db.commit()
                return False, None
            return True, expiry

        return True, None


# ==========================================
# BUILD KEYBOARD
# ==========================================
def build_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➕ Add Account", callback_data="menu_add_account"),
            InlineKeyboardButton(text="📢 Broadcast", callback_data="menu_broadcast")
        ],
        [
            InlineKeyboardButton(text="👤 My Accounts", callback_data="menu_my_accounts"),
            InlineKeyboardButton(text="⚙️ Settings", callback_data="menu_settings")
        ],
        [
            InlineKeyboardButton(text="👑 Grand Pass — ₹120/month", callback_data="menu_grand_pass")
        ]
    ])


# ==========================================
# BUILD CAPTION BASED ON PREMIUM
# ==========================================
def build_menu_caption(is_premium: bool, expiry: datetime | None) -> str:
    if is_premium and expiry:
        days_left = (expiry - datetime.now(timezone.utc)).days
        expiry_str = expiry.strftime("%d %b %Y")
        return (
            "👋 <b>Welcome back to VIP Ads Bot!</b>\n\n"
            "👑 <b>Grand Pass — ACTIVE</b>\n"
            f"⏳ Expires: <b>{expiry_str}</b> ({days_left} days left)\n\n"
            "<b>✨ Your Premium Features:</b>\n"
            "🔹 <b>3 Accounts</b> — Full multi-account broadcasting\n"
            "🔹 <b>24/7 Broadcasting</b> — No time limits\n"
            "🔹 <b>Custom Bio & Name</b> — On all accounts\n"
            "🔹 <b>Auto Replies</b> — DM responses enabled\n"
            "🔹 <b>Stealth Mode Pro</b> — Advanced anti-ban\n"
            "🔹 <b>Priority Support</b> — Faster help\n\n"
            "👇 <i>Select an option below:</i>"
        )
    else:
        return (
            "👋 <b>Welcome to VIP Ads Bot!</b>\n\n"
            "This tool empowers you to control your personal Telegram accounts "
            "for seamless, natural advertising.\n\n"
            "<b>✨ Core Features:</b>\n"
            "🔹 <b>Auto-Discovery:</b> Scans and cycles ads through joined groups\n"
            "🔹 <b>Stealth Mode:</b> Ads sent from your personal account\n\n"
            "⚠️ <b>Free Tier Limits:</b>\n"
            "👤 1 Account only\n"
            "⏳ 9-Hour Trial broadcasting\n\n"
            "👑 <b>Upgrade to Grand Pass</b> for ₹120/month to unlock everything!\n\n"
            "👇 <i>Select an option below:</i>"
        )


# ==========================================
# SEND MAIN MENU
# ==========================================
async def send_main_menu(message_or_call, bot: Bot, user_id: int):
    is_premium, expiry = await get_premium_status(user_id)
    caption = build_menu_caption(is_premium, expiry)
    keyboard = build_main_keyboard()

    if isinstance(message_or_call, Message):
        await message_or_call.answer_photo(
            photo=START_PHOTO_URL,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        try:
            await message_or_call.message.delete()
        except TelegramBadRequest:
            pass
        await message_or_call.message.answer_photo(
            photo=START_PHOTO_URL,
            caption=caption,
            reply_markup=keyboard,
            parse_mode="HTML"
        )


# ==========================================
# /start COMMAND
# ==========================================
@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
    is_member = await check_membership(bot, message.from_user.id)

    if not is_member:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="📢 Join Channel",
                url=f"https://t.me/{FORCE_SUB_CHANNEL.lstrip('@')}"
            )],
            [InlineKeyboardButton(text="✅ I Joined — Try Again", callback_data="check_sub")]
        ])
        await message.answer(
            "⚠️ <b>Access Denied!</b>\n\n"
            "You must join our official channel to use this bot.\n\n"
            "👇 Join below then tap <b>I Joined</b>.",
            reply_markup=kb,
            parse_mode="HTML"
        )
        return

    await send_main_menu(message, bot, message.from_user.id)

    try:
        await log_new_user(
            bot,
            message.from_user.id,
            message.from_user.username,
            message.from_user.full_name
        )
    except Exception as e:
        logger.warning(f"[start] log_new_user failed: {e}")

    logger.info(f"[start] User {message.from_user.id} started the bot")


# ==========================================
# CHECK SUB CALLBACK
# ==========================================
@router.callback_query(F.data == "check_sub")
async def cb_check_sub(call: CallbackQuery, bot: Bot):
    is_member = await check_membership(bot, call.from_user.id)

    if not is_member:
        await call.answer(
            "❌ You haven't joined yet! Please join the channel first.",
            show_alert=True
        )
        return

    await call.answer()
    await send_main_menu(call, bot, call.from_user.id)

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from utils.logger import logger
from database.db import SessionLocal, UserSettings, BroadcastTemplate
from sqlalchemy import select
from datetime import datetime, timezone, timedelta
import html

router = Router()

LOGS_CHANNEL_ID = -1003795731089
UPI_ID = "IrenicAbhi@ptyes"
PREMIUM_DURATION_DAYS = 30


class GrandPassStates(StatesGroup):
    waiting_screenshot = State()


def get_expiry_date(granted_at: datetime) -> datetime:
    return granted_at + timedelta(days=PREMIUM_DURATION_DAYS)


def is_expired(expiry: datetime) -> bool:
    return datetime.now(timezone.utc) > expiry


# ==========================================
# GRAND PASS INFO / STATUS PAGE
# ==========================================
@router.callback_query(F.data == "menu_grand_pass")
async def show_grand_pass(call: CallbackQuery):
    async with SessionLocal() as db:
        res = await db.execute(
            select(UserSettings).filter(UserSettings.telegram_user_id == call.from_user.id)
        )
        settings = res.scalars().first()
        is_premium = bool(settings and settings.is_premium)

        # ✅ If already premium — show status page instead of sales page
        if is_premium and settings.premium_granted_at:
            expiry = get_expiry_date(settings.premium_granted_at)
            expired = is_expired(expiry)

            if expired:
                # Auto-revoke if expired
                settings.is_premium = False
                await db.commit()
                is_premium = False
            else:
                granted_str = settings.premium_granted_at.strftime("%d %b %Y, %I:%M %p UTC")
                expiry_str = expiry.strftime("%d %b %Y, %I:%M %p UTC")
                days_left = (expiry - datetime.now(timezone.utc)).days

                text = (
                    "👑 <b>GRAND PASS — Active</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    "✅ <b>Your premium is active!</b>\n\n"
                    f"📅 <b>Activated:</b> {granted_str}\n"
                    f"⏳ <b>Expires:</b> {expiry_str}\n"
                    f"🗓 <b>Days Remaining:</b> {days_left} days\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    "🚀 You have full access to all premium features!"
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Renew Pass", callback_data="purchase_grand_pass")],
                    [InlineKeyboardButton(text="🔙 Back", callback_data="check_sub")]
                ])
                await call.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
                await call.answer()
                return

        # ✅ Non-premium — show sales page
        text = (
            "👑 <b>GRAND PASS — Premium Membership</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "🚀 <b>Unlock the full power of Abhi Ads Bot!</b>\n\n"
            "✨ <b>What You Get:</b>\n\n"
            "✏️ <b>Custom Bio</b> — Set your own promotional bio on all accounts\n\n"
            "🏷️ <b>Custom Name</b> — Personalize the display name on your userbots\n\n"
            "📡 <b>24/7 Broadcasting</b> — Non-stop ad broadcasting without any time limits\n\n"
            "🤖 <b>Auto Replies Setup</b> — Auto-respond to DMs with your promo message\n\n"
            "👥 <b>3 Accounts</b> — Add up to 3 Telegram accounts simultaneously\n\n"
            "⚡ <b>Priority Support</b> — Get faster help from our team\n\n"
            "🔒 <b>Stealth Mode Pro</b> — Advanced anti-ban broadcasting patterns\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💰 <b>Just ₹120/month</b> — Less than ₹4 per day!\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Purchase Grand Pass", callback_data="purchase_grand_pass")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="check_sub")]
        ])
        await call.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        await call.answer()


# ==========================================
# PURCHASE PAGE — SHOW UPI
# ==========================================
@router.callback_query(F.data == "purchase_grand_pass")
async def show_purchase(call: CallbackQuery):
    text = (
        "💳 <b>Complete Your Payment</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📲 <b>Pay ₹120 via UPI:</b>\n\n"
        f"🏦 UPI ID: <code>{UPI_ID}</code>\n\n"
        "📝 <b>Steps:</b>\n"
        "1️⃣ Open any UPI app (GPay, PhonePe, Paytm)\n"
        "2️⃣ Send ₹120 to the UPI ID above\n"
        "3️⃣ Take a screenshot of the payment\n"
        "4️⃣ Tap ✅ <b>Done Payment</b> below and send the screenshot\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ Your premium will be activated within <b>15 minutes</b> after verification!"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Done Payment", callback_data="done_payment")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="menu_grand_pass")]
    ])
    await call.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
    await call.answer()


# ==========================================
# DONE PAYMENT — ASK FOR SCREENSHOT
# ==========================================
@router.callback_query(F.data == "done_payment")
async def done_payment(call: CallbackQuery, state: FSMContext):
    await call.message.answer(
        "📸 <b>Please send the screenshot of your payment now.</b>\n\n"
        "We will verify and activate your Grand Pass within 15 minutes!",
        parse_mode="HTML"
    )
    await state.set_state(GrandPassStates.waiting_screenshot)
    await call.answer()


# ==========================================
# RECEIVE SCREENSHOT & FORWARD TO LOGS
# ==========================================
@router.message(GrandPassStates.waiting_screenshot, F.photo)
async def receive_screenshot(message: Message, state: FSMContext, bot: Bot):
    user = message.from_user
    username_text = f"@{user.username}" if user.username else "No username"

    caption = (
        f"💳 <b>#payment_screenshot</b>\n\n"
        f"🆔 User ID: <code>{user.id}</code>\n"
        f"📛 Name: {html.escape(user.full_name)}\n"
        f"🔗 Username: {username_text}\n\n"
        f"📦 Plan: Grand Pass — ₹120/month\n"
        f"⏳ Status: <b>Pending Verification</b>\n\n"
        f"👇 Tap below to activate:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✅ Grant Grand Pass",
            callback_data=f"admin_grant_{user.id}"
        )]
    ])

    try:
        await bot.send_photo(
            chat_id=LOGS_CHANNEL_ID,
            photo=message.photo[-1].file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        logger.info(f"[grand_pass] Screenshot received from user {user.id}")
    except Exception as e:
        logger.error(f"[grand_pass] Failed to forward screenshot: {e}")

    await state.clear()
    await message.answer(
        "✅ <b>Screenshot received! Thank you.</b>\n\n"
        "Our team will verify your payment and activate your <b>Grand Pass</b> within <b>15 minutes</b>.\n\n"
        "📩 You will receive a confirmation message here once activated!",
        parse_mode="HTML"
    )


# ==========================================
# ADMIN GRANTS FROM LOGS CHANNEL BUTTON
# ==========================================
@router.callback_query(F.data.startswith("admin_grant_"))
async def admin_grant_from_channel(call: CallbackQuery, bot: Bot):
    target_id = int(call.data.split("_")[2])

    async with SessionLocal() as db:
        try:
            res = await db.execute(
                select(UserSettings).filter(UserSettings.telegram_user_id == target_id)
            )
            settings = res.scalars().first()

            now = datetime.now(timezone.utc)

            if not settings:
                settings = UserSettings(
                    telegram_user_id=target_id,
                    is_premium=True,
                    premium_granted_at=now       # ✅ Save grant time
                )
                db.add(settings)
            else:
                settings.is_premium = True
                settings.premium_granted_at = now  # ✅ Save grant time

            await db.commit()
            await db.refresh(settings)

            expiry = get_expiry_date(now)
            granted_str = now.strftime("%d %b %Y, %I:%M %p UTC")
            expiry_str = expiry.strftime("%d %b %Y, %I:%M %p UTC")

            # ✅ Notify user with full details
            try:
                await bot.send_message(
                    chat_id=target_id,
                    text=(
                        "🎉 <b>Grand Pass Activated!</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        "✅ Your payment has been verified!\n\n"
                        f"📅 <b>Activated:</b> {granted_str}\n"
                        f"⏳ <b>Expires:</b> {expiry_str}\n"
                        f"🗓 <b>Duration:</b> 30 days\n\n"
                        "━━━━━━━━━━━━━━━━━━━━\n"
                        "👑 You now have full premium access!\n\n"
                        "🚀 Go back to the bot menu to enjoy your features."
                    ),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"[grand_pass] Could not notify user {target_id}: {e}")

            # ✅ Update button to prevent double-grant
            await call.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(
                        text=f"✅ Granted on {now.strftime('%d %b %Y')}",
                        callback_data="noop"
                    )]
                ])
            )
            await call.answer("✅ Grand Pass granted successfully!", show_alert=True)

        except Exception as e:
            await call.answer(f"❌ Error: {str(e)}", show_alert=True)
            logger.error(f"[grand_pass] Grant error: {e}")


# ==========================================
# HANDLE NON-PHOTO IN SCREENSHOT STATE
# ==========================================
@router.message(GrandPassStates.waiting_screenshot)
async def wrong_screenshot(message: Message):
    await message.answer(
        "❌ Please send a <b>photo/screenshot</b> of your payment, not text.",
        parse_mode="HTML"
            )

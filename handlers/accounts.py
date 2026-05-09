from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from pyrogram import Client
from pyrogram.errors import (
    SessionPasswordNeeded, PhoneCodeExpired,
    PhoneCodeInvalid, FloodWait, PhoneNumberInvalid
)
from utils.logger import logger
from utils.encryption import encrypt_session
from database.db import UserAccount, UserSettings, SessionLocal
from userbot.client_manager import client_manager
from config import OWNER_ID, API_ID, API_HASH
import asyncio
from sqlalchemy import select, func
import html

router = Router()


class AddAccountStates(StatesGroup):
    waiting_phone = State()
    waiting_code = State()
    waiting_password = State()


# ==========================================
# ADD ACCOUNT (WITH PREMIUM LIMITS)
# ==========================================
@router.callback_query(F.data == "menu_add_account")
async def add_account_start(call: CallbackQuery, state: FSMContext):
    async with SessionLocal() as db:
        # ✅ Fresh query — always get latest is_premium from DB
        res = await db.execute(
            select(UserSettings).filter(UserSettings.telegram_user_id == call.from_user.id)
        )
        settings = res.scalars().first()
        is_premium = bool(settings and settings.is_premium)  # ✅ Safe bool check

        acc_count_res = await db.execute(
            select(func.count()).select_from(UserAccount).filter(
                UserAccount.telegram_user_id == call.from_user.id
            )
        )
        current_accounts = acc_count_res.scalar()

        max_accounts = 3 if is_premium else 1

        if current_accounts >= max_accounts:
            if not is_premium:
                await call.answer(
                    "❌ Free Tier Limit!\n\nYou can only add 1 account.\nBuy Grand Pass (₹120/month) to add up to 3!",
                    show_alert=True
                )
            else:
                await call.answer(
                    "❌ Premium Limit Reached!\nYou already have 3 accounts (maximum).",
                    show_alert=True
                )
            return

        await call.message.edit_caption(
            caption=(
                "📱 <b>Add Telegram Account</b>\n\n"
                "Send your phone number with country code.\n"
                "Example: <code>+919876543210</code>"
            ),
            parse_mode="HTML"
        )
        await state.set_state(AddAccountStates.waiting_phone)
        await call.answer()


# ==========================================
# STEP 1: PROCESS PHONE NUMBER
# ==========================================
@router.message(AddAccountStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    phone = message.text.strip()

    if not phone.startswith("+") or not phone[1:].isdigit():
        await message.answer(
            "❌ Invalid format. Please send your number with country code.\n"
            "Example: <code>+919876543210</code>",
            parse_mode="HTML"
        )
        return

    await message.answer("⏳ Sending OTP to your Telegram account...")

    try:
        client = Client(
            name=f"session_{message.from_user.id}",
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True
        )
        await client.connect()
        sent = await client.send_code(phone)

        await state.update_data(
            phone=phone,
            phone_code_hash=sent.phone_code_hash,
            client=client
        )
        await state.set_state(AddAccountStates.waiting_code)

        await message.answer(
            "✅ OTP sent! Please enter the code you received.\n\n"
            "⚠️ Enter it with spaces like: <code>1 2 3 4 5</code>",
            parse_mode="HTML"
        )

    except PhoneNumberInvalid:
        await message.answer("❌ This phone number is invalid. Please try again.")
        await state.clear()
    except FloodWait as e:
        await message.answer(
            f"⏳ Too many attempts. Please wait <b>{e.value} seconds</b> and try again.",
            parse_mode="HTML"
        )
        await state.clear()
    except Exception as e:
        logger.error(f"[add_account] OTP error for {message.from_user.id}: {e}")
        await message.answer(
            f"❌ Failed to send OTP.\nError: <code>{html.escape(str(e))}</code>\n\nPlease try again.",
            parse_mode="HTML"
        )
        await state.clear()


# ==========================================
# STEP 2: PROCESS OTP CODE
# ==========================================
@router.message(AddAccountStates.waiting_code)
async def process_code(message: Message, state: FSMContext):
    code = message.text.strip().replace(" ", "")
    data = await state.get_data()

    phone = data.get("phone")
    phone_code_hash = data.get("phone_code_hash")
    client: Client = data.get("client")

    if not client:
        await message.answer("❌ Session expired. Please start again.")
        await state.clear()
        return

    try:
        await client.sign_in(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            phone_code=code
        )
        await save_account(message, state, client)

    except SessionPasswordNeeded:
        await state.set_state(AddAccountStates.waiting_password)
        await message.answer(
            "🔐 Your account has <b>2-Step Verification</b> enabled.\n\nPlease send your password:",
            parse_mode="HTML"
        )

    except PhoneCodeInvalid:
        await message.answer("❌ Invalid OTP code. Please try again:")

    except PhoneCodeExpired:
        await message.answer("❌ OTP has expired. Please start the process again with /start.")
        try:
            await client.disconnect()
        except:
            pass
        await state.clear()

    except Exception as e:
        logger.error(f"[add_account] Sign-in error for {message.from_user.id}: {e}")
        await message.answer(
            f"❌ Login failed.\nError: <code>{html.escape(str(e))}</code>",
            parse_mode="HTML"
        )
        try:
            await client.disconnect()
        except:
            pass
        await state.clear()


# ==========================================
# STEP 3: PROCESS 2FA PASSWORD
# ==========================================
@router.message(AddAccountStates.waiting_password)
async def process_password(message: Message, state: FSMContext):
    password = message.text.strip()
    data = await state.get_data()
    client: Client = data.get("client")

    if not client:
        await message.answer("❌ Session expired. Please start again.")
        await state.clear()
        return

    try:
        await client.check_password(password)
        await save_account(message, state, client)

    except Exception as e:
        logger.error(f"[add_account] 2FA failed for {message.from_user.id}: {e}")
        await message.answer("❌ Wrong password. Please try again:")


# ==========================================
# HELPER: SAVE ACCOUNT TO DB
# ==========================================
async def save_account(message: Message, state: FSMContext, client: Client):
    async with SessionLocal() as db:
        try:
            me = await client.get_me()
            session_string = await client.export_session_string()
            encrypted_session = encrypt_session(session_string)
            data = await state.get_data()

            new_account = UserAccount(
                telegram_user_id=message.from_user.id,
                phone_number=data.get("phone"),
                session_string_encrypted=encrypted_session,
                account_username=me.username,
                first_name=me.first_name
            )
            db.add(new_account)
            await db.commit()
            await db.refresh(new_account)

            try:
                await client.disconnect()
            except:
                pass

            # Load account into client manager
            await client_manager.get_client(new_account.id)
            await state.clear()

            username_raw = f"@{me.username}" if me.username else me.first_name or "Unknown"
            username_text = html.escape(username_raw)

            await message.answer(
                f"✅ <b>Account Added Successfully!</b>\n\n"
                f"👤 Account: {username_text}\n"
                f"📱 Phone: <code>{new_account.phone_number}</code>\n\n"
                f"You can now use this account for broadcasting! 🚀",
                parse_mode="HTML"
            )
            logger.info(f"[add_account] User {message.from_user.id} added {new_account.phone_number}")

        except Exception as e:
            await db.rollback()
            logger.error(f"[add_account] Save failed for {message.from_user.id}: {e}")
            await message.answer(
                f"❌ Failed to save account.\nError: <code>{html.escape(str(e))}</code>",
                parse_mode="HTML"
            )
            try:
                await client.disconnect()
            except:
                pass
            await state.clear()


# ==========================================
# MY ACCOUNTS DASHBOARD
# ==========================================
@router.callback_query(F.data == "menu_my_accounts")
async def show_my_accounts(call: CallbackQuery):
    async with SessionLocal() as db:
        result = await db.execute(
            select(UserAccount).filter(UserAccount.telegram_user_id == call.from_user.id)
        )
        accounts = result.scalars().all()

        if not accounts:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Add Account", callback_data="menu_add_account")],
                [InlineKeyboardButton(text="🔙 Back", callback_data="check_sub")]
            ])
            await call.message.edit_caption(
                caption="❌ You don't have any accounts added yet.",
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            await call.answer()
            return

        text = "👤 <b>Your Added Accounts:</b>\n\n"
        for acc in accounts:
            username_raw = f"@{acc.account_username}" if acc.account_username else "No Username"
            username = html.escape(username_raw)
            text += f"🔹 {username} — <code>{acc.phone_number}</code>\n"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back to Main Menu", callback_data="check_sub")]
        ])
        await call.message.edit_caption(caption=text, reply_markup=keyboard, parse_mode="HTML")
        await call.answer()


# ==========================================
# SETTINGS DASHBOARD
# ==========================================
@router.callback_query(F.data == "menu_settings")
async def show_settings(call: CallbackQuery):
    async with SessionLocal() as db:
        result = await db.execute(
            select(UserAccount).filter(UserAccount.telegram_user_id == call.from_user.id)
        )
        accounts = result.scalars().all()

        kb = []
        for acc in accounts:
            kb.append([InlineKeyboardButton(
                text=f"🗑 Remove {acc.phone_number}",
                callback_data=f"remove_acc_{acc.id}"
            )])

        kb.append([InlineKeyboardButton(text="📢 Broadcast Settings", callback_data="menu_broadcast")])
        kb.append([InlineKeyboardButton(text="🔙 Back", callback_data="check_sub")])

        keyboard = InlineKeyboardMarkup(inline_keyboard=kb)
        await call.message.edit_caption(
            caption="⚙️ <b>Bot Settings</b>\n\nManage your accounts and broadcast settings here.",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await call.answer()


# ==========================================
# REMOVE ACCOUNT
# ==========================================
@router.callback_query(F.data.startswith("remove_acc_"))
async def remove_account(call: CallbackQuery):
    acc_id = int(call.data.split("_")[2])

    async with SessionLocal() as db:
        try:
            await client_manager.stop_client(acc_id)

            result = await db.execute(
                select(UserAccount).filter(UserAccount.id == acc_id)
            )
            acc = result.scalars().first()

            if acc:
                await db.delete(acc)
                await db.commit()
                await call.answer("✅ Account removed successfully!", show_alert=True)
            else:
                await call.answer("⚠️ Account not found.", show_alert=True)

        except Exception as e:
            logger.error(f"[add_account] Remove error: {e}")
            await call.answer(f"❌ Error: {str(e)}", show_alert=True)

    await show_settings(call)

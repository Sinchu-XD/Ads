from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from utils.logger import logger
from database.db import SessionLocal, UserSettings, UserAccount, BroadcastTemplate
from sqlalchemy import select
import json

router = Router()

ANIMATED_EMOJIS = {
    "🔥 Fire":      ("5199885118214255388", "🔥"),
    "⭐ Star":      ("5368324170671202286", "⭐"),
    "💎 Diamond":   ("5471952986970267163", "💎"),
    "👑 Crown":     ("5471912804244811950", "👑"),
    "⚡ Lightning": ("5278600589496024099", "⚡"),
    "🚀 Rocket":    ("5460878567521085440", "🚀"),
    "💰 Money":     ("5445284980978621387", "💰"),
    "✅ Check":     ("5206607081334906820", "✅"),
}


class BroadcastStates(StatesGroup):
    waiting_for_ad_text = State()
    waiting_for_button_text = State()
    waiting_for_button_url = State()


# ==========================================
# 1. BROADCAST CONTROL PANEL
# ==========================================
@router.callback_query(F.data == "menu_broadcast")
async def show_broadcast_dashboard(call: CallbackQuery, state: FSMContext):
    await state.clear()

    async with SessionLocal() as db:
        try:
            acc_res = await db.execute(
                select(UserAccount).filter(UserAccount.telegram_user_id == call.from_user.id)
            )
            if not acc_res.scalars().first():
                await call.answer("❌ You need to add a Telegram account first!", show_alert=True)
                return

            res = await db.execute(
                select(UserSettings).filter(UserSettings.telegram_user_id == call.from_user.id)
            )
            settings = res.scalars().first()
            if not settings:
                settings = UserSettings(telegram_user_id=call.from_user.id)
                db.add(settings)
                await db.commit()
                await db.refresh(settings)

            tmpl_res = await db.execute(
                select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == call.from_user.id)
            )
            template = tmpl_res.scalars().first()

            status_text = "🟢 ON (Broadcasting)" if settings.is_broadcasting else "🔴 OFF (Paused)"
            toggle_text = "🔴 Turn OFF" if settings.is_broadcasting else "🟢 Turn ON"
            dm_status = "🟢 DM ON" if settings.dm_broadcast_enabled else "🔴 DM OFF"
            dm_toggle = "🔴 Disable DM" if settings.dm_broadcast_enabled else "🟢 Enable DM"

            if template and template.message_text:
                clean_text = template.message_text.replace("<", "").replace(">", "")
                msg_preview = clean_text[:120] + "..." if len(clean_text) > 120 else clean_text
            else:
                msg_preview = "❌ No message saved yet."

            btns_preview = "❌ No buttons added."
            if template and template.buttons_json:
                try:
                    btns = json.loads(template.buttons_json)
                    btns_preview = "\n".join([f"🔘 {b['text']} → {b['url']}" for b in btns])
                except Exception:
                    pass

            text = (
                f"📢 <b>Broadcast Control Panel</b>\n\n"
                f"<b>Status:</b> {status_text}\n\n"
                f"<b>📝 Saved Message:</b>\n<code>{msg_preview}</code>\n\n"
                f"<b>🔘 Buttons:</b>\n{btns_preview}\n\n"
                f"<i>Every 5 minutes your userbot will auto-send this to all groups.</i>"
            )

            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=toggle_text, callback_data="toggle_broadcast")],
                [InlineKeyboardButton(text="✏️ Edit Message", callback_data="edit_broadcast_msg")],
                [InlineKeyboardButton(text="😎 Add Animated Emoji", callback_data="emoji_picker")],
                [InlineKeyboardButton(text="🔘 Add URL Button", callback_data="add_url_button")],
                [InlineKeyboardButton(text="🗑 Clear Buttons", callback_data="clear_buttons")],
                [InlineKeyboardButton(text="👁 Preview Message", callback_data="preview_broadcast")],
                [InlineKeyboardButton(text=dm_toggle, callback_data="toggle_dm_broadcast")],
                [InlineKeyboardButton(text="🔙 Close", callback_data="close_panel")]
            ])

            try:
                await call.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
            except TelegramBadRequest as e:
                err = str(e).lower()
                if "message is not modified" in err:
                    pass
                elif "there is no text in the message to edit" in err:
                    await call.message.delete()
                    await call.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
                else:
                    logger.error(f"[broadcast] Dashboard TelegramBadRequest: {e}")
                    await call.answer("Error updating dashboard.", show_alert=True)
            except Exception as e:
                logger.error(f"[broadcast] Dashboard fallback error: {e}")
                try:
                    await call.message.delete()
                except Exception:
                    pass
                await call.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

            await call.answer()

        except Exception as e:
            logger.error(f"[broadcast] Dashboard error: {e}")
            await call.answer("Error loading dashboard.", show_alert=True)


# ==========================================
# 2. TOGGLE ON/OFF
# ==========================================
@router.callback_query(F.data == "toggle_broadcast")
async def toggle_broadcast_status(call: CallbackQuery, state: FSMContext):
    async with SessionLocal() as db:
        res = await db.execute(
            select(UserSettings).filter(UserSettings.telegram_user_id == call.from_user.id)
        )
        settings = res.scalars().first()
        if not settings:
            await call.answer("Settings not found.", show_alert=True)
            return

        tmpl_res = await db.execute(
            select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == call.from_user.id)
        )
        template = tmpl_res.scalars().first()

        if not settings.is_broadcasting and (not template or not template.message_text):
            await call.answer("❌ Set a broadcast message first!", show_alert=True)
            return

        settings.is_broadcasting = not settings.is_broadcasting
        await db.commit()

        action = "STARTED 🚀" if settings.is_broadcasting else "PAUSED 🛑"
        await call.answer(f"Broadcast {action}", show_alert=False)

    await show_broadcast_dashboard(call, state)


# ==========================================
# 3. EDIT MESSAGE
# ==========================================
@router.callback_query(F.data == "edit_broadcast_msg")
async def ask_for_broadcast_msg(call: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="menu_broadcast")]
    ])
    await call.message.edit_text(
        "✏️ <b>Send your new broadcast message.</b>\n\n"
        "You can use HTML formatting:\n"
        "<code>&lt;b&gt;Bold&lt;/b&gt;</code> → <b>Bold</b>\n"
        "<code>&lt;i&gt;Italic&lt;/i&gt;</code> → <i>Italic</i>\n"
        "<code>&lt;a href='URL'&gt;Link&lt;/a&gt;</code> → Clickable link\n\n"
        "Send your message now 👇",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_ad_text)
    await call.answer()


@router.message(BroadcastStates.waiting_for_ad_text)
async def save_new_broadcast_msg(message: Message, state: FSMContext):
    ad_text = message.html_text

    async with SessionLocal() as db:
        res = await db.execute(
            select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == message.from_user.id)
        )
        template = res.scalars().first()
        if not template:
            template = BroadcastTemplate(telegram_user_id=message.from_user.id)
            db.add(template)

        template.message_text = ad_text

        settings_res = await db.execute(
            select(UserSettings).filter(UserSettings.telegram_user_id == message.from_user.id)
        )
        settings = settings_res.scalars().first()
        if settings:
            settings.is_broadcasting = False  # ✅ Pause on edit for safety

        await db.commit()

    await state.clear()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="menu_broadcast")]
    ])
    await message.answer(
        "✅ <b>Message saved!</b>\n\nBroadcast paused for safety. Go back and turn it ON.",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ==========================================
# 4. ANIMATED EMOJI PICKER
# ==========================================
@router.callback_query(F.data == "emoji_picker")
async def show_emoji_picker(call: CallbackQuery):
    buttons = []
    for name, (emoji_id, fallback) in ANIMATED_EMOJIS.items():
        buttons.append([InlineKeyboardButton(
            text=f"{fallback} {name}",
            callback_data=f"add_emoji_{emoji_id}_{fallback}"
        )])
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="menu_broadcast")])

    try:
        await call.message.edit_text(
            "😎 <b>Pick an animated emoji to add to your message:</b>\n\n"
            "It will be appended at the end of your current message.\n"
            "<i>(Appears animated for Telegram Premium users!)</i>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.error(f"[broadcast] Emoji picker error: {e}")
    await call.answer()


@router.callback_query(F.data.startswith("add_emoji_"))
async def add_emoji_to_message(call: CallbackQuery):
    parts = call.data.split("_", 3)
    emoji_id = parts[2]
    fallback = parts[3]

    async with SessionLocal() as db:
        res = await db.execute(
            select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == call.from_user.id)
        )
        template = res.scalars().first()
        if not template:
            template = BroadcastTemplate(telegram_user_id=call.from_user.id)
            db.add(template)

        current_text = template.message_text or ""
        emoji_tag = f"<tg-emoji emoji-id='{emoji_id}'>{fallback}</tg-emoji>"
        template.message_text = current_text + " " + emoji_tag
        await db.commit()

    await call.answer(f"{fallback} Emoji added!", show_alert=False)
    await show_emoji_picker(call)


# ==========================================
# 5. ADD URL BUTTON
# ==========================================
@router.callback_query(F.data == "add_url_button")
async def ask_button_text(call: CallbackQuery, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="menu_broadcast")]
    ])
    await call.message.edit_text(
        "🔘 <b>Adding a URL Button</b>\n\n"
        "<b>Step 1:</b> Send the <b>button text</b>\n"
        "Example: <code>🔥 Join Our Channel</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_button_text)
    await call.answer()


@router.message(BroadcastStates.waiting_for_button_text)
async def save_button_text(message: Message, state: FSMContext):
    await state.update_data(button_text=message.text.strip())
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="menu_broadcast")]
    ])
    await message.answer(
        "✅ Button text saved!\n\n"
        "<b>Step 2:</b> Now send the <b>URL</b> for this button\n"
        "Example: <code>https://t.me/yourchannel</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await state.set_state(BroadcastStates.waiting_for_button_url)


@router.message(BroadcastStates.waiting_for_button_url)
async def save_button_url(message: Message, state: FSMContext):
    url = message.text.strip()
    if not url.startswith(("http://", "https://", "tg://")):
        await message.answer(
            "❌ Invalid URL. Must start with <code>https://</code> or <code>tg://</code>",
            parse_mode="HTML"
        )
        return

    data = await state.get_data()
    button_text = data.get("button_text", "Button")

    async with SessionLocal() as db:
        res = await db.execute(
            select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == message.from_user.id)
        )
        template = res.scalars().first()
        if not template:
            template = BroadcastTemplate(telegram_user_id=message.from_user.id)
            db.add(template)

        existing_buttons = []
        if template.buttons_json:
            try:
                existing_buttons = json.loads(template.buttons_json)
            except Exception:
                pass

        existing_buttons.append({"text": button_text, "url": url})
        template.buttons_json = json.dumps(existing_buttons)
        await db.commit()

    await state.clear()

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Another Button", callback_data="add_url_button")],
        [InlineKeyboardButton(text="🔙 Back to Dashboard", callback_data="menu_broadcast")]
    ])
    await message.answer(
        f"✅ <b>Button added!</b>\n\n"
        f"🔘 <b>{button_text}</b> → <code>{url}</code>",
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ==========================================
# 6. CLEAR BUTTONS
# ==========================================
@router.callback_query(F.data == "clear_buttons")
async def clear_buttons(call: CallbackQuery, state: FSMContext):
    async with SessionLocal() as db:
        res = await db.execute(
            select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == call.from_user.id)
        )
        template = res.scalars().first()
        if template:
            template.buttons_json = None
            await db.commit()

    await call.answer("🗑 All buttons cleared!", show_alert=False)
    await show_broadcast_dashboard(call, state)


# ==========================================
# 7. PREVIEW MESSAGE
# ==========================================
@router.callback_query(F.data == "preview_broadcast")
async def preview_broadcast(call: CallbackQuery):
    async with SessionLocal() as db:
        res = await db.execute(
            select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == call.from_user.id)
        )
        template = res.scalars().first()

        if not template or not template.message_text:
            await call.answer("❌ No message saved yet!", show_alert=True)
            return

        keyboard = None
        if template.buttons_json:
            try:
                btns = json.loads(template.buttons_json)
                rows = [[InlineKeyboardButton(text=b["text"], url=b["url"])] for b in btns]
                rows.append([InlineKeyboardButton(text="🔙 Back", callback_data="menu_broadcast")])
                keyboard = InlineKeyboardMarkup(inline_keyboard=rows)
            except Exception:
                pass

        if not keyboard:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Back", callback_data="menu_broadcast")]
            ])

        await call.message.answer(
            f"👁 <b>Preview of your broadcast:</b>\n\n{template.message_text}",
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await call.answer()


# ==========================================
# 8. CLOSE PANEL
# ==========================================
@router.callback_query(F.data == "close_panel")
async def close_panel(call: CallbackQuery):
    try:
        await call.message.delete()
    except TelegramBadRequest:
        pass
    await call.answer()

@router.message(F.chat.type == "private")
async def handle_dm_broadcast(message: Message):
    if message.from_user.is_bot:
        return

    async with SessionLocal() as db:
        res = await db.execute(
            select(UserSettings).filter(UserSettings.telegram_user_id == message.from_user.id)
        )
        settings = res.scalars().first()

        if not settings or not settings.dm_broadcast_enabled:
            return

        tmpl_res = await db.execute(
            select(BroadcastTemplate).filter(BroadcastTemplate.telegram_user_id == message.from_user.id)
        )
        template = tmpl_res.scalars().first()

        if not template or not template.message_text:
            return

        try:
            keyboard = None
            if template.buttons_json:
                import json
                btns = json.loads(template.buttons_json)
                rows = [[InlineKeyboardButton(text=b["text"], url=b["url"])] for b in btns]
                keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

            await message.answer(
                template.message_text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )

        except Exception as e:
            logger.error(f"DM Broadcast Error: {e}")

@router.callback_query(F.data == "toggle_dm_broadcast")
async def toggle_dm_broadcast(call: CallbackQuery, state: FSMContext):
    async with SessionLocal() as db:
        res = await db.execute(
            select(UserSettings).filter(UserSettings.telegram_user_id == call.from_user.id)
        )
        settings = res.scalars().first()

        if not settings:
            await call.answer("Settings not found", show_alert=True)
            return

        settings.dm_broadcast_enabled = not settings.dm_broadcast_enabled
        await db.commit()

        status = "ON 🟢" if settings.dm_broadcast_enabled else "OFF 🔴"
        await call.answer(f"DM Broadcast {status}")

    await show_broadcast_dashboard(call, state)
